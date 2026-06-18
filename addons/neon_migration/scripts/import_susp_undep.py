# -*- coding: utf-8 -*-
"""Suspense + Undeposited JSON -> Odoo reference records loader (prod, odoo shell).

Mirrors the petty-cash loader. Reference-only, verbatim, idempotent per
period_month (re-load replaces that statement + cascade lines). date_parsed
NULLABLE (False where the parser left it null — never fabricated). Empty
undeposited tabs (July) are SKIPPED and surfaced, never silently dropped.

Prod invocation (after -u neon_migration):
    docker compose exec -e SUSP_UNDEP_JSON=/tmp/susp_undep.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_susp_undep.py
"""
import json
import os


def load_susp_undep(env, payload, dry_run=False):
    Susp = env["neon.suspense.statement"].sudo()
    Undep = env["neon.undeposited.statement"].sudo()
    rep = {"suspense_created": 0, "suspense_replaced": 0, "susp_lines": 0,
           "undep_created": 0, "undep_replaced": 0, "undep_lines": 0,
           "skipped": []}

    for s in payload.get("suspense", []):
        pm = s.get("period_month")
        if not pm:
            rep["skipped"].append({"tab": s.get("tab"), "why": "no period"})
            continue
        existing = Susp.with_context(active_test=False).search(
            [("period_month", "=", pm)])
        action = "replaced" if existing else "created"
        lvals = [(0, 0, {
            "sequence": ln.get("sequence") or 10,
            "date_raw": ln.get("date_raw") or "",
            "date_parsed": ln.get("date_parsed") or False,
            "details": ln.get("details") or "",
            "acc_code": ln.get("acc_code") or "",
            "debit": ln.get("debit") or 0.0,
            "credit": ln.get("credit") or 0.0,
            "balance": ln.get("balance") if ln.get("balance") is not None
            else 0.0,
        }) for ln in s.get("lines", [])]
        if not dry_run:
            if existing:
                existing.unlink()
            Susp.create({
                "name": s.get("name") or pm, "period_month": pm,
                "currency_code": s.get("currency_code") or "USD",
                "opening_balance": s.get("opening_balance") or 0.0,
                "closing_balance": s.get("closing_balance") or 0.0,
                "source_tab": s.get("source_tab") or s.get("tab") or "",
                "line_ids": lvals,
            })
        rep["suspense_" + action] += 1
        rep["susp_lines"] += len(lvals)

    for s in payload.get("undeposited", []):
        pm = s.get("period_month")
        fmt = s.get("statement_format")
        if not pm or fmt == "empty" or not s.get("lines"):
            rep["skipped"].append(
                {"tab": s.get("tab"), "why": fmt or "no period/lines"})
            continue
        existing = Undep.with_context(active_test=False).search(
            [("period_month", "=", pm)])
        action = "replaced" if existing else "created"
        lvals = [(0, 0, {
            "sequence": ln.get("sequence") or 10,
            "date_raw": ln.get("date_raw") or "",
            "date_parsed": ln.get("date_parsed") or False,
            "details": ln.get("details") or "",
            "acc_code": ln.get("acc_code") or "",
            "section": ln.get("section") or "statement",
            "invoice_no": ln.get("invoice_no") or "",
            "debit": ln.get("debit") or 0.0,
            "credit": ln.get("credit") or 0.0,
            "amount": ln.get("amount") or 0.0,
            "currency": ln.get("currency") or "USD",
            "note": ln.get("note") or "",
        }) for ln in s.get("lines", [])]
        if not dry_run:
            if existing:
                existing.unlink()
            Undep.create({
                "name": s.get("name") or pm, "period_month": pm,
                "statement_format": fmt or "amount",
                "currency_default": s.get("currency_default") or "USD",
                "source_tab": s.get("source_tab") or s.get("tab") or "",
                "line_ids": lvals,
            })
        rep["undep_" + action] += 1
        rep["undep_lines"] += len(lvals)
    return rep


def _maybe_run(env):
    path = os.environ.get("SUSP_UNDEP_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("SUSP_UNDEP_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_susp_undep(env, payload)
    env.cr.commit()
    print("SUSP_UNDEP_LOAD_DONE", json.dumps(rep))


try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
