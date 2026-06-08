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
counters = {"run_turn": 0, "handle_tap": 0, "variant_for": 0, "dispatch": 0}


def _reset_spies():
    for k in counters:
        counters[k] = 0


try:
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

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
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
        dec = wa_payload.decode(secret, esc_btn[3][0]["id"]) if esc_btn else None
        check("C1: escalation notified with a signed assign_open button",
              dec and dec[0] == "assign_open" and int(dec[1][0]) == lead.id,
              dec)
        check("C1: escalation body carries wa.me + Odoo deep-links",
              esc_btn and "wa.me/" in esc_btn[2] and "/web#id=" in esc_btn[2])
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
        ndec = wa_payload.decode(secret, nbtn[3][0]["id"]) if nbtn else None
        check("D4: assign_pick set lead.user_id = assignee_a",
              lead.user_id.id == a_u.id, lead.user_id.login)
        check("D4: assignee notified with an assignee_decline button",
              ndec and ndec[0] == "assignee_decline"
              and int(ndec[1][1]) == a_u.id, ndec)

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
        check("D5: decline bounces back to escalation (assign_open button)",
              (lambda e: e and (wa_payload.decode(secret, e[3][0]["id"])
                                or [None])[0] == "assign_open")(
                  last("buttons", ESC_PHONE)))
        check("D7: NEVER auto-reassigned -- still unowned after decline",
              not lead.user_id)

        # idempotency: a second decline of an already-unowned lead is safe
        _sent.clear()
        WM.handle_inbound(tap_msg(dec_a, A_FROM), {})
        check("D5: re-decline of an unowned lead is idempotent (no crash)",
              last("text", A_PHONE) is not None)

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