# -*- coding: utf-8 -*-
"""B11 / WA-4 dual-role lens-routing smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pwa4_dual_role_smoke.py

Through handle_inbound, Meta + provider mocked. Builds a throwaway
dual-role (Bookkeeper + HR Admin) user (local user 10 is a single-role
sales rep) + a single-role user, exercises lens routing, and ROLLS BACK.

Covers: dual-role detection; intent classifier; resolve_lens (finance->
bookkeeper, HR->hr, ambiguous->2-button ask, explicit override); the ask
tap sets the lens for the turn (reuses WA-1 tap-back); the "as <lens>"
surface; CRITICAL guardrail (a lens never exposes a tool beyond the
user's groups + no money write in any lens); single-role user unchanged.
"""
import json
import traceback
from contextlib import ExitStack
from unittest.mock import patch

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


_sent = []
_seen = []


class _Resp:
    status_code = 200
    text = "ok"


def _fake_post(url, json=None, headers=None, **kw):
    _sent.append({"json": json or {}})
    return _Resp()


try:
    from odoo.addons.neon_channels.models import whatsapp_message as WMMOD
    from odoo.addons.neon_channels.models import wa_payload
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry
    from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import (
        ChatTurnResult,
    )

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True,
                           mail_notify_force_send=False))
    secret = env["ir.config_parameter"].sudo().get_param(
        "database.secret") or ""
    WM = env["neon.whatsapp.message"].sudo()
    WMcls = type(WM)
    svc = WhatsAppCopilotService(env)

    g_book = env.ref("neon_core.group_neon_bookkeeper")
    g_hr = env.ref("neon_hr.group_neon_hr_admin", raise_if_not_found=False)
    g_sales = env.ref("neon_core.group_neon_sales_rep")
    g_user = env.ref("base.group_user")
    check("fixtures: bookkeeper + hr-admin groups exist",
          bool(g_book) and bool(g_hr))

    env["neon.whatsapp.config"].sudo().create({
        "name": "WA4 cfg", "phone_number_id": "pn", "access_token": "t",
        "whatsapp_business_account_id": "w", "active": True})

    # dual-role user (Bookkeeper + HR Admin), not superuser
    dual = env["res.users"].sudo().create({
        "name": "WA4 Dual", "login": "wa4_dual_smoke",
        "groups_id": [(6, 0, [g_user.id, g_book.id, g_hr.id])]})
    DUAL_PHONE, DUAL_FROM = "+263770004001", "263770004001"
    env["neon.bot.user"].sudo().create({
        "name": "WA4 dual", "phone_number": DUAL_PHONE, "user_id": dual.id})
    bu_dual = svc.resolve(DUAL_FROM)

    # single-role user (sales rep)
    single = env["res.users"].sudo().search(
        [("groups_id", "in", g_sales.id), ("share", "=", False),
         ("active", "=", True),
         ("groups_id", "not in", g_book.id)], limit=1)
    if single:
        SING_PHONE, SING_FROM = "+263770004002", "263770004002"
        env["neon.bot.user"].sudo().create({
            "name": "WA4 single", "phone_number": SING_PHONE,
            "user_id": single.id})
        bu_single = svc.resolve(SING_FROM)

    # ---- 1: dual-role detection ------------------------------------
    check("D1: _held_lenses(dual) == {bookkeeper, hr}",
          svc._held_lenses(dual) == {"bookkeeper", "hr"},
          svc._held_lenses(dual))
    if single:
        check("D1: _held_lenses(single sales) == {sales} (single-role)",
              svc._held_lenses(single) == {"sales"},
              svc._held_lenses(single))

    # ---- 2: intent classifier --------------------------------------
    check("D2: finance keywords -> 'finance'",
          svc.classify_intent("which invoices are overdue?") == "finance")
    check("D2: HR keywords -> 'hr'",
          svc.classify_intent("show me the payroll for staff") == "hr")
    check("D2: no keywords -> None (ambiguous)",
          svc.classify_intent("hello there") is None)
    check("D2: BOTH finance+HR keywords -> None (ambiguous)",
          svc.classify_intent("invoice for payroll") is None)

    # ---- 3: resolve_lens -------------------------------------------
    r_fin = svc.resolve_lens(bu_dual, "which invoices are overdue?", 0)
    check("D3: finance -> bookkeeper lens, routed",
          r_fin["variant"] == "bookkeeper" and r_fin["routed"]
          and not r_fin["ask"], r_fin)
    r_hr = svc.resolve_lens(bu_dual, "payroll for staff please", 0)
    check("D3: HR -> hr lens, routed",
          r_hr["variant"] == "hr" and r_hr["routed"] and not r_hr["ask"])
    r_amb = svc.resolve_lens(bu_dual, "hello there", 0)
    check("D3: ambiguous -> ask (no variant)",
          r_amb["ask"] and r_amb["variant"] is None)
    r_ov = svc.resolve_lens(bu_dual, "as bookkeeper what is the leave balance", 0)
    check("D3: explicit override beats HR keyword -> bookkeeper + stripped",
          r_ov["variant"] == "bookkeeper"
          and "leave balance" in r_ov["text"]
          and "as bookkeeper" not in r_ov["text"].lower(), r_ov)
    if single:
        r_sng = svc.resolve_lens(bu_single, "which invoices are overdue?", 0)
        check("D3: single-role -> NOT routed (today's behaviour)",
              r_sng["routed"] is False
              and r_sng["variant"] == svc.variant_for(single))

    # ---- 4: CRITICAL guardrail (no unlock beyond groups; no money) --
    entitled = {t.name for t in tool_registry
                .filter_tools_for_variant_and_user(dual, "director",
                                                   category=None)}
    book_lens = {t.name for t in svc.whatsapp_tools(dual, "bookkeeper")}
    hr_lens = {t.name for t in svc.whatsapp_tools(dual, "hr")}
    check("G4: bookkeeper lens ⊆ entitled (never unlocks beyond groups)",
          book_lens <= entitled, book_lens - entitled)
    check("G4: hr lens ⊆ entitled (never unlocks beyond groups)",
          hr_lens <= entitled, hr_lens - entitled)
    check("G4: NO money write (update_deal_value) in either lens",
          "update_deal_value" not in book_lens
          and "update_deal_value" not in hr_lens)
    check("G4: bookkeeper lens is FOCUSED (strict subset of hr/all)",
          book_lens < hr_lens, "book=%d hr=%d" % (len(book_lens),
                                                  len(hr_lens)))

    # ---- mocked through handle_inbound ------------------------------
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_list(self, to, body, bt, sections):
        _sent.append(("list", to, body, sections)); return True

    def s_cta(self, to, body, disp, url):
        _sent.append(("cta", to, body, url)); return True

    def _stub_chat(self, messages, schemas):
        _seen.append({"sys": messages[0]["content"] if messages else "",
                      "tools": sorted(s["function"]["name"]
                                      for s in (schemas or []))})
        return (ChatTurnResult(success=True, assistant_message="ok",
                               tool_calls=[]), "google")

    def text_msg(body, frm):
        return {"id": "wamid.X", "from": frm, "type": "text",
                "text": {"body": body}}

    def tap_msg(rid, frm, title="x"):
        return {"id": "wamid.T", "from": frm, "type": "interactive",
                "interactive": {"type": "button",
                                "button_reply": {"id": rid, "title": title}}}

    def last(kind):
        for e in reversed(_sent):
            if isinstance(e, tuple) and e[0] == kind:
                return e
        return None

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", _stub_chat))

        # ---- 5: finance turn -> bookkeeper lens + frame + surface ---
        _sent.clear(); _seen.clear()
        WM.handle_inbound(text_msg("which invoices are overdue?", DUAL_FROM), {})
        txt = last("text")
        check("D5: finance turn used the BOOKKEEPER lens toolset",
              _seen and set(_seen[-1]["tools"]) == book_lens,
              _seen[-1]["tools"] if _seen else None)
        check("D5: system prompt framed as Bookkeeper",
              _seen and "Bookkeeper" in _seen[-1]["sys"])
        check("D5: reply surfaces the lens ('as Bookkeeper')",
              txt and "as Bookkeeper" in txt[2], txt[2] if txt else None)

        # ---- 6: HR turn -> hr lens -------------------------------------
        _sent.clear(); _seen.clear()
        WM.handle_inbound(text_msg("payroll for staff please", DUAL_FROM), {})
        check("D6: HR turn used the HR lens toolset (all-entitled)",
              _seen and set(_seen[-1]["tools"]) == hr_lens)
        check("D6: reply surfaces 'as HR'",
              last("text") and "as HR" in last("text")[2])

        # ---- 7: ambiguous -> ask, tap sets lens ------------------------
        _sent.clear(); _seen.clear()
        WM.handle_inbound(text_msg("hello there", DUAL_FROM), {})
        b = last("buttons")
        decoded = [wa_payload.decode(secret, x["id"]) for x in b[3]] if b else []
        check("D7: ambiguous -> 2-button lens ask (lens:bookkeeper/hr)",
              b and len(b[3]) == 2 and all(d and d[0] == "lens" for d in decoded)
              and {d[1][0] for d in decoded} == {"bookkeeper", "hr"}, decoded)
        check("D7: ask did NOT call the model (no run_turn yet)",
              not _seen)
        # tap the Bookkeeper option
        book_btn = next(x["id"] for x, d in zip(b[3], decoded)
                        if d[1][0] == "bookkeeper")
        _sent.clear(); _seen.clear()
        WM.handle_inbound(tap_msg(book_btn, DUAL_FROM, "Bookkeeper"), {})
        check("D7: tap re-runs the original msg under the chosen lens",
              _seen and set(_seen[-1]["tools"]) == book_lens
              and last("text") and "as Bookkeeper" in last("text")[2])

        # ---- 8: single-role user UNCHANGED (no routing, no surface) +
        #         guardrail in-context (lens ⊆ the single user's entitled)
        if single:
            _sent.clear(); _seen.clear()
            WM.handle_inbound(
                text_msg("which invoices are overdue?", SING_FROM), {})
            sing_lens = {t.name for t in svc.whatsapp_tools(
                single, svc.variant_for(single))}
            sing_entitled = {t.name for t in tool_registry
                             .filter_tools_for_variant_and_user(
                                 single, "director", category=None)}
            check("D8: single-role reply has NO lens surface ('as ')",
                  last("text") and "🔖 as" not in last("text")[2])
            check("D8: single-role used today's variant_for lens (no routing)",
                  _seen and set(_seen[-1]["tools"]) == sing_lens,
                  _seen[-1]["tools"] if _seen else None)
            check("D8: single-role lens ⊆ its OWN entitled (no over-exposure)",
                  _seen and set(_seen[-1]["tools"]) <= sing_entitled)

    # ---- regression bar --------------------------------------------
    check("REG: Copilot 18 tools unchanged",
          len(tool_registry.list_tools(category="read")) == 14
          and len(tool_registry.list_tools(category="write")) == 4)
    check("REG: 'lens' added to wa_payload INTENTS",
          "lens" in wa_payload.INTENTS)

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    try:
        env.cr.rollback()
    except Exception:  # noqa: BLE001
        pass

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))