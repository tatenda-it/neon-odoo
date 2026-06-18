# -*- coding: utf-8 -*-
"""Crew-roster JSON -> Odoo neon.crew.member loader (prod, odoo shell).

Reference-only, verbatim aliases. Idempotent FULL-REPLACE scoped to ``source``.
Former crew load with active=False (default-hidden), never deleted.

Prod invocation (after -u neon_migration):
    docker compose exec -e CREW_JSON=/tmp/crew.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_crew.py
"""
import json
import os


def load_crew(env, payload, dry_run=False, source="wages_sheet"):
    M = env["neon.crew.member"].sudo()
    rep = {"created": 0, "active": 0, "former": 0, "leads": 0,
           "alias_total": 0, "unmapped": payload.get("unmapped", {})}
    if not dry_run:
        M.with_context(active_test=False).search(
            [("source", "=", source)]).unlink()
    vals = []
    for m in payload.get("members", []):
        n_alias = len([a for a in (m.get("aliases") or "").split("\n")
                       if a.strip()])
        rep["alias_total"] += n_alias
        if m.get("status") == "former":
            rep["former"] += 1
        else:
            rep["active"] += 1
        if m.get("is_lead"):
            rep["leads"] += 1
        vals.append({
            "name": m["name"], "aliases": m.get("aliases") or "",
            "role": m.get("role") or "unknown",
            "is_lead": bool(m.get("is_lead")),
            "status": m.get("status") or "active",
            "active": bool(m.get("active", True)),
            "source": source,
        })
    if not dry_run:
        M.create(vals)
        rep["created"] = len(vals)
    return rep


def _maybe_run(env):
    path = os.environ.get("CREW_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("CREW_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_crew(env, payload)
    env.cr.commit()
    print("CREW_LOAD_DONE", json.dumps(
        {k: rep[k] for k in ("created", "active", "former", "leads",
                             "alias_total", "unmapped")}))


try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
