# -*- coding: utf-8 -*-
"""Wages JSON -> Odoo neon.wages.entry loader (prod, odoo shell).

Reference-only, weekly-lump. Resolves the raw technician to a neon.crew.member
via the roster's aliases (EVERY row must resolve — unmapped is surfaced).
Conservative job fuzzy-match vs neon.job.history (high-confidence only; jobs_raw
always kept). Idempotent full-replace scoped to ``source``. dry_run reports
crew-FK + job-link stats WITHOUT creating.

Prod invocation (after -u neon_migration):
    docker compose exec -e WAGES_JSON=/tmp/wages.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_wages.py
"""
import collections
import json
import os
import re


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                  (s or "").lower())).strip()


def _build_crew_index(env):
    idx = {}
    C = env["neon.crew.member"].sudo().with_context(active_test=False)
    for c in C.search([]):
        idx[_norm(c.name)] = c.id
        for a in (c.aliases or "").split("\n"):
            if a.strip():
                idx[_norm(a)] = c.id
    return idx


def _build_job_index(env):
    idx = {}
    for j in env["neon.job.history"].sudo().search([("is_job", "=", True)]):
        n = _norm(j.title)
        if n and len(n) >= 5:
            idx.setdefault(n, j.id)
    return idx


def _match_jobs(jobs_raw, job_idx, job_norms):
    ids = set()
    for line in (jobs_raw or "").split("\n"):
        n = _norm(line)
        if len(n) < 5:
            continue
        if n in job_idx:                       # exact
            ids.add(job_idx[n])
            continue
        for jn, jid in job_norms:              # strong token-run (>=6)
            if len(jn) >= 6 and ((" %s " % jn) in (" %s " % n)
                                 or (" %s " % n) in (" %s " % jn)):
                ids.add(jid)
                break
    return list(ids)


def load_wages(env, payload, dry_run=False, source="wages_sheet"):
    crew_idx = _build_crew_index(env)
    job_idx = _build_job_index(env)
    job_norms = sorted(job_idx.items(), key=lambda kv: -len(kv[0]))
    rep = {"created": 0, "entries": 0, "distinct_crew": set(),
           "unmapped": collections.Counter(), "job_lines": 0,
           "job_lines_matched": 0, "entries_with_link": 0,
           "examples": []}
    if not dry_run:
        env["neon.wages.entry"].sudo().with_context(active_test=False).search(
            [("source", "=", source)]).unlink()
    vals = []
    for e in payload.get("entries", []):
        rep["entries"] += 1
        craw = e.get("technician_raw") or ""
        cid = crew_idx.get(_norm(craw))
        if cid:
            rep["distinct_crew"].add(cid)
        else:
            rep["unmapped"][craw] += 1
        jids = _match_jobs(e.get("jobs_raw"), job_idx, job_norms)
        n_lines = len([x for x in (e.get("jobs_raw") or "").split("\n")
                       if x.strip()])
        rep["job_lines"] += n_lines
        rep["job_lines_matched"] += len(jids)
        if jids:
            rep["entries_with_link"] += 1
        if len(rep["examples"]) < 8 and jids:
            rep["examples"].append("%s -> %d job link(s)" % (craw, len(jids)))
        vals.append({
            "week_date": e.get("week_date") or False,
            "week_label": e.get("week_label") or e.get("sheet") or "(week)",
            "crew_member_id": cid or False,
            "total": e.get("total") or 0.0,
            "currency_code": e.get("currency_code") or "USD",
            "paid": e.get("paid") or "unknown",
            "jobs_raw": e.get("jobs_raw") or "",
            "job_ids": [(6, 0, jids)],
            "job_link_count": len(jids),
            "source": source,
        })
    if not dry_run:
        env["neon.wages.entry"].sudo().create(vals)
        rep["created"] = len(vals)
    rep["distinct_crew"] = len(rep["distinct_crew"])
    rep["unmapped"] = dict(rep["unmapped"])
    return rep


def _maybe_run(env):
    path = os.environ.get("WAGES_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("WAGES_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_wages(env, payload)
    env.cr.commit()
    print("WAGES_LOAD_DONE", json.dumps(
        {k: rep[k] for k in ("created", "entries", "distinct_crew", "unmapped",
                             "job_lines", "job_lines_matched",
                             "entries_with_link")}))


try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
