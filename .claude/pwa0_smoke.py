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
        # WA-1: handle_inbound canonicalises at the boundary, so the stored
        # rows (and any fallback lead) are E.164 '+263...'. The inbound
        # `from` (msg above) stays raw '263...' -- that raw->canonical hop
        # IS the normalization under test; assert the CANONICAL result.
        leads_before = _lead_ct("+263990887766")
        WM.handle_inbound(msg, {})
        inrow = WM.search([("phone_number", "=", "+263990887766"),
                           ("direction", "=", "inbound")],
                          order="id desc", limit=1)
        outrow = WM.search([("phone_number", "=", "+263990887766"),
                            ("direction", "=", "outbound")],
                           order="id desc", limit=1)
        leads_after = _lead_ct("+263990887766")
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
        # WA-1: ambiguous -> falls through; the fallback lead + any row are
        # canonical (+263...). Assert the canonical form so priv==0 means
        # "genuinely no privileged row", not "query missed the raw form".
        priv = WM.search_count([("phone_number", "=", "+263990112233"),
                                ("bot_user_id", "!=", False)])
        lead_amb = _lead_ct("+263990112233")
    check("handle_inbound ambiguous(>1) -> NO privilege (no bot_user_id row)",
          priv == 0)
    check("handle_inbound ambiguous(>1) -> fell through to raw-lead",
          lead_amb >= 1)

    # ---- T8: Gemini 503 resilience (retry -> Groq fallback -> graceful)
    from unittest.mock import MagicMock as _MM
    from odoo.addons.neon_ai_core.models.ai.gemini_chat_adapter import (
        GeminiChatAdapter as _GAd)
    prov_g = env["neon.dashboard.ai.provider"].sudo().search(
        [("provider_key", "=", "google")], limit=1)
    _GP = "odoo.addons.neon_ai_core.models.ai.gemini_chat_adapter"
    _GRP = ("odoo.addons.neon_ai_core.models.ai.groq_chat_adapter."
            "GroqChatAdapter.chat")

    def _resp(status, body):
        m = _MM()
        m.status_code = status
        m.ok = (200 <= status < 300)
        m.content = b"x"
        m.text = ""
        m.json.return_value = body
        return m

    _ok_body = {"candidates": [{"content": {"role": "model", "parts": [
        {"text": "hi"}]}}], "usageMetadata": {}}
    _503_body = {"error": {"code": 503, "message": "high demand"}}

    def _post_always_503(*a, **k):
        return _resp(503, _503_body)

    # 8a: 503-then-200 -> retry succeeds, one reply
    _seq = {"n": 0}

    def _post_503_then_200(*a, **k):
        _seq["n"] += 1
        return _resp(503, _503_body) if _seq["n"] == 1 else _resp(200, _ok_body)
    with _patch(_GP + ".requests.post", side_effect=_post_503_then_200), \
         _patch(_GP + ".time.sleep", lambda s: None):
        rr = _GAd(prov_g).chat([{"role": "user", "content": "hi"}], tools=None)
    check("503-then-200 -> retry succeeds (one reply)",
          rr.success and rr.assistant_message == "hi", rr.error_message)
    check("503-then-200 -> exactly 2 attempts", _seq["n"] == 2)

    # 8b: 503-always -> Groq fallback answers (this is why we kept Groq)
    bu_fb = env["neon.bot.user"].sudo().create({
        "name": "WA0 fb", "phone_number": "+263 990 55 4433",
        "user_id": sales.id})

    def _groq_ok(self, messages, tools=None):
        return ChatTurnResult(success=True, assistant_message="groq-served",
                              tool_calls=[], latency_ms=10)
    with _patch(_GP + ".requests.post", side_effect=_post_always_503), \
         _patch(_GP + ".time.sleep", lambda s: None), \
         _patch(_GRP, _groq_ok):
        res_fb = svc.run_turn(bu_fb, "hello")
    check("503-always -> Groq fallback served the turn",
          res_fb.get("provider_key") == "groq",
          "pk=%s" % res_fb.get("provider_key"))
    check("503-always -> real reply (not the can't-reach fallback)",
          "groq-served" in (res_fb.get("text") or ""))

    # 8c: both providers fail -> graceful fallback + error surfaced
    def _groq_fail(self, messages, tools=None):
        return ChatTurnResult(success=False, error_message="Groq HTTP 503",
                              latency_ms=5)
    with _patch(_GP + ".requests.post", side_effect=_post_always_503), \
         _patch(_GP + ".time.sleep", lambda s: None), \
         _patch(_GRP, _groq_fail):
        res_bf = svc.run_turn(bu_fb, "hello again")
    check("both providers fail -> graceful 'can't reach' message",
          "can't reach the assistant" in (res_bf.get("text") or "").lower())
    check("both fail -> error surfaced", bool(res_bf.get("error")))

    # ---- T9: tool-use LOOP -- the tool result must come back as NL, never
    #          raw JSON to the user (the leak bug), and stay under the cap.
    _GA_chat = ("odoo.addons.neon_ai_core.models.ai.gemini_chat_adapter."
                "GeminiChatAdapter.chat")
    bu_loop = env["neon.bot.user"].sudo().create({
        "name": "WA0 loop", "phone_number": "+263 990 77 1100",
        "user_id": su.id})

    # 9a: model calls a READ tool, then replies in NL -> user gets prose.
    _lp = {"n": 0}

    def _chat_tool_then_text(self, messages, tools=None):
        _lp["n"] += 1
        if _lp["n"] == 1:
            return ChatTurnResult(
                success=True, assistant_message="",
                tool_calls=[{"tool_call_id": "c1",
                             "tool_name": "get_dashboard_summary",
                             "params": {}}], latency_ms=5)
        return ChatTurnResult(
            success=True, tool_calls=[], latency_ms=5,
            assistant_message="Your cash on hand looks healthy and AR is "
                              "under control.")
    with _patch(_GA_chat, _chat_tool_then_text):
        rloop = svc.run_turn(bu_loop, "can i check finance?")
    _txt = rloop.get("text") or ""
    check("tool-loop: read result returned as NATURAL LANGUAGE",
          "cash on hand looks healthy" in _txt, _txt[:80])
    check("tool-loop: NO raw JSON leaked to user",
          '"kpi"' not in _txt and not _txt.strip().startswith("{"))
    check("tool-loop: looped once (tool -> NL = 2 model calls)",
          _lp["n"] == 2, "calls=%d" % _lp["n"])

    # 9b: a model that ALWAYS calls a tool -> stays under the cap and
    #     returns a graceful (non-JSON) message, not an infinite loop.
    _cap = {"n": 0}

    def _chat_always_tool(self, messages, tools=None):
        _cap["n"] += 1
        return ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "cX",
                         "tool_name": "get_dashboard_summary",
                         "params": {}}], latency_ms=5)
    with _patch(_GA_chat, _chat_always_tool):
        rcap = svc.run_turn(bu_loop, "loop please")
    _ctxt = rcap.get("text") or ""
    check("tool-loop: capped (model calls <= MAX_TOOL_ITERATIONS=3)",
          _cap["n"] <= 3, "calls=%d" % _cap["n"])
    check("tool-loop: cap hit -> graceful reply, NOT raw JSON",
          '"kpi"' not in _ctxt and not _ctxt.strip().startswith("{"))

    # 9c: the id-18 scenario -- Gemini FORCED to fail so GROQ serves, and
    #     Groq itself makes a tool call -> the loop must STILL synthesize
    #     NL (the leak was on the Groq-fallback tool path, untested before).
    _grl = {"n": 0}

    def _groq_tool_then_text(self, messages, tools=None):
        _grl["n"] += 1
        if _grl["n"] == 1:
            return ChatTurnResult(
                success=True, assistant_message="",
                tool_calls=[{"tool_call_id": "g1",
                             "tool_name": "get_dashboard_summary",
                             "params": {}}], latency_ms=5)
        return ChatTurnResult(
            success=True, tool_calls=[], latency_ms=5,
            assistant_message="Cash on hand is healthy and nothing overdue.")
    with _patch(_GP + ".requests.post", side_effect=_post_always_503), \
         _patch(_GP + ".time.sleep", lambda s: None), \
         _patch(_GRP, _groq_tool_then_text):
        rgl = svc.run_turn(bu_loop, "can i check finance?")
    _gt = rgl.get("text") or ""
    check("Groq-fallback tool turn -> NL synthesis (the id-18 scenario)",
          "Cash on hand is healthy" in _gt, _gt[:80])
    check("Groq-fallback: NO raw JSON leaked",
          '"kpi"' not in _gt and not _gt.strip().startswith("{"))
    check("Groq-fallback: served=groq + looped (tool -> NL)",
          rgl.get("provider_key") == "groq" and _grl["n"] == 2,
          "pk=%s calls=%d" % (rgl.get("provider_key"), _grl["n"]))

    # ---- T10: WA-1 phone normalization + conversation memory ----
    import json as _json
    from odoo.addons.neon_channels.models.phone_utils import to_e164 as _e164
    WMs = env["neon.whatsapp.message"].sudo()

    def _stub_send2(self, *a, **k):
        return True

    # 10a: to_e164 matrix (the format class that bit us)
    _matrix = {
        "+263772336333": "+263772336333", "263772336333": "+263772336333",
        "+263 77 233-6333": "+263772336333", "00263772336333": "+263772336333",
        "0772336333": "+263772336333", "263785273824": "+263785273824"}
    _bad = {k: _e164(k) for k, v in _matrix.items() if _e164(k) != v}
    check("WA1 to_e164 matrix (+/no-+/spaces/00/local-0)", not _bad, _bad)

    # 10b: conversation memory THROUGH handle_inbound (Gemini path)
    bu_mem = env["neon.bot.user"].sudo().create({
        "name": "WA0 mem", "phone_number": "+263 990 22 1100",
        "user_id": sales.id})

    _seen = []

    def _chat_capture(self, messages, tools=None):
        _seen.append(_json.dumps(messages))
        return ChatTurnResult(success=True, tool_calls=[], latency_ms=5,
                              assistant_message="reply-%d" % (len(_seen)))
    with _patch(_GA_chat, _chat_capture), \
         _patch.object(type(WMs), "send_message", _stub_send2), \
         _patch.object(type(WMs), "send_cta_url", lambda s, *a, **k: True):
        WMs.handle_inbound({"id": "mem1", "from": "263990221100",
            "type": "text",
            "text": {"body": "first question about quotes"}}, {})
        WMs.handle_inbound({"id": "mem2", "from": "263990221100",
            "type": "text", "text": {"body": "and the second?"}}, {})
    check("WA1 memory: 2nd turn prompt CONTAINS the 1st message",
          len(_seen) >= 2 and "first question about quotes" in _seen[1],
          "turns=%d" % len(_seen))
    check("WA1 memory: 2nd turn also carries the 1st assistant reply",
          len(_seen) >= 2 and "reply-1" in _seen[1])
    check("WA1 no double-count: current msg appears once in its own turn",
          len(_seen) >= 1
          and _seen[0].count("first question about quotes") == 1)
    check("WA1 boundary: rows stored canonical (+263), not raw",
          WMs.search_count([("phone_number", "=", "+263990221100")]) >= 2
          and WMs.search_count([("phone_number", "=", "263990221100")]) == 0)

    # 10c: Groq-fallback path ALSO carries history
    env["neon.bot.user"].sudo().create({
        "name": "WA0 memg", "phone_number": "+263 990 33 2200",
        "user_id": sales.id})

    def _gem_fail2(self, messages, tools=None):
        return ChatTurnResult(success=False, is_fallback=True,
                              error_message="forced", latency_ms=1)
    _gseen = []

    def _groq_capture(self, messages, tools=None):
        _gseen.append(_json.dumps(messages))
        return ChatTurnResult(success=True, tool_calls=[], latency_ms=5,
                              assistant_message="groq-reply-%d" % len(_gseen))
    with _patch(_GA_chat, _gem_fail2), _patch(_GRP, _groq_capture), \
         _patch.object(type(WMs), "send_message", _stub_send2), \
         _patch.object(type(WMs), "send_cta_url", lambda s, *a, **k: True):
        WMs.handle_inbound({"id": "g1", "from": "263990332200",
            "type": "text", "text": {"body": "groq first msg"}}, {})
        WMs.handle_inbound({"id": "g2", "from": "263990332200",
            "type": "text", "text": {"body": "groq second"}}, {})
    check("WA1 Groq-fallback path carries history",
          len(_gseen) >= 2 and "groq first msg" in _gseen[1],
          "groq_turns=%d" % len(_gseen))

    # 10d: UNMAPPED inbound -> created crm.lead phone is canonical E.164
    #      (proves boundary normalize reaches _find_or_create_lead)
    Lead = env["crm.lead"].sudo()
    WMs.handle_inbound({"id": "u1", "from": "263999888777", "type": "text",
        "text": {"body": "hello I want a quote"}}, {})
    check("WA1 lead-intake: unmapped -> crm.lead phone canonical (+263)",
          bool(Lead.search([("phone", "=", "+263999888777")], limit=1)),
          "no lead with canonical phone")

    # 10e: migration logic -- normalizes + idempotent + count preserved
    t1 = WMs.create({"name": "MIGT1", "direction": "inbound",
                     "phone_number": "263111222333", "message_type": "text"})
    t2 = WMs.create({"name": "MIGT2", "direction": "inbound",
                     "phone_number": "+263444555666", "message_type": "text"})

    def _migrate(recs):
        n = 0
        for r in recs:
            new = _e164(r.phone_number or "")
            if new and new != r.phone_number:
                r.phone_number = new
                n += 1
        return n
    pair = t1 + t2
    n1 = _migrate(pair)
    pair.invalidate_recordset()
    n2 = _migrate(pair)
    check("WA1 migration: normalizes + idempotent + count preserved",
          t1.phone_number == "+263111222333"
          and t2.phone_number == "+263444555666"
          and n1 == 1 and n2 == 0 and len(pair) == 2,
          "n1=%d n2=%d" % (n1, n2))

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
