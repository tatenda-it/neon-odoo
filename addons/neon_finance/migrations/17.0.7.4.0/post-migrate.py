# -*- coding: utf-8 -*-
"""P6.M6 post-migration -- recompute budget_alert_level on existing
event_jobs with quoted_budget set.

The field is stored + computed; Odoo's standard registry init handles
the initial compute on -u. This script provides a defensive
re-trigger that ALSO suppresses notification dispatch via the
skip_finance_notification context flag -- without that suppression,
the migration would generate "alert now firing" mail.activity TODOs
for every event that has been in breach for weeks. The dispatch
should fire prospectively, not retroactively.

last_alert_dispatched_at stays null after migration so the first
ACTUAL escalation post-deploy correctly fires (the idempotency
window only kicks in on subsequent writes).
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    ejs = env["commercial.event.job"].search(
        [("quoted_budget", ">", 0)])
    if not ejs:
        return
    # Trigger the compute via a no-op write under the suppression
    # context. The compute is @api.depends on quoted_budget +
    # cost_total_*; writing the same value re-runs it and the
    # context flag short-circuits _dispatch_budget_alert.
    ejs.with_context(skip_finance_notification=True).write({})
