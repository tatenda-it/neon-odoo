# -*- coding: utf-8 -*-
"""B11 / WA-6.1 Face-3 crew-initiated dispatch smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pwa6_1_face3_dispatch_smoke.py

Exercises the REAL path -- command -> list -> pick -> RECEIVE buttons ->
tap -> checkout/checkin -- NOT synthesised taps (the gap pwa6 missed).
Rolls back.

T1  chief "check out" -> numbered list of HIS eligible jobs; Copilot 0
T2  one-eligible-job user -> still listed (no silent auto-assume)
T3  multi: pick "2" -> bot SENDS [Check out all][Item-by-item] for job #2
T4  full round-trip: tap the REALLY-sent button -> checkout fires (actor)
T5  FALSE-POSITIVE: "can I check out the venue options" -> Copilot, no grab
T6  mapped user, NO eligible job, exact "check out" -> falls through (Copilot)
T7  unmapped phone "check out" -> intercept returns None (client lane)
T8  check-in symmetric: "check in" -> list -> pick -> [good][flag] buttons
T9  quantity job CLEARS the check-in list after a (partial) checkin movement
T10 normal message, no session -> Copilot (no regression)
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


def _reset():
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
    EJ = env["commercial.event.job"].sudo()
    Line = env["commercial.event.job.equipment.line"].sudo()
    Unit = env["neon.equipment.unit"].sudo()
    Move = env["neon.equipment.movement"].sudo()
    Prod = env["product.template"].sudo()
    Wizard = env["neon.equipment.checkin.wizard"]

    g_user = env.ref("base.group_user")
    g_lead = env.ref("neon_jobs.group_neon_jobs_crew_leader")
    cat_sound = env.ref("neon_jobs.equipment_category_sound")
    cat_truss = env.ref("neon_jobs.equipment_category_trussing")
    parent = env["commercial.job"].sudo().search([], limit=1, order="id")
    check("fixtures: groups/cats/parent", all([g_lead, cat_sound, cat_truss,
                                               parent]))

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(u, phone):
        env["neon.bot.user"].sudo().create({
            "name": u.login, "phone_number": phone, "user_id": u.id})

    chief = mk_user("wa61_chief", [g_user, g_lead])
    CHIEF_PHONE, CHIEF_FROM = "+263881007001", "263881007001"
    mk_bot(chief, CHIEF_PHONE)
    lead1 = mk_user("wa61_lead1", [g_user, g_lead])
    LEAD1_PHONE, LEAD1_FROM = "+263881007002", "263881007002"
    mk_bot(lead1, LEAD1_PHONE)
    rando = mk_user("wa61_rando", [g_user])
    RANDO_PHONE, RANDO_FROM = "+263881007003", "263881007003"
    mk_bot(rando, RANDO_PHONE)
    UNMAPPED_FROM = "263881007999"

    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})
    for ph in (CHIEF_PHONE, LEAD1_PHONE, RANDO_PHONE):
        warm(ph)

    # products
    p_serial = Prod.create({
        "name": "WA61 Serial Mic", "workshop_name": "WA61 Serial Mic",
        "is_workshop_item": True, "equipment_category_id": cat_sound.id,
        "tracking_mode": "serial"})
    Unit.create([{"product_template_id": p_serial.id,
                  "serial_number": "WA61M-%03d" % i, "state": "active"}
                 for i in range(6)])
    p_qty = Prod.create({
        "name": "WA61 Truss Pins", "workshop_name": "WA61 Truss Pins",
        "is_workshop_item": True, "equipment_category_id": cat_truss.id,
        "tracking_mode": "quantity", "quantity_on_hand": 10})

    W = ("2026-12-15 06:00:00", "2026-12-16 20:00:00", "2026-12-15")

    def mk_job(lead, name):
        ej = EJ.create({"commercial_job_id": parent.id,
                        "lead_tech_id": lead.id, "event_date": W[2],
                        "prep_start_datetime": W[0],
                        "return_eta_datetime": W[1], "name": name})
        ej.invalidate_recordset()
        return ej

    def add_alloc(ej, product, qty):
        ln = Line.create({"event_job_id": ej.id,
                          "product_template_id": product.id,
                          "quantity_planned": qty})
        ln.action_allocate()
        ln.invalidate_recordset()
        return ln

    jobA = mk_job(chief, "WA61 JOB A")      # serial, chief
    jobB = mk_job(chief, "WA61 JOB B")      # quantity, chief
    jobC = mk_job(lead1, "WA61 JOB C")      # serial, lead1
    add_alloc(jobA, p_serial, 2)
    add_alloc(jobB, p_qty, 4)
    add_alloc(jobC, p_serial, 1)
    check("fixtures: chief has 2 checkout-eligible jobs (A serial, B qty)",
          set(WM._wa6_eligible_checkout_jobs(chief).ids) == {jobA.id, jobB.id},
          WM._wa6_eligible_checkout_jobs(chief).ids)

    # ---- mocks + spies ----
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_list(self, to, body, bt, sections):
        _sent.append(("list", to, body, sections)); return True

    def s_cta(self, to, body, disp, url):
        _sent.append(("cta", to, body, url)); return True

    def s_tmpl(self, to, name, language="en", body_params=None,
               quick_reply_payloads=None, url_button_param=None,
               recipient_partner=None, audit_body=None):
        return {"ok": True, "reason": "sent"}

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

    def btn_intents(evt):
        return [((wa_payload.decode(secret, b["id"]) or [None])[0])
                for b in evt[3]] if evt else []

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
        st.enter_context(patch.object(WMcls, "send_template", s_tmpl))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", stub_chat))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "run_turn", sp_rt))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "variant_for", sp_vf))

        # T1: chief "check out" -> numbered list of A + B; Copilot 0
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("check out", CHIEF_FROM), {})
        lst = last("text", CHIEF_PHONE)
        check("T1: chief 'check out' -> numbered list of his 2 jobs; "
              "Copilot untouched",
              lst and "WA61 JOB A" in lst[2] and "WA61 JOB B" in lst[2]
              and "1." in lst[2] and "2." in lst[2]
              and counters["run_turn"] == 0, lst[2] if lst else None)

        # T2: one-eligible-job user still gets a list
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("checkout", LEAD1_FROM), {})
        l2 = last("text", LEAD1_PHONE)
        check("T2: one-job user -> still listed (1. WA61 JOB C)",
              l2 and "1." in l2[2] and "WA61 JOB C" in l2[2], l2[2] if l2 else None)

        # T3: chief picks "2" -> bot SENDS [Check out all][Item-by-item] for B
        _sent.clear()
        WM.handle_inbound(text_msg("2", CHIEF_FROM), {})
        bt = last("buttons", CHIEF_PHONE)
        ids = [b["id"] for b in bt[3]] if bt else []
        decoded = [wa_payload.decode(secret, i) for i in ids]
        check("T3: pick 2 -> SENT [co_all][co_item] for JOB B (the dispatch)",
              bt and [d[0] for d in decoded] == ["wa6_co_all", "wa6_co_item"]
              and all(int(d[1][0]) == jobB.id for d in decoded),
              [d[0] if d else None for d in decoded])

        # T4: full round-trip -- tap the REALLY-sent button -> checkout fires
        co_all_payload = ids[0]   # the actually-sent wa6_co_all button
        WM.handle_inbound(tap_msg(co_all_payload, CHIEF_FROM), {})
        jobB.invalidate_recordset()
        bres = jobB.equipment_line_ids.reservation_ids.filtered(
            lambda r: r.product_template_id.id == p_qty.id)
        mv = Move.search([("event_job_id", "=", jobB.id),
                          ("movement_type", "=", "checkout")])
        check("T4: tapping the sent button checked out JOB B (qty res "
              "fulfilled; movement actor = chief)",
              bres.state == "fulfilled" and mv and mv.quantity == 4
              and mv.actor_id.id == chief.id, (bres.state, len(mv)))

        # T5: FALSE-POSITIVE -- mid-sentence "check out" is NOT a command,
        # so the parser does NOT grab it (intercept returns None -> the
        # message falls through to the Copilot UNCHANGED). The precise
        # "not stolen" signal is the intercept verdict (the Copilot then
        # sends its own reply, which is expected, so we don't assert on
        # _sent). Also confirm no co_pick session was opened.
        _sent.clear(); _reset()
        r5 = WM._wa6_maybe_intercept(
            text_msg("can I check out the venue options", CHIEF_FROM))
        WM.handle_inbound(
            text_msg("can I check out the venue options", CHIEF_FROM), {})
        check("T5: mid-sentence 'check out' NOT grabbed (intercept None -> "
              "Copilot ran), no co_pick session opened",
              r5 is None and counters["run_turn"] >= 1
              and not env["neon.wa.equip.session"].sudo().search([
                  ("phone_number", "=", CHIEF_PHONE),
                  ("step", "=", "co_pick"), ("active", "=", True)]),
              (r5, dict(counters)))

        # T6: mapped user, exact command, but NO eligible job -> NOT grabbed
        # (intercept None -> falls through to Copilot unchanged).
        _sent.clear(); _reset()
        r6 = WM._wa6_maybe_intercept(text_msg("check out", RANDO_FROM))
        WM.handle_inbound(text_msg("check out", RANDO_FROM), {})
        check("T6: mapped user with NO eligible job -> NOT grabbed "
              "(intercept None -> Copilot ran)",
              r6 is None and counters["run_turn"] >= 1, (r6, dict(counters)))

        # T7: unmapped phone -> intercept returns None (client lane)
        r7 = WM._wa6_maybe_intercept(text_msg("check out", UNMAPPED_FROM))
        check("T7: unmapped 'check out' -> _wa6_maybe_intercept None "
              "(falls to client lane, not grabbed)", r7 is None, r7)

        # T8: check-in symmetric -- JOB B now has out gear (from T4)
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("check in", CHIEF_FROM), {})
        cil = last("text", CHIEF_PHONE)
        check("T8: 'check in' -> list incl JOB B (gear out); Copilot 0",
              cil and "WA61 JOB B" in cil[2] and counters["run_turn"] == 0,
              cil[2] if cil else None)
        _sent.clear()
        WM.handle_inbound(text_msg("1", CHIEF_FROM), {})
        cib = last("buttons", CHIEF_PHONE)
        check("T8: pick -> SENT [ci_good][ci_flag] for JOB B",
              cib and btn_intents(cib) == ["wa6_ci_good", "wa6_ci_flag"]
              and all(int((wa_payload.decode(secret, b["id"]) or [0, [0]])[1][0])
                      == jobB.id for b in cib[3]),
              btn_intents(cib))

        # T9: a (partial) check-in movement CLEARS JOB B from the list
        check("T9 pre: JOB B is check-in-eligible before check-in",
              jobB.id in WM._wa6_eligible_checkin_jobs(chief).ids)
        _PNG = (b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE"
                b"QVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        wz = Wizard.with_user(chief.id).with_context(
            default_event_job_id=jobB.id)
        wv = wz.default_get(["event_job_id", "checkin_line_ids",
                            "to_location_text"])
        w = wz.create(wv)
        w.checkin_line_ids.write({"condition_at_event": "damaged",
                                  "damaged_qty": 2, "photo": _PNG})
        w.action_confirm()
        check("T9: after a (partial-damage) check-in movement, JOB B CLEARS "
              "the check-in list (quantity no-longer-out)",
              jobB.id not in WM._wa6_eligible_checkin_jobs(chief).ids
              and Move.search_count([
                  ("event_job_id", "=", jobB.id),
                  ("movement_type", "=", "checkin")]) >= 1)

        # T10: normal message, no session -> Copilot (regression)
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("hello what's my schedule", CHIEF_FROM), {})
        check("T10: normal message -> Copilot (run_turn>=1), no WA-6 grab",
              counters["run_turn"] >= 1, dict(counters))

        # wrong-job-by-name impossible: list ids are a SUBSET of his jobs
        check("SAFETY: listed jobs are only the chief's eligible jobs "
              "(pick-by-number, never name)",
              set(WM._wa6_eligible_checkout_jobs(chief).ids)
              <= {jobA.id, jobB.id})

    check("REG: wa6 intents still registered",
          {"wa6_co_all", "wa6_ci_good"} <= wa_payload.INTENTS)

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
