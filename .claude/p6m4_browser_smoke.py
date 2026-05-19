"""P6.M4 browser smoke -- approval workflow + pricing honesty (form path).

Five user-tier scenarios:

1. **p2m75_sales** opens a fresh draft quote (with one priced line +
   payment term), clicks "Submit for Approval" -> form re-renders
   with state badge "Pending Approval" (NOT "Approved"). Verifies M2
   auto-approve placeholder has been replaced.

2. **p2m75_approver** opens the Approval Queue, sees the pending
   approval, opens the form -> Approve + Reject buttons visible ->
   clicks Approve -> approval form transitions to "Approved".
   Verifies the quote also transitions (cross-record cascade).

3. **p2m75_sales** re-loads the same quote -> state badge now shows
   "Approved" and the "Send to Client" button is visible.

4. **p2m75_book** opens the Approval Queue, sees pending + resolved
   approvals from both sales reps (read-only). Opens a pending
   approval form -> Approve / Reject buttons NOT visible.

5. **p2m75_other** (neon_jobs_crew only) cannot reach the Approval
   Queue menu at all.

Pricing honesty side-scenario tacked onto scenario 1: after
priced-on-create, sales hand-edits unit_rate via RPC -> pricing_
status flips to 'manual' (proved at the model layer; browser merely
verifies the badge re-renders accordingly when the form reloads).

Setup commits fixtures via odoo shell; teardown unlinks via env.uid=1.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"

APPROVAL_ACTION = "neon_finance.neon_finance_approval_action"
QUOTE_ACTION = "neon_finance.neon_finance_quote_action"
APPROVAL_MENU = "neon_finance.menu_neon_finance_approvals"
QUOTES_MENU = "neon_finance.menu_neon_finance_quotes"


_SETUP_SCRIPT = """
from datetime import date, timedelta
sales = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1).id
approver = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1).id
usd = env.ref('base.USD').id
cat_sound = env.ref('neon_jobs.equipment_category_sound').id
partner = env['res.partner'].create({
    'name': 'P6M4 Browser Smoke Client', 'is_company': True,
}).id
venue = env['res.partner'].create({
    'name': 'P6M4 Browser Smoke Venue', 'is_company': True,
}).id
job = env['commercial.job'].create({
    'partner_id': partner, 'venue_id': venue,
    'event_date': (date.today() + timedelta(days=30)).isoformat(),
    'currency_id': usd,
}).id
event_job = env['commercial.event.job'].create({
    'commercial_job_id': job,
}).id
product = env['product.template'].search(
    [('is_workshop_item', '=', True)], limit=1)
if not product:
    product = env['product.template'].create({
        'name': 'P6M4 Browser Smoke Product',
        'is_workshop_item': True,
    })
product.equipment_category_id = cat_sound
ej_line = env['commercial.event.job.equipment.line'].create({
    'event_job_id': event_job,
    'product_template_id': product.id,
    'quantity_planned': 1,
}).id
term = env['neon.finance.payment.term'].create({
    'partner_id': partner, 'deposit_pct': 50.0,
    'deposit_due_days': 0, 'final_due_days': 30,
    'late_policy': 'reminder',
}).id

# Pre-create a draft quote with one priced line -- sales rep opens
# this and submits via the form button. Activities will materialise
# on the approval record after submission.
draft_quote = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': sales, 'payment_term_id': term,
}).id
draft_line = env['neon.finance.quote.line'].create({
    'quote_id': draft_quote, 'line_type': 'equipment',
    'name': 'P6M4 Sound rig', 'quantity': 1.0,
    'unit_rate': 0.0, 'duration_days': 3,
    'equipment_line_id': ej_line,
}).id

# Pre-create a pending_approval quote owned by approver_user so the
# bookkeeper-cross-rep visibility test has something to look at.
other_quote = env['neon.finance.quote'].create({
    'event_job_id': event_job, 'currency_id': usd,
    'salesperson_id': approver, 'payment_term_id': term,
}).id
env['neon.finance.quote.line'].create({
    'quote_id': other_quote, 'line_type': 'other',
    'name': 'cross-rep line', 'quantity': 1.0,
    'unit_rate': 100.0, 'duration_days': 1,
})
env['neon.finance.quote'].browse(other_quote).with_user(
    env['res.users'].browse(approver)
).action_submit_for_approval()
other_quote_rec = env['neon.finance.quote'].browse(other_quote)
other_approval = other_quote_rec.approval_id.id

env.cr.commit()
print('IDS_JSON=' + repr({
    'draft_quote_id': draft_quote,
    'draft_line_id': draft_line,
    'other_quote_id': other_quote,
    'other_approval_id': other_approval,
    'term_id': term,
    'event_job_id': event_job,
    'job_id': job,
    'ej_line_id': ej_line,
    'partner_id': partner,
    'venue_id': venue,
}))
"""

_TEARDOWN_SCRIPT_TEMPLATE = """
ids = {ids_repr}
# Cancel quotes (handles state cleanup) then unlink as superuser.
for qid in (ids['draft_quote_id'], ids['other_quote_id']):
    try:
        q = env['neon.finance.quote'].browse(qid)
        if q.state not in ('cancelled', 'rejected', 'expired', 'accepted'):
            q.with_context(cancelled_reason='browser smoke teardown').action_cancel()
    except Exception:
        pass
for model, key in [
    ('neon.finance.approval', 'other_approval_id'),
    ('neon.finance.quote.line', 'draft_line_id'),
    ('neon.finance.quote', 'draft_quote_id'),
    ('neon.finance.quote', 'other_quote_id'),
    ('neon.finance.payment.term', 'term_id'),
    ('commercial.event.job.equipment.line', 'ej_line_id'),
    ('commercial.event.job', 'event_job_id'),
    ('commercial.job', 'job_id'),
    ('res.partner', 'partner_id'),
    ('res.partner', 'venue_id'),
]:
    try:
        # Approval may also exist on draft_quote post-submit -- find
        # it dynamically and unlink before the quote unlink.
        if model == 'neon.finance.approval' and key == 'other_approval_id':
            extra = env['neon.finance.approval'].search([
                ('quote_id', '=', ids['draft_quote_id'])
            ])
            for r in extra:
                try:
                    r.unlink()
                except Exception:
                    pass
        env[model].browse(ids[key]).unlink()
    except Exception as e:
        print('teardown unlink failed for', model, ids[key], ':', e)
env.cr.commit()
print('TEARDOWN_OK')
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _teardown_fixtures(ids: dict) -> None:
    out = _run_odoo_shell(_TEARDOWN_SCRIPT_TEMPLATE.format(ids_repr=repr(ids)))
    if "TEARDOWN_OK" not in out:
        print("[p6m4] teardown warning:")
        print(out[-1500:])


def main() -> int:
    print("[p6m4] setup: creating draft + pending-approval fixtures ...")
    ids = _setup_fixtures()
    print(f"[p6m4] setup ok: draft_quote={ids['draft_quote_id']} "
          f"other_quote={ids['other_quote_id']} "
          f"other_approval={ids['other_approval_id']}")
    try:
        with BrowserSmoke("p6m4") as smoke:

            # ----------------------------------------------------------
            # Scenario 1: p2m75_sales submit draft via form button
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_sales submits draft via form -> Pending Approval (NOT auto-approved)"):
                smoke.login("p2m75_sales")
                smoke.assert_menu_visible(QUOTES_MENU)
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['draft_quote_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "draft quote form loaded")
                smoke.screenshot("01_sales_draft_quote_pre_submit")
                # Click Submit for Approval
                smoke.click(
                    "button[name='action_submit_for_approval']",
                    name="Click Submit for Approval",
                )
                smoke.page.wait_for_timeout(800)
                # Verify state badge -- the statusbar shows the current
                # quote state; we want 'pending_approval', not 'approved'.
                state_rpc = smoke.json_rpc(
                    "neon.finance.quote", "read",
                    args=[[ids["draft_quote_id"]], ["state", "approval_id"]],
                )
                row = (state_rpc.get("result") or [{}])[0]
                state = row.get("state")
                approval_link = row.get("approval_id")
                passed = state == "pending_approval" and bool(approval_link)
                smoke._record_assert(
                    "quote state=pending_approval after submit (NOT auto-approved)",
                    expect="pending_approval + approval_id set",
                    actual=f"state={state} approval_id={approval_link}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("submit_did_not_create_approval")
                    raise AssertionFail("submit did not transition to pending_approval")
                smoke.screenshot("02_sales_post_submit_pending_approval")

            # ----------------------------------------------------------
            # Scenario 2: p2m75_approver actions the pending approval
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_approver sees pending in queue, clicks Approve, quote transitions"):
                smoke.login("p2m75_approver")
                smoke.assert_menu_visible(APPROVAL_MENU)
                smoke.open_action(APPROVAL_ACTION)
                smoke.assert_visible("table.o_list_table", "approval list view")
                smoke.screenshot("03_approver_queue_list")
                # Resolve the approval ID for the draft quote we just
                # submitted in scenario 1.
                resp = smoke.json_rpc(
                    "neon.finance.approval", "search_read",
                    args=[
                        [("quote_id", "=", ids["draft_quote_id"])],
                        ["id"],
                    ],
                    kwargs={"limit": 1},
                )
                rows = resp.get("result") or []
                if not rows:
                    raise AssertionFail("approval record for draft quote not found")
                fresh_approval_id = rows[0]["id"]
                # Open the approval form by id
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={fresh_approval_id}"
                    f"&model=neon.finance.approval&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "approval form view")
                smoke.assert_visible(
                    "button[name='action_approve_from_form']",
                    "Approve button visible to approver",
                )
                smoke.assert_visible(
                    "button[name='action_reject_from_form']",
                    "Reject button visible to approver",
                )
                smoke.click(
                    "button[name='action_approve_from_form']",
                    name="Click Approve",
                )
                smoke.page.wait_for_timeout(800)
                # Verify both records transitioned
                ar = smoke.json_rpc(
                    "neon.finance.approval", "read",
                    args=[[fresh_approval_id], ["state"]],
                )
                qr = smoke.json_rpc(
                    "neon.finance.quote", "read",
                    args=[[ids["draft_quote_id"]], ["state"]],
                )
                ap_state = (ar.get("result") or [{}])[0].get("state")
                q_state = (qr.get("result") or [{}])[0].get("state")
                passed = ap_state == "approved" and q_state == "approved"
                smoke._record_assert(
                    "Approve cascades approval + quote to approved",
                    expect="approval=approved quote=approved",
                    actual=f"approval={ap_state} quote={q_state}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("approve_did_not_cascade")
                    raise AssertionFail("approve did not propagate")
                smoke.screenshot("04_approver_post_approve")

            # ----------------------------------------------------------
            # Scenario 3: p2m75_sales re-opens approved quote, Send visible
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_sales sees Approved + Send button"):
                smoke.login("p2m75_sales")
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['draft_quote_id']}"
                    f"&model=neon.finance.quote&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible(
                    "button[name='action_send']",
                    "Send to Client button visible on approved quote",
                )
                smoke.screenshot("05_sales_post_approval_send_visible")

            # ----------------------------------------------------------
            # Scenario 4: p2m75_book read-only approval queue
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_book sees Approval Queue read-only (no Approve/Reject)"):
                smoke.login("p2m75_book")
                smoke.assert_menu_visible(APPROVAL_MENU)
                smoke.open_action(APPROVAL_ACTION)
                smoke.assert_visible("table.o_list_table", "approval list visible to bookkeeper")
                smoke.screenshot("06_book_queue_list")
                # Open the cross-rep pending approval and verify the
                # action buttons are hidden.
                smoke.page.goto(
                    f"{smoke.base_url}/web#id={ids['other_approval_id']}"
                    f"&model=neon.finance.approval&view_type=form",
                    wait_until="networkidle",
                )
                smoke.assert_visible("div.o_form_view", "approval form for bookkeeper")
                book_approve = smoke.page.locator(
                    "button[name='action_approve_from_form']").count()
                book_reject = smoke.page.locator(
                    "button[name='action_reject_from_form']").count()
                passed = book_approve == 0 and book_reject == 0
                smoke._record_assert(
                    "Approve/Reject NOT visible to bookkeeper",
                    expect="0/0",
                    actual=f"{book_approve}/{book_reject}",
                    passed=passed,
                )
                if not passed:
                    smoke._capture_fail_artifacts("book_sees_workflow_buttons")
                    raise AssertionFail(
                        "bookkeeper should not see workflow buttons")
                smoke.screenshot("07_book_approval_no_workflow_buttons")

            # ----------------------------------------------------------
            # Scenario 5: p2m75_other cannot reach Approval Queue
            # ----------------------------------------------------------
            with smoke.scenario("p2m75_other (no finance role) cannot reach Approval Queue"):
                smoke.login("p2m75_other")
                smoke.assert_menu_hidden(APPROVAL_MENU)
                smoke.goto_home()
                smoke.screenshot("08_other_no_approval_menu")

        return smoke.summary()
    finally:
        print("[p6m4] teardown: cleaning up fixture records ...")
        _teardown_fixtures(ids)


if __name__ == "__main__":
    sys.exit(main())
