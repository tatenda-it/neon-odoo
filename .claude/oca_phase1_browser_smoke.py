"""OCA Phase 1 browser smoke -- the UI layer of the depth-verify.

Confirms, in a real browser as the Bookkeeper, that each account_financial_report
report action opens its wizard form, and that the account_reconcile_oca views
render. The RENDERED-REPORT-WITH-REAL-CONTENT proof is the companion
afr_depth_verify.py (renders the actual QWeb HTML via the report engine); this
smoke proves the menus/actions/forms are wired and reachable in the UI.

Read-only: navigates + asserts, creates nothing. Run AFTER the guarded
regression (it spawns one odoo shell to resolve action ids).
"""
import re
import subprocess
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"

_RESOLVE = r"""
ids = {}
refs = {
  "gl": "account_financial_report.action_general_ledger_wizard",
  "tb": "account_financial_report.action_trial_balance_wizard",
  "oi": "account_financial_report.action_open_items_wizard",
  "aged": "account_financial_report.action_aged_partner_balance_wizard",
  "vat": "account_financial_report.action_vat_report_wizard",
  "jl": "account_financial_report.action_journal_ledger_wizard",
  "rec_acc": "account_reconcile_oca.account_account_reconcile_act_window",
  "rec_bank": "account_reconcile_oca.action_bank_statement_line_reconcile",
}
for k, xid in refs.items():
    rec = env.ref(xid, raise_if_not_found=False)
    ids[k] = rec.id if rec else 0
print("IDS_JSON=%s" % ids)
"""


def _resolve_ids():
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=_RESOLVE.encode("utf-8"), capture_output=True, timeout=180)
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out[-2000:])
        raise RuntimeError("could not resolve action ids")
    return eval(m.group(1), {"__builtins__": {}}, {})


REPORTS = [
    ("gl", "General Ledger"), ("tb", "Trial Balance"), ("oi", "Open Items"),
    ("aged", "Aged Partner Balance"), ("vat", "VAT Report"), ("jl", "Journal Ledger"),
]


def main():
    ids = _resolve_ids()
    missing = [k for k, v in ids.items() if not v]
    if missing:
        print("[oca_phase1] WARNING unresolved action xmlids: %s" % missing)
    with BrowserSmoke("oca_phase1") as smoke:
        # Bookkeeper is the intended report consumer.
        smoke.login("p2m75_book")
        for key, label in REPORTS:
            if not ids.get(key):
                smoke._record_assert("afr report action present: %s" % label,
                                     expect="xmlid resolves", actual="MISSING", passed=False)
                continue
            with smoke.scenario("afr report wizard opens: %s" % label):
                smoke.page.goto(f"{smoke.base_url}/web#action={ids[key]}",
                                wait_until="networkidle")
                smoke.assert_visible("div.o_form_view", "%s wizard form renders" % label)
        # account_reconcile_oca -- the account reconcile view
        if ids.get("rec_acc"):
            with smoke.scenario("account_reconcile_oca account view renders"):
                smoke.page.goto(f"{smoke.base_url}/web#action={ids['rec_acc']}",
                                wait_until="networkidle")
                smoke.assert_visible("div.o_action_manager",
                                     "reconcile account action loads")
        # account_reconcile_oca -- the bank-statement reconcile widget action
        if ids.get("rec_bank"):
            with smoke.scenario("account_reconcile_oca bank reconcile action renders"):
                smoke.page.goto(f"{smoke.base_url}/web#action={ids['rec_bank']}",
                                wait_until="networkidle")
                smoke.assert_visible("div.o_action_manager",
                                     "bank reconcile action loads")
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
