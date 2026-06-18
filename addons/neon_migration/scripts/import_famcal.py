# -*- coding: utf-8 -*-
"""FamCal JSON -> Odoo neon.job.history loader (prod, odoo shell).

Reference-only, verbatim. Conservative client-match against res.partner
(HIGH-CONFIDENCE only: a partner's name as a clear token-run in the title ->
exact/strong; else partner_id NULL, match='none'). Raw title ALWAYS preserved.

Idempotent: FULL-REPLACE by source='famcal_scrape' (re-run = clean refresh of
the same 726). dry_run=True does the match + reports stats WITHOUT creating.

Prod invocation (after -u neon_migration):
    docker compose exec -e FAMCAL_JSON=/tmp/famcal.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_famcal.py
"""
import json
import os
import re

_GENERIC = {"events", "event", "company", "ltd", "pvt", "the", "neon",
            "services", "hire", "hires", "and", "for", "group"}

# Gate-approved (2026-06-18): a clear CLIENT-NAME signal outweighs an admin
# keyword -> the row is a job, not admin. Applied generally to the 'admin'
# category (a partner match flips it to job) PLUS this explicit safety net for
# the 2 client jobs the 'birthday' keyword wrongly tagged. 'reminder'-category
# rows (zoho/expiry/renewal/subscription) are NEVER flipped.
_FORCE_JOB_TITLES = {
    "glamour events - birthday event",
    "kuyana - 50th birthday celebration",
}


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                  (s or "").lower())).strip()


def _build_index(env):
    """normalized partner name -> partner id. Skips tiny/generic names."""
    exact = {}
    strong = []  # (norm_name, id) for token-run matching
    P = env["res.partner"].sudo().with_context(active_test=False)
    for p in P.search([("name", "!=", False)]):
        n = _norm(p.name)
        if not n:
            continue
        exact.setdefault(n, p.id)
        toks = n.split()
        # eligible for substring/token-run matching only if specific enough
        if len(n) >= 6 and not (len(toks) == 1 and n in _GENERIC):
            strong.append((n, p.id))
    # longest names first -> most specific match wins
    strong.sort(key=lambda x: len(x[0]), reverse=True)
    return exact, strong


def _match(title, exact, strong):
    tn = _norm(title)
    if not tn:
        return None, "none"
    if tn in exact:
        return exact[tn], "exact"
    padded = " %s " % tn
    for n, pid in strong:
        if (" %s " % n) in padded:  # whole token-run present in the title
            return pid, "strong"
    return None, "none"


def load_famcal(env, payload, dry_run=False, source="famcal_scrape"):
    # NB: res.partner only is read in dry_run mode (the match-stats gate runs
    # against prod partners without needing the neon.job.history model yet).
    # ``source`` is parameterised so tests load under an isolated tag and never
    # touch the real famcal_scrape rows (full-replace is scoped to ``source``).
    exact, strong = _build_index(env)
    rep = {"created": 0, "is_job": 0, "non_job": 0,
           "match_exact": 0, "match_strong": 0, "match_none": 0,
           "matched_examples": [], "unmatched_examples": []}
    if not dry_run:
        JH = env["neon.job.history"].sudo()
        JH.with_context(active_test=False).search(
            [("source", "=", source)]).unlink()  # full refresh (scoped)
    vals_list = []
    for e in payload.get("events", []):
        title = e.get("title") or "(untitled)"
        is_job = bool(e.get("is_job"))
        category = e.get("category") or "job"
        # Match for jobs AND admin-category rows (admin may flip to job on a
        # client match); never match reminder-category rows.
        pid, m = (None, "none")
        if is_job or category == "admin":
            pid, m = _match(title, exact, strong)
        # client-name-wins: an admin row with a client match (or a gate-named
        # title) is really a job.
        if not is_job and (title.strip().lower() in _FORCE_JOB_TITLES
                           or (category == "admin" and m != "none")):
            is_job, category = True, "job"
        # non-job rows carry no partner link (a reminder mentioning a name is
        # still not that client's job).
        if not is_job:
            pid, m = None, "none"
            rep["non_job"] += 1
        else:
            rep["is_job"] += 1
        rep["match_" + m] += 1
        if m != "none" and len(rep["matched_examples"]) < 10:
            rep["matched_examples"].append(
                "%s -> partner#%s (%s)" % (title, pid, m))
        elif m == "none" and is_job and len(rep["unmatched_examples"]) < 10:
            rep["unmatched_examples"].append(title)
        vals_list.append({
            "date_start": e.get("date_start") or False,
            "date_end": e.get("date_end") or False,
            "all_day": bool(e.get("all_day")),
            "is_multiday": bool(e.get("is_multiday")),
            "title": title,
            "location": e.get("location") or "",
            "notes": e.get("notes") or "",
            "created_by": e.get("created_by") or "",
            "event_type": e.get("event_type") or "",
            "participants_raw": e.get("participants_raw") or "",
            "is_job": is_job,
            "category": category,
            "partner_id": pid or False,
            "partner_match": m,
            "source": source,
        })
    if not dry_run:
        env["neon.job.history"].sudo().create(vals_list)
        rep["created"] = len(vals_list)
    return rep


def _maybe_run(env):
    path = os.environ.get("FAMCAL_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("FAMCAL_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_famcal(env, payload)
    env.cr.commit()
    print("FAMCAL_LOAD_DONE", json.dumps(
        {k: rep[k] for k in ("created", "is_job", "non_job", "match_exact",
                             "match_strong", "match_none")}))


try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
