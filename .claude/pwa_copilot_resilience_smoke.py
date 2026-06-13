"""P-WA Copilot RESILIENCE smoke — the LLM (Groq) is OPTIONAL; the bot must NOT
go dark when it's down.

The lesson behind this suite (2026-06-13 prod incident): a live "Hello" + a
screen-list request both returned "Sorry -- I can't reach the assistant right
now" when Groq blipped. Every other WA harness MOCKS the LLM to SUCCEED, so none
of them could catch a dead-end on LLM FAILURE. This suite does the opposite: it
patches the provider to FAIL and drives the REAL path (handle_inbound) to prove:

  R1  is_greeting() is a TIGHT match (a greeting; not a greeting+request)
  R2  run_turn on all-providers-fail -> the DETERMINISTIC menu (not a dead-end)
  R3  through handle_inbound, a non-greeting turn with Groq DOWN -> degraded menu
  R4  a bare GREETING -> deterministic menu, and the LLM is NEVER called
  R5  a multi-role greeting still gets the deterministic 2-button lens ask
      (WA-4 intact), and the LLM is NEVER called

Runs in `odoo shell -d neon_crm`. Self-contained [TEST-RESIL] users + bot.users;
torn down at the end.
"""
from contextlib import ExitStack
from unittest.mock import patch

_passed = 0
_total = 0
results = {}


def check(name, ok, detail=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[name] = ok
    print("%s:" % name, "PASS" if ok else "FAIL", detail if not ok else "")


from odoo.addons.neon_channels.models import whatsapp_message as WMMOD  # noqa
from odoo.addons.neon_channels.models import wa_payload
from odoo.addons.neon_channels.models.wa_copilot import WhatsAppCopilotService
from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import ChatTurnResult

env = env(context=dict(env.context, tracking_disable=True,
                       mail_create_nosubscribe=True,
                       mail_notify_force_send=False))
secret = env["ir.config_parameter"].sudo().get_param("database.secret") or ""
WM = env["neon.whatsapp.message"].sudo()
WMcls = type(WM)
svc = WhatsAppCopilotService(env)
Users = env["res.users"].sudo()
BotU = env["neon.bot.user"].sudo()

g_user = env.ref("base.group_user")
g_book = env.ref("neon_core.group_neon_bookkeeper")
g_hr = env.ref("neon_hr.group_neon_hr_admin", raise_if_not_found=False)

if not env["neon.whatsapp.config"].sudo().search([("active", "=", True)], limit=1):
    env["neon.whatsapp.config"].sudo().create({
        "name": "RESIL cfg", "phone_number_id": "pn", "access_token": "t",
        "whatsapp_business_account_id": "w", "active": True})


def _wipe_login(login):
    u = Users.with_context(active_test=False).search([("login", "=", login)])
    if u:
        BotU.with_context(active_test=False).search(
            [("user_id", "in", u.ids)]).unlink()
        u.unlink()


# single-role BOOKKEEPER (NOT sales -> _wa12_llm_intake_maybe never claims it,
# so a non-command turn falls cleanly to run_turn = the Copilot LLM path).
_wipe_login("resil_book_smoke")
u_book = Users.with_context(no_reset_password=True).create({
    "name": "[TEST-RESIL] BookOnly", "login": "resil_book_smoke",
    "groups_id": [(6, 0, [g_user.id, g_book.id])]})
BOOK_PHONE, BOOK_FROM = "+263770009101", "263770009101"
BotU.create({"name": "[TEST-RESIL] book", "phone_number": BOOK_PHONE,
             "user_id": u_book.id})
bu_book = svc.resolve(BOOK_FROM)

# dual-role (book + hr) for the WA-4 lens-ask-on-greeting check.
bu_dual = None
if g_hr:
    _wipe_login("resil_dual_smoke")
    u_dual = Users.with_context(no_reset_password=True).create({
        "name": "[TEST-RESIL] Dual", "login": "resil_dual_smoke",
        "groups_id": [(6, 0, [g_user.id, g_book.id, g_hr.id])]})
    DUAL_PHONE, DUAL_FROM = "+263770009102", "263770009102"
    BotU.create({"name": "[TEST-RESIL] dual", "phone_number": DUAL_PHONE,
                 "user_id": u_dual.id})
    bu_dual = svc.resolve(DUAL_FROM)

# ---- R1: is_greeting() tight matching --------------------------------------
greet_true = all(svc.is_greeting(x) for x in (
    "Hello", "hi", "Hey!", "Good morning", "good afternoon ", "start",
    "Hi there", "HELLO", "hey there", "evening"))
greet_false = not any(svc.is_greeting(x) for x in (
    "hello can you quote for acme", "quote: acme events", "",
    "what screens do you have", "hi i need a quote", "good rates?"))
check("R1: is_greeting tight (greetings yes; greeting+request/command no)",
      greet_true and greet_false,
      "true_set=%s false_set=%s" % (greet_true, greet_false))
check("R1b: 'menu' is a menu trigger, NOT a greeting (no overlap)",
      svc.wants_menu("menu") and not svc.is_greeting("menu"))


# ---- send + provider mocks -------------------------------------------------
_sent = []
_calls = []


def s_msg(self, to, body):
    _sent.append(("text", to, body)); return True


def s_buttons(self, to, body, buttons):
    _sent.append(("buttons", to, body, buttons)); return True


def s_list(self, to, body, bt, sections):
    _sent.append(("list", to, body, sections)); return True


def s_cta(self, to, body, disp, url):
    _sent.append(("cta", to, body, url)); return True


def _fail_chat(self, messages, schemas):
    """Simulate Groq DOWN: every provider attempt fails."""
    _calls.append({"n": len(messages)})
    return (ChatTurnResult(success=False, error_message="stub: groq down"),
            "groq")


def text_msg(body, frm):
    return {"id": "wamid.X", "from": frm, "type": "text",
            "text": {"body": body}}


def last_any():
    return _sent[-1] if _sent else None


def reply_text(entry):
    """The text body of an outbound entry (text / buttons / list / cta)."""
    if not entry:
        return ""
    return entry[2] if len(entry) > 2 else ""


with ExitStack() as st:
    st.enter_context(patch.object(WMcls, "send_message", s_msg))
    st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
    st.enter_context(patch.object(WMcls, "send_list", s_list))
    st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
    # NB: do NOT patch send_interactive_or_text -- let the real one decompose an
    # interactive into send_buttons / send_list (the mocks above), exactly as
    # pwa4 does, so a structured reply is captured as ("buttons"|"list", ...).
    st.enter_context(patch.object(
        WhatsAppCopilotService, "_provider_chat", _fail_chat))

    # ---- R2: run_turn unit -- all providers fail -> degraded MENU ----------
    _calls.clear()
    r2 = svc.run_turn(bu_book, "what is a good colour scheme for a gala")
    r2txt = (r2.get("text") or "") + " " + (r2.get("text_fallback") or "")
    check("R2: run_turn(Groq down) -> degraded menu, NOT the dead-end",
          "briefly unavailable" in r2txt
          and "can't reach the assistant" not in r2txt
          and (r2.get("interactive") or r2.get("text_fallback")),
          "text=%r" % (r2.get("text") or "")[:80])
    check("R2b: degraded result still carries the provider error (audit)",
          bool(r2.get("error")) and r2.get("provider_key") is None,
          "error=%r" % r2.get("error"))

    # ---- R3: handle_inbound, non-greeting, Groq DOWN -> degraded menu ------
    _sent.clear(); _calls.clear()
    WM.handle_inbound(text_msg("any tips for lighting a marquee?", BOOK_FROM), {})
    out3 = reply_text(last_any())
    check("R3: through handle_inbound, Groq down -> degraded menu (not dark)",
          "briefly unavailable" in out3
          and "can't reach the assistant" not in out3,
          "reply=%r" % out3[:90])
    check("R3b: the LLM WAS attempted then degraded (not silently skipped)",
          len(_calls) >= 1, "provider calls=%d" % len(_calls))

    # ---- R4: a bare GREETING -> deterministic menu, LLM NEVER called -------
    _sent.clear(); _calls.clear()
    WM.handle_inbound(text_msg("Hello", BOOK_FROM), {})
    out4 = reply_text(last_any())
    check("R4: greeting -> deterministic greeting menu",
          ("Hi " in out4) and ("can't reach the assistant" not in out4)
          and bool(last_any()),
          "reply=%r kind=%s" % (out4[:80], last_any()[0] if last_any() else None))
    check("R4b: greeting did NOT touch the LLM (provider never called)",
          len(_calls) == 0, "provider calls=%d" % len(_calls))

    # ---- R5: multi-role greeting still ASKS (WA-4 intact), no LLM ----------
    if bu_dual:
        _sent.clear(); _calls.clear()
        WM.handle_inbound(text_msg("hello there", DUAL_FROM), {})
        e5 = last_any()
        is_ask = bool(e5) and e5[0] == "buttons" and len(e5[3]) == 2
        decoded = ([wa_payload.decode(secret, x["id"]) for x in e5[3]]
                   if is_ask else [])
        check("R5: multi-role greeting -> 2-button lens ASK (not the menu)",
              is_ask and all(d and d[0] == "lens" for d in decoded),
              "kind=%s decoded=%s" % (e5[0] if e5 else None, decoded))
        check("R5b: the lens ask did NOT touch the LLM",
              len(_calls) == 0, "provider calls=%d" % len(_calls))

        # ---- R6: degrade threads the ROUTED lens (review LOW fix) ----------
        # A multi-role user routed to a NON-default lens, then Groq down: the
        # degraded menu must reflect the ROUTED lens's tools (not the default)
        # + carry the lens marker. (Pre-fix, build_menu_result ignored the
        # passed variant and re-resolved the default -> wrong tool subset.)
        def _opt_labels(res):
            inter = res.get("interactive") or {}
            if inter.get("kind") == "buttons":
                return sorted(b.get("title", "") for b in inter.get("buttons", []))
            if inter.get("kind") == "list":
                out = []
                for s in inter.get("sections", []):
                    out += [r.get("title", "") for r in s.get("rows", [])]
                return sorted(out)
            return []  # _safe text-only (no tools)

        default_v = svc.variant_for(u_dual)
        routed_v = "bookkeeper" if default_v != "bookkeeper" else "hr"
        bk = {t.name for t in svc.whatsapp_tools(u_dual, routed_v)}
        df = {t.name for t in svc.whatsapp_tools(u_dual, default_v)}
        res_routed = svc._degraded_menu(bu_dual, routed_v, "stub: down",
                                        lens_routed=True)
        res_def = svc._degraded_menu(bu_dual, default_v, "stub: down")
        rtxt = (res_routed.get("text") or "") + " " + (
            res_routed.get("text_fallback") or "")
        check("R6: degraded menu threads the ROUTED lens (not the default)",
              bk != df  # precondition: lenses genuinely differ
              and _opt_labels(res_routed) != _opt_labels(res_def)
              and res_routed.get("variant") == routed_v,
              "routed=%s default=%s opts_differ=%s var=%s"
              % (routed_v, default_v,
                 _opt_labels(res_routed) != _opt_labels(res_def),
                 res_routed.get("variant")))
        check("R6b: degraded routed turn re-surfaces the lens marker",
              "🔖 as" in rtxt, "text=%r" % rtxt[:80])
    else:
        check("R5: (skipped — neon_hr group absent)", True)
        check("R5b: (skipped — neon_hr group absent)", True)
        check("R6: (skipped — neon_hr group absent)", True)
        check("R6b: (skipped — neon_hr group absent)", True)

    # ---- R7: degraded body says 'Tap an option:' AT MOST once (NIT fix) ----
    rb = svc._degraded_menu(bu_book, svc.variant_for(u_book), "stub")
    rbtext = rb.get("text") or rb.get("text_fallback") or ""
    check("R7: degraded body does not duplicate the 'Tap an option:' CTA",
          rbtext.lower().count("tap an option") <= 1
          and "can't reach the assistant" not in rbtext,
          "count=%d text=%r" % (rbtext.lower().count("tap an option"),
                                rbtext[:80]))

# ---- teardown --------------------------------------------------------------
_wipe_login("resil_book_smoke")
if g_hr:
    _wipe_login("resil_dual_smoke")
env["neon.whatsapp.config"].sudo().search([("name", "=", "RESIL cfg")]).unlink()
env.cr.commit()

print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
