# -*- coding: utf-8 -*-
"""B11 / WA-6.2 OD WhatsApp-initiated finalize dispatch smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pwa6_2_finalize_dispatch_smoke.py

Exercises the REAL path -- OD texts a tight "finalize" command -> bot lists
ONLY planning/prep jobs with no equipment lines yet (from-scratch) -> OD
picks a number -> bot SENDS the existing [I'll finalize][Send to crew chief]
[Open in Odoo] choice -> tapping [I'll finalize] opens the proven Face-2
finalize session (await_items). NOT synthesised taps. Rolls back.

PARSE  tight command recognises finalize/finalise/finalize equipment; never
       mid-sentence ("can you finalize the budget", "I'll finalize it later")
GATE   OD (config login) + superuser pass _wa6_can_initiate; plain crew fails
ELIG   planning/prep + no lines = eligible; has-lines + draft excluded
T1     OD "finalize" -> numbered list (elig only); Copilot 0; fin_pick session
T2     pick the listed number -> SENT [fin_self][fin_route][fin_odoo] for it
T3     tap the REALLY-sent [I'll finalize] -> fresh await_items session (handoff)
T6     non-OD mapped "finalize" -> NOT grabbed (intercept None -> Copilot)
T7     unmapped "finalize" -> intercept None (client lane)
T8     mid-sentence "finalize" -> NOT grabbed (intercept None -> Copilot)
T9     British "finalise" -> recognised (list sent); Copilot 0
T10    OD normal message, no session -> Copilot (no regression)
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
    Line = env["commercial.event.job.equipment.line"].sudo()
    Prod = env["product.template"].sudo()
    Sess = env["neon.wa.equip.session"].sudo()

    g_user = env.ref("base.group_user")
    g_su = env.ref("neon_core.group_neon_superuser")
    cat_truss = env.ref("neon_jobs.equipment_category_trussing")
    parent = env["commercial.job"].sudo().search([], limit=1, order="id")
    check("fixtures: group/superuser/cat/parent present",
          all([g_user, g_su, cat_truss, parent]))

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(u, phone):
        env["neon.bot.user"].sudo().create({
            "name": u.login, "phone_number": phone, "user_id": u.id})

    # OD resolved by the config login param (real OD-resolution path, NOT a
    # superuser shortcut). A separate superuser user exercises the fallback.
    od = mk_user("wa62_od", [g_user])
    OD_PHONE, OD_FROM = "+263881008001", "263881008001"
    mk_bot(od, OD_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa6_od_login", od.login)

    crew = mk_user("wa62_crew", [g_user])           # mapped, NON-OD
    CREW_PHONE, CREW_FROM = "+263881008002", "263881008002"
    mk_bot(crew, CREW_PHONE)

    su = mk_user("wa62_su", [g_user, g_su])         # away-fallback superuser
    SU_PHONE, SU_FROM = "+263881008003", "263881008003"
    mk_bot(su, SU_PHONE)
    UNMAPPED_FROM = "263881008999"

    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})
    for ph in (OD_PHONE, CREW_PHONE, SU_PHONE):
        warm(ph)

    W = ("2026-12-15 06:00:00", "2026-12-16 20:00:00", "2026-12-15")

    def mk_job(name, state):
        ej = EJ.create({"commercial_job_id": parent.id, "lead_tech_id": od.id,
                        "event_date": W[2], "prep_start_datetime": W[0],
                        "return_eta_datetime": W[1], "name": name,
                        "state": state})
        ej.invalidate_recordset()
        return ej

    elig_a = mk_job("WA62 ELIG A", "planning")      # planning, no lines
    elig_b = mk_job("WA62 ELIG B", "prep")          # prep, no lines
    has_lines = mk_job("WA62 HAS-LINES", "planning")  # planning, HAS a line
    draft_job = mk_job("WA62 DRAFT", "draft")       # not planning/prep

    p_qty = Prod.create({
        "name": "WA62 Truss Pins", "workshop_name": "WA62 Truss Pins",
        "is_workshop_item": True, "equipment_category_id": cat_truss.id,
        "tracking_mode": "quantity", "quantity_on_hand": 10})
    Line.create({"event_job_id": has_lines.id,
                 "product_template_id": p_qty.id, "quantity_planned": 2})
    has_lines.invalidate_recordset()

    # ---- PARSE: tight command, no false positives (deterministic) ----
    check("PARSE: finalize/finalise/finalize equipment -> 'finalize'; "
          "mid-sentence & budget -> None; checkout still 'checkout'",
          WM._wa6_is_command("finalize") == "finalize"
          and WM._wa6_is_command("finalise") == "finalize"
          and WM._wa6_is_command("Finalize Equipment") == "finalize"
          and WM._wa6_is_command("finalize WA62 ELIG A") == "finalize"
          and WM._wa6_is_command("can you finalize the budget") is None
          and WM._wa6_is_command("I'll finalize it later") is None
          and WM._wa6_is_command("check out") == "checkout",
          [WM._wa6_is_command(x) for x in
           ("finalize", "finalise", "can you finalize the budget")])

    # ---- GATE: OD (param) + superuser pass; plain crew fails ----
    check("GATE: OD-by-login + superuser pass _wa6_can_initiate; crew fails",
          WM._wa6_can_initiate(od) and WM._wa6_can_initiate(su)
          and not WM._wa6_can_initiate(crew),
          (WM._wa6_can_initiate(od), WM._wa6_can_initiate(su),
           WM._wa6_can_initiate(crew)))

    # ---- ELIG: from-scratch + state filter ----
    elig_ids = set(WM._wa6_eligible_finalize_jobs(od).ids)
    check("ELIG: elig_a + elig_b are finalize-eligible (planning/prep, "
          "no lines)", {elig_a.id, elig_b.id} <= elig_ids,
          sorted(elig_ids)[-6:])
    check("ELIG: FROM-SCRATCH -- a job WITH equipment lines is excluded",
          has_lines.id not in elig_ids)
    check("ELIG: STATE -- a draft (non planning/prep) job is excluded",
          draft_job.id not in elig_ids)

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

        # T1: OD "finalize" -> numbered list of eligible only; Copilot 0
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("finalize", OD_FROM), {})
        lst = last("text", OD_PHONE)
        check("T1: OD 'finalize' -> list incl ELIG A + ELIG B, excl "
              "HAS-LINES + DRAFT; Copilot untouched",
              lst and "WA62 ELIG A" in lst[2] and "WA62 ELIG B" in lst[2]
              and "WA62 HAS-LINES" not in lst[2]
              and "WA62 DRAFT" not in lst[2]
              and counters["run_turn"] == 0, lst[2] if lst else None)

        sess = od_sess()
        buf = sess._get_buffer() if sess else []
        check("T1b: fin_pick session opened, eligible job ids buffered",
              sess and sess.step == "fin_pick" and elig_b.id in buf,
              (sess.step if sess else None, buf[-6:]))
        pos_b = (buf.index(elig_b.id) + 1) if elig_b.id in buf else 0

        # T2: pick ELIG B's number -> SENT the 3-button finalize choice
        _sent.clear()
        WM.handle_inbound(text_msg(str(pos_b), OD_FROM), {})
        bt = last("buttons", OD_PHONE)
        ids = [b["id"] for b in bt[3]] if bt else []
        decoded = [wa_payload.decode(secret, i) for i in ids]
        check("T2: pick ELIG B -> SENT [fin_self][fin_route][fin_odoo] for "
              "ELIG B (the dispatch)",
              bt and [d[0] for d in decoded]
              == ["wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo"]
              and all(int(d[1][0]) == elig_b.id for d in decoded),
              [d[0] if d else None for d in decoded])

        # T3: tap the REALLY-sent [I'll finalize] -> fresh await_items session
        fin_self_payload = ids[0] if ids else ""
        WM.handle_inbound(tap_msg(fin_self_payload, OD_FROM), {})
        fsess = od_sess()
        check("T3: tap [I'll finalize] -> FRESH finalize session "
              "(await_items, ELIG B, OD) -- handoff to the proven Face-2 flow",
              fsess and fsess.step == "await_items"
              and fsess.event_job_id.id == elig_b.id
              and fsess.user_id.id == od.id,
              (fsess.step if fsess else None,
               fsess.event_job_id.id if fsess else None,
               fsess.user_id.id if fsess else None))

        # T3a: tap [Open in Odoo] (the WA-6.2-sent fin_odoo button) -> link
        _sent.clear()
        WM.handle_inbound(tap_msg(ids[2] if len(ids) > 2 else "", OD_FROM), {})
        odoo_reply = last("text", OD_PHONE)
        check("T3a: tap [Open in Odoo] from the WA-6.2 buttons -> Odoo link "
              "reply for ELIG B (fin_odoo via the existing Face-2 path)",
              odoo_reply and "Odoo" in odoo_reply[2]
              and ("#id=%d" % elig_b.id) in odoo_reply[2]
              and "commercial.event.job" in odoo_reply[2],
              odoo_reply[2] if odoo_reply else None)

        # T3b: tap [Send to crew chief] (fin_route) -> routes to the job's
        # lead_tech/crew_chief (here lead_tech = OD) via the existing path
        _sent.clear()
        WM.handle_inbound(tap_msg(ids[1] if len(ids) > 1 else "", OD_FROM), {})
        route_reply = last("text", OD_PHONE)
        check("T3b: tap [Send to crew chief] from the WA-6.2 buttons -> "
              "fin_route handled via the existing Face-2 path (routed, or "
              "target has no phone / none assigned -- all valid route "
              "outcomes; NOT an auth refusal)",
              route_reply and any(s in route_reply[2] for s in (
                  "Sent to", "no WhatsApp number", "assign one in Odoo"))
              and "Only the OD" not in route_reply[2],
              route_reply[2] if route_reply else None)

        check("SAFETY: listed/buffered jobs are a SUBSET of the eligible set "
              "(pick-by-number, never by name)",
              set(buf) <= set(WM._wa6_eligible_finalize_jobs(od).ids))

        # T6: non-OD mapped 'finalize' -> NOT grabbed (intercept None)
        clear_od()
        _sent.clear(); _reset()
        r6 = WM._wa6_maybe_intercept(text_msg("finalize", CREW_FROM))
        WM.handle_inbound(text_msg("finalize", CREW_FROM), {})
        check("T6: non-OD mapped 'finalize' -> NOT grabbed (intercept None "
              "-> Copilot ran), no fin_pick session",
              r6 is None and counters["run_turn"] >= 1
              and not Sess.search([("phone_number", "=", CREW_PHONE),
                                   ("step", "=", "fin_pick"),
                                   ("active", "=", True)]),
              (r6, dict(counters)))

        # T7: unmapped 'finalize' -> intercept None (client lane)
        r7 = WM._wa6_maybe_intercept(text_msg("finalize", UNMAPPED_FROM))
        check("T7: unmapped 'finalize' -> intercept None (client lane)",
              r7 is None, r7)

        # T8: mid-sentence 'finalize' -> NOT grabbed (intercept None)
        clear_od()
        _sent.clear(); _reset()
        r8a = WM._wa6_maybe_intercept(
            text_msg("can you finalize the budget for me", OD_FROM))
        r8b = WM._wa6_maybe_intercept(
            text_msg("I'll finalize it later", OD_FROM))
        WM.handle_inbound(
            text_msg("can you finalize the budget for me", OD_FROM), {})
        check("T8: mid-sentence 'finalize' NOT grabbed (intercept None x2 -> "
              "Copilot ran), no fin_pick session",
              r8a is None and r8b is None and counters["run_turn"] >= 1
              and not Sess.search([("phone_number", "=", OD_PHONE),
                                   ("step", "=", "fin_pick"),
                                   ("active", "=", True)]),
              (r8a, r8b, dict(counters)))

        # T9: British 'finalise' -> recognised (list sent); Copilot 0
        clear_od()
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("finalise", OD_FROM), {})
        l9 = last("text", OD_PHONE)
        check("T9: British 'finalise' recognised -> list sent; Copilot 0",
              l9 and "WA62 ELIG" in l9[2] and counters["run_turn"] == 0,
              l9[2] if l9 else None)

        # T10: OD normal message, no session -> Copilot (regression)
        clear_od()
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("hello what's my schedule", OD_FROM), {})
        check("T10: OD normal message -> Copilot (run_turn>=1), no WA-6 grab",
              counters["run_turn"] >= 1, dict(counters))

        # T-SU: a mapped SUPERUSER (away-fallback) runs the FULL flow:
        # finalize -> list -> pick -> [I'll finalize] -> await_items handoff.
        # Proves superuser resolution + session binding through the real
        # path, not just the unit gate check above.
        clear_od()
        Sess.search([("phone_number", "=", SU_PHONE)]).write({"active": False})
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("finalize", SU_FROM), {})
        su_list = last("text", SU_PHONE)
        su_sess = Sess.search([("phone_number", "=", SU_PHONE),
                               ("active", "=", True)], limit=1)
        su_buf = su_sess._get_buffer() if su_sess else []
        check("T-SU: superuser 'finalize' -> list + fin_pick session; "
              "Copilot 0 (away-fallback resolves through the full path)",
              su_list and "WA62 ELIG" in su_list[2] and su_sess
              and su_sess.step == "fin_pick" and elig_b.id in su_buf
              and counters["run_turn"] == 0,
              (su_sess.step if su_sess else None, counters["run_turn"]))
        su_pos = (su_buf.index(elig_b.id) + 1) if elig_b.id in su_buf else 0
        _sent.clear()
        WM.handle_inbound(text_msg(str(su_pos), SU_FROM), {})
        su_bt = last("buttons", SU_PHONE)
        su_ids = [b["id"] for b in su_bt[3]] if su_bt else []
        WM.handle_inbound(tap_msg(su_ids[0] if su_ids else "", SU_FROM), {})
        su_fsess = Sess.search([("phone_number", "=", SU_PHONE),
                                ("active", "=", True)], limit=1)
        check("T-SU: superuser pick -> buttons -> [I'll finalize] tap -> "
              "FRESH await_items session (full integration, not just gate)",
              su_bt and su_fsess and su_fsess.step == "await_items"
              and su_fsess.event_job_id.id == elig_b.id
              and su_fsess.user_id.id == su.id,
              (su_fsess.step if su_fsess else None,
               su_fsess.user_id.id if su_fsess else None))

        # T-RANGE + T-RETYPE: an out-of-range number re-shows the list; a
        # re-typed 'finalize' restarts -- both keep step=fin_pick, no buttons.
        clear_od()
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("finalize", OD_FROM), {})
        _sent.clear()
        WM.handle_inbound(text_msg("99", OD_FROM), {})
        rng_reply = last("text", OD_PHONE)
        rng_btn = last("buttons", OD_PHONE)
        rng_sess = od_sess()
        check("T-RANGE: out-of-range '99' -> list re-shown, NO buttons, "
              "still fin_pick (no session corruption)",
              rng_reply and "finalize" in rng_reply[2].lower()
              and rng_btn is None and rng_sess
              and rng_sess.step == "fin_pick",
              (rng_sess.step if rng_sess else None, rng_btn is not None))
        _sent.clear()
        WM.handle_inbound(text_msg("finalize", OD_FROM), {})
        rt_reply = last("text", OD_PHONE)
        rt_btn = last("buttons", OD_PHONE)
        rt_sess = od_sess()
        check("T-RETYPE: re-typed 'finalize' during fin_pick -> fresh list, "
              "NO buttons, still fin_pick",
              rt_reply and "Jobs ready to finalize" in rt_reply[2]
              and rt_btn is None and rt_sess and rt_sess.step == "fin_pick",
              (rt_sess.step if rt_sess else None, rt_btn is not None))

        # T-RELIST: a buffered job that GAINS equipment lines after listing
        # is REJECTED at pick time (the from-scratch re-check hardening).
        clear_od()
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("finalize", OD_FROM), {})
        rl_sess = od_sess()
        rl_buf = rl_sess._get_buffer() if rl_sess else []
        check("T-RELIST pre: ELIG A is in the fresh buffer (still from-scratch)",
              elig_a.id in rl_buf, rl_buf[-6:])
        rl_pos = (rl_buf.index(elig_a.id) + 1) if elig_a.id in rl_buf else 0
        # concurrent finalize: ELIG A gains a line AFTER it was listed
        Line.create({"event_job_id": elig_a.id,
                     "product_template_id": p_qty.id, "quantity_planned": 1})
        elig_a.invalidate_recordset()
        _sent.clear()
        WM.handle_inbound(text_msg(str(rl_pos), OD_FROM), {})
        rl_reply = last("text", OD_PHONE)
        rl_btn = last("buttons", OD_PHONE)
        check("T-RELIST: picking a job that gained lines after listing is "
              "REJECTED (no buttons; from-scratch re-checked at pick time)",
              rl_reply and ("isn't awaiting" in rl_reply[2]
                            or "already has equipment" in rl_reply[2])
              and rl_btn is None,
              (rl_reply[2] if rl_reply else None, rl_btn is not None))

    check("REG: wa6_fin_* intents still registered (NO new intent added)",
          {"wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo"}
          <= wa_payload.INTENTS)

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