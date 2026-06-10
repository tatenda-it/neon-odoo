# -*- coding: utf-8 -*-
"""B11 / WA-7 crew selection on WhatsApp smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pwa7_crew_selection_smoke.py

Exercises the REAL path -- OD texts "select crew" -> list FROM-SCRATCH jobs
-> pick job -> multi-pick people "1, 3" -> pick chief -> [Confirm] creates
commercial.job.crew rows (chief flagged, crew_chief_id recomputed, actor =
OD) with ZERO outbound -> [Notify] fires WA-2 to the picked people only.
NOT synthesised taps. Rolls back.

PARSE  select crew / assign crew tight match; mid-sentence -> not a command
GATE   OD/superuser passes _wa6_can_initiate; plain crew fails
ELIG   parent-no-crew planning/prep job eligible; parent-with-crew excluded
T1     OD "select crew" -> job list + cs_job session; Copilot 0
T2     pick job -> people list (active mapped bot.users); cs_people
T3     multi-pick "1, 3" -> chief list; team read-back; cs_chief
T4     pick chief -> [Confirm team][Change]; cs_confirm
T5     tap Confirm -> 2 crew rows (1 chief), crew_chief_id recomputed,
       create_uid = OD, ZERO WA-2 outbound; then offer [Notify]
T6     tap Notify -> WA-2 send_template to the 2 picked people ONLY
T7     non-OD "select crew" -> NOT grabbed (intercept None)
T8     mid-sentence "select crew" -> NOT grabbed
T9     unmapped "select crew" -> intercept None
T10    one-chief: exactly one is_crew_chief on the created team
T11    parent-with-crew job NEVER in the job list
T12    Change -> back to people step
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
counters = {"run_turn": 0, "variant_for": 0}


def _reset():
    for k in counters:
        counters[k] = 0


try:
    from odoo.addons.neon_channels.models import wa_payload
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry  # noqa: F401
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
    EJ = env["commercial.event.job"].sudo()
    CJ = env["commercial.job"].sudo()
    Crew = env["commercial.job.crew"].sudo()
    Sess = env["neon.wa.equip.session"].sudo()

    g_user = env.ref("base.group_user")
    g_su = env.ref("neon_core.group_neon_superuser")
    sample = CJ.search([], limit=1, order="id desc")
    venue_id = sample.venue_id.id if sample and sample.venue_id else False
    currency_id = (sample.currency_id.id if sample and sample.currency_id
                   else env.ref("base.USD").id)
    check("fixtures: groups + reusable venue/currency present",
          bool(g_user and g_su and venue_id and currency_id),
          (venue_id, currency_id))

    def mk_user(login, groups):
        # email REQUIRED: neon_hr's commercial.job.crew create() gate
        # message_post resolves the acting user's author email; a fixture
        # user without one trips _message_compute_author (prod OD has one).
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "email": "".join(login.split()).lower() + "@test.neon",
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(u, phone):
        env["neon.bot.user"].sudo().create({
            "name": u.login, "phone_number": phone, "user_id": u.id})

    # OD = Neon Superuser (mirrors Robin: implies jobs-manager -> can_edit_crew
    # + crew CRUD). Param set too (the superuser branch passes regardless).
    od = mk_user("wa7_od", [g_user, g_su])
    OD_PHONE, OD_FROM = "+263881009001", "263881009001"
    mk_bot(od, OD_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa6_od_login", od.login)

    crewA = mk_user("WA7 Crew Aaa", [g_user])
    crewB = mk_user("WA7 Crew Bbb", [g_user])
    crewC = mk_user("WA7 Crew Ccc", [g_user])
    mk_bot(crewA, "+263881009101")
    mk_bot(crewB, "+263881009102")
    mk_bot(crewC, "+263881009103")
    rando = mk_user("wa7_rando", [g_user])          # mapped, NON-OD
    RANDO_PHONE, RANDO_FROM = "+263881009002", "263881009002"
    mk_bot(rando, RANDO_PHONE)
    UNMAPPED_FROM = "263881009999"

    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})
    for ph in (OD_PHONE, RANDO_PHONE):
        warm(ph)

    test_partner = env["res.partner"].sudo().create(
        {"name": "WA7 Test Client", "is_company": True})

    def mk_commjob(name, crew_user=None):
        job = CJ.create({"name": name, "partner_id": test_partner.id,
                         "venue_id": venue_id, "currency_id": currency_id,
                         "state": "active", "event_date": "2026-12-20"})
        if crew_user:
            Crew.create({"job_id": job.id, "user_id": crew_user.id,
                         "role": "tech"})
        job.invalidate_recordset()
        return job

    def mk_eventjob(parent, name, state="planning"):
        ej = EJ.create({"commercial_job_id": parent.id, "name": name,
                        "state": state, "event_date": "2026-12-20"})
        ej.invalidate_recordset()
        return ej

    elig_parent = mk_commjob("WA7 ELIG Parent")          # no crew
    elig_ej = mk_eventjob(elig_parent, "WA7 ELIG Event", "planning")
    crewed_parent = mk_commjob("WA7 CREWED Parent", crew_user=rando)  # crew
    crewed_ej = mk_eventjob(crewed_parent, "WA7 CREWED Event", "prep")

    # ---- PARSE (deterministic) ----
    check("PARSE: select/assign crew -> command; mid-sentence -> not",
          WM._wa7_is_command("select crew")
          and WM._wa7_is_command("Assign Crew")
          and WM._wa7_is_command("select crew for the gala")
          and not WM._wa7_is_command("can you select crew options")
          and not WM._wa7_is_command("I'll assign crew later"),
          [WM._wa7_is_command(x) for x in
           ("select crew", "can you select crew options")])

    # ---- GATE ----
    check("GATE: OD/superuser passes _wa6_can_initiate; plain crew fails",
          WM._wa6_can_initiate(od) and not WM._wa6_can_initiate(crewA))

    # ---- ELIG ----
    elig_ids = set(WM._wa7_eligible_jobs().ids)
    check("ELIG: parent-no-crew planning job eligible",
          elig_ej.id in elig_ids)
    check("ELIG: parent-WITH-crew job excluded (from-scratch)",
          crewed_ej.id not in elig_ids)

    # ---- mocks + spies ----
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_list(self, to, body, bt, sections):
        _sent.append(("list", to, body, sections)); return True

    def s_cta(self, to, body, disp, url):
        _sent.append(("cta", to, body, url)); return True

    def s_iot(self, to, interactive, body):
        _sent.append(("iot", to, interactive, body)); return "interactive"

    def s_tmpl(self, to, name, language="en", body_params=None,
               quick_reply_payloads=None, url_button_param=None,
               recipient_partner=None, audit_body=None):
        _sent.append(("template", to, name)); return {"ok": True,
                                                       "reason": "sent"}

    def stub_chat(self, messages, schemas):
        return (ChatTurnResult(success=True, assistant_message="ok",
                               tool_calls=[]), "google")

    o_rt = WhatsAppCopilotService.run_turn
    o_vf = WhatsAppCopilotService.variant_for

    def sp_rt(*a, **k):
        counters["run_turn"] += 1; return o_rt(*a, **k)

    def sp_vf(*a, **k):
        counters["variant_for"] += 1; return o_vf(*a, **k)

    def text_msg(b, frm):
        return {"id": "wamid.X", "from": frm, "type": "text",
                "text": {"body": b}}

    def tap_msg(rid, frm):
        return {"id": "wamid.T", "from": frm, "type": "interactive",
                "interactive": {"type": "button",
                                "button_reply": {"id": rid, "title": "x"}}}

    def _d(s):
        return "".join(c for c in str(s or "") if c.isdigit())

    def last(kind, to=None):
        for e in reversed(_sent):
            if isinstance(e, tuple) and e[0] == kind \
                    and (to is None or _d(e[1]) == _d(to)):
                return e
        return None

    def od_sess():
        return Sess.search([("phone_number", "=", OD_PHONE),
                            ("active", "=", True)], limit=1)

    def clear_od():
        Sess.search([("phone_number", "=", OD_PHONE)]).write(
            {"active": False})

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
        st.enter_context(patch.object(
            WMcls, "send_interactive_or_text", s_iot))
        st.enter_context(patch.object(WMcls, "send_template", s_tmpl))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", stub_chat))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "run_turn", sp_rt))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "variant_for", sp_vf))

        # T1: OD "select crew" -> job list; Copilot 0
        clear_od(); _sent.clear(); _reset()
        WM.handle_inbound(text_msg("select crew", OD_FROM), {})
        lst = last("text", OD_PHONE)
        s1 = od_sess()
        check("T1: OD 'select crew' -> job list incl ELIG, excl CREWED; "
              "cs_job session; Copilot 0",
              lst and "WA7 ELIG Event" in lst[2]
              and "WA7 CREWED Event" not in lst[2]
              and s1 and s1.step == "cs_job"
              and counters["run_turn"] == 0, lst[2] if lst else None)

        # T2: pick the ELIG job -> people list
        job_ids = s1._get_buffer()
        jpos = job_ids.index(elig_ej.id) + 1
        _sent.clear()
        WM.handle_inbound(text_msg(str(jpos), OD_FROM), {})
        plst = last("text", OD_PHONE)
        s2 = od_sess()
        buf2 = s2._get_buffer() if s2 else {}
        pool = buf2.get("pool") or []
        check("T2: pick job -> people list (active mapped users); cs_people; "
              "pool incl crewA/B/C",
              plst and s2 and s2.step == "cs_people"
              and {crewA.id, crewB.id, crewC.id} <= set(pool),
              (s2.step if s2 else None, len(pool)))

        # T3: multi-pick crewA + crewC -> chief list
        posA = pool.index(crewA.id) + 1
        posC = pool.index(crewC.id) + 1
        _sent.clear()
        WM.handle_inbound(text_msg("%d, %d" % (posA, posC), OD_FROM), {})
        clst = last("text", OD_PHONE)
        s3 = od_sess()
        buf3 = s3._get_buffer() if s3 else {}
        check("T3: multi-pick '%d, %d' -> cs_chief; picked = crewA+crewC; "
              "team read-back" % (posA, posC),
              s3 and s3.step == "cs_chief"
              and buf3.get("picked") == [crewA.id, crewC.id]
              and clst and "WA7 Crew Aaa" in clst[2]
              and "WA7 Crew Ccc" in clst[2],
              (s3.step if s3 else None, buf3.get("picked")))

        # T4: pick chief = crewA (position 1 in picked) -> confirm buttons
        _sent.clear()
        WM.handle_inbound(text_msg("1", OD_FROM), {})
        cbt = last("buttons", OD_PHONE)
        cids = [wa_payload.decode(secret, b["id"])[0] for b in cbt[3]] \
            if cbt else []
        s4 = od_sess()
        check("T4: pick chief -> [Confirm team][Change]; cs_confirm",
              s4 and s4.step == "cs_confirm"
              and cids == ["wa7_confirm", "wa7_change"]
              and s4._get_buffer().get("chief") == crewA.id, cids)

        # T5: tap Confirm -> rows created, ZERO WA-2 outbound, offer Notify
        confirm_pl = cbt[3][0]["id"]
        _sent.clear()
        WM.handle_inbound(tap_msg(confirm_pl, OD_FROM), {})
        elig_parent.invalidate_recordset()
        rows = Crew.search([("job_id", "=", elig_parent.id)])
        chiefs = rows.filtered(lambda c: c.is_crew_chief)
        elig_ej.invalidate_recordset()
        tmpl_after_confirm = [e for e in _sent if e[0] == "template"]
        nbt = last("buttons", OD_PHONE)
        check("T5: Confirm -> 2 crew rows (1 chief=crewA), crew_chief_id "
              "recomputed, create_uid=OD, ZERO WA-2 sent, [Notify] offered",
              set(rows.mapped("user_id").ids) == {crewA.id, crewC.id}
              and len(chiefs) == 1 and chiefs.user_id.id == crewA.id
              and elig_ej.crew_chief_id.id == crewA.id
              and all(r.create_uid.id == od.id for r in rows)
              and not tmpl_after_confirm
              and nbt and wa_payload.decode(secret, nbt[3][0]["id"])[0]
              == "wa7_notify",
              (rows.mapped("user_id").ids, len(chiefs),
               elig_ej.crew_chief_id.id, len(tmpl_after_confirm)))

        # T10: exactly one crew chief on the team
        check("T10: exactly one is_crew_chief on the created team",
              len(rows.filtered(lambda c: c.is_crew_chief)) == 1)

        # T6: tap Notify -> WA-2 send_template to the 2 picked ONLY
        notify_pl = nbt[3][0]["id"]
        _sent.clear()
        WM.handle_inbound(tap_msg(notify_pl, OD_FROM), {})
        tmpls = [e for e in _sent if e[0] == "template"]
        tmpl_phones = {_d(e[1]) for e in tmpls}
        check("T6: Notify -> WA-2 template to crewA + crewC phones ONLY "
              "(2 sends)",
              len(tmpls) == 2
              and tmpl_phones == {_d("+263881009101"), _d("+263881009103")},
              (len(tmpls), tmpl_phones))

        # T7: non-OD mapped 'select crew' -> NOT grabbed
        clear_od(); _sent.clear(); _reset()
        r7 = WM._wa7_maybe_intercept(text_msg("select crew", RANDO_FROM))
        WM.handle_inbound(text_msg("select crew", RANDO_FROM), {})
        check("T7: non-OD 'select crew' -> intercept None (Copilot ran), "
              "no cs_* session",
              r7 is None and counters["run_turn"] >= 1
              and not Sess.search([("phone_number", "=", RANDO_PHONE),
                                   ("step", "like", "cs_%"),
                                   ("active", "=", True)]),
              (r7, dict(counters)))

        # T8: mid-sentence 'select crew' -> NOT grabbed
        clear_od(); _sent.clear(); _reset()
        r8 = WM._wa7_maybe_intercept(
            text_msg("can you select crew options for me", OD_FROM))
        check("T8: mid-sentence 'select crew' -> intercept None", r8 is None)

        # T9: unmapped 'select crew' -> intercept None
        r9 = WM._wa7_maybe_intercept(text_msg("select crew", UNMAPPED_FROM))
        check("T9: unmapped 'select crew' -> intercept None", r9 is None)

        # T11 + T12: a FRESH from-scratch job (elig_ej's parent now has crew
        # from T5, so it's no longer eligible). T11 = list incl ELIG2 + excl
        # CREWED; T12 = Change goes back to the people step.
        clear_od(); _sent.clear(); _reset()
        elig2_parent = mk_commjob("WA7 ELIG2 Parent")
        elig2_ej = mk_eventjob(elig2_parent, "WA7 ELIG2 Event", "planning")
        WM.handle_inbound(text_msg("select crew", OD_FROM), {})
        l11 = last("text", OD_PHONE)
        check("T11: list incl ELIG2, excl parent-WITH-crew CREWED job",
              l11 and "WA7 ELIG2 Event" in l11[2]
              and "WA7 CREWED Event" not in l11[2], l11[2] if l11 else None)
        sA = od_sess()
        jb = sA._get_buffer()
        WM.handle_inbound(text_msg(str(jb.index(elig2_ej.id) + 1), OD_FROM), {})
        poolB = od_sess()._get_buffer().get("pool") or []
        WM.handle_inbound(
            text_msg(str(poolB.index(crewA.id) + 1), OD_FROM), {})   # people
        WM.handle_inbound(text_msg("1", OD_FROM), {})                # chief
        cbt12 = last("buttons", OD_PHONE)
        change_pl = cbt12[3][1]["id"]   # [Confirm][Change] -> Change
        _sent.clear()
        WM.handle_inbound(tap_msg(change_pl, OD_FROM), {})
        s12b = od_sess()
        check("T12: Change -> back to cs_people",
              s12b and s12b.step == "cs_people", s12b.step if s12b else None)

        # T13: continue from T12 (cs_people after Change) -- re-pick a
        # DIFFERENT team (crewB only) -> Confirm creates the NEW team
        # (exercises the [Change] pool-refresh + the full re-pick cycle).
        poolC = od_sess()._get_buffer().get("pool") or []
        WM.handle_inbound(
            text_msg(str(poolC.index(crewB.id) + 1), OD_FROM), {})   # people
        WM.handle_inbound(text_msg("1", OD_FROM), {})                # chief
        cbt13 = last("buttons", OD_PHONE)
        _sent.clear()
        WM.handle_inbound(tap_msg(cbt13[3][0]["id"], OD_FROM), {})   # Confirm
        elig2_parent.invalidate_recordset()
        rows13 = Crew.search([("job_id", "=", elig2_parent.id)])
        check("T13: re-pick (crewB) -> Confirm -> team={crewB}, chief=crewB "
              "(Change pool-refresh + full re-pick cycle)",
              set(rows13.mapped("user_id").ids) == {crewB.id}
              and rows13.filtered(lambda c: c.is_crew_chief).user_id.id
              == crewB.id, rows13.mapped("user_id").ids)

        # T-PARSE: multi-select parser dedups + bounds-checks
        check("T-PARSE: multi-pick dedup + out-of-range + empty",
              WM._wa7_parse_multi("1, 3", 3) == [1, 3]
              and WM._wa7_parse_multi("1,1,3", 3) == [1, 3]
              and WM._wa7_parse_multi("5", 3) == []
              and WM._wa7_parse_multi("1, 3, 5, 3", 3) == [1, 3]
              and WM._wa7_parse_multi("", 3) == [],
              [WM._wa7_parse_multi(x, 3) for x in ("1,1,3", "5", "1, 3, 5, 3")])

        def drive_to_confirm(name, team_uids, chief_uid):
            """Fresh from-scratch job -> drive to cs_confirm; return
            (parent, event_job, last_buttons)."""
            clear_od(); _sent.clear()
            par = mk_commjob(name)
            ev = mk_eventjob(par, name + " Ev", "planning")
            WM.handle_inbound(text_msg("select crew", OD_FROM), {})
            jb2 = od_sess()._get_buffer()
            WM.handle_inbound(text_msg(str(jb2.index(ev.id) + 1), OD_FROM), {})
            pl2 = od_sess()._get_buffer().get("pool") or []
            picks = ", ".join(str(pl2.index(u) + 1) for u in team_uids)
            WM.handle_inbound(text_msg(picks, OD_FROM), {})
            pk2 = od_sess()._get_buffer().get("picked") or []
            WM.handle_inbound(
                text_msg(str(pk2.index(chief_uid) + 1), OD_FROM), {})
            return par, ev, last("buttons", OD_PHONE)

        # T15: a stolen/replayed Confirm tap from a DIFFERENT phone is refused
        par15, ev15, cb15 = drive_to_confirm("WA7 STOLEN", [crewA.id], crewA.id)
        _sent.clear()
        WM.handle_inbound(tap_msg(cb15[3][0]["id"], RANDO_FROM), {})
        r15 = last("text", RANDO_PHONE)
        par15.invalidate_recordset()
        check("T15: Confirm tap from another phone -> refused (two-factor), "
              "no crew created",
              r15 and "isn't linked to your number" in r15[2]
              and not par15.crew_assignment_ids,
              (r15[2] if r15 else None, len(par15.crew_assignment_ids)))

        # T16: parent crewed CONCURRENTLY between list and Confirm -> rejected
        par16, ev16, cb16 = drive_to_confirm("WA7 RACE", [crewA.id], crewA.id)
        Crew.with_user(od.id).with_context(
            mail_create_nosubscribe=True, mail_create_nolog=True,
            mail_notify_force_send=False, tracking_disable=True).create(
            {"job_id": par16.id, "user_id": crewB.id, "role": "tech"})
        _sent.clear()
        WM.handle_inbound(tap_msg(cb16[3][0]["id"], OD_FROM), {})
        r16 = last("text", OD_PHONE)
        par16.invalidate_recordset()
        check("T16: parent crewed concurrently -> Confirm rejected, no "
              "double-assign (only concurrent crewB remains)",
              r16 and "already has a crew" in r16[2]
              and set(par16.crew_assignment_ids.mapped("user_id").ids)
              == {crewB.id},
              (r16[2] if r16 else None,
               par16.crew_assignment_ids.mapped("user_id").ids))

    check("REG: wa7_* intents registered",
          {"wa7_confirm", "wa7_change", "wa7_notify"} <= wa_payload.INTENTS)

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
