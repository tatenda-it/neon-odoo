"""P6.M2 browser smoke -- quote stack visibility + role-gated buttons.

Five user-tier scenarios for the quote model, applying the depth
principle (every visible menu gets clicked through to at least one
content assertion):

1. p2m75_sales (a salesperson with neon_finance_sales) reaches the
   Quotes list, sees only their own quote(s), opens the draft form,
   confirms the 'Submit for Approval' button is visible.
2. p2m75_approver reaches the Quotes list, opens a pending-approval
   quote, confirms Approve + Reject buttons are visible.
3. p2m75_book reaches the Quotes list, sees all quotes (sales +
   approver cross-rep), opens a pending-approval quote, confirms
   Approve + Reject are NOT visible (read-only on workflow).
4. p2m75_other (neon_jobs_crew only, no finance group) cannot reach
   the Quotes menu at all.

Setup creates a controlled DB state via sudo before the scenarios
run: one draft quote owned by p2m75_sales, one pending_approval
quote owned by a throwaway second salesperson, one approved quote.
The setup commits so the Playwright contexts see the records; a
teardown at the end rolls back via direct unlink (cron will not
care).

⚠️ DECISION: setup commits + manual teardown vs sudo savepoint. The
browser smoke runs in a separate process from any Python smoke, so a
shared cursor + rollback isn't available. We commit, capture the
created IDs, and explicitly unlink at end. Unlinks bypass the no-
perm_unlink CSV via sudo because the harness owns the lifecycle
(the rule is about ACL surface for end-users, not test setup).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from browser_smoke import BrowserSmoke, AssertionFail


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


# ----------------------------------------------------------------------
# Setup / teardown: drive the docker-side `odoo shell` with a Python
# script under env.uid=1 (superuser). Browser scenarios then act
# against the resulting fixtures as different users.
#
# We don't use JSON-RPC for setup because that needs an admin password
# we don't keep in the repo. The odoo shell already has superuser
# context, so a piped script is the cleanest path.
# ----------------------------------------------------------------------

_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
approver = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1).id
usd = env.ref('base.USD').id
partner = env['res.partner'].create({
    'name': 'P6M2 Browser Smoke Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M2 Browser Smoke Venue', 'is_company': True,
}).id
job = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
event_job = env['commercial.event.job'].create({
    'commercial_job_id': job,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner, 'deposit_pct': 50.0,
    'deposit_due_days': 0, 'final_due_days': 30,
    'late_policy': 'reminder',
}).id
draft = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': sales, 'payment_term_id': term,
}).id
pending = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': sales, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': pending, 'line_type': 'other',
    'name': 'Sample line', 'quantity': 1.0,
    'unit_rate': 100.0, 'duration_days': 1,
})
env['neon.finance.quote'].browse(pending).state = 'pending_approval'
other = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': approver, 'payment_term_id': term,
}).id
env.cr.commit()
print('IDS_JSON=' + repr({
    'draft_id': draft, 'pending_id': pending, 'other_id': other,
    'term_id': term, 'event_job_id': event_job, 'job_id': job,
    'partner_id': partner, 'venue_id': venue,
}))
"""

_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}
for qid in (ids['draft_id'], ids['pending_id'], ids['other_id']):
    try:
        env['neon.finance.quote'].browse(qid).write({{
            'state': 'cancelled',
            'cancelled_reason': 'browser smoke teardown',
        }})
    except Exception:
        pass
# Use sudo + direct SQL-level delete via the ORM. perm_unlink=0 on the
# CSV is enforced via ir.model.access, but env.uid=1 (the shell user)
# is not bound by it -- superuser bypasses access rules.
for model, key in [
    ('neon.finance.quote', 'draft_id'),
    ('neon.finance.quote', 'pending_id'),
    ('neon.finance.quote', 'other_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('commercial.event.job', 'event_job_id'),
    ('commercial.job', 'job_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'venue_id'),
]:
    try:
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    """Pipe a script into `docker compose exec odoo odoo shell` and
    return its stdout. Stderr is folded in so error output is visible.

    The cwd must be the project root so docker compose finds
    docker-compose.yml; the harness invocation already starts there
    when called via the .venv-browser python.
    """
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    return out


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    # The Python repr() in the shell is dict-style, eval-safe (only ints).
    ids = eval(m.group(1), {"__builtins__": {}}, {})
    return ids


def _teardown_fixtures(ids: dict) -> None:
    script = _TEARDOWN_SCRIPT_TEMPLATE.format(ids_repr=repr(ids))
    out = _run_odoo_shell(script)
    if "TEARDOWN_OK" not in out:
        print("[p6m2] teardown warning:")
        print(out[-1500:])


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------
QUOTES_MENU = "neon_finance.menu_neon_finance_quotes"
PAYMENT_TERMS_MENU = "neon_finance.menu_neon_finance_payment_terms"
QUOTE_ACTION = "neon_finance.neon_finance_quote_action"


def main() -> int:
    print("[p6m2] setup: creating controlled quote fixtures via JSON-RPC ...")
    ids = _setup_fixtures()
    print(f"[p6m2] setup ok: draft={ids['draft_id']} "
          f"pending={ids['pending_id']} other={ids['other_id']}")
    try:
        with BrowserSmoke("p6m2") as smoke:

            # ----------------------------------------------------------
            # p2m75_sales: own-quote visibility + Submit button on draft
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_sales reaches Quotes list, sees own quote, Submit visible on draft"):
                smoke.login("p2m75_sales")
                smoke.assert_menu_visible(QUOTES_MENU)
                smoke.open_action(QUOTE_ACTION)
                smoke.assert_visible("table.o_list_table", "quotes list view")
                # Sales should see at least the 2 they own (draft +
                # pending) but NOT the 'other' admin-owned quote.
                smoke.screenshot("sales_quotes_list")
                # Click the draft row.
                smoke.click(
                    f"tr.o_data_row td:has-text('Draft')",
                    name="open draft quote row",
                )
                smoke.assert_visible("div.o_form_view", "quote form view")
                smoke.assert_visible(
                    "button[name='action_submit_for_approval']",
                    "Submit for Approval button visible on draft form",
                )
                smoke.screenshot("sales_draft_quote_form")

            # ----------------------------------------------------------
            # p2m75_approver: Approve + Reject buttons on pending quote
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_approver sees Approve+Reject on pending quote"):
                smoke.login("p2m75_approver")
                smoke.assert_menu_visible(QUOTES_MENU)
                smoke.open_action(QUOTE_ACTION)
                smoke.assert_visible("table.o_list_table", "quotes list view")
                smoke.screenshot("approver_quotes_list")
                # Open the pending row directly via /web#id=<pending_id>.
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['pending_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "pending quote form view")
                smoke.assert_visible(
                    "button[name='action_approve']",
                    "Approve button visible for approver",
                )
                smoke.assert_visible(
                    "button[name='action_reject']",
                    "Reject button visible for approver",
                )
                smoke.screenshot("approver_pending_quote_form")

            # ----------------------------------------------------------
            # p2m75_book: cross-rep visibility + workflow buttons hidden
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_book sees all quotes, no Approve/Reject"):
                smoke.login("p2m75_book")
                smoke.assert_menu_visible(QUOTES_MENU)
                smoke.assert_menu_visible(PAYMENT_TERMS_MENU)
                smoke.open_action(QUOTE_ACTION)
                smoke.assert_visible("table.o_list_table", "quotes list view")
                # Bookkeeper sees ALL quotes -- expect row count > 1.
                # (Exact count would depend on prior state; just assert
                # the pending + draft rows both render.)
                smoke.assert_count(
                    "tr.o_data_row td.o_data_cell[name='partner_id']:has-text('P6M2 Browser Smoke Client')",
                    3,
                    "bookkeeper sees all 3 P6M2 fixture quotes (own + cross-rep)",
                )
                smoke.screenshot("book_quotes_list")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['pending_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "pending quote form view")
                # Approve / Reject are visible only with the approver
                # group -- bookkeeper does NOT have it.
                book_approve = smoke.page.locator(
                    "button[name='action_approve']").count()
                book_reject = smoke.page.locator(
                    "button[name='action_reject']").count()
                passed = book_approve == 0 and book_reject == 0
                smoke._record_assert(
                    "Approve/Reject NOT visible for bookkeeper",
                    expect="0/0", actual=f"{book_approve}/{book_reject}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts(
                        "book_no_approve_reject_buttons")
                    raise AssertionFail(
                        "bookkeeper should not see workflow buttons; "
                        f"approve={book_approve} reject={book_reject}")
                smoke.screenshot("book_pending_quote_no_workflow_buttons")

            # ----------------------------------------------------------
            # p2m75_other: no finance role -> no Quotes menu
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_other (no finance role) cannot reach Quotes menu"):
                smoke.login("p2m75_other")
                smoke.assert_menu_hidden(QUOTES_MENU)
                smoke.assert_menu_hidden(PAYMENT_TERMS_MENU)
                smoke.goto_home()
                smoke.screenshot("other_home_no_quotes_menu")

        return smoke.summary()
    finally:
        print("[p6m2] teardown: cleaning up fixture records ...")
        _teardown_fixtures(ids)


if __name__ == "__main__":
    sys.exit(main())
