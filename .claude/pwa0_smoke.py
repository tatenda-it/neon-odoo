# -*- coding: utf-8 -*-
"""B11 / WA-0 rails smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pwa0_smoke.py
Self-contained: creates its own bot.user fixtures + a write.log proposal,
mocks Gemini HTTP, and ROLLS BACK at the end (no residue). Asserts the
Gate-2 acceptance set + the Copilot-unchanged regression bar.
"""
import hashlib
import hmac
import inspect
import traceback
from unittest.mock import MagicMock, patch

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    line = ("PASS" if ok else "FAIL") + " " + name
    if detail and not ok:
        line += " :: " + str(detail)
    print(line)


ICP = env["ir.config_parameter"].sudo()

try:
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService, _WA_SAFE_WRITES,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry as TR
    from odoo.addons.neon_ai_core.models.ai.gemini_chat_adapter import (
        GeminiChatAdapter,
    )
    from odoo.addons.neon_channels.controllers.webhook import _hmac_matches

    svc = WhatsAppCopilotService(env)

    def user_in_group(xmlid):
        g = env.ref(xmlid, raise_if_not_found=False)
        if not g:
            return env["res.users"]
        return env["res.users"].sudo().search(
            [("groups_id", "in", g.id), ("share", "=", False),
             ("active", "=", True)], limit=1)

    # ---- T1: resolver  bot.user -> variant (representative tiers) ----
    tiers = [
        ("neon_core.group_neon_superuser", "director"),
        ("neon_core.group_neon_bookkeeper", "bookkeeper"),
        ("neon_core.group_neon_lead_tech", "lead_tech"),
        ("neon_core.group_neon_sales_rep", "sales"),
    ]
    resolved = 0
    for i, (xmlid, expected) in enumerate(tiers):
        u = user_in_group(xmlid)
        if not u:
            check("resolver:%s (no user)" % expected, False, xmlid)
            continue
        bu = env["neon.bot.user"].sudo().create({
            "name": "WA0 %s" % expected,
            "phone_number": "+99900000%02d" % i,
            "user_id": u.id})
        v = svc.variant_for(bu.user_id)
        check("resolver %s -> %s" % (xmlid.split('.')[-1], expected),
              v == expected, "got %s" % v)
        resolved += int(v == expected)
    check("resolver: all representative tiers map correctly",
          resolved == len(tiers))

    su = user_in_group("neon_core.group_neon_superuser")
    sales = user_in_group("neon_core.group_neon_sales_rep")

    # ---- T1b: resolve() by Meta-format `from` (the gap that 24/24 missed)
    # Meta sends digits WITHOUT '+'; bot.user stores '+E.164' (often with
    # spaces). resolve() must normalise digits-only and match.
    bu_fmt = env["neon.bot.user"].sudo().create({
        "name": "WA0 fmt", "phone_number": "+263 990 12 3456",
        "user_id": sales.id})
    r1 = svc.resolve("263990123456")            # Meta: digits, no '+'
    check("resolve Meta-format from (no +) -> right bot.user",
          len(r1) == 1 and r1.id == bu_fmt.id, "got %s" % r1)
    r2 = svc.resolve("+263990123456")           # with '+'
    check("resolve with + -> same bot.user",
          len(r2) == 1 and r2.id == bu_fmt.id)
    r3 = svc.resolve("+263 990 12 3456")        # spaces in stored form
    check("resolve with spaces -> same bot.user",
          len(r3) == 1 and r3.id == bu_fmt.id)
    # full privileged turn must now resolve (not fall through to raw-lead)
    check("Meta-format from resolves to a variant (privileged path)",
          svc.variant_for(svc.resolve("263990123456").user_id) in (
              "director", "sales", "bookkeeper", "lead_tech"))
    # DEFENSIVE: a 2nd active row with the SAME normalised digits ->
    # UNRESOLVED (RBAC safety: never pick one of several).
    bu_dup = env["neon.bot.user"].sudo().create({
        "name": "WA0 dup", "phone_number": "263990123456",
        "user_id": su.id})
    check("resolve ambiguous (>1 normalised match) -> UNRESOLVED (empty)",
          len(svc.resolve("263990123456")) == 0)

    # ---- T2: intersection-ACL (a tool the user's groups disallow is
    #          rejected by dispatch, even if "the agent" emits it) ----
    blocked = None
    for t in TR.list_tools():
        if not TR.user_can_call(sales, t):
            blocked = t
            break
    if blocked:
        disp = TR.dispatch(blocked.name, env, sales, {})
        check("intersection-ACL: off-scope tool rejected",
              disp.get("ok") is False
              and "access" in (disp.get("error", "").lower()),
              "%s -> %s" % (blocked.name, disp))
    else:
        check("intersection-ACL: a blocked tool exists for sales",
              False, "sales can call EVERY tool?")

    # ---- T3: NO money tool to ANY variant incl director (Robin/OD) ----
    money_absent = True
    for variant in ["director", "sales", "bookkeeper", "lead_tech"]:
        tools = svc.whatsapp_tools(su, variant)
        names = {t.name for t in tools}
        writes = {t.name for t in tools if t.category == "write"}
        if "update_deal_value" in names or not writes.issubset(_WA_SAFE_WRITES):
            money_absent = False
    check("no money tool over WhatsApp for ANY variant (incl director)",
          money_absent)
    dir_tools = svc.whatsapp_tools(su, "director")
    dir_names = {t.name for t in dir_tools}
    dir_writes = {t.name for t in dir_tools if t.category == "write"}
    check("director(OD superuser): update_deal_value ABSENT",
          "update_deal_value" not in dir_names)
    check("director(OD superuser): WA writes subset of WA_SAFE_WRITES",
          dir_writes.issubset(_WA_SAFE_WRITES), str(dir_writes))

    # ---- T4: cta_url generated for a reversible write ----
    sess = env["neon.finance.ai.chat.session"].sudo()\
        .get_or_create_for_user(sales.id)
    proposal = {
        "action_type": "log_lead", "target_model": "crm.lead",
        "human_summary": "Create lead Acme (WA-0 smoke)",
        "params": {"name": "Acme"}, "before_state": None,
        "after_state": {"name": "Acme"}}
    prop = env["neon.finance.ai.chat.write.log"].sudo().propose(
        sess, sales, proposal)
    cta = svc._cta_url(prop["record"]) if prop.get("ok") else ""
    check("cta_url generated for a reversible write",
          prop.get("ok") and "/web#id=" in cta
          and "neon.finance.ai.chat.write.log" in cta, cta)
    lt = TR.get_tool("log_lead")
    check("log_lead is a WA-safe reversible write tool",
          "log_lead" in _WA_SAFE_WRITES and lt and lt.category == "write")

    # ---- T5a: Gemini chat() round-trip (mocked HTTP) ----
    ICP.set_param("neon_dashboard.ai_keys_google", "test-key")
    prov = env["neon.dashboard.ai.provider"].sudo().search(
        [("provider_key", "=", "google")], limit=1)
    fake = MagicMock()
    fake.ok = True
    fake.status_code = 200
    fake.json.return_value = {
        "candidates": [{"content": {"role": "model", "parts": [
            {"text": "Hi"},
            {"functionCall": {"name": "get_open_quotes",
                              "args": {"limit": 3}}}]}}],
        "usageMetadata": {"promptTokenCount": 5,
                          "candidatesTokenCount": 7}}
    check("gemini provider row present", bool(prov))
    with patch("odoo.addons.neon_ai_core.models.ai."
               "gemini_chat_adapter.requests.post", return_value=fake):
        r = GeminiChatAdapter(prov).chat(
            [{"role": "system", "content": "sys"},
             {"role": "user", "content": "hello"}],
            tools=TR.groq_tool_schemas(category="read"))
    check("Gemini chat() success", r.success, r.error_message)
    check("Gemini parsed assistant text", r.assistant_message == "Hi")
    check("Gemini parsed functionCall -> tool_call",
          len(r.tool_calls) == 1
          and r.tool_calls[0]["tool_name"] == "get_open_quotes"
          and r.tool_calls[0]["params"] == {"limit": 3},
          str(r.tool_calls))

    # ---- T5b: signature -- genuine PASS + wrong/unsigned/tampered FAIL --
    secret = "test-app-secret"
    raw = b'{"entry":[{"changes":[]}]}'
    good = "sha256=" + hmac.new(secret.encode(), raw,
                                hashlib.sha256).hexdigest()
    check("signature: GENUINE Meta-signed payload PASSES",
          _hmac_matches(secret, raw, good) is True)
    check("signature: wrong signature FAILS",
          _hmac_matches(secret, raw, "sha256=deadbeef") is False)
    check("signature: missing header FAILS",
          _hmac_matches(secret, raw, "") is False)
    check("signature: tampered body FAILS",
          _hmac_matches(secret, raw + b" ", good) is False)

    # ---- T6: Twilio path intact + no longer auth-via-authorised_numbers
    from odoo.addons.neon_channels.controllers import twilio_webhook as TW
    check("twilio controller + route present",
          hasattr(TW, "TwilioWebhookController")
          and hasattr(TW.TwilioWebhookController, "twilio_webhook"))
    src = inspect.getsource(TW.TwilioWebhookController.twilio_webhook)
    # Behavioural check (robust to comments): bot access is reachable via
    # exactly ONE _process_bot_command call -- the bot.user-gated one. The
    # old authorised_numbers branch had a second call; it's gone.
    check("twilio: bot access ONLY via bot.user (single command path)",
          src.count("_process_bot_command(") == 1,
          "calls=%d" % src.count("_process_bot_command("))

    # ---- T7: INTEGRATION -- handle_inbound must ROUTE via resolve()
    #          (the gap that bit twice: unit resolve() worked, the live
    #          handle_inbound path used its own exact-match + fell through).
    #          Gemini + send are mocked so no live API / WhatsApp calls.
    from unittest.mock import patch as _patch
    from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import (
        ChatTurnResult)
    WM = env["neon.whatsapp.message"].sudo()
    _GCA = ("odoo.addons.neon_ai_core.models.ai.gemini_chat_adapter."
            "GeminiChatAdapter.chat")

    def _stub_chat(self, messages, tools=None):
        return ChatTurnResult(success=True, assistant_message="stub",
                              tool_calls=[])

    _sends = []

    def _stub_send(self, to, body, *a, **k):
        _sends.append((to, body))
        return True

    def _lead_ct(num):
        return env["crm.lead"].sudo().search_count(
            ['|', ("phone", "=", num), ("mobile", "=", num)])

    # resolved case: Meta-format `from` (no '+') -> PRIVILEGED path
    bu_int = env["neon.bot.user"].sudo().create({
        "name": "WA0 int", "phone_number": "+263 990 88 7766",
        "user_id": sales.id})
    msg = {"id": "wamid.INT", "from": "263990887766", "type": "text",
           "text": {"body": "hello"}}
    with _patch(_GCA, _stub_chat), \
         _patch.object(type(WM), "send_message", _stub_send), \
         _patch.object(type(WM), "send_cta_url",
                       lambda self, *a, **k: True):
        leads_before = _lead_ct("263990887766")
        WM.handle_inbound(msg, {})
        inrow = WM.search([("phone_number", "=", "263990887766"),
                           ("direction", "=", "inbound")],
                          order="id desc", limit=1)
        outrow = WM.search([("phone_number", "=", "263990887766"),
                            ("direction", "=", "outbound")],
                           order="id desc", limit=1)
        leads_after = _lead_ct("263990887766")
    check("handle_inbound(Meta-format) -> PRIVILEGED (inbound bot_user_id set)",
          bool(inrow) and inrow.bot_user_id.id == bu_int.id,
          "bu=%s" % (inrow.bot_user_id if inrow else None))
    check("handle_inbound -> outbound reply row carries variant",
          bool(outrow) and bool(outrow.variant), "out=%s" % outrow)
    check("handle_inbound -> process_incoming NOT called (no raw lead)",
          leads_after == leads_before)
    check("handle_inbound -> send attempted", len(_sends) >= 1)

    # ambiguous case: two active rows, same normalised digits -> fall
    # through to raw-lead, NO privilege (RBAC safety at the live layer).
    env["neon.bot.user"].sudo().create({
        "name": "WA0 amb A", "phone_number": "+263 990 11 2233",
        "user_id": sales.id})
    env["neon.bot.user"].sudo().create({
        "name": "WA0 amb B", "phone_number": "263990112233",
        "user_id": su.id})
    msg2 = {"id": "wamid.AMB", "from": "263990112233", "type": "text",
            "text": {"body": "hi"}}
    with _patch(_GCA, _stub_chat), \
         _patch.object(type(WM), "send_message", _stub_send), \
         _patch.object(type(WM), "send_cta_url",
                       lambda self, *a, **k: True):
        WM.handle_inbound(msg2, {})
        priv = WM.search_count([("phone_number", "=", "263990112233"),
                                ("bot_user_id", "!=", False)])
        lead_amb = _lead_ct("263990112233")
    check("handle_inbound ambiguous(>1) -> NO privilege (no bot_user_id row)",
          priv == 0)
    check("handle_inbound ambiguous(>1) -> fell through to raw-lead",
          lead_amb >= 1)

    # ---- Copilot-unchanged regression bar ----
    nr = len(TR.list_tools(category="read"))
    nw = len(TR.list_tools(category="write"))
    check("Copilot R3: 18 tools (14 read + 4 write)", nr == 14 and nw == 4)
    dft = env["neon.dashboard.ai.provider"].sudo().search(
        [("is_default", "=", True)], limit=1)
    check("Copilot: Groq still is_default (WA didn't steal it)",
          bool(dft) and dft.provider_key == "groq")
    tat = env["res.users"].sudo().search(
        [("login", "=", "tatenda@neonhiring.co.zw")], limit=1)
    if tat:
        check("Copilot R4: Tatenda -> Director",
              env["neon.dashboard"].sudo()
              ._default_dashboard_type_for_user(tat.id) == "director")
    else:
        check("Copilot R4: Tatenda present on DB", False)

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    env.cr.rollback()

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))
