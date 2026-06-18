# -*- coding: utf-8 -*-
"""Collections JSON -> Odoo neon.collections.item seed loader (prod, odoo shell).

This seeds the LIVE, team-owned collections worklist. UNLIKE the inert archive
loaders it is NOT a full-replace: re-running must never clobber the team's edits.
So it is GET-OR-CREATE scoped by (source, client_name, event_name): existing
items are left untouched; only missing items are created. Seed once; the team
owns it thereafter.

Resolution (conservative, never guess):
  * partner_id — exact normalized client_name, else strong (>=6-char) token-run
    vs res.partner; else NULL. client_name is kept verbatim regardless.
  * sales_rep_id — only unambiguous raw reps map (Robin, Lisar). "Mr. G" /
    "Mrs. G" are AMBIGUOUS -> left NULL, sales_rep_raw kept, flagged at the gate.

dry_run reports the would-create/would-skip split, partner matches, the rep
mapping table, and the data quirks WITHOUT writing.

Prod invocation (after -u neon_migration):
    docker compose exec -e COLLECTIONS_JSON=/tmp/collections.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_collections.py
"""
import json
import os
import re

# Raw-rep -> res.users login. Keys are the _norm()ed forms ("Mrs. G" -> "mrs g").
# Mr. G / Mrs. G confirmed by Tatenda at the gate (2026-06-18): Mrs. G = Munashe
# Goneso, Mr. G = Robin Goneso. No ambiguous reps remain (all 12 rows resolve).
REP_LOGIN = {
    "robin": "robin@neonhiring.co.zw",
    "lisar": "lisar@neonhiring.co.zw",
    "mrs g": "munashe@neonhiring.co.zw",   # Mrs. G -> Munashe Goneso
    "mr g": "robin@neonhiring.co.zw",      # Mr. G  -> Robin Goneso
}
AMBIGUOUS_REPS = set()  # all reps confirmed; kept for the mechanism's sake


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ",
                  (s or "").lower())).strip()


def _build_partner_index(env):
    """Normalized partner-name -> id (companies + named contacts)."""
    idx = {}
    P = env["res.partner"].sudo().search([("name", "!=", False)])
    for p in P:
        n = _norm(p.name)
        if n and len(n) >= 4:
            idx.setdefault(n, p.id)
    return idx


def _match_partner(client_name, p_idx, p_norms):
    n = _norm(client_name)
    if not n:
        return None, ""
    if n in p_idx:
        return p_idx[n], "exact"
    for pn, pid in p_norms:                    # strong token-run (>=6 chars)
        if len(pn) >= 6 and ((" %s " % pn) in (" %s " % n)
                             or (" %s " % n) in (" %s " % pn)):
            return pid, "token-run:%s" % pn
    return None, ""


def _resolve_rep(env, raw, cache):
    nr = _norm(raw)
    if not nr:
        return None, "blank"
    if nr in AMBIGUOUS_REPS:
        return None, "ambiguous"
    login = REP_LOGIN.get(nr)
    if not login:
        return None, "unmapped"
    if login in cache:
        return cache[login], "mapped"
    u = env["res.users"].sudo().search([("login", "=", login)], limit=1)
    cache[login] = u.id if u else None
    return cache[login], ("mapped" if u else "login-missing")


def load_collections(env, payload, dry_run=False, source="outstanding_sheet"):
    p_idx = _build_partner_index(env)
    p_norms = sorted(p_idx.items(), key=lambda kv: -len(kv[0]))
    M = env["neon.collections.item"].sudo().with_context(active_test=False)
    rep_cache = {}
    rep = {"items": 0, "created": 0, "skipped_existing": 0,
           "partner_matched": 0, "rep_mapped": 0, "rep_ambiguous": 0,
           "total_usd": 0.0, "rows": []}
    for it in payload.get("items", []):
        rep["items"] += 1
        client = it.get("client_name") or ""
        event = it.get("event_name") or ""
        pid, how = _match_partner(client, p_idx, p_norms)
        rid, rhow = _resolve_rep(env, it.get("sales_rep_raw"), rep_cache)
        if pid:
            rep["partner_matched"] += 1
        if rhow == "mapped":
            rep["rep_mapped"] += 1
        elif rhow == "ambiguous":
            rep["rep_ambiguous"] += 1
        rep["total_usd"] += it.get("amount_usd") or 0.0
        existing = M.search([("source", "=", source),
                             ("client_name", "=", client),
                             ("event_name", "=", event)], limit=1)
        rep["rows"].append({
            "client": client, "event": event,
            "usd": it.get("amount_usd"), "zwg": it.get("amount_zwg"),
            "currency_flag": it.get("currency_flag") or "",
            "status": it.get("status"), "period": it.get("period_year"),
            "contact": "%s / %s" % (it.get("contact_name") or "",
                                    it.get("contact_phone") or ""),
            "rep_raw": it.get("sales_rep_raw") or "",
            "rep_resolved": rhow, "partner": how or "NONE",
            "exists": bool(existing),
        })
        if existing:
            rep["skipped_existing"] += 1
            continue
        if not dry_run:
            M.create({
                "client_name": client,
                "event_name": event,
                "partner_id": pid or False,
                "amount_usd": it.get("amount_usd") or 0.0,
                "amount_zwg": it.get("amount_zwg") or 0.0,
                "currency_flag": it.get("currency_flag") or "",
                "contact_name": it.get("contact_name") or "",
                "contact_phone": it.get("contact_phone") or "",
                "sales_rep_raw": it.get("sales_rep_raw") or "",
                "sales_rep_id": rid or False,
                "status": it.get("status") or "chasing",
                "note": it.get("note") or "",
                "period_year": it.get("period_year") or False,
                "source": source,
            })
            rep["created"] += 1
    return rep


def _maybe_run(env):
    path = os.environ.get("COLLECTIONS_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("COLLECTIONS_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_collections(env, payload)
    env.cr.commit()
    print("COLLECTIONS_LOAD_DONE", json.dumps(
        {k: rep[k] for k in ("items", "created", "skipped_existing",
                             "partner_matched", "rep_mapped", "rep_ambiguous",
                             "total_usd")}))


try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
