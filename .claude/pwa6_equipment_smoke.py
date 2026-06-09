# -*- coding: utf-8 -*-
"""B11 / WA-6 crew + OD equipment face smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pwa6_equipment_smoke.py

Through handle_inbound (Meta + provider mocked), end-to-end. Builds
throwaway role users (OD/superuser, lead tech, crew chief, a non-role
rando, a second-job lead) + bot.user phone mappings + fresh equipment
catalogue products/units, exercises:

  A  GATES (the centerpiece -- Face 2 is UNGATED in the model, so WA-6's
     gate IS the safety): initiate / finalize / warehouse, per-record per
     job. POSITIVE crew-chief-finalize, NEGATIVE cross-job, NEGATIVE
     non-role, NARROW warehouse gate.
  B  MATCHER: qty parse, category map, match, not-found + closest-in-
     category suggestions (never auto-invents).
  C  FACE 2 FINALIZE FSM: OD 3-button initiate -> items -> review ->
     confirm (proven line.create + allocate) ; "send to crew chief" route
     ; route-refuse when neither role set ; Fix-an-item.
  D  FACE 2 two-factor + cross-job gate on the live FSM.
  E  FACE 3 warehouse checkout / check-in (run as the real user) ;
     all-good one tap ; flag bounces to Odoo ; damaged needs a photo
     (wizard contract) ; NARROW + cross-job warehouse gate.
  REG no WA-4/Copilot regression (free text w/o a session -> run_turn ;
     a WA-6 tap NEVER hits the Copilot handle_tap) ; intents registered.

Rolls back -- never commits.
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
    from odoo import fields
    from odoo.exceptions import UserError
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

    EventJob = env["commercial.event.job"].sudo()
    Line = env["commercial.event.job.equipment.line"].sudo()
    Unit = env["neon.equipment.unit"].sudo()
    Movement = env["neon.equipment.movement"].sudo()
    Crew = env["commercial.job.crew"].sudo()
    Product = env["product.template"].sudo()
    Sess = env["neon.wa.equip.session"].sudo()
    Wizard = env["neon.equipment.checkin.wizard"]

    g_user = env.ref("base.group_user")
    g_super = env.ref("neon_core.group_neon_superuser")
    g_lead = env.ref("neon_jobs.group_neon_jobs_crew_leader")
    g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
    cat_truss = env.ref("neon_jobs.equipment_category_trussing")
    cat_visual = env.ref("neon_jobs.equipment_category_visual")
    cat_cabling = env.ref("neon_jobs.equipment_category_cabling")
    check("fixtures: groups + categories resolve",
          all([g_super, g_lead, g_crew, cat_truss, cat_visual, cat_cabling]))

    env["neon.whatsapp.config"].sudo().create({
        "name": "WA6 cfg", "phone_number_id": "pn", "access_token": "t",
        "whatsapp_business_account_id": "w", "active": True})

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(user, phone):
        return env["neon.bot.user"].sudo().create({
            "name": user.login, "phone_number": phone, "user_id": user.id})

    # --- role users + phone mappings -------------------------------
    od_u = mk_user("wa6_od_smoke", [g_user, g_super])
    OD_PHONE, OD_FROM = "+263881006001", "263881006001"
    mk_bot(od_u, OD_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa6_od_login", "wa6_od_smoke")

    su_u = mk_user("wa6_su_smoke", [g_user, g_super])   # superuser, not OD
    SU_PHONE, SU_FROM = "+263881006002", "263881006002"
    mk_bot(su_u, SU_PHONE)

    lead_u = mk_user("wa6_lead_smoke", [g_user, g_lead])
    LEAD_PHONE, LEAD_FROM = "+263881006003", "263881006003"
    mk_bot(lead_u, LEAD_PHONE)

    chief_u = mk_user("wa6_chief_smoke", [g_user, g_crew])
    CHIEF_PHONE, CHIEF_FROM = "+263881006004", "263881006004"
    mk_bot(chief_u, CHIEF_PHONE)

    rando_u = mk_user("wa6_rando_smoke", [g_user])
    RANDO_PHONE, RANDO_FROM = "+263881006005", "263881006005"
    mk_bot(rando_u, RANDO_PHONE)

    leadB_u = mk_user("wa6_leadb_smoke", [g_user, g_lead])
    LEADB_PHONE, LEADB_FROM = "+263881006006", "263881006006"
    mk_bot(leadB_u, LEADB_PHONE)

    # warm OD / lead / chief so the in-window interactive path fires.
    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})

    for ph in (OD_PHONE, SU_PHONE, LEAD_PHONE, CHIEF_PHONE):
        warm(ph)

    # --- catalogue: products + active units (fresh; rolled back) ---
    def mk_product(name, wsn, cat):
        return Product.create({
            "name": name, "workshop_name": wsn, "is_workshop_item": True,
            "equipment_category_id": cat.id, "tracking_mode": "serial"})

    def mk_units(product, n, prefix):
        Unit.create([{
            "product_template_id": product.id,
            "serial_number": "%s-%03d" % (prefix, i),
            "state": "active"} for i in range(n)])

    p_truss = mk_product("Truss 2.5m Black", "2.5 Black Truss", cat_truss)
    p_truss2 = mk_product("Truss 3m Silver", "3m Silver Truss", cat_truss)
    p_screen = mk_product("LED Screen 3x2", "Screen 3x2", cat_visual)
    p_distro = mk_product("Power Distro 32A", "32A Distro", cat_cabling)
    mk_units(p_truss, 20, "WA6TR")
    mk_units(p_truss2, 5, "WA6TS")
    mk_units(p_screen, 20, "WA6SC")
    mk_units(p_distro, 10, "WA6DI")
    check("fixtures: catalogue products + active units created",
          Unit.search_count([("product_template_id", "=", p_truss.id),
                             ("state", "=", "active")]) == 20)

    # --- parent commercial.jobs + event jobs -----------------------
    parentA = env["commercial.job"].sudo().search([], limit=1, order="id")
    parentB = env["commercial.job"].sudo().search(
        [("id", "!=", parentA.id)], limit=1, order="id")
    check("fixtures: two parent commercial.jobs exist",
          bool(parentA) and bool(parentB))

    # crew chief = chief_u on parentA; clear any prior chiefs on both.
    Crew.search([("job_id", "in", (parentA.id, parentB.id))]).write(
        {"is_crew_chief": False})

    def set_chief(job, user):
        existing = Crew.search(
            [("job_id", "=", job.id),
             ("partner_id", "=", user.partner_id.id)], limit=1)
        if existing:
            existing.write({"user_id": user.id, "is_crew_chief": True})
        else:
            Crew.create({"job_id": job.id, "user_id": user.id,
                         "partner_id": user.partner_id.id,
                         "is_crew_chief": True})

    set_chief(parentA, chief_u)

    def mk_ej(parent, lead, name_hint):
        ej = EventJob.create({
            "commercial_job_id": parent.id,
            "lead_tech_id": lead.id if lead else False,
            "event_date": "2026-12-15",
            "prep_start_datetime": "2026-12-15 06:00:00",
            "return_eta_datetime": "2026-12-16 20:00:00"})
        ej.invalidate_recordset()
        return ej

    ejA = mk_ej(parentA, lead_u, "A")       # lead=lead_u, chief=chief_u
    ejW = mk_ej(parentA, lead_u, "W")       # Face-3 job, same parent/chief
    ejB = mk_ej(parentB, leadB_u, "B")      # lead=leadB, NO chief
    ejC = mk_ej(parentB, False, "C")        # NO lead, NO chief (route-refuse)
    ejA.invalidate_recordset()
    ejW.invalidate_recordset()
    check("fixtures: ejA crew_chief=chief, lead=lead",
          ejA.crew_chief_id.id == chief_u.id
          and ejA.lead_tech_id.id == lead_u.id,
          (ejA.crew_chief_id.login, ejA.lead_tech_id.login))
    check("fixtures: ejC has NO crew chief and NO lead tech",
          not ejC.crew_chief_id and not ejC.lead_tech_id)

    # ---- mocks + spies (mirror pwa5) -------------------------------
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
        for e in reversed(_sent):
            if isinstance(e, tuple) and e[0] == kind \
                    and (to is None or _digits(e[1]) == _digits(to)):
                return e
        return None

    def btn_intents(evt):
        if not evt:
            return []
        out = []
        for b in evt[3]:
            d = wa_payload.decode(secret, b["id"])
            out.append(d[0] if d else None)
        return out

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
        # A -- GATES (the centerpiece)
        # =========================================================
        check("A1: _wa6_can_initiate -- OD True, superuser True",
              WM._wa6_can_initiate(od_u) and WM._wa6_can_initiate(su_u))
        check("A1: _wa6_can_initiate -- lead/chief/rando all False",
              not WM._wa6_can_initiate(lead_u)
              and not WM._wa6_can_initiate(chief_u)
              and not WM._wa6_can_initiate(rando_u))

        check("A2: _wa6_can_finalize(ejA) -- OD + superuser allowed",
              WM._wa6_can_finalize(ejA, od_u)
              and WM._wa6_can_finalize(ejA, su_u))
        check("A2: POSITIVE -- ejA's lead tech CAN finalize ejA",
              WM._wa6_can_finalize(ejA, lead_u))
        check("A2: POSITIVE -- ejA's crew chief CAN finalize ejA",
              WM._wa6_can_finalize(ejA, chief_u))
        check("A2: NEGATIVE -- a non-role user (rando) CANNOT finalize ejA",
              not WM._wa6_can_finalize(ejA, rando_u))

        check("A3: NEGATIVE cross-job -- ejA's crew chief CANNOT finalize "
              "ejB (per-job gate holds even for chiefs)",
              not WM._wa6_can_finalize(ejB, chief_u))
        check("A3: NEGATIVE cross-job -- ejA's lead tech CANNOT finalize ejB",
              not WM._wa6_can_finalize(ejB, lead_u))

        check("A4: NARROW warehouse gate(ejA) -- lead + chief allowed",
              WM._wa6_can_warehouse(ejA, lead_u)
              and WM._wa6_can_warehouse(ejA, chief_u))
        check("A4: NARROW warehouse gate -- OD/superuser NOT allowed "
              "(per-job roles only, not the initiator)",
              not WM._wa6_can_warehouse(ejA, od_u)
              and not WM._wa6_can_warehouse(ejA, su_u))
        check("A4: NARROW warehouse gate -- rando NOT allowed",
              not WM._wa6_can_warehouse(ejA, rando_u))
        check("A4: cross-job warehouse -- ejA's lead can't warehouse ejB",
              not WM._wa6_can_warehouse(ejB, lead_u))

        check("A5: route target = crew_chief (precedence) on ejA",
              WM._wa6_route_target(ejA).id == chief_u.id)
        check("A5: route target falls back to lead_tech when no chief (ejB)",
              WM._wa6_route_target(ejB).id == leadB_u.id)
        check("A5: route target EMPTY when neither set (ejC)",
              not WM._wa6_route_target(ejC))

        # =========================================================
        # B -- MATCHER
        # =========================================================
        check("B1: qty parse 'truss x4' -> (4,'truss')",
              WM._wa6_parse_qty("truss x4") == (4, "truss"))
        check("B1: qty parse '2x screen' -> (2,'screen')",
              WM._wa6_parse_qty("2x screen") == (2, "screen"))
        check("B1: qty parse '3x2 screen' keeps dimension -> (1,'3x2 screen')",
              WM._wa6_parse_qty("3x2 screen") == (1, "3x2 screen"))
        check("B1: qty parse 'qty 5 par' -> (5,'par')",
              WM._wa6_parse_qty("qty 5 par") == (5, "par"))
        check("B1: qty parse 'par' -> (1,'par')",
              WM._wa6_parse_qty("par") == (1, "par"))

        check("B2: category map -- 'truss'->trussing, 'led screen 3x2'->"
              "visual, '17a distro'->cabling",
              WM._wa6_category_for("2.5 black truss").id == cat_truss.id
              and WM._wa6_category_for("led screen 3x2").id == cat_visual.id
              and WM._wa6_category_for("17a distro").id == cat_cabling.id)

        m = WM._wa6_match_one("2.5 black truss x4")
        check("B3: '2.5 black truss x4' -> product=Truss 2.5m Black, qty 4",
              m["status"] == "matched" and m["qty"] == 4
              and m["product_id"] == p_truss.id, m)

        m2 = WM._wa6_match_one("florble widget x1")
        check("B4: unknown no-category item -> not_found, no auto-invent, "
              "no suggestions",
              m2["status"] == "not_found" and not m2["product_id"]
              and m2["suggestions"] == [], m2)

        m3 = WM._wa6_match_one("trussing gizmo flux")
        check("B5: unknown IN a category -> not_found + closest-in-category "
              "suggestions (never auto-invents a product_id)",
              m3["status"] == "not_found" and not m3["product_id"]
              and len(m3["suggestions"]) >= 1, m3)

        items = WM._wa6_match_items(
            "2x screen 3x2, 2.5 black truss x4, florble widget")
        check("B6: multi-item split -> 3 lines (screen q2 matched, truss q4 "
              "matched, florble not_found)",
              len(items) == 3 and items[0]["qty"] == 2
              and items[0]["product_id"] == p_screen.id
              and items[1]["qty"] == 4
              and items[1]["product_id"] == p_truss.id
              and items[2]["status"] == "not_found",
              [(i["qty"], i["status"]) for i in items])

        # =========================================================
        # C -- FACE 2 FINALIZE FSM (end-to-end via handle_inbound)
        # =========================================================
        # C0: OD initiate (Odoo action) -> 3-button choice to OD
        _sent.clear()
        act = ejA.with_user(od_u.id).action_wa6_initiate_finalize()
        ib = last("buttons", OD_PHONE)
        check("C0: OD initiate -> 3-button choice to OD "
              "(self / route / odoo) on ejA",
              ib and btn_intents(ib)
              == ["wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo"]
              and isinstance(act, dict)
              and act.get("params", {}).get("type") == "success",
              btn_intents(ib))

        # C1: OD taps "I'll finalize" -> session opens (await_items)
        _sent.clear(); _reset_spies()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fin_self", ejA.id), OD_FROM), {})
        sess = Sess.search([("phone_number", "=", OD_PHONE)], limit=1)
        check("C1: 'I'll finalize' -> session(await_items) bound to OD+ejA; "
              "prompt sent; Copilot NOT touched",
              sess and sess.step == "await_items"
              and sess.user_id.id == od_u.id
              and sess.event_job_id.id == ejA.id
              and last("text", OD_PHONE) is not None
              and counters["handle_tap"] == 0
              and counters["run_turn"] == 0, sess.step if sess else None)

        # C2: OD free-texts the gear list -> matcher -> review + 2 buttons
        _sent.clear(); _reset_spies()
        WM.handle_inbound(
            text_msg("2.5 black truss x4, 2x screen 3x2", OD_FROM), {})
        sess.invalidate_recordset()
        rb = last("buttons", OD_PHONE)
        check("C2: item list -> review step, [Confirm][Fix] buttons, "
              "Copilot NOT touched (free text grabbed by the session)",
              sess.step == "review"
              and btn_intents(rb) == ["wa6_confirm", "wa6_fix"]
              and counters["run_turn"] == 0
              and counters["handle_tap"] == 0,
              (sess.step, btn_intents(rb), dict(counters)))
        check("C2: buffer holds 2 matched items (truss q4 + screen q2)",
              len(sess._get_buffer()) == 2
              and all(it["status"] == "matched"
                      for it in sess._get_buffer()))

        # C3: OD taps Confirm -> lines created + allocated on ejA
        _sent.clear()
        n_lines0 = len(ejA.equipment_line_ids)
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_confirm", sess.id), OD_FROM), {})
        ejA.invalidate_recordset()
        sess.invalidate_recordset()
        tl = ejA.equipment_line_ids.filtered(
            lambda l: l.product_template_id.id == p_truss.id)
        sl = ejA.equipment_line_ids.filtered(
            lambda l: l.product_template_id.id == p_screen.id)
        check("C3: Confirm created 2 lines on ejA (truss q4 + screen q2)",
              len(ejA.equipment_line_ids) == n_lines0 + 2
              and tl.quantity_planned == 4 and sl.quantity_planned == 2)
        check("C3: each line's units are bound + reservations confirmed "
              "(proven allocate path)",
              len(tl.reservation_ids.filtered(
                  lambda r: r.state == "confirmed" and r.unit_id)) == 4
              and len(sl.reservation_ids.filtered(
                  lambda r: r.state == "confirmed" and r.unit_id)) == 2)
        check("C3: session -> done + inactive after confirm",
              sess.step == "done" and not sess.active)

        # C4: 'Send to crew chief' -> session opens for the CHIEF + notify
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fin_route", ejA.id), OD_FROM), {})
        sess_c = Sess.search([("phone_number", "=", CHIEF_PHONE)], limit=1)
        check("C4: route -> session bound to the CREW CHIEF for ejA; chief "
              "notified; OD gets an ack",
              sess_c and sess_c.user_id.id == chief_u.id
              and sess_c.event_job_id.id == ejA.id
              and sess_c.step == "await_items"
              and last("buttons", CHIEF_PHONE) is not None
              and last("text", OD_PHONE) is not None,
              sess_c.step if sess_c else None)

        # C5: route when NEITHER chief nor lead is set -> refuse
        _sent.clear()
        # OD initiates ejC first so the OD phone is the initiator context;
        # route on ejC has no target.
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fin_route", ejC.id), OD_FROM), {})
        ref = last("text", OD_PHONE)
        check("C5: route with no crew chief AND no lead tech -> refused "
              "('assign one first'), no session for ejC",
              ref and "assign one" in ref[2].lower()
              and not Sess.search_count(
                  [("event_job_id", "=", ejC.id), ("active", "=", True)]),
              ref[2] if ref else None)

        # =========================================================
        # D -- FACE 2 two-factor + cross-job gate on the live FSM
        # =========================================================
        # D1: TWO-FACTOR -- a different phone taps the chief's session id
        _sent.clear()
        nbuf = len(sess_c._get_buffer())
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_confirm", sess_c.id), RANDO_FROM), {})
        sess_c.invalidate_recordset()
        d1 = last("text", RANDO_PHONE)
        check("D1: two-factor -- a valid payload tapped from the WRONG phone "
              "is refused ('not linked'), buffer untouched",
              d1 and "isn't linked" in d1[2].lower()
              and len(sess_c._get_buffer()) == nbuf, d1[2] if d1 else None)

        # D2: POSITIVE crew-chief finalize -- the routed-to chief CAN
        # finalize ejA (received the scope): items -> confirm -> reservations
        _sent.clear()
        WM.handle_inbound(text_msg("3m silver truss x2", CHIEF_FROM), {})
        sess_c.invalidate_recordset()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_confirm", sess_c.id), CHIEF_FROM), {})
        ejA.invalidate_recordset()
        chief_line = ejA.equipment_line_ids.filtered(
            lambda l: l.product_template_id.id == p_truss2.id)
        check("D2: POSITIVE -- the routed-to crew chief finalized ejA; "
              "reservations created + bound (truss2 q2)",
              chief_line and chief_line.quantity_planned == 2
              and len(chief_line.reservation_ids.filtered(
                  lambda r: r.state == "confirmed" and r.unit_id)) == 2,
              chief_line.mapped("reservation_ids.state") if chief_line
              else None)

        # D3: NEGATIVE cross-job on the live FSM -- a session mis-bound to
        # the chief on ejB is re-gated on the text turn and refused (the
        # per-job gate holds even for a crew chief), NO lines on ejB.
        mis = Sess._start(CHIEF_PHONE, chief_u, ejB)
        _sent.clear()
        n_b = len(ejB.equipment_line_ids)
        WM.handle_inbound(text_msg("2.5 black truss x4", CHIEF_FROM), {})
        ejB.invalidate_recordset()
        mis.invalidate_recordset()
        d3 = last("text", CHIEF_PHONE)
        check("D3: NEGATIVE cross-job -- chief of A finalizing ejB is "
              "re-gated + refused; NO lines written to ejB; session killed",
              d3 and "authorised" in d3[2].lower()
              and len(ejB.equipment_line_ids) == n_b
              and not mis.active, d3[2] if d3 else None)

        # D-FIX: Fix-an-item -- a not_found item blocks Confirm, fix patches
        # one row, then Confirm succeeds.
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fin_self", ejW.id), OD_FROM), {})
        sess_f = Sess.search([("phone_number", "=", OD_PHONE)], limit=1)
        WM.handle_inbound(
            text_msg("2x screen 3x2, florble widget", OD_FROM), {})
        sess_f.invalidate_recordset()
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_confirm", sess_f.id), OD_FROM), {})
        blocked = last("text", OD_PHONE)
        check("DF1: Confirm with a not_found item is REFUSED until fixed",
              blocked and "need fixing" in blocked[2].lower(),
              blocked[2] if blocked else None)
        # tap Fix -> a list of rows; pick row index 1 (the florble item)
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fix", sess_f.id), OD_FROM), {})
        fl = last("list", OD_PHONE)
        check("DF2: Fix an item -> a row list (one wa6_fixrow row per item)",
              fl and len(fl[3][0]["rows"]) == 2)
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fixrow", sess_f.id, 1), OD_FROM), {})
        sess_f.invalidate_recordset()
        check("DF3: picking a row -> step=fixing on that index",
              sess_f.step == "fixing" and sess_f.fix_index == 1)
        # retype the bad item correctly -> re-match -> back to review
        WM.handle_inbound(text_msg("2.5 black truss x4", OD_FROM), {})
        sess_f.invalidate_recordset()
        buf_f = sess_f._get_buffer()
        check("DF4: retype patched ONLY that row (rest stays); all matched",
              sess_f.step == "review" and len(buf_f) == 2
              and buf_f[0]["product_id"] == p_screen.id
              and buf_f[1]["product_id"] == p_truss.id
              and all(it["status"] == "matched" for it in buf_f),
              [(i["qty"], i["status"]) for i in buf_f])
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_confirm", sess_f.id), OD_FROM), {})
        ejW.invalidate_recordset()
        check("DF5: after fixing, Confirm creates both lines on ejW",
              len(ejW.equipment_line_ids) == 2)

        # =========================================================
        # E -- FACE 3 WAREHOUSE checkout / check-in (real user)
        # =========================================================
        # dedicated allocated line on ejW for a clean checkout/checkin
        coLine = Line.create({
            "event_job_id": ejW.id, "product_template_id": p_distro.id,
            "quantity_planned": 3})
        coLine.action_allocate_units()
        coLine.invalidate_recordset()
        check("E0: dedicated distro line allocated on ejW (3 reserved)",
              len(coLine.reservation_ids.filtered(
                  lambda r: r.state == "confirmed" and r.unit_id)) == 3)

        # E1 NEGATIVE: rando can't check out (NARROW gate), no movement
        _sent.clear()
        mv0 = Movement.search_count([("event_job_id", "=", ejW.id)])
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_co_all", ejW.id), RANDO_FROM), {})
        e1 = last("text", RANDO_PHONE)
        check("E1: NEGATIVE -- rando check-out refused; NO movement written",
              e1 and "lead tech or crew chief" in e1[2].lower()
              and Movement.search_count(
                  [("event_job_id", "=", ejW.id)]) == mv0,
              e1[2] if e1 else None)

        # E1b cross-job: ejW's lead can't warehouse ejB
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_co_all", ejB.id), LEAD_FROM), {})
        e1b = last("text", LEAD_PHONE)
        check("E1b: cross-job -- ejW's lead can't check out ejB",
              e1b and "lead tech or crew chief" in e1b[2].lower(),
              e1b[2] if e1b else None)

        # E2 POSITIVE: lead checks out all -> units checked_out, actor=lead
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_co_all", ejW.id), LEAD_FROM), {})
        coLine.invalidate_recordset()
        co_units = coLine.reservation_ids.mapped("unit_id")
        mv = Movement.search([("event_job_id", "=", ejW.id),
                              ("movement_type", "=", "checkout")])
        check("E2: lead 'check out all' -> units checked_out; movement "
              "actor_id = the REAL lead user (audit honest)",
              all(u.state == "checked_out" for u in co_units)
              and mv and all(m.actor_id.id == lead_u.id for m in mv),
              co_units.mapped("state"))

        # E3 DAMAGED needs a photo (wizard contract that ci_flag bounces to)
        wiz = Wizard.sudo().with_context(
            default_event_job_id=ejW.id).create({"event_job_id": ejW.id})
        vals_lines = wiz.default_get(["checkin_line_ids"])
        wiz.write({"checkin_line_ids": vals_lines.get("checkin_line_ids")})
        err = None
        if wiz.checkin_line_ids:
            wiz.checkin_line_ids[0].condition_at_event = "damaged"
            try:
                with env.cr.savepoint():
                    wiz.action_confirm()
            except Exception as e:  # noqa: BLE001
                err = e
        check("E3: check-in condition=damaged with NO photo -> UserError "
              "(photo required) -- the contract the WA flag-path bounces to",
              isinstance(err, UserError) and "photo" in str(err).lower(),
              type(err).__name__ if err else None)

        # E4 FLAG -> bounce to Odoo with a deep link (no state change)
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_ci_flag", ejW.id), LEAD_FROM), {})
        e4 = last("text", LEAD_PHONE)
        check("E4: 'Flag an item' -> bounce reply with an Odoo deep link "
              "(photo/condition captured in Odoo)",
              e4 and "/web#id=%s" % ejW.id in e4[2]
              and "odoo" in e4[2].lower(), e4[2] if e4 else None)

        # E5 ALL GOOD -> headless wizard, units returned to active
        _sent.clear()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_ci_good", ejW.id), LEAD_FROM), {})
        co_units.invalidate_recordset()
        e5 = last("text", LEAD_PHONE)
        check("E5: 'All returned good' -> headless check-in; units back to "
              "active; confirmation sent",
              all(u.state == "active" for u in co_units)
              and e5 and "checked in" in e5[2].lower(),
              co_units.mapped("state"))

        # =========================================================
        # REG -- no WA-4/Copilot regression + intents registered
        # =========================================================
        # a mapped staff member with NO active finalize session -> the free
        # text falls THROUGH to the Copilot (run_turn), unchanged.
        Sess.search([("phone_number", "=", RANDO_PHONE)]).write(
            {"active": False})
        _sent.clear(); _reset_spies()
        WM.handle_inbound(text_msg("what's my schedule?", RANDO_FROM), {})
        check("REG1: mapped staff, NO session -> free text reaches the "
              "Copilot (run_turn + variant_for), zero WA-4 regression",
              counters["run_turn"] >= 1 and counters["variant_for"] >= 1,
              dict(counters))

        # a WA-6 tap is handled by the bridge and NEVER reaches the Copilot
        # handle_tap router.
        _reset_spies()
        WM.handle_inbound(
            tap_msg(WM._wa6_payload("wa6_fin_odoo", ejA.id), OD_FROM), {})
        check("REG2: a WA-6 tap is intercepted by the bridge; the Copilot "
              "handle_tap is NEVER called",
              counters["handle_tap"] == 0, dict(counters))

    # ---- regression bar --------------------------------------------
    WA6_INTENTS = {
        "wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo", "wa6_confirm",
        "wa6_fix", "wa6_fixrow", "wa6_co_all", "wa6_co_item", "wa6_co_line",
        "wa6_ci_good", "wa6_ci_flag"}
    check("REG3: all 11 WA-6 intents registered in wa_payload.INTENTS",
          WA6_INTENTS <= wa_payload.INTENTS)
    check("REG3: pre-existing WA-5 intents still present (no clobber)",
          {"assign_open", "assign_pick", "assignee_decline",
           "crew_confirm", "crew_decline"} <= wa_payload.INTENTS)

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
