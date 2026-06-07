# -*- coding: utf-8 -*-
"""B11 / WA-2 WhatsApp-to-ops smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pwa2_crew_ops_smoke.py

Integration tests through the real models + handle_inbound, with Meta
HTTP mocked (requests.post -> fake 200). Builds a controlled test job +
crew assignments, then exercises every WA-2 surface and ROLLS BACK.

Covers: crew->phone resolver (+priority), "Notify crew" wizard (sends
crew_assignment template per notifiable crew; skips no-phone / opted-out;
12h rate-limit), crew_confirm tap (phone-verified -> state confirmed +
rollup), crew_decline tap (decline wizard + reason + ops flagged),
phone-mismatch reject, tampered payload no-misroute, already-responded
idempotency, role-gate (non-ops blocked), STOP/START opt-out.
"""
import traceback
from datetime import date, timedelta
from contextlib import ExitStack
from unittest.mock import patch

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    line = ("PASS" if ok else "FAIL") + " " + name
    if detail and not ok:
        line += " :: " + str(detail)
    print(line)


_posts = []


class _Resp:
    status_code = 200
    text = "ok"


def _fake_post(url, json=None, headers=None, **kw):
    _posts.append({"url": url, "json": json or {}})
    return _Resp()


try:
    from odoo.addons.neon_channels.models import whatsapp_message as WMMOD
    from odoo.addons.neon_channels.models import wa_payload
    from odoo.addons.neon_ai_core.models.ai import tool_registry

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True,
                           mail_notify_force_send=False))
    ICP = env["ir.config_parameter"].sudo()
    secret = ICP.get_param("database.secret") or ""
    WM = env["neon.whatsapp.message"].sudo()
    Crew = env["commercial.job.crew"].sudo()
    Partner = env["res.partner"].sudo()
    Job = env["commercial.job"].sudo()

    def user_in_group(xmlid):
        g = env.ref(xmlid, raise_if_not_found=False)
        if not g:
            return env["res.users"]
        return env["res.users"].sudo().search(
            [("groups_id", "in", g.id), ("share", "=", False),
             ("active", "=", True)], limit=1)

    # ---- fixtures: active WhatsApp config (dev DB has none), client,
    #      venue, job, crew --------------------------------------------
    env["neon.whatsapp.config"].sudo().create({
        "name": "WA2 Test Config", "phone_number_id": "test_pnid",
        "whatsapp_business_account_id": "test_waba",
        "access_token": "test_token", "active": True})
    client = Partner.create({"name": "WA2 Client", "is_company": True})
    venue = Partner.create({"name": "WA2 Venue", "is_venue": True})
    ev = (date.today() + timedelta(days=3)).isoformat()
    job = Job.create({"name": "WA2 TEST JOB", "partner_id": client.id,
                      "venue_id": venue.id, "event_date": ev})

    P1, P2 = "+263770000001", "+263770000002"
    P4, P5 = "+263770000004", "+263770000005"
    cp1 = Partner.create({"name": "WA2 Crew One", "mobile": P1})
    cp2 = Partner.create({"name": "WA2 Crew Two", "mobile": P2})
    cp3 = Partner.create({"name": "WA2 Crew NoPhone"})
    cp4 = Partner.create({"name": "WA2 Crew Four", "mobile": P4})
    cp5 = Partner.create({"name": "WA2 Crew Five", "mobile": P5})
    a1 = Crew.create({"job_id": job.id, "partner_id": cp1.id, "role": "tech"})
    a2 = Crew.create({"job_id": job.id, "partner_id": cp2.id, "role": "runner"})
    a3 = Crew.create({"job_id": job.id, "partner_id": cp3.id, "role": "tech"})
    a4 = Crew.create({"job_id": job.id, "partner_id": cp4.id, "role": "tech"})
    a5 = Crew.create({"job_id": job.id, "partner_id": cp5.id, "role": "runner"})

    # ---- 0: resolver ----------------------------------------------
    check("R0a: _wa_resolve_phone via partner mobile (freelancer path)",
          a1._wa_resolve_phone() == P1, a1._wa_resolve_phone())
    check("R0b: _wa_all_phones contains the canonical mobile",
          P1 in a1._wa_all_phones(), a1._wa_all_phones())
    check("R0c: no-phone crew resolves to False",
          a3._wa_resolve_phone() is False)

    def crew_tap(payload, frm, text="x"):
        return {"id": "wamid.CT", "from": frm, "type": "button",
                "button": {"payload": payload, "text": text}}

    def text_msg(body, frm):
        return {"id": "wamid.TX", "from": frm, "type": "text",
                "text": {"body": body}}

    def n_template_rows(phone):
        return WM.search_count([("phone_number", "=", phone),
                                ("message_type", "=", "template"),
                                ("direction", "=", "outbound")])

    with ExitStack() as stack:
        stack.enter_context(patch.object(WMMOD.requests, "post", _fake_post))

        # ---- 1: Notify crew wizard ---------------------------------
        Wiz = env["commercial.job.crew.notify.wizard"].sudo()
        vals = Wiz.with_context(default_job_id=job.id).default_get(
            ["job_id", "candidate_crew_ids", "summary"])
        cand_ids = vals["candidate_crew_ids"][0][2]
        check("S1: wizard candidates = notifiable pending crew "
              "(a1,a2,a4,a5; a3 no-phone excluded)",
              set(cand_ids) == {a1.id, a2.id, a4.id, a5.id}, cand_ids)
        _posts.clear()
        wiz = Wiz.create(vals)
        wiz.action_send()
        check("S1: crew_assignment template sent to each (4 template rows)",
              n_template_rows(P1) == 1 and n_template_rows(P2) == 1
              and n_template_rows(P4) == 1 and n_template_rows(P5) == 1)
        check("S1: notification_sent + notified_on set on sent crew",
              a1.notification_sent and a1.notified_on
              and a2.notification_sent and a2.notified_on)
        # payload-building: the crew_assignment send for P1 carries the
        # template name + 2 quick-reply payloads (confirm/decline).
        p1send = next((p for p in _posts
                       if p["json"].get("to") == P1
                       and p["json"].get("type") == "template"), None)
        comps = (p1send or {}).get("json", {}).get(
            "template", {}).get("components", []) if p1send else []
        qr = [c for c in comps if c.get("sub_type") == "quick_reply"]
        qr_payloads = [c["parameters"][0]["payload"] for c in qr]
        body_comp = next((c for c in comps if c.get("type") == "body"), None)
        body_n = len(body_comp.get("parameters", [])) if body_comp else 0
        check("S1: send_template payload = crew_assignment + 2 quick-reply "
              "buttons",
              bool(p1send)
              and p1send["json"]["template"]["name"] == "crew_assignment"
              and len(qr) == 2, "qr=%d" % len(qr))
        # PARAM-COUNT CONTRACT (the Meta 132000 bug): crew_assignment's
        # approved template has EXACTLY 5 body vars (name, job, date,
        # time, role). A mismatch is what Meta rejected on prod.
        check("S1: crew_assignment body has EXACTLY 5 params (count "
              "contract vs approved template)", body_n == 5,
              "body params=%d (expected 5)" % body_n)
        decoded_qr = [wa_payload.decode(secret, p) for p in qr_payloads]
        check("S1: quick-reply payloads decode to crew_confirm/crew_decline "
              "for a1",
              len(decoded_qr) == 2 and all(decoded_qr)
              and {decoded_qr[0][0], decoded_qr[1][0]}
              == {"crew_confirm", "crew_decline"}
              and decoded_qr[0][1] == [str(a1.id)],
              qr_payloads)

        # ---- 2: rate-limit (re-notify within 12h) ------------------
        vals2 = Wiz.with_context(default_job_id=job.id).default_get(
            ["candidate_crew_ids"])
        check("S2: 12h rate-limit -> already-notified crew not candidates",
              vals2["candidate_crew_ids"][0][2] == [],
              vals2["candidate_crew_ids"][0][2])

        # ---- 3: opt-out suppression at send_template ---------------
        cp2.sudo().write({"wa_opt_out": True})
        res_oo = WM.send_template(P2, "crew_assignment", body_params=["x"],
                                  recipient_partner=cp2)
        check("S3: send_template suppressed for opted-out partner",
              res_oo.get("ok") is False and res_oo.get("reason") == "opted_out")
        cp2.sudo().write({"wa_opt_out": False})

        # ---- 4: crew_confirm tap (phone-verified) ------------------
        confirm_a1 = wa_payload.encode(secret, "crew_confirm", a1.id)
        WM.handle_inbound(crew_tap(confirm_a1, "263770000001", "Confirm"), {})
        a1.invalidate_recordset()
        check("S4: crew_confirm tap -> state confirmed + responded_on",
              a1.state == "confirmed" and a1.responded_on, a1.state)
        check("S4: job crew_confirmed_count rollup reflects the confirm",
              job.crew_confirmed_count >= 1, job.crew_confirmed_count)

        # ---- 5: crew_decline tap -> wizard + reason + ops flagged --
        decline_a2 = wa_payload.encode(secret, "crew_decline", a2.id)
        msgs_before = len(job.message_ids)
        WM.handle_inbound(crew_tap(decline_a2, "263770000002", "Can't make it"), {})
        a2.invalidate_recordset()
        check("S5: crew_decline tap -> state declined + decline_reason set",
              a2.state == "declined" and bool(a2.decline_reason), a2.state)
        check("S5: ops flagged (chatter posted on the job re decline)",
              len(job.message_ids) > msgs_before
              and any("decline" in (m.body or "").lower()
                      for m in job.message_ids), "no decline chatter")

        # ---- 6: phone-mismatch tap -> rejected, no mutation --------
        confirm_a4 = wa_payload.encode(secret, "crew_confirm", a4.id)
        WM.handle_inbound(crew_tap(confirm_a4, "263779999999", "Confirm"), {})
        a4.invalidate_recordset()
        check("S6: phone-mismatch crew_confirm -> NOT confirmed (two-factor)",
              a4.state == "pending", a4.state)

        # ---- 7: tampered payload -> no crew misroute ---------------
        tampered = confirm_a4[:-1] + ("0" if confirm_a4[-1] != "0" else "1")
        WM.handle_inbound(crew_tap(tampered, "263770000004", "Confirm"), {})
        a4.invalidate_recordset()
        check("S7: tampered crew payload -> NOT routed (a4 still pending)",
              a4.state == "pending"
              and wa_payload.decode(secret, tampered) is None)

        # ---- 8: already-responded idempotency ----------------------
        WM.handle_inbound(crew_tap(confirm_a1, "263770000001", "Confirm"), {})
        a1.invalidate_recordset()
        check("S8: re-tap on a confirmed assignment -> stays confirmed "
              "(idempotent)",
              a1.state == "confirmed")

        # ---- 9: STOP / START opt-out (any sender) ------------------
        WM.handle_inbound(text_msg("STOP", P4), {})
        cp4.invalidate_recordset()
        check("S9: STOP -> res.partner.wa_opt_out set",
              cp4.wa_opt_out is True)
        # and a subsequent proactive send is suppressed
        res_after_stop = WM.send_template(P4, "crew_assignment",
                                          body_params=["x"],
                                          recipient_partner=cp4)
        check("S9: post-STOP send_template suppressed",
              res_after_stop.get("reason") == "opted_out")
        WM.handle_inbound(text_msg("START", P4), {})
        cp4.invalidate_recordset()
        check("S9: START -> wa_opt_out cleared", cp4.wa_opt_out is False)

        # ---- 10: role-gate (non-ops cannot Notify crew) ------------
        sales = user_in_group("neon_core.group_neon_sales_rep")
        if sales:
            from odoo.exceptions import UserError
            try:
                job.with_user(sales.id).action_notify_crew()
                gate_blocked = False
            except UserError:
                gate_blocked = True
            check("S10: non-ops (sales rep) blocked from Notify crew",
                  gate_blocked)
        else:
            check("S10: a sales-rep fixture exists", False, "no sales user")

        # ---- 11: job_reminder param contract (4 params + URL button) --
        # a1 was confirmed in S4, so it's reminder-eligible.
        _posts.clear()
        a1.invalidate_recordset()
        rr = a1._wa_send_reminder()
        rsend = next((p for p in _posts
                      if p["json"].get("type") == "template"
                      and p["json"]["template"]["name"] == "job_reminder"),
                     None)
        rcomps = (rsend or {}).get("json", {}).get(
            "template", {}).get("components", [])
        rbody = next((c for c in rcomps if c.get("type") == "body"), None)
        rbody_n = len(rbody.get("parameters", [])) if rbody else 0
        rurl = [c for c in rcomps if c.get("sub_type") == "url"]
        check("S11: job_reminder send fired for a confirmed crew member",
              rr.get("ok") and bool(rsend), rr)
        check("S11: job_reminder body has EXACTLY 4 params (count contract: "
              "job, time, venue, role)", rbody_n == 4,
              "body params=%d (expected 4)" % rbody_n)
        check("S11: job_reminder carries a single URL button",
              len(rurl) == 1, "url buttons=%d" % len(rurl))

    # ---- regression bar: Copilot tool registry unchanged ----------
    nr = len(tool_registry.list_tools(category="read"))
    nw = len(tool_registry.list_tools(category="write"))
    check("REG: Copilot 18 tools (14 read + 4 write) unchanged",
          nr == 14 and nw == 4, "read=%d write=%d" % (nr, nw))
    check("REG: crew_confirm/crew_decline added to wa_payload INTENTS",
          {"crew_confirm", "crew_decline"} <= set(wa_payload.INTENTS))

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