# -*- coding: utf-8 -*-
"""Petty-cash JSON -> Odoo reference records loader (runs on prod via odoo shell).

Mirrors the Zoho JSON->loader flow. The xlsx is parsed LOCALLY by
parse_petty_cash.py into JSON; the JSON is transferred to prod; this loader
applies it. Reference-only: amounts/balances stored VERBATIM, no recompute, no
ledger touch.

Idempotent per period_month: re-loading a month REPLACES that month's statement
(+ its cascade lines) and recreates it — no natural row id, so month is the key.
date_parsed is NULLABLE (loaded as False where the parser left it null — never
fabricated).

Prod invocation (after -u neon_migration):
    docker compose exec -e PETTY_CASH_JSON=/tmp/petty_cash_combined.json -T \\
        odoo odoo shell -d neon_crm --no-http < .../import_petty_cash.py
The PETTY_CASH_JSON env var triggers the auto-load; without it (e.g. when a test
exec()s this file) nothing loads.
"""
import json
import os


def load_petty_cash(env, payload, dry_run=False):
    """Load parsed petty-cash statements. Returns a report dict."""
    Stmt = env["neon.petty.cash.statement"].sudo()
    report = {"created": 0, "replaced": 0, "lines": 0, "skipped": [],
              "statements": []}
    for s in payload.get("statements", []):
        pm = s.get("period_month")
        if not pm:
            report["skipped"].append({"tab": s.get("tab"),
                                      "why": "no period_month"})
            continue
        existing = Stmt.with_context(active_test=False).search(
            [("period_month", "=", pm)])
        action = "replaced" if existing else "created"
        line_vals = [(0, 0, {
            "sequence": ln.get("sequence") or 10,
            "date_raw": ln.get("date_raw") or "",
            "date_parsed": ln.get("date_parsed") or False,  # nullable
            "details": ln.get("details") or "",
            "acc_code": ln.get("acc_code") or "",
            "debit": ln.get("debit") or 0.0,
            "credit": ln.get("credit") or 0.0,
            "balance": (ln.get("balance")
                        if ln.get("balance") is not None else 0.0),
        }) for ln in s.get("lines", [])]
        if not dry_run:
            if existing:
                existing.unlink()  # idempotent replace (superuser unlink)
            Stmt.create({
                "name": s.get("name") or pm,
                "period_month": pm,
                "currency_code": s.get("currency_code") or "USD",
                "opening_balance": s.get("opening_balance") or 0.0,
                "closing_balance": s.get("closing_balance") or 0.0,
                "cr_total": s.get("cr_total") or 0.0,
                "source_tab": s.get("source_tab") or s.get("tab") or "",
                "line_ids": line_vals,
            })
        report[action] += 1
        report["lines"] += len(line_vals)
        report["statements"].append(
            {"period_month": pm, "action": action, "lines": len(line_vals)})
    return report


def _maybe_run(env):
    """Auto-load ONLY when PETTY_CASH_JSON is set (the prod invocation).
    A test exec()-ing this file (no env var) gets the function but no load."""
    path = os.environ.get("PETTY_CASH_JSON")
    if not path:
        return
    if not os.path.exists(path):
        print("PETTY_CASH_JSON set but file not found:", path)
        return
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rep = load_petty_cash(env, payload)
    env.cr.commit()
    print("PETTY_CASH_LOAD_DONE", json.dumps(
        {k: rep[k] for k in ("created", "replaced", "lines", "skipped")}))


# When piped into `odoo shell`, `env` is in scope.
try:
    env  # noqa: F821
    _maybe_run(env)  # noqa: F821
except NameError:
    pass
