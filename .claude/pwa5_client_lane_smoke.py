# -*- coding: utf-8 -*-
"""B11 / WA-5 client intake lane smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pwa5_client_lane_smoke.py

Through handle_inbound, Meta + provider mocked. Builds a throwaway
escalation target + two assignable salespeople + a superuser-in-sales +
an unmapped CLIENT number, exercises the full client lane + handoff +
assignment loop, and ROLLS BACK.

CRITICAL (WA-5's equivalent of WA-2's phone-mismatch test): drive an
UNMAPPED number across greeting / every button / quote flow /
pricing+"talk to team" text and assert run_turn / handle_tap /
variant_for / tool_registry.dispatch are NEVER invoked; no money/CRM tool
fires (write.log unchanged); the only crm.lead write is the single raw
intake lead. Mapped number -> staff assistant byte-identical.

Also: assign role-gated; assignee decline two-factor (HMAC + sender ==
assigned user); decline clears user_id + bounces to escalation (never
auto-reassign / never unowned); lead-create contract; activity fallback.
"""
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
_templates = []
counters = {"run_turn": 0, "handle_tap": 0, "variant_for": 0, "dispatch": 0}


def _reset_spies():
    for k in counters:
        counters[k] = 0


try:
    from datetime import timedelta as _td
    from odoo import fields
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

    Lead = env["crm.lead"].sudo()
    WriteLog = env["neon.finance.ai.chat.write.log"].sudo()
    Act = env["mail.activity"].sudo()

    g_user = env.ref("base.group_user")
    g_sales = env.ref("neon_finance.group_neon_finance_sales",
                      raise_if_not_found=False)
    g_super = env.ref("neon_core.group_neon_superuser")
    check("fixtures: finance_sales + superuser groups exist",
          bool(g_sales) and bool(g_super))

    env["neon.whatsapp.config"].sudo().create({
        "name": "WA5 cfg", "phone_number_id": "pn", "access_token": "t",
        "whatsapp_business_account_id": "w", "active": True})

    # data records present (proves wa5_client_data.xml loaded on -u)
    tag = env.ref("neon_channels.crm_tag_whatsapp", raise_if_not_found=False)
    src = env.ref("neon_channels.utm_source_whatsapp",
                  raise_if_not_found=False)
    med = env.ref("neon_channels.utm_medium_whatsapp",
                  raise_if_not_found=False)
    check("fixtures: WhatsApp crm.tag + utm source/medium installed",
          bool(tag) and bool(src) and bool(med))

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(user, phone):
        return env["neon.bot.user"].sudo().create({
            "name": user.login, "phone_number": phone, "user_id": user.id})

    # escalation target (Munashe analog): IS a sales-team member on prod,
    # excluded from the list by ESCALATION-LOGIN identity (the assigner).
    esc_u = mk_user("wa5_esc_smoke", [g_user, g_sales])
    ESC_PHONE, ESC_FROM = "+263880002001", "263880002001"
    mk_bot(esc_u, ESC_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa5_escalation_login", "wa5_esc_smoke")

    # OD/owner (Robin analog): sales-team member + superuser, excluded by
    # OWNER-LOGIN identity -- NOT by the superuser group.
    owner_u = mk_user("wa5_owner_smoke", [g_user, g_sales, g_super])
    OWN_PHONE = "+263880002005"
    mk_bot(owner_u, OWN_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa5_owner_login", "wa5_owner_smoke")

    # two plain salespeople (Lisa / Evrill analogs)
    a_u = mk_user("wa5_assignee_a", [g_user, g_sales])
    A_PHONE, A_FROM = "+263880002002", "263880002002"
    mk_bot(a_u, A_PHONE)
    b_u = mk_user("wa5_assignee_b", [g_user, g_sales])
    B_PHONE, B_FROM = "+263880002003", "263880002003"
    mk_bot(b_u, B_PHONE)
    # superuser who is ALSO a salesperson and is NOT the owner (Tatenda
    # analog) -> must STAY assignable under the corrected rule.
    su_u = mk_user("wa5_su_smoke", [g_user, g_sales, g_super])
    SU_PHONE, SU_FROM = "+263880002004", "263880002004"
    mk_bot(su_u, SU_PHONE)

    # WA-5.1 window control. An INBOUND (recent) opens the 24h window ->
    # in-window INTERACTIVE notifies. Warm esc + a_u + su_u so the
    # interactive-path tests hold; leave b_u COLD so the closed-window
    # TEMPLATE path is exercised.
    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})

    def cool(phone):
        env["neon.whatsapp.message"].sudo().search(
            [("phone_number", "=", phone),
             ("direction", "=", "inbound")]).unlink()

    for ph in (ESC_PHONE, A_PHONE, SU_PHONE):
        warm(ph)

    # the unmapped CLIENT
    CLIENT_E164, CLIENT_FROM = "+263880001001", "263880001001"
    check("fixtures: client number is UNMAPPED (no bot.user)",
          not svc.resolve(CLIENT_FROM))

    bu_esc = svc.resolve(ESC_FROM)
    bu_a = svc.resolve(A_FROM)
    bu_b = svc.resolve(B_FROM)
    bu_su = svc.resolve(SU_FROM)

    # ---- mocks -----------------------------------------------------
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_list(self, to, body, bt, sections):
        _sent.append(("list", to, body, sections)); return True

    def s_cta(self, to, body, disp, url):
        _sent.append(("cta", to, body, url)); return True

    def s_template(self, to, name, language="en", body_params=None,
                   quick_reply_payloads=None, url_button_param=None,
                   recipient_partner=None, audit_body=None):
        _templates.append({"to": to, "name": name, "lang": language,
                           "params": body_params or [],
                           "qr": quick_reply_payloads or []})
        return {"ok": True, "reason": "sent"}

    def _stub_chat(self, messages, schemas):
        return (ChatTurnResult(success=True, assistant_message="ok",
                               tool_calls=[]), "google")

    _orig_rt = WhatsAppCopilotService.run_turn
    _orig_ht = WhatsAppCopilotService.handle_tap
    _orig_vf = WhatsAppCopilotService.variant_for
    _orig_disp = tool_registry.dispatch

    def spy_rt(*a, **k):
        counters["run_turn"] += 1; return _orig_rt(*a, **k)

    def spy_ht(*a, **k):
        counters["handle_tap"] += 1; return _orig_ht(*a, **k)

    def spy_vf(*a, **k):
        counters["variant_for"] += 1; return _orig_vf(*a, **k)

    def spy_disp(*a, **k):
        counters["dispatch"] += 1; return _orig_disp(*a, **k)

    def text_msg(body, frm):
        return {"id": "wamid.X", "from": frm, "type": "text",
                "text": {"body": body}}

    def tap_msg(rid, frm, title="x"):
        return {"id": "wamid.T", "from": frm, "type": "interactive",
                "interactive": {"type": "button",
                                "button_reply": {"id": rid, "title": title}}}

    def list_tap_msg(rid, frm, title="x"):
        return {"id": "wamid.L", "from": frm, "type": "interactive",
                "interactive": {"type": "list_reply",
                                "list_reply": {"id": rid, "title": title}}}

    def _digits(s):
        return "".join(ch for ch in str(s or "") if ch.isdigit())

    def last(kind, to=None):
        # match on digits-only: client-directed + tap-ack sends go to the
        # raw 'from' (no '+'); cross-party notifies go to the stored
        # bot.user '+E.164' -- same number, different surface formatting.
        for e in reversed(_sent):
            if isinstance(e, tuple) and e[0] == kind \
                    and (to is None or _digits(e[1]) == _digits(to)):
                return e
        return None

    def sent_to(to):
        return [e for e in _sent
                if isinstance(e, tuple) and _digits(e[1]) == _digits(to)]

    def has_intent(btn_evt, intent):
        # WA-5.6: escalation/bounce now carry 3 buttons -- find an intent
        # among them rather than assuming a fixed position.
        if not btn_evt:
            return False
        for b in btn_evt[3]:
            d = wa_payload.decode(secret, b["id"])
            if d and d[0] == intent:
                return True
        return False

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
        st.enter_context(patch.object(WMcls, "send_template", s_template))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", _stub_chat))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "run_turn", spy_rt))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "handle_tap", spy_ht))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "variant_for", spy_vf))
        st.enter_context(patch.object(tool_registry, "dispatch", spy_disp))

        # =========================================================
        # A -- SANDBOX & ROUTING (the core)
        # =========================================================
        # A1: greeting + 3-button menu, UNSIGNED fixed ids
        _sent.clear(); _reset_spies()
        n_lead0 = Lead.search_count([])
        WM.handle_inbound(text_msg("hi", CLIENT_FROM), {})
        g = last("buttons", CLIENT_E164)
        ids = [b["id"] for b in g[3]] if g else []
        check("A1: unmapped -> greeting + 3-button menu",
              g and ids == ["cl_quote", "cl_services", "cl_team"], ids)
        check("A1: client button ids are UNSIGNED (not HMAC payloads)",
              all(wa_payload.decode(secret, i) is None for i in ids))
        check("A2: greeting invoked NO privileged path "
              "(run_turn/handle_tap/variant_for/dispatch == 0)",
              counters == {"run_turn": 0, "handle_tap": 0,
                           "variant_for": 0, "dispatch": 0}, dict(counters))
        check("A2: greeting created NO crm.lead",
              Lead.search_count([]) == n_lead0)

        # A3: "Our services" -> canned blurb, no pricing, spies 0, no lead
        _sent.clear(); _reset_spies()
        WM.handle_inbound(tap_msg("cl_services", CLIENT_FROM), {})
        svc_txt = last("text", CLIENT_E164)
        blurb = svc_txt[2].lower() if svc_txt else ""
        check("A3: services blurb sent, NO price/$ quoted",
              svc_txt and "$" not in svc_txt[2]
              and not any(w in blurb for w in
                          ("price", "cost ", "usd", "zig", "per ")),
              svc_txt[2] if svc_txt else None)
        check("A3: services tap -> spies still 0, no lead",
              counters["dispatch"] == 0 and counters["run_turn"] == 0
              and Lead.search_count([]) == n_lead0)

        # A4: "Request a quote" -> asks for details; step=awaiting_quote
        _sent.clear(); _reset_spies()
        WM.handle_inbound(tap_msg("cl_quote", CLIENT_FROM), {})
        sess = env["neon.wa.client.session"].sudo().search(
            [("phone_number", "=", CLIENT_E164)], limit=1)
        check("A4: quote tap -> awaiting_quote, no lead yet, spies 0",
              sess.step == "awaiting_quote"
              and Lead.search_count([]) == n_lead0
              and counters["run_turn"] == 0 and counters["dispatch"] == 0,
              sess.step)

        # A5: details text -> EXACTLY ONE raw crm.lead; spies 0; client ack
        _sent.clear(); _reset_spies()
        n_wl0 = WriteLog.search_count([])
        WM.handle_inbound(
            text_msg("Corporate dinner, 14/08/2026, Harare", CLIENT_FROM), {})
        n_lead1 = Lead.search_count([])
        lead = Lead.search([("phone", "=", CLIENT_E164)], limit=1)
        check("A5: quote details -> exactly ONE new crm.lead",
              n_lead1 == n_lead0 + 1, "%d -> %d" % (n_lead0, n_lead1))
        check("A5: CRITICAL -- no LLM/tool/money path "
              "(run_turn/handle_tap/variant_for/dispatch == 0)",
              counters == {"run_turn": 0, "handle_tap": 0,
                           "variant_for": 0, "dispatch": 0}, dict(counters))
        check("A5: CRITICAL -- write.log (money audit) UNCHANGED",
              WriteLog.search_count([]) == n_wl0)
        check("A5: client received a confirmation",
              last("text", CLIENT_E164) is not None)
        check("A5: session -> done, linked to the lead",
              sess.step == "done" and sess.lead_id.id == lead.id)

        # A6: pricing keyword in free text -> handoff (no price quoted)
        CL2_E164, CL2_FROM = "+263880001002", "263880001002"
        _sent.clear(); _reset_spies()
        nl = Lead.search_count([])
        WM.handle_inbound(
            text_msg("hi how much does a wedding cost?", CL2_FROM), {})
        check("A6: pricing free-text -> handoff lead created, spies 0",
              Lead.search_count([]) == nl + 1
              and counters["run_turn"] == 0 and counters["dispatch"] == 0)
        check("A6: pricing handoff -> Munashe notified, client NOT quoted",
              last("buttons", ESC_PHONE) is not None
              and "$" not in (last("text", CL2_E164) or ("", "", ""))[2])

        # A7: "talk to the team" button -> handoff
        CL3_E164, CL3_FROM = "+263880001003", "263880001003"
        _sent.clear(); _reset_spies()
        nl = Lead.search_count([])
        WM.handle_inbound(tap_msg("cl_team", CL3_FROM), {})
        check("A7: talk-to-team -> handoff lead + escalation notify, spies 0",
              Lead.search_count([]) == nl + 1
              and last("buttons", ESC_PHONE) is not None
              and counters["dispatch"] == 0 and counters["handle_tap"] == 0)

        # A8: handoff classifier word-boundary (no costume/celebrate match)
        check("A8: 'costume party' does NOT trip the pricing handoff",
              WM._wa5_is_handoff("we want a costume party") is False)
        check("A8: 'celebrate' does NOT trip 'rate'",
              WM._wa5_is_handoff("we want to celebrate") is False)
        check("A8: 'what is the price' DOES trip handoff",
              WM._wa5_is_handoff("what is the price") is True)

        # A9: MAPPED number -> staff assistant path (regression guard)
        _sent.clear(); _reset_spies()
        WM.handle_inbound(text_msg("hello", A_FROM), {})
        check("A9: mapped sender -> Copilot path (run_turn + variant_for)",
              counters["run_turn"] >= 1 and counters["variant_for"] >= 1,
              dict(counters))

        # =========================================================
        # B -- LEAD-CREATE CONTRACT
        # =========================================================
        check("B1: lead.partner_id EMPTY (no AI-created contact)",
              not lead.partner_id)
        check("B1: lead.contact_name EMPTY", not lead.contact_name)
        check("B1: lead.type == 'lead'", lead.type == "lead")
        check("B1: lead at lowest-sequence stage",
              lead.stage_id == env["crm.stage"].sudo().search(
                  [], order="sequence, id", limit=1))
        check("B1: lead tagged WhatsApp", tag and tag in lead.tag_ids)
        check("B1: lead source/medium == WhatsApp",
              lead.source_id == src and lead.medium_id == med)
        check("B1: lead.user_id EMPTY (unowned == escalation backstop)",
              not lead.user_id)
        check("B1: lead.phone == client E.164", lead.phone == CLIENT_E164)
        check("B1: date parsed from details (14/08/2026)",
              bool(lead.date_deadline)
              and str(lead.date_deadline) == "2026-08-14",
              lead.date_deadline)
        check("B2: intake mirrored to lead chatter",
              any("WhatsApp client intake" in (m.body or "")
                  for m in lead.message_ids))

        # =========================================================
        # C -- ESCALATION NOTIFY CONTENT + ACTIVITY FALLBACK
        # =========================================================
        # fresh notify so the buffer is deterministic (A6/A7 already
        # proved the end-to-end notify FIRES; C checks its CONTENT).
        _sent.clear()
        WM._wa5_notify_escalation(lead, CLIENT_E164)
        esc_btn = last("buttons", ESC_PHONE)
        edec = [wa_payload.decode(secret, b["id"])
                for b in (esc_btn[3] if esc_btn else [])]
        check("C1: WA-5.6 escalation = 3 reply-buttons incl. signed "
              "assign_open on the lead",
              esc_btn and len(esc_btn[3]) == 3
              and [d[0] for d in edec]
              == ["escalation_chat", "escalation_odoo", "assign_open"]
              and all(int(d[1][0]) == lead.id for d in edec),
              [d[0] if d else None for d in edec])
        check("C1: WA-5.4/5.6 escalation body is CLEAN (no raw wa.me/Odoo "
              "URLs) + keeps the client number",
              esc_btn and "wa.me/" not in esc_btn[2]
              and "/web#id=" not in esc_btn[2]
              and CLIENT_E164 in esc_btn[2], esc_btn[2] if esc_btn else None)
        check("C2: activity fallback on the lead (handoff never lost)",
              Act.search_count(
                  [("res_model", "=", "crm.lead"),
                   ("res_id", "=", lead.id)]) >= 1)
        check("C3: escalation resolved via LOGIN param (not hardcoded)",
              WM._wa5_escalation_botuser().user_id.id == esc_u.id)

        # C4: FIX A -- escalation UNRESOLVABLE (bad login) -> the activity
        # fallback must STILL land on a HUMAN (superuser/sales), never the
        # sudo OdooBot/system user (D4 'a handoff is never lost').
        root_id = env.ref("base.user_root").id
        env["ir.config_parameter"].sudo().set_param(
            "neon_channels.wa5_escalation_login", "wa5_does_not_exist")
        CL4_FROM = "263880001004"
        _sent.clear()
        WM.handle_inbound(text_msg("what's your pricing for a gala", CL4_FROM),
                          {})
        lead4 = Lead.search([("phone", "=", "+263880001004")], limit=1)
        acts4 = Act.search([("res_model", "=", "crm.lead"),
                            ("res_id", "=", lead4.id)]) if lead4 else Act
        check("C4: escalation unresolvable -> handoff lead still created",
              bool(lead4))
        check("C4: FIX A -- fallback activity lands on a HUMAN, not OdooBot",
              acts4 and all(a.user_id.id != root_id and not a.user_id.share
                            for a in acts4),
              acts4.mapped("user_id.login") if acts4 else None)
        # restore the escalation param for the D-section assignment loop
        env["ir.config_parameter"].sudo().set_param(
            "neon_channels.wa5_escalation_login", "wa5_esc_smoke")

        # =========================================================
        # D -- ASSIGNMENT LOOP (mapped staff via handle_tap)
        # =========================================================
        # D1: assignee set = sales ∩ bot.user minus escalation minus super
        au = WM._wa5_assignee_users()
        check("D1: assignee list = {assignee_a, assignee_b, su(Tatenda)}",
              set(au.ids) == {a_u.id, b_u.id, su_u.id}, au.mapped("login"))
        check("D1: escalation target (Munashe) EXCLUDED by login",
              esc_u.id not in au.ids)
        check("D1: OD/owner (Robin) EXCLUDED by login identity",
              owner_u.id not in au.ids)
        check("D1: CORRECTED RULE -- superuser-salesperson (Tatenda) STAYS "
              "assignable (not dropped by the superuser group)",
              su_u.id in au.ids)

        # D2: assign_open by escalation -> a LIST of the two assignees
        open_id = WM._wa5_payload("assign_open", lead.id)
        _sent.clear()
        WM.handle_inbound(tap_msg(open_id, ESC_FROM), {})
        lst = last("list", ESC_PHONE)
        rows = lst[3][0]["rows"] if lst else []
        picks = [wa_payload.decode(secret, r["id"]) for r in rows]
        check("D2: assign_open -> list of 3, rows carry assign_pick",
              lst and len(rows) == 3
              and all(p and p[0] == "assign_pick" for p in picks)
              and {int(p[1][1]) for p in picks}
              == {a_u.id, b_u.id, su_u.id}, picks)

        # D3: assign_open by a NON-authorised user -> refused
        _sent.clear()
        WM.handle_inbound(tap_msg(open_id, A_FROM), {})
        check("D3: non-manager assign_open refused (no list)",
              last("list", A_PHONE) is None
              and last("text", A_PHONE)
              and "manager" in last("text", A_PHONE)[2].lower())
        # superuser CAN open (D6 authorised)
        _sent.clear()
        WM.handle_inbound(tap_msg(open_id, SU_FROM), {})
        check("D3: superuser CAN open the assignee list (authorised)",
              last("list", SU_PHONE) is not None)

        # D4: assign_pick by escalation -> sets user_id + notifies assignee
        pick_a = WM._wa5_payload("assign_pick", lead.id, a_u.id)
        _sent.clear()
        WM.handle_inbound(list_tap_msg(pick_a, ESC_FROM), {})
        lead.invalidate_recordset()
        nbtn = last("buttons", A_PHONE)
        dbtns = [wa_payload.decode(secret, b["id"])
                 for b in (nbtn[3] if nbtn else [])]
        decb = next((d for d in dbtns if d and d[0] == "assignee_decline"),
                    None)
        check("D4: assign_pick set lead.user_id = assignee_a",
              lead.user_id.id == a_u.id, lead.user_id.login)
        check("D4: WA-5.3 assignee notify = 3 buttons "
              "(assignee_chat / assignee_odoo / assignee_decline)",
              nbtn and len(nbtn[3]) == 3
              and {d[0] for d in dbtns if d}
              == {"assignee_chat", "assignee_odoo", "assignee_decline"}
              and decb and int(decb[1][1]) == a_u.id,
              [d[0] if d else None for d in dbtns])

        # D5/D6: decline two-factor -- WRONG sender refused first
        dec_a = WM._wa5_payload("assignee_decline", lead.id, a_u.id)
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_a, B_FROM), {})  # B declines A's lead
        lead.invalidate_recordset()
        check("D6: decline by a NON-assigned sender refused (two-factor)",
              lead.user_id.id == a_u.id
              and last("text", B_PHONE)
              and "isn't linked" in last("text", B_PHONE)[2], lead.user_id.id)

        # D5: the assigned user declines -> clears user_id + bounces back
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_a, A_FROM), {})
        lead.invalidate_recordset()
        check("D5: assigned user's decline CLEARS user_id (unowned)",
              not lead.user_id)
        check("D5: decline bounces back to escalation (assign_open among "
              "the 3 buttons)",
              has_intent(last("buttons", ESC_PHONE), "assign_open"))
        check("D7: NEVER auto-reassigned -- still unowned after decline",
              not lead.user_id)

        # idempotency: a second decline of an already-unowned lead is safe
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_a, A_FROM), {})
        check("D5: re-decline of an unowned lead is idempotent (no crash)",
              last("text", A_PHONE) is not None)

        # =========================================================
        # E -- ESCALATE-ONCE GUARD (WA-5.0 #1)
        # =========================================================
        CE_E164, CE_FROM = "+263880001010", "263880001010"
        _sent.clear(); _templates.clear()
        WM.handle_inbound(tap_msg("cl_quote", CE_FROM), {})
        WM.handle_inbound(
            text_msg("Gala dinner, 20/09/2026, Bulawayo", CE_FROM), {})
        lead_e = Lead.search([("phone", "=", CE_E164)], limit=1)

        def esc_acts(l):
            return Act.search_count(
                [("res_model", "=", "crm.lead"), ("res_id", "=", l.id),
                 ("summary", "ilike", "assign a salesperson")])
        acts1 = esc_acts(lead_e)
        # repeated client msgs (handoff keywords) must NOT re-escalate
        WM.handle_inbound(text_msg("what's the price?", CE_FROM), {})
        WM.handle_inbound(text_msg("any discount available?", CE_FROM), {})
        acts2 = esc_acts(lead_e)
        check("E1: unowned lead escalates ONCE across repeated client msgs",
              acts1 == 1 and acts2 == 1, "%s -> %s" % (acts1, acts2))
        check("E1: no duplicate lead for the same client phone",
              Lead.search_count([("phone", "=", CE_E164)]) == 1)
        check("E1: follow-up client msgs appended to chatter (no re-fire)",
              sum(1 for m in lead_e.message_ids
                  if "follow-up" in (m.body or "")) >= 2)

        # =========================================================
        # F -- WINDOW-AWARE SEND (WA-5.1) on all 3 notify paths
        # =========================================================
        # b_u accumulated an inbound when B_FROM tapped in D6 -> cool it so
        # the closed-window path is genuinely exercised.
        cool(B_PHONE)
        check("F1: window OPEN for a warmed phone, CLOSED for a cold one",
              WM._wa5_window_open(ESC_PHONE) is True
              and WM._wa5_window_open(B_PHONE) is False
              and WM._wa5_window_open("+263000000000") is False)

        # open-window escalation -> interactive (esc warm), NO template
        _sent.clear(); _templates.clear()
        WM._wa5_notify_escalation(lead_e, CE_E164)
        check("F2: open window -> interactive buttons, no template",
              last("buttons", ESC_PHONE) is not None
              and not any(t["name"] == "wa5_lead_handoff"
                          for t in _templates))

        # closed-window assignee -> wa5_lead_assigned (WA-5.7: 3 params --
        # name, summary, CLIENT PHONE -- matching the Meta-Active template)
        _sent.clear(); _templates.clear()
        WM._wa5_notify_assignee(lead_e, b_u)   # b_u is COLD
        tA = next((t for t in _templates
                   if _digits(t["to"]) == _digits(B_PHONE)), None)
        qrA = wa_payload.decode(secret, tA["qr"][0]) if (tA and tA["qr"]) \
            else None
        check("F3: closed window (assignee) -> wa5_lead_assigned, en_US, "
              "3 params (name, summary, client) in order",
              tA and tA["name"] == "wa5_lead_assigned"
              and len(tA["params"]) == 3 and tA["lang"] == "en_US"
              and tA["params"][2] == (lead_e.phone or "—"), tA)
        check("F3: assignee template carries the assignee_decline payload "
              "(no URL button -- wa.me banned)",
              qrA and qrA[0] == "assignee_decline"
              and int(qrA[1][1]) == b_u.id, qrA)
        check("F3: closed-window send STILL lands the Odoo activity (D4)",
              Act.search_count(
                  [("res_model", "=", "crm.lead"),
                   ("res_id", "=", lead_e.id),
                   ("user_id", "=", b_u.id)]) >= 1)

        # closed-window escalation -> template wa5_lead_handoff
        cool(ESC_PHONE)
        _sent.clear(); _templates.clear()
        WM._wa5_notify_escalation(lead_e, CE_E164)
        tH = next((t for t in _templates
                   if _digits(t["to"]) == _digits(ESC_PHONE)), None)
        qrH = wa_payload.decode(secret, tH["qr"][0]) if (tH and tH["qr"]) \
            else None
        check("F4: closed window (escalation) -> wa5_lead_handoff, 2 params",
              tH and tH["name"] == "wa5_lead_handoff"
              and len(tH["params"]) == 2, tH)
        check("F4: handoff template carries the assign_open payload",
              qrH and qrH[0] == "assign_open", qrH)
        warm(ESC_PHONE)   # restore the window for the G-section bounce

        # =========================================================
        # G -- DECLINE SPLIT-STATES + assign_pick idempotency (WA-5.0 #2/#1)
        # =========================================================
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_e.id, a_u.id), ESC_FROM), {})
        lead_e.invalidate_recordset()
        dec_e = WM._wa5_payload("assignee_decline", lead_e.id, a_u.id)
        # G1: non-assigned sender -> two-factor refuse, owner intact
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_e, B_FROM), {})
        lead_e.invalidate_recordset()
        check("G1: decline by a NON-assigned sender refused (two-factor)",
              lead_e.user_id.id == a_u.id
              and "isn't linked" in (last("text", B_FROM)
                                     or ("", "", ""))[2])
        # G2: current owner declines -> cleared + 'sent back' + re-notify
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_e, A_FROM), {})
        lead_e.invalidate_recordset()
        ackG = last("text", A_FROM)
        check("G2: current-owner decline CLEARS user_id", not lead_e.user_id)
        check("G2: reply = 'sent it back to the team' (NOT 'reassigned')",
              ackG and "sent it back to the team" in ackG[2]
              and "reassigned" not in ackG[2].lower(),
              ackG[2] if ackG else None)
        check("G2: bounce re-notifies Munashe (assign_open among the 3 "
              "buttons)",
              has_intent(last("buttons", ESC_PHONE), "assign_open"))
        # G3: same user declines AGAIN (now unowned) -> 'already declined'
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_e, A_FROM), {})
        ackG3 = last("text", A_FROM)
        check("G3: double-decline -> 'already declined' (idempotent friendly)",
              ackG3 and "already declined" in ackG3[2].lower(),
              ackG3[2] if ackG3 else None)
        # G4: a DIFFERENT user holds it -> 'reassigned to someone else'
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_e.id, b_u.id), ESC_FROM), {})
        lead_e.invalidate_recordset()
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_e, A_FROM), {})  # a_u's old payload
        ackG4 = last("text", A_FROM)
        check("G4: decline when a DIFFERENT user holds it -> 'someone else'",
              ackG4 and "someone else" in ackG4[2].lower(),
              ackG4[2] if ackG4 else None)
        # G5: assign_pick IDEMPOTENT -- repeat tap of the SAME pick = no-op
        _sent.clear()
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_e.id, b_u.id), ESC_FROM), {})
        ackG5 = last("text", ESC_FROM)
        check("G5: assign_pick repeat tap -> no-op ack ('already has')",
              ackG5 and "already has this lead" in ackG5[2].lower(),
              ackG5[2] if ackG5 else None)

        # =========================================================
        # H -- TEMPLATE type='button' tap routes to handle_tap
        # =========================================================
        _sent.clear()
        WM.handle_inbound({"id": "wamid.BTN", "from": ESC_FROM,
                           "type": "button",
                           "button": {"payload": WM._wa5_payload(
                               "assign_open", lead_e.id),
                               "text": "Assign salesperson"}}, {})
        check("H1: template button tap (type=button) -> handle_tap -> list",
              last("list", ESC_FROM) is not None)

        # =========================================================
        # HTML -- html2plaintext on every body + summary (no leaked tags)
        # =========================================================
        ht = Lead.sudo().create({
            "name": "HTMLTEST", "type": "lead",
            "description": "<p>Corporate <b>gala</b> &amp; awards</p>"})
        summ = WM._wa5_lead_summary(ht)
        check("HTML: _wa5_lead_summary strips tags from the Html description",
              "<" not in summ and ">" not in summ and "gala" in summ, summ)
        _sent.clear()
        WM._wa5_notify_escalation(ht, "+263880001099")
        eb = last("buttons", ESC_PHONE)
        check("HTML: escalation body has NO raw </> (html2plaintext clean)",
              eb and "<" not in eb[2] and ">" not in eb[2],
              eb[2] if eb else None)

        # FIX-A: the activity fallback recipient is ALWAYS a real human
        # (never empty / OdooBot / a portal user) -- the D4 'never lost'
        # promise holds even with a broken escalation + empty su/sales set.
        fb = WM._wa5_fallback_human()
        check("FIXA: _wa5_fallback_human always resolves a real human",
              fb and fb.id and not fb.share
              and fb.id != env.ref("base.user_root").id,
              fb.login if fb else None)

        # =========================================================
        # I -- WA-5.2 DEBOUNCED RE-HANDOFF (returning-client follow-up)
        # =========================================================
        Sess = env["neon.wa.client.session"].sudo()

        def esc_acts_for(l):
            return Act.search_count(
                [("res_model", "=", "crm.lead"), ("res_id", "=", l.id),
                 ("summary", "ilike", "assign a salesperson")])

        # fresh client -> quote -> UNOWNED lead; session done + last_notify
        CI_E164, CI_FROM = "+263880001020", "263880001020"
        _sent.clear(); _templates.clear()
        WM.handle_inbound(tap_msg("cl_quote", CI_FROM), {})
        WM.handle_inbound(
            text_msg("Launch event, 02/10/2026, Vic Falls", CI_FROM), {})
        lead_i = Lead.search([("phone", "=", CI_E164)], limit=1)
        sess_i = Sess.search([("phone_number", "=", CI_E164)], limit=1)
        check("I0: initial escalation stamped last_notify, lead unowned",
              bool(sess_i.last_notify) and not lead_i.user_id)

        # I1: RAPID duplicate (last_notify just set) -> DEBOUNCED, no re-fire
        _sent.clear(); _templates.clear()
        before = esc_acts_for(lead_i)
        WM.handle_inbound(text_msg("any update on pricing?", CI_FROM), {})
        ackI1 = last("text", CI_FROM)
        check("I1: rapid follow-up DEBOUNCED -> NO second escalation",
              esc_acts_for(lead_i) == before
              and not any(_digits(t["to"]) == _digits(ESC_PHONE)
                          for t in _templates))
        check("I1: debounced ack is honest (no false 'be in touch' promise)",
              ackI1 and "your enquiry" in ackI1[2].lower()
              and "be in touch" not in ackI1[2].lower(),
              ackI1[2] if ackI1 else None)
        check("I1: follow-up still appended to the lead chatter",
              any("follow-up" in (m.body or "") for m in lead_i.message_ids))

        # I2: STALE follow-up (force last_notify into the past) on an
        # UNOWNED lead -> RE-ESCALATE Munashe (window cold -> template)
        sess_i.write(
            {"last_notify": fields.Datetime.now() - _td(minutes=30)})
        cool(ESC_PHONE)
        _sent.clear(); _templates.clear()
        WM.handle_inbound(
            text_msg("following up on my quote please", CI_FROM), {})
        sess_i.invalidate_recordset()
        tI = next((t for t in _templates
                   if _digits(t["to"]) == _digits(ESC_PHONE)), None)
        check("I2: stale follow-up, UNOWNED -> re-escalate Munashe (template)",
              tI and tI["name"] == "wa5_lead_handoff", tI)
        check("I2: re-notify stamped a FRESH last_notify",
              sess_i.last_notify
              and (fields.Datetime.now() - sess_i.last_notify)
              < _td(minutes=5))
        ackI2 = last("text", CI_FROM)
        check("I2: re-notified ack promises contact ('be in touch')",
              ackI2 and "be in touch" in ackI2[2].lower(),
              ackI2[2] if ackI2 else None)
        warm(ESC_PHONE)

        # I3: ASSIGNED lead + stale follow-up -> ping the ASSIGNEE, not Munashe
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_i.id, a_u.id), ESC_FROM), {})
        lead_i.invalidate_recordset()
        sess_i.write(
            {"last_notify": fields.Datetime.now() - _td(minutes=30)})
        _sent.clear(); _templates.clear()
        WM.handle_inbound(text_msg("when can we meet?", CI_FROM), {})
        pa = last("buttons", A_PHONE)
        check("I3: assigned-lead follow-up pings the ASSIGNEE (a_u), "
              "NOT Munashe",
              pa is not None and last("buttons", ESC_PHONE) is None
              and not any(_digits(t["to"]) == _digits(ESC_PHONE)
                          for t in _templates))
        check("I3: assignee follow-up ping carries the 'follow-up' framing",
              pa and "follow-up" in pa[2].lower(), pa[2] if pa else None)

        # CHATTER: Markup render -- <b> kept, client text auto-escaped
        # (fixes the &lt;b&gt; leak seen since WA-5)
        WM.handle_inbound(
            text_msg("hi pricing for a & b launch", "263880001030"), {})
        lead_ch = Lead.search([("phone", "=", "+263880001030")], limit=1)
        intake = next((m for m in lead_ch.message_ids
                       if "client intake" in (m.body or "")), None)
        check("CHATTER: intake renders <b> (NOT &lt;b&gt;) via Markup",
              intake and "<b>" in intake.body
              and "&lt;b&gt;" not in intake.body,
              (intake.body[:90] if intake else None))

        # TTL: a >24h-idle return is a FULL clean slate -- step + lead_id +
        # last_notify all cleared (so a fresh conversation isn't gated by a
        # stale debounce stamp).
        CT_E164 = "+263880001040"
        Sess.create({"phone_number": CT_E164, "step": "done",
                     "lead_id": lead_i.id,
                     "last_inbound": fields.Datetime.now() - _td(hours=30),
                     "last_notify": fields.Datetime.now() - _td(hours=30)})
        st2 = Sess._get_or_start(CT_E164)
        check("TTL: >24h reset clears step + lead_id + last_notify (clean slate)",
              st2.step == "greeted" and not st2.lead_id
              and not st2.last_notify)

        # =========================================================
        # J -- WA-5.3 three-button assignee + chat/odoo link replies +
        #      decline-once + hard-lock idempotency
        # =========================================================
        CJ_E164, CJ_FROM = "+263880001050", "263880001050"
        WM.handle_inbound(
            text_msg("hi pricing for a product launch", CJ_FROM), {})
        lead_j = Lead.search([("phone", "=", CJ_E164)], limit=1)
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_j.id, a_u.id), ESC_FROM), {})
        lead_j.invalidate_recordset()

        # J1: 'Chat with client' tap -> reply carries the wa.me link
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("assignee_chat", lead_j.id), A_FROM), {})
        rc = last("text", A_FROM)
        check("J1: 'Chat with client' tap -> reply carries the wa.me link",
              rc and "wa.me/" in rc[2] and _digits(CJ_E164) in rc[2],
              rc[2] if rc else None)

        # J2: 'Open in Odoo' tap -> reply carries the /web#id= lead link
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("assignee_odoo", lead_j.id), A_FROM), {})
        ro = last("text", A_FROM)
        check("J2: 'Open in Odoo' tap -> reply carries the Odoo lead link",
              ro and ("/web#id=%s" % lead_j.id) in ro[2],
              ro[2] if ro else None)

        # J3: FIRST decline by the owner -> 'sent it back', user_id cleared,
        # NEVER 'already declined' on a first tap
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("assignee_decline", lead_j.id, a_u.id), A_FROM),
            {})
        lead_j.invalidate_recordset()
        ad = last("text", A_FROM)
        check("J3: first decline -> 'sent it back' + cleared, NOT "
              "'already declined'",
              not lead_j.user_id and ad
              and "sent it back to the team" in ad[2]
              and "already declined" not in ad[2].lower(),
              ad[2] if ad else None)
        check("J3b: bounce re-notified Munashe ONCE (assign_open among the "
              "3 buttons)",
              has_intent(last("buttons", ESC_PHONE), "assign_open"))

        # J4: hard-lock helper acquires (sanity; cross-tx protection isn't
        # unit-testable in a single shell transaction)
        check("J4: _wa5_try_lock acquires the per-lead advisory lock",
              WM._wa5_try_lock(lead_j) is True)

        # J5: repeat assign_pick of the SAME user -> no-op ack (idempotent)
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_j.id, b_u.id), ESC_FROM), {})
        lead_j.invalidate_recordset()
        _sent.clear()
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_j.id, b_u.id), ESC_FROM), {})
        rr = last("text", ESC_FROM)
        check("J5: repeat assign_pick (same user) -> no-op ack ('already has')",
              lead_j.user_id.id == b_u.id and rr
              and "already has this lead" in rr[2].lower(),
              rr[2] if rr else None)

        # =========================================================
        # K -- WA-5.4 prod-fix: the user_id write must NOT fire the native
        #      CRM assignment notification (the public-env read -> 403 ->
        #      rollback that lost user_id on prod). The smoke runs admin /
        #      single-tx so it can't reproduce the deferred-flush 403, but
        #      it CAN prove the trigger is gone: no assignment tracking
        #      message + no AccessError under a public-user flush.
        # =========================================================
        MailMail = env["mail.mail"].sudo()
        CK_E164, CK_FROM = "+263880001060", "263880001060"
        WM.handle_inbound(
            text_msg("hi pricing for a corporate gala", CK_FROM), {})
        lead_k = Lead.search([("phone", "=", CK_E164)], limit=1)
        msgs_before = len(lead_k.message_ids)
        mail_before = MailMail.search_count([])
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_k.id, a_u.id), ESC_FROM), {})
        lead_k.invalidate_recordset()
        check("K1: assign persists user_id (write not rolled back)",
              lead_k.user_id.id == a_u.id,
              lead_k.user_id.login if lead_k.user_id else None)
        check("K2: assign fires NO native CRM tracking message on the lead "
              "(tracking_disable -- the prod 403 trigger is gone)",
              len(lead_k.message_ids) == msgs_before,
              "%d -> %d" % (msgs_before, len(lead_k.message_ids)))
        # K3: the FULL assign+notify+ACTIVITY under a PUBLIC env + flush must
        # NOT raise an AccessError on crm.lead -- this exercises the actual
        # WA-5.3 prod 403 path end-to-end (incl. the activity notification,
        # a possible SECOND trigger the user_id-write fix alone wouldn't
        # cover). (+1 mail.mail from the activity is legitimate, not the
        # bug; K2 already proved the CRM tracking notification is gone.)
        WM.handle_inbound(
            text_msg("hi pricing for an awards night", "263880001062"), {})
        lead_p2 = Lead.search([("phone", "=", "+263880001062")], limit=1)
        raised2 = None
        try:
            envp2 = env(user=env.ref("base.public_user").id)
            WMp2 = envp2["neon.whatsapp.message"].sudo()
            WMp2._wa5_set_owner(lead_p2, a_u.id)
            WMp2._wa5_notify_assignee(lead_p2, a_u)
            envp2.flush_all()
        except Exception as e:  # noqa: BLE001
            raised2 = type(e).__name__
        check("K3: full assign+notify+activity under PUBLIC env + flush does "
              "NOT raise (the whole prod 403 path)",
              raised2 is None and lead_p2.sudo().user_id.id == a_u.id,
              raised2)

        # K4: the WA-5.3 prod failure path -- the user_id write + a flush
        # under a PUBLIC-user env must NOT raise an AccessError on crm.lead.
        pub_id = env.ref("base.public_user").id
        WM.handle_inbound(
            text_msg("hi pricing for a launch party", "263880001061"), {})
        lead_p = Lead.search([("phone", "=", "+263880001061")], limit=1)
        raised = None
        try:
            envp = env(user=pub_id)
            envp["neon.whatsapp.message"].sudo()._wa5_set_owner(
                lead_p, a_u.id)
            envp.flush_all()
        except Exception as e:  # noqa: BLE001
            raised = type(e).__name__
        check("K4: user_id write + flush under PUBLIC env does NOT raise "
              "(no deferred public crm.lead read)",
              raised is None and lead_p.sudo().user_id.id == a_u.id, raised)

        # K5: the webhook controller flushes inside its own try (defense)
        # AND under SUPERUSER. WA-5.5: K5 used to assert only that flush_all()
        # + rollback() were present -- it did NOT assert the flush ran as
        # sudo, which is precisely the gap that let the prod bug through. In
        # the PUBLIC controller env, request.env.flush_all() recomputed a
        # deferred crm.lead field -> AccessError -> rollback undid the
        # assignment + audit + lock (sends already gone) -> unaudited Meta
        # re-delivery storm. The binding guard is: the flush MUST be
        # su-scoped, so the deferred recompute bypasses the public ACL.
        import inspect as _insp
        from odoo.addons.neon_channels.controllers import webhook as _wh
        _src = _insp.getsource(_wh.WhatsAppWebhookController.webhook_receive)
        _flush_is_sudo = ("(su=True).flush_all()" in _src.replace(" ", "")) \
            or ("env(su=True).flush_all()" in _src.replace(" ", ""))
        check("K5: webhook controller flushes inside its try (caught + 200, "
              "no retry storm)",
              "flush_all()" in _src and "rollback()" in _src)
        check("K5b: that flush is SUPERUSER-scoped -- env(su=True).flush_all() "
              "-- so a deferred crm.lead recompute can't 403+rollback the "
              "assign under the public webhook env (WA-5.5)",
              _flush_is_sudo,
              "su-flush present" if _flush_is_sudo else "BARE public flush!")

        # K6: the EXACT controller path -- handle_inbound under a PUBLIC env
        # (uid 4) THEN the controller's su-scoped flush -- end to end. Proves
        # the assignment PERSISTS (rollback gone), the audit row SURVIVES, and
        # a 2nd identical Meta delivery is an idempotent no-op (no re-send).
        # NOTE: the smoke is single-tx/admin and can't reproduce the deferred
        # crm.lead 403 in-process (same limitation that hid the bug from
        # K3/K4) -- K5b is the binding source guard; K6 exercises the
        # persist/audit/idempotency behaviour the fix must preserve, and the
        # post-deploy SQL verify on a real assign is the ground-truth proof.
        WAM = env["neon.whatsapp.message"].sudo()
        WM.handle_inbound(
            text_msg("hi pricing for a product launch", "263880001064"), {})
        lead_k6 = Lead.search([("phone", "=", "+263880001064")], limit=1)
        audit_before = WAM.search_count([("direction", "=", "outbound")])
        raised6 = None
        try:
            pub = env(user=env.ref("base.public_user").id)
            # EXACTLY as the controller does it: sudo handle_inbound, then a
            # su-scoped flush of the public request env.
            pub["neon.whatsapp.message"].sudo().handle_inbound(
                list_tap_msg(
                    WM._wa5_payload("assign_pick", lead_k6.id, a_u.id),
                    ESC_FROM), {})
            pub(su=True).flush_all()
        except Exception as e:  # noqa: BLE001
            raised6 = type(e).__name__
        lead_k6.invalidate_recordset()
        audit_after = WAM.search_count([("direction", "=", "outbound")])
        check("K6a: controller path (public handle_inbound + su-flush) does "
              "NOT raise", raised6 is None, raised6)
        check("K6b: user_id PERSISTS through the public-env flush "
              "(the prod rollback that lost assignments is gone)",
              lead_k6.user_id.id == a_u.id,
              lead_k6.user_id.login if lead_k6.user_id else "UNOWNED")
        check("K6c: the outbound audit row SURVIVES the flush "
              "(not rolled back -> no more invisible sends)",
              audit_after > audit_before,
              "%d -> %d" % (audit_before, audit_after))
        _sent.clear()
        pub2 = env(user=env.ref("base.public_user").id)
        pub2["neon.whatsapp.message"].sudo().handle_inbound(
            list_tap_msg(
                WM._wa5_payload("assign_pick", lead_k6.id, a_u.id),
                ESC_FROM), {})
        pub2(su=True).flush_all()
        rr6 = last("text", ESC_FROM)
        check("K6d: 2nd identical Meta delivery -> idempotent no-op "
              "('already has', no re-assign, no re-send to assignee)",
              lead_k6.user_id.id == a_u.id and rr6
              and "already has this lead" in rr6[2].lower(),
              rr6[2] if rr6 else None)

        # =========================================================
        # L -- WA-5.6 MANAGER (escalation) THREE-button message
        # =========================================================
        CL_E164, CL_FROM = "+263880001070", "263880001070"
        WM.handle_inbound(
            text_msg("hi pricing for a corporate retreat", CL_FROM), {})
        lead_l = Lead.search([("phone", "=", CL_E164)], limit=1)
        _sent.clear()
        WM._wa5_notify_escalation(lead_l, CL_E164)   # esc warm -> interactive
        eb = last("buttons", ESC_PHONE)
        ed = [wa_payload.decode(secret, b["id"]) for b in (eb[3] if eb else [])]
        check("L1: escalation = 3 reply-buttons "
              "(escalation_chat / escalation_odoo / assign_open) on the lead",
              eb and len(eb[3]) == 3
              and [d[0] for d in ed]
              == ["escalation_chat", "escalation_odoo", "assign_open"]
              and all(int(d[1][0]) == lead_l.id for d in ed),
              [d[0] if d else None for d in ed])
        check("L1: escalation body keeps the client number",
              eb and CL_E164 in eb[2], eb[2] if eb else None)

        # L2: Chat tap -> wa.me reply; Odoo tap -> lead-link reply
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("escalation_chat", lead_l.id), ESC_FROM), {})
        rcl = last("text", ESC_FROM)
        check("L2: escalation_chat tap -> wa.me link reply",
              rcl and "wa.me/" in rcl[2] and _digits(CL_E164) in rcl[2],
              rcl[2] if rcl else None)
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("escalation_odoo", lead_l.id), ESC_FROM), {})
        rol = last("text", ESC_FROM)
        check("L2: escalation_odoo tap -> Odoo lead-link reply",
              rol and ("/web#id=%s" % lead_l.id) in rol[2],
              rol[2] if rol else None)

        # L3: assign_open still opens the assignee LIST (unchanged flow)
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("assign_open", lead_l.id), ESC_FROM), {})
        check("L3: assign_open still renders the assignee LIST (unchanged)",
              last("list", ESC_FROM) is not None)

        # L4: the decline-bounce to Munashe ALSO carries the 3 buttons
        WM.handle_inbound(list_tap_msg(
            WM._wa5_payload("assign_pick", lead_l.id, a_u.id), ESC_FROM), {})
        _sent.clear()
        WM.handle_inbound(tap_msg(
            WM._wa5_payload("assignee_decline", lead_l.id, a_u.id), A_FROM),
            {})
        bb = last("buttons", ESC_PHONE)
        bd = [wa_payload.decode(secret, b["id"]) for b in (bb[3] if bb else [])]
        check("L4: decline-bounce to Munashe = same 3 buttons "
              "(chat / odoo / assign)",
              bb and len(bb[3]) == 3
              and [d[0] for d in bd]
              == ["escalation_chat", "escalation_odoo", "assign_open"],
              [d[0] if d else None for d in bd])

        # L5: the ASSIGNEE path is UNCHANGED (its 3 buttons end in
        # assignee_decline, NOT assign_open)
        ab = [wa_payload.decode(secret, b["id"])
              for b in WM._wa5_assignee_buttons(lead_l, a_u)]
        check("L5: assignee buttons untouched "
              "(chat / odoo / assignee_decline)",
              [d[0] for d in ab]
              == ["assignee_chat", "assignee_odoo", "assignee_decline"],
              [d[0] for d in ab])

        # =========================================================
        # M -- TEST-INFRA: reset a DESIGNATED test client (re-runnable)
        # =========================================================
        from odoo.exceptions import UserError as _UserErr
        ttag = env.ref("neon_channels.crm_tag_test_client",
                       raise_if_not_found=False)
        check("M0: TEST-CLIENT crm.tag installed", bool(ttag))

        # designate a standing test number
        TEST_E164, TEST_FROM = "+263880009999", "263880009999"
        env["ir.config_parameter"].sudo().set_param(
            "neon_channels.wa5_test_numbers", TEST_E164)
        check("M0: number is designated; a non-listed number is not",
              WM._wa5_is_test_number(TEST_E164)
              and not WM._wa5_is_test_number("+263880008888"))

        # run the flow: greet -> quote -> lead (auto-tagged TEST-CLIENT)
        _sent.clear()
        WM.handle_inbound(tap_msg("cl_quote", TEST_FROM), {})
        WM.handle_inbound(
            text_msg("Test gala, 01/12/2026, Harare", TEST_FROM), {})
        lead_t = Lead.search([("phone", "=", TEST_E164)], limit=1)
        sess_t = env["neon.wa.client.session"].sudo().search(
            [("phone_number", "=", TEST_E164)], limit=1)
        check("M1: a designated number's lead is auto-tagged TEST-CLIENT",
              lead_t and ttag and ttag in lead_t.tag_ids)
        check("M1: session reached 'done' with a lead (pre-reset state)",
              sess_t.step == "done" and sess_t.lead_id.id == lead_t.id)

        # reset
        lead_t_id = lead_t.id
        res = WM._wa5_reset_test_client(TEST_FROM)
        sess_t.invalidate_recordset()
        check("M2: reset DELETES the TEST-CLIENT lead",
              not Lead.search_count([("id", "=", lead_t_id)])
              and res["leads_deleted"] >= 1, res)
        check("M2: reset RESETS the session to a fresh-greeting state",
              sess_t.step == "greeted" and not sess_t.lead_id
              and not sess_t.last_notify and res["sessions_reset"] == 1)
        check("M2: reset PURGES the test number's own WhatsApp audit rows",
              WM.search_count([("phone_number", "=", TEST_E164)]) == 0
              and res["messages_purged"] >= 1, res)

        # after reset, the SAME number greets FRESH (not a returning client)
        _sent.clear(); _reset_spies()
        WM.handle_inbound(text_msg("hi again", TEST_FROM), {})
        g2 = last("buttons", TEST_E164)
        check("M3: SAME number after reset -> fresh 3-button greeting "
              "(not a returning-client follow-up), spies 0",
              g2 and [b["id"] for b in g2[3]]
              == ["cl_quote", "cl_services", "cl_team"]
              and counters["run_turn"] == 0
              and counters["handle_tap"] == 0,
              [b["id"] for b in g2[3]] if g2 else None)

        # SAFETY GATE: a NON-designated number is REFUSED (can't wipe a
        # real client) -- and that client's lead is NOT deleted.
        raised_rst = None
        try:
            WM._wa5_reset_test_client("+263880008888")
        except _UserErr:
            raised_rst = "UserError"
        except Exception as e:  # noqa: BLE001
            raised_rst = type(e).__name__
        check("M4: reset REFUSES a non-designated number (UserError)",
              raised_rst == "UserError", raised_rst)
        check("M4: the real client's lead survives a refused reset attempt",
              Lead.search_count([("id", "=", lead.id)]) == 1)

        # a REAL (never-designated) client's lead is NOT tagged TEST-CLIENT
        check("M5: a real (non-test) client's lead is NOT tagged TEST-CLIENT",
              ttag and ttag not in lead.tag_ids)

        # one-click server-action entry resets ALL designated numbers and
        # returns a display_notification (the UI path)
        WM.handle_inbound(tap_msg("cl_quote", TEST_FROM), {})
        WM.handle_inbound(
            text_msg("Another test, 02/12/2026, Harare", TEST_FROM), {})
        check("M6: pre-action -- a fresh TEST-CLIENT lead exists",
              Lead.search_count([("phone", "=", TEST_E164)]) == 1)
        act = WM._wa5_reset_test_clients_action()
        check("M6: server-action returns a success display_notification",
              isinstance(act, dict)
              and act.get("tag") == "display_notification"
              and act["params"]["type"] == "success", act)
        check("M6: server-action reset cleared the re-created test lead",
              not Lead.search_count([("phone", "=", TEST_E164)]))

        # empty designation -> the action is a friendly warning, no-op
        env["ir.config_parameter"].sudo().set_param(
            "neon_channels.wa5_test_numbers", "")
        act0 = WM._wa5_reset_test_clients_action()
        check("M7: no designated numbers -> warning notification (no crash)",
              isinstance(act0, dict)
              and act0["params"]["type"] == "warning", act0)

        # the server-action record is installed + admin-gated
        sa = env.ref("neon_channels.action_wa5_reset_test_client",
                     raise_if_not_found=False)
        check("M8: 'Reset WA-5 Test Client' server action installed, "
              "bound to the session model, group_system-gated",
              sa and sa.model_id.model == "neon.wa.client.session"
              and env.ref("base.group_system") in sa.groups_id)

    # ---- regression bar --------------------------------------------
    check("REG: 3 WA-5 intents in wa_payload INTENTS",
          {"assign_open", "assign_pick", "assignee_decline"}
          <= wa_payload.INTENTS)
    check("REG: Copilot tool counts UNCHANGED (no new tool registered)",
          len(tool_registry.list_tools(category="read")) == 14
          and len(tool_registry.list_tools(category="write")) == 4)

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