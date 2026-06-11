# -*- coding: utf-8 -*-
"""B11 / WA-10 post-event feedback loop smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http \
        < pwa10_feedback_smoke.py

NOTE: WA-10 adds columns + ir.rules -> run a local `-u neon_jobs,
neon_crew_comms,neon_channels` ONCE before this (the shell sees the new
schema). REAL dispatch path (handle_inbound taps + command); mocked sends;
rolls back.

PUSH    check-in landing -> prompts to EXACTLY sales-owner + OD + assigned
        crew; NEVER a client/partner phone; wa10_prompted guards re-fire
TAP     a sentiment tap records a commercial.event.feedback row AS THE REAL
        user (create_uid honest); find-or-update (2nd tap updates, no dup);
        two-factor (crew can't record as 'sales'); zero send on save
NOTES   a free-text note after a tap UPDATES the row
PULL    "feedback" lists the sender's wrapped events; pick -> prompt;
        unmapped / mid-sentence / non-command NOT grabbed
READ(b) crew read a CLIENT row on their event (unchanged) + their OWN staff
        row, but NOT another crew member's staff row on a shared event
CRIT(c) feedback_ids client-only by construction (count/closeout unaffected
        by staff rows); wa_feedback_ids carries the staff voices
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
counters = {"run_turn": 0}


def _d(s):
    return "".join(c for c in str(s or "") if c.isdigit())


try:
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry  # noqa: F401
    from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import (
        ChatTurnResult,
    )
    from odoo.addons.neon_channels.models import wa_payload

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True, mail_create_nolog=True,
                           mail_notify_force_send=False))
    WM = env["neon.whatsapp.message"].sudo()
    WMcls = type(WM)
    EJ = env["commercial.event.job"].sudo()
    CJ = env["commercial.job"].sudo()
    Crew = env["commercial.job.crew"].sudo()
    Fb = env["commercial.event.feedback"].sudo()
    Lead = env["crm.lead"].sudo()
    secret = env["ir.config_parameter"].sudo().get_param("database.secret") or ""

    g_user = env.ref("base.group_user")
    g_jobs_user = env.ref("neon_jobs.group_neon_jobs_user")
    g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
    g_su = env.ref("neon_core.group_neon_superuser")
    sample = CJ.search([], limit=1, order="id desc")
    venue_id = sample.venue_id.id if sample and sample.venue_id else False
    currency_id = (sample.currency_id.id if sample and sample.currency_id
                   else env.ref("base.USD").id)

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "email": "".join(login.split()).lower() + "@test.neon",
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(u, phone):
        env["neon.bot.user"].sudo().create(
            {"name": u.login, "phone_number": phone, "user_id": u.id})

    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})

    sales = mk_user("wa10_sales", [g_user, g_jobs_user])
    od = mk_user("wa10_od", [g_user, g_su])
    crewA = mk_user("wa10_crewA", [g_user, g_crew])
    crewB = mk_user("wa10_crewB", [g_user, g_crew])
    SALES_PH, OD_PH = "+263772100001", "+263772100002"
    A_PH, A_FROM = "+263772100003", "263772100003"
    B_PH, B_FROM = "+263772100004", "263772100004"
    mk_bot(sales, SALES_PH); mk_bot(od, OD_PH)
    mk_bot(crewA, A_PH); mk_bot(crewB, B_PH)
    for ph in (SALES_PH, OD_PH, A_PH, B_PH):
        warm(ph)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa6_od_login", od.login)

    CLIENT_PH = "+263772100099"
    client = env["res.partner"].sudo().create(
        {"name": "WA10 Client", "phone": CLIENT_PH, "is_company": True})
    lead = Lead.create({"type": "opportunity", "name": "WA10 opp",
                        "partner_id": client.id, "user_id": sales.id})
    job = CJ.create({"name": "WA10 Parent", "partner_id": client.id,
                    "venue_id": venue_id, "currency_id": currency_id,
                    "crm_lead_id": lead.id, "state": "active",
                    "event_date": "2026-05-01"})
    ej = EJ.create({"commercial_job_id": job.id, "name": "WA10 GALA",
                    "event_date": "2026-05-01"})
    # assigned crew: A (chief) + B
    Crew.create({"job_id": job.id, "partner_id": crewA.partner_id.id,
                 "user_id": crewA.id, "role": "tech", "is_crew_chief": True})
    Crew.create({"job_id": job.id, "partner_id": crewB.partner_id.id,
                 "user_id": crewB.id, "role": "tech"})
    # event_job.state is an authority-GATED transition; for the smoke force a
    # WRAPPED state directly (we test WA-10 eligibility, not the state machine).
    env.cr.execute(
        "UPDATE commercial_event_job SET state='completed' WHERE id=%s",
        (ej.id,))
    ej.invalidate_recordset()

    check("fixtures: wrapped event with sales-owner + OD + 2 crew; client "
          "partner has a phone",
          ej.exists() and job.crm_lead_id.user_id.id == sales.id
          and len(job.crew_assignment_ids) == 2 and client.phone == CLIENT_PH,
          ej.state)

    # ---- sales-owner + role resolution units ----
    check("sales-owner resolves via crm_lead.user_id; roles per voice",
          WM._wa10_resolve_sales_owner(job).id == sales.id
          and WM._wa10_role_for(sales, ej) == "sales"
          and WM._wa10_role_for(crewA, ej) == "crew_chief"
          and WM._wa10_role_for(crewB, ej) == "crew"
          and WM._wa10_role_for(od, ej) == "od",
          (WM._wa10_role_for(crewA, ej), WM._wa10_role_for(crewB, ej)))

    # ---- mocks ----
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_iot(self, to, interactive, body):
        _sent.append(("iot", to, interactive, body)); return "interactive"

    def stub_chat(self, messages, schemas):
        return (ChatTurnResult(success=True, assistant_message="ok",
                               tool_calls=[]), "google")

    o_rt = WhatsAppCopilotService.run_turn

    def sp_rt(*a, **k):
        counters["run_turn"] += 1; return o_rt(*a, **k)

    def btn_msg(payload, frm):
        return {"id": "wamid.X", "from": frm, "type": "button",
                "button": {"payload": payload, "text": "tap"}}

    def txt_msg(b, frm):
        return {"id": "wamid.Y", "from": frm, "type": "text",
                "text": {"body": b}}

    def sent_phones():
        return {_d(e[1]) for e in _sent if e[0] in ("buttons", "text", "iot")}

    def fb_rows():
        return Fb.search([("event_job_id", "=", ej.id)])

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(
            WMcls, "send_interactive_or_text", s_iot))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", stub_chat))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "run_turn", sp_rt))

        # ============ PUSH on check-in landing ============
        _sent.clear()
        WM._wa10_on_checkin(ej, od.id)
        phones = sent_phones()
        ej.invalidate_recordset()
        check("T-PUSH recipients = EXACTLY sales-owner + OD + both crew; "
              "NEVER the client phone; wa10_prompted set",
              phones == {_d(SALES_PH), _d(OD_PH), _d(A_PH), _d(B_PH)}
              and _d(CLIENT_PH) not in phones and ej.wa10_prompted,
              phones)

        _sent.clear()
        WM._wa10_on_checkin(ej, od.id)
        check("T-PUSH re-fire guard: a second check-in sends NOTHING "
              "(wa10_prompted already set)", not _sent, len(_sent))

        # ============ TAP records (real dispatch path) ============
        _sent.clear()
        before_partners = env["res.partner"].sudo().search_count([])
        pay = wa_payload.encode(secret, "wa10_fb", ej.id, "crew", "positive")
        WM.handle_inbound(btn_msg(pay, B_FROM), {})   # crewB taps All good
        rb = fb_rows().filtered(lambda f: f.captured_by.id == crewB.id)
        check("T-TAP crewB records: 1 row, wa_role=crew, channel=whatsapp, "
              "sentiment=positive, create_uid=crewB (honest, no sudo)",
              len(rb) == 1 and rb.wa_role == "crew"
              and rb.channel == "whatsapp" and rb.sentiment == "positive"
              and rb.create_uid.id == crewB.id and rb.captured_by.id == crewB.id,
              (len(rb), rb.wa_role, rb.create_uid.id if rb else None))

        # 2nd tap (different sentiment) -> UPDATE, no duplicate
        pay2 = wa_payload.encode(secret, "wa10_fb", ej.id, "crew", "negative")
        WM.handle_inbound(btn_msg(pay2, B_FROM), {})
        rb2 = fb_rows().filtered(lambda f: f.captured_by.id == crewB.id)
        check("T-TAP find-or-update: 2nd tap UPDATES the same row "
              "(sentiment->negative), no duplicate",
              len(rb2) == 1 and rb2.sentiment == "negative", len(rb2))

        check("T-TAP zero res.partner created (feedback never makes a partner)",
              env["res.partner"].sudo().search_count([]) == before_partners)

        # two-factor: crewB tapping a 'sales' role payload -> refused, no row
        pays = wa_payload.encode(secret, "wa10_fb", ej.id, "sales", "positive")
        WM.handle_inbound(btn_msg(pays, B_FROM), {})
        check("T-TAP two-factor: crew can't record as 'sales' (role mismatch) "
              "-> no sales row by crewB",
              not fb_rows().filtered(
                  lambda f: f.captured_by.id == crewB.id and f.wa_role == "sales"))

        # ============ NOTES session updates the row ============
        WM.handle_inbound(txt_msg("the client loved the lighting", B_FROM), {})
        rb3 = fb_rows().filtered(lambda f: f.captured_by.id == crewB.id)
        check("T-NOTES: free-text after the tap UPDATES the row's feedback_text",
              len(rb3) == 1 and "lighting" in (rb3.feedback_text or ""),
              rb3.feedback_text if rb3 else None)

        # ============ zero-send-on-save ============
        _sent.clear()
        WM._wa10_record(ej, "od", od, "positive", body="ops smooth")
        check("T-ZERO-SEND: _wa10_record creates/updates a row and sends "
              "NOTHING", not _sent and fb_rows().filtered(
                  lambda f: f.wa_role == "od"), len(_sent))

        # ============ PULL command ============
        _sent.clear(); counters["run_turn"] = 0
        WM.handle_inbound(txt_msg("feedback", A_FROM), {})
        Sess = env["neon.wa.equip.session"].sudo()
        sA = Sess.search([("phone_number", "=", "+" + A_FROM),
                          ("active", "=", True)], limit=1)
        check("T-PULL: crewA texts 'feedback' -> lists their wrapped events; "
              "fb_pull session; Copilot 0",
              sA and sA.step == "fb_pull" and _sent
              and "WA10 GALA" in (_sent[-1][2] if _sent else "")
              and counters["run_turn"] == 0, sA.step if sA else None)

        # pick #1 -> sentiment prompt for crewA's role (crew_chief)
        _sent.clear()
        WM.handle_inbound(txt_msg("1", A_FROM), {})
        check("T-PULL pick -> sentiment prompt sent (buttons)",
              any(e[0] == "buttons" for e in _sent), _sent[-1][0] if _sent else None)

        # not grabbed: unmapped / mid-sentence / non-command
        n_unmapped = WM._wa10_maybe_intercept(txt_msg("feedback", "263770000000"))
        n_mid = WM._wa10_maybe_intercept(
            txt_msg("any feedback on the lights?", A_FROM))
        check("T-PULL not grabbed: unmapped sender + mid-sentence 'feedback' "
              "-> intercept None",
              n_unmapped is None and n_mid is None, (n_unmapped, n_mid))

        # ============ (b) READ-RULE 3-part ============
        # seed: a CLIENT row (wa_role=False) + crewA staff row + crewB staff row
        client_row = Fb.create({
            "event_job_id": ej.id, "channel": "phone", "sentiment": "positive",
            "feedback_text": "client phoned in praise"})   # wa_role=False
        WM._wa10_record(ej, "crew_chief", crewA, "positive", body="A note")
        a_row = fb_rows().filtered(lambda f: f.captured_by.id == crewA.id)
        b_row = fb_rows().filtered(lambda f: f.captured_by.id == crewB.id)
        visibleA = Fb.with_user(crewA.id).search(
            [("event_job_id", "=", ej.id)])
        check("T-READ(b)(i): crewA SEES the client row (wa_role=False) on "
              "their event (unchanged by the amendment)",
              client_row.id in visibleA.ids)
        check("T-READ(b)(ii): crewA does NOT see crewB's staff-voice row on "
              "the shared event",
              b_row and b_row.id not in visibleA.ids, b_row.ids)
        check("T-READ(b)(iii): crewA DOES see their OWN staff-voice row",
              a_row and a_row.id in visibleA.ids, a_row.ids)

        # ============ (c) client-scoping by construction ============
        ej.invalidate_recordset()
        client_fb = ej.feedback_ids
        staff_fb = ej.wa_feedback_ids
        check("T-CRIT(c): feedback_ids = CLIENT rows only (wa_role unset); "
              "wa_feedback_ids = the staff voices; count is client-only",
              all(not f.wa_role for f in client_fb)
              and all(f.wa_role for f in staff_fb)
              and client_row.id in client_fb.ids
              and a_row.id in staff_fb.ids
              and ej.feedback_count == len(client_fb),
              (client_fb.ids, staff_fb.ids, ej.feedback_count))
        # a staff-voice row must NOT satisfy the "client feedback present"
        # closeout requirement -> a fresh event with ONLY a staff row still
        # reads as missing client feedback.
        ej2 = EJ.create({"commercial_job_id": job.id, "name": "WA10 EMPTY",
                         "event_date": "2026-05-02"})
        WM._wa10_record(ej2, "od", od, "positive", body="ops fine")
        ej2.invalidate_recordset()
        check("T-CRIT(c): an event with ONLY a staff-voice row still reads as "
              "MISSING client feedback (closeout unaffected)",
              not ej2.feedback_ids and ej2.wa_feedback_ids
              and ej2.has_soft_requirements_outstanding,
              (ej2.feedback_ids.ids, ej2.wa_feedback_ids.ids))

        # ---- review fix: a DEACTIVATED voice is never prompted ----
        crewB.sudo().write({"active": False})
        ej.invalidate_recordset()
        v_after = WM._wa10_voices(ej)
        check("T-ACTIVE (review fix): a deactivated voice (crewB) is SKIPPED "
              "from the prompt set; active crewA stays",
              not any(v["user"].id == crewB.id for v in v_after)
              and any(v["user"].id == crewA.id for v in v_after),
              [v["user"].id for v in v_after])

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
