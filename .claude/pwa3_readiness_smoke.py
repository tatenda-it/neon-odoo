# -*- coding: utf-8 -*-
"""B11 / WA-3 readiness-digest smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pwa3_readiness_smoke.py

Integration tests against the real models + the served board, Meta HTTP
mocked. Builds controlled jobs in each RAG bucket and ROLLS BACK.

Covers: composite RAG (_rag per job), collect() bucketing, manual send
(4 fixed counts: date/ready/needs-attention/not-started + static board
URL, no per-recipient params), cron present + DISABLED, opt-out
suppression, empty-day -> no send, manager-gate on the manual send,
board gate (manager yes / sales+portal no) + board renders.
"""
import traceback
from datetime import date, timedelta
from contextlib import ExitStack
from unittest.mock import patch

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


_posts = []


class _Resp:
    status_code = 200
    text = "ok"


def _fake_post(url, json=None, headers=None, **kw):
    _posts.append({"url": url, "json": json or {}})
    return _Resp()


try:
    from odoo.addons.neon_channels.models import whatsapp_message as WMMOD
    from odoo.addons.neon_ai_core.models.ai import tool_registry
    from odoo.addons.neon_crew_comms.controllers.readiness import (
        board_may_view,
    )
    from odoo.exceptions import UserError

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True,
                           mail_notify_force_send=False))
    Digest = env["neon.readiness.digest"].sudo()
    Job = env["commercial.job"].sudo()
    Crew = env["commercial.job.crew"].sudo()
    Partner = env["res.partner"].sudo()

    def user_in_group(xmlid):
        g = env.ref(xmlid, raise_if_not_found=False)
        if not g:
            return env["res.users"]
        return env["res.users"].sudo().search(
            [("groups_id", "in", g.id), ("share", "=", False),
             ("active", "=", True)], limit=1)

    # ---- fixtures --------------------------------------------------
    env["neon.whatsapp.config"].sudo().create({
        "name": "WA3 Test Config", "phone_number_id": "test_pnid",
        "whatsapp_business_account_id": "test_waba",
        "access_token": "test_token", "active": True})
    client = Partner.create({"name": "WA3 Client", "is_company": True})
    venue = Partner.create({"name": "WA3 Venue", "is_venue": True})
    ev = (date.today() + timedelta(days=2)).isoformat()

    def mkjob(name, op_status):
        return Job.create({"name": name, "partner_id": client.id,
                           "venue_id": venue.id, "event_date": ev,
                           "operational_status": op_status})

    job_red = mkjob("WA3 RED", "planning")          # not started -> red
    job_amber = mkjob("WA3 AMBER", "confirmed")      # locked, crew gap
    job_green = mkjob("WA3 GREEN", "confirmed")      # locked, crew full
    # amber: 1 pending crew (gap). green: 1 confirmed crew.
    cpa = Partner.create({"name": "WA3 Crew A", "mobile": "+263770000071"})
    cpb = Partner.create({"name": "WA3 Crew B", "mobile": "+263770000072"})
    Crew.create({"job_id": job_amber.id, "partner_id": cpa.id,
                 "role": "tech"})
    gcrew = Crew.create({"job_id": job_green.id, "partner_id": cpb.id,
                         "role": "tech"})
    gcrew.action_confirm()
    for j in (job_red, job_amber, job_green):
        j.invalidate_recordset()

    # ---- 1: composite RAG per job ----------------------------------
    check("R1: planning -> red", Digest._rag(job_red) == "red",
          Digest._rag(job_red))
    check("R1: confirmed + crew gap (0/1) -> amber",
          Digest._rag(job_amber) == "amber",
          "%s crew=%s/%s" % (Digest._rag(job_amber),
                             job_amber.crew_confirmed_count,
                             job_amber.crew_total_count))
    check("R1: confirmed + crew full (1/1) -> green",
          Digest._rag(job_green) == "green",
          "%s crew=%s/%s" % (Digest._rag(job_green),
                             job_green.crew_confirmed_count,
                             job_green.crew_total_count))

    # ---- 2: collect() bucketing (robust to other jobs in window) ---
    data = Digest.collect()
    by_id = {r["id"]: r for r in data["jobs"]}
    check("R2: collect buckets my 3 jobs correctly",
          by_id.get(job_red.id, {}).get("rag") == "red"
          and by_id.get(job_amber.id, {}).get("rag") == "amber"
          and by_id.get(job_green.id, {}).get("rag") == "green")
    check("R2: counts sum == total (consistent aggregate)",
          sum(data["counts"].values()) == data["total"]
          and data["total"] >= 3)
    check("R2: no money field leaked into rows",
          all(not any(k in r for k in
                      ("quoted_value", "amount", "price"))
              for r in data["jobs"]))

    with ExitStack() as stack:
        stack.enter_context(patch.object(WMMOD.requests, "post", _fake_post))

        # ---- 3: manual send (manager) -> 4 fixed counts ------------
        mgr = (user_in_group("neon_jobs.group_neon_jobs_manager")
               or user_in_group("neon_jobs.group_neon_jobs_crew_leader"))
        if mgr:
            mgr.partner_id.sudo().write({"mobile": "+263770000099",
                                         "wa_opt_out": False})
            _posts.clear()
            res = Digest.with_user(mgr.id).action_send_now()
            d2 = Digest.collect()
            c = d2["counts"]
            tpl = next((p for p in _posts
                        if p["json"].get("type") == "template"
                        and p["json"]["template"]["name"] == "daily_readiness"),
                       None)
            body = []
            if tpl:
                bc = next((x for x in tpl["json"]["template"]["components"]
                           if x.get("type") == "body"), None)
                body = [pp["text"] for pp in bc["parameters"]] if bc else []
            check("R3: manual send fired (>=1 manager reached)",
                  res.get("sent", 0) >= 1 and bool(tpl), res)
            check("R3: daily_readiness body = EXACTLY 4 fixed counts "
                  "(date, ready, needs-attention, not-started)",
                  len(body) == 4
                  and body == [d2["date_label"], str(c["green"]),
                               str(c["amber"]), str(c["red"])], body)
            check("R3: no quick-reply/url params (static board URL "
                  "button in approved template)",
                  tpl and not any(
                      x.get("sub_type") in ("quick_reply", "url")
                      for x in tpl["json"]["template"]["components"]))
        else:
            check("R3: a manager/crew-leader fixture exists", False,
                  "no manager user")

        # ---- 4: opt-out suppression (unit) -------------------------
        cpa.sudo().write({"wa_opt_out": True})
        oo = env["neon.whatsapp.message"].sudo().send_template(
            "+263770000071", "daily_readiness",
            body_params=["x", "1", "2", "3"], recipient_partner=cpa)
        check("R4: send_template suppressed for an opted-out recipient",
              oo.get("reason") == "opted_out")

        # ---- 5: empty-day -> no send -------------------------------
        empty = {"total": 0, "counts": {"green": 0, "amber": 0, "red": 0},
                 "date_label": "x", "jobs": []}
        _posts.clear()
        with patch.object(type(Digest), "collect",
                          lambda self, window_days=7: empty):
            r_empty = Digest._send_to_managers()
        check("R5: empty window -> empty=True, nothing sent",
              r_empty.get("empty") is True and r_empty.get("sent") == 0
              and not _posts)

        # ---- 6: manager-gate on the manual send --------------------
        sales = user_in_group("neon_core.group_neon_sales_rep")
        if sales:
            try:
                Digest.with_user(sales.id).action_send_now()
                blocked = False
            except UserError:
                blocked = True
            check("R6: non-ops (sales) blocked from manual send", blocked)
        else:
            check("R6: a sales fixture exists", False, "no sales user")

        # ---- 7: board gate + render --------------------------------
        pub = env.ref("base.public_user").sudo()
        check("R7: board gate -- manager yes",
              bool(mgr) and board_may_view(mgr))
        check("R7: board gate -- public/portal NO",
              not board_may_view(pub))
        check("R7: board gate -- sales NO",
              bool(sales) and not board_may_view(sales))
        html = env["ir.qweb"]._render(
            "neon_crew_comms.readiness_board", {"data": Digest.collect()})
        check("R7: board template renders + shows RAG legend",
              "Readiness" in str(html) and "Needs attention" in str(html))

    # ---- 8: cron present + DISABLED --------------------------------
    cron = env.ref("neon_crew_comms.ir_cron_wa3_readiness_digest",
                   raise_if_not_found=False)
    check("R8: readiness cron present + DISABLED (active=False)",
          bool(cron) and cron.active is False,
          "present=%s active=%s" % (bool(cron),
                                    cron.active if cron else None))

    # ---- regression bar --------------------------------------------
    check("REG: Copilot 18 tools unchanged",
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