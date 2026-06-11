# -*- coding: utf-8 -*-
"""B11 / WA-11 feedback INSIGHTS smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http \
        < pwa11_insights_smoke.py

NOTE: -i neon_insights once before this. NO prod seed ships (amendment) —
the fixtures live HERE: create feedback across clients/months/voices, assert
the three views' aggregates + the ACL exclusion + Harare month bucketing,
then roll back.

ACL    manager + superuser may view; sales/crew DENIED at the DATA layer
       (collector raises AccessError), not merely menu-hidden
VIEW1  top clients by feedback count + sentiment breakdown; per-client timeline
VIEW2  recent stream + role (client/staff) + sentiment filters
VIEW3  sentiment-by-month (Africa/Harare buckets) + recurring-negative flags
TZ     a 23:30-UTC month-end row buckets in the NEXT month (Harare), not UTC's
READ   the collectors create nothing (pure read)
"""
import traceback
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


def raises_access(fn):
    try:
        fn(); return False
    except AccessError:
        return True
    except Exception:  # noqa: BLE001 — any other error is NOT the gate
        return False


try:
    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True, mail_create_nolog=True))
    C = env["neon.insights.collector"]
    Fb = env["commercial.event.feedback"].sudo()
    EJ = env["commercial.event.job"].sudo()
    CJ = env["commercial.job"].sudo()
    P = env["res.partner"].sudo()
    g_user = env.ref("base.group_user")
    g_jobs_user = env.ref("neon_jobs.group_neon_jobs_user")
    g_mgr = env.ref("neon_jobs.group_neon_jobs_manager")
    g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
    g_su = env.ref("neon_core.group_neon_superuser")
    s = CJ.search([("venue_id", "!=", False), ("currency_id", "!=", False)],
                  limit=1, order="id desc")
    venue_id, currency_id = s.venue_id.id, s.currency_id.id

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "email": login + "@test.neon",
            "groups_id": [(6, 0, [g.id for g in groups])]})

    mgr = mk_user("wa11_mgr", [g_user, g_mgr])
    su = mk_user("wa11_su", [g_user, g_su])
    sales = mk_user("wa11_sales", [g_user, g_jobs_user])   # NOT manager
    crew = mk_user("wa11_crew", [g_user, g_crew])

    def mk_event(pname):
        p = P.create({"name": pname, "is_company": True})
        job = CJ.create({"name": "[WA11] " + pname, "partner_id": p.id,
                         "venue_id": venue_id, "currency_id": currency_id,
                         "state": "active", "event_date": "2026-05-10"})
        ej = EJ.create({"commercial_job_id": job.id, "name": "[WA11] " + pname
                        + " GALA", "event_date": "2026-05-10"})
        return p, ej

    def mk_fb(ej, wa_role, sentiment, text, when=None):
        vals = {"event_job_id": ej.id, "sentiment": sentiment,
                "feedback_text": text}
        if wa_role:
            vals.update({"channel": "whatsapp", "wa_role": wa_role,
                         "client_relayed": wa_role == "sales"})
        else:
            vals["channel"] = "phone"   # a P3.M7-style client row
        rec = Fb.with_user(mgr.id).create(vals)
        if when:
            rec.sudo().write({"captured_at": when})
        return rec

    now = fields.Datetime.now()
    pA, ejA = mk_event("WA11 Alpha Co")
    pB, ejB = mk_event("WA11 Bravo Ltd")
    pC, ejC = mk_event("WA11 Charlie Inc")
    # Alpha: most feedback + 2 recent negatives (recurring flag) + a client row
    mk_fb(ejA, "sales", "negative", "client unhappy with delays",
          now - timedelta(days=4))
    mk_fb(ejA, "od", "negative", "ops rough", now - timedelta(days=9))
    mk_fb(ejA, "crew", "positive", "we recovered well", now - timedelta(days=9))
    mk_fb(ejA, False, "neutral", "client phoned, mixed", now - timedelta(days=40))
    # Bravo: positive, 1 negative (NOT recurring — only one in window)
    mk_fb(ejB, "sales", "positive", "client thrilled", now - timedelta(days=3))
    mk_fb(ejB, "od", "negative", "late load-out", now - timedelta(days=2))
    # Charlie: the Harare month-end boundary row (2026-06-30 23:30 UTC ->
    # 2026-07-01 01:30 Harare -> buckets in JULY, not June)
    mk_fb(ejC, "sales", "mixed", "month-end gala", "2026-06-30 23:30:00")

    base_count = Fb.search_count([])
    check("fixtures: 7 feedback rows across 3 clients/voices/months",
          base_count >= 7, base_count)

    # ---- ACL ----
    check("ACL predicate: manager + superuser may view; sales + crew do NOT",
          C._user_may_view(mgr) and C._user_may_view(su)
          and not C._user_may_view(sales) and not C._user_may_view(crew))
    check("ACL EXCLUSION at the DATA layer: sales is DENIED (AccessError) on "
          "every collector method — not just menu-hidden",
          raises_access(lambda: C.with_user(sales.id).collect_all())
          and raises_access(lambda: C.with_user(sales.id).collect_stream())
          and raises_access(lambda: C.with_user(sales.id).collect_top_clients())
          and raises_access(lambda: C.with_user(sales.id).collect_aggregates())
          and raises_access(
              lambda: C.with_user(sales.id).collect_partner_timeline(pA.id)))
    check("ACL EXCLUSION: crew is also DENIED at the data layer",
          raises_access(lambda: C.with_user(crew.id).collect_all()))
    check("ACL: manager CAN read (no raise)",
          isinstance(C.with_user(mgr.id).collect_all(), dict))

    Cm = C.with_user(mgr.id)

    # ---- VIEW 1: top clients + timeline ----
    top = Cm.collect_top_clients()
    a_row = [t for t in top if t["partner_id"] == pA.id]
    check("VIEW1 top clients: Alpha present, ranked by feedback count, with a "
          "sentiment breakdown (2 negative)",
          a_row and a_row[0]["feedback_count"] == 4
          and a_row[0]["sentiment"]["negative"] == 2
          and top[0]["feedback_count"] >= top[-1]["feedback_count"],
          a_row[0] if a_row else None)
    tl = Cm.collect_partner_timeline(pA.id)
    check("VIEW1 timeline: Alpha's event with the per-voice sentiments",
          tl and tl[0]["event_id"] == ejA.id
          and len(tl[0]["voices"]) == 4
          and {v["role"] for v in tl[0]["voices"]}
          == {"sales", "od", "crew", "client"},
          [v["role"] for v in tl[0]["voices"]] if tl else None)

    # ---- VIEW 2: stream + filters ----
    alls = Cm.collect_stream(role_filter="all", sentiment_filter="all")
    clients_only = Cm.collect_stream(role_filter="client")
    staff_only = Cm.collect_stream(role_filter="staff")
    neg_only = Cm.collect_stream(sentiment_filter="negative")
    # the stream is GLOBAL (limit 50) so it may include pre-existing feedback
    # rows beyond this test's 7 -> assert the FILTERS are correct (every
    # returned row matches) + lower bounds, not exact totals on a shared DB.
    check("VIEW2 stream: filters correct — client_only all wa_role-less, "
          "staff_only all wa_role rows, sentiment filter all-negative; my "
          "rows present",
          len(alls) >= 7
          and clients_only and all(r["role"] == "client" for r in clients_only)
          and staff_only and all(r["role"] != "client" for r in staff_only)
          and all(r["sentiment"] == "negative" for r in neg_only)
          and len(neg_only) >= 3 and len(staff_only) >= 6,
          (len(clients_only), len(staff_only), len(neg_only)))

    # ---- VIEW 3: aggregates + Harare bucket + recurring ----
    agg = Cm.collect_aggregates()
    months = {m["month"]: m for m in agg["months"]}
    jul = [k for k in months if "Jul" in k or "07" in k]
    jun = [k for k in months if "Jun" in k or ("06" in k and "Jul" not in k)]
    check("VIEW3 TZ: the 23:30-UTC 30-Jun row buckets in JULY (Africa/Harare), "
          "NOT June",
          jul and months[jul[0]]["mixed"] >= 1
          and (not jun or months[jun[0]].get("mixed", 0) == 0),
          {"months": list(months.keys())})
    recur_pids = {r["partner_id"] for r in agg["recurring"]}
    check("VIEW3 recurring-negative: Alpha (2 negatives in 30d) FLAGGED; "
          "Bravo (1) NOT; threshold/window reported",
          pA.id in recur_pids and pB.id not in recur_pids
          and agg["threshold"] == 2 and agg["window_days"] == 30
          and agg["tz"] == "Africa/Harare",
          (list(recur_pids), agg["threshold"]))

    # ---- READ-ONLY ----
    Cm.collect_all(); Cm.collect_stream(); Cm.collect_aggregates()
    Cm.collect_top_clients(); Cm.collect_partner_timeline(pA.id)
    check("READ-ONLY: the collectors create NOTHING (feedback count unchanged)",
          Fb.search_count([]) == base_count, Fb.search_count([]))

    # ---- empty-state shape ----
    has = Cm.collect_all()
    check("collect_all shape: has_data True with rows; carries tz + the three "
          "view payloads",
          has["has_data"] is True and "top_clients" in has
          and "stream" in has and "aggregates" in has
          and has["tz"] == "Africa/Harare")

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
