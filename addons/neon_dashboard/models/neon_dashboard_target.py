# -*- coding: utf-8 -*-
"""Phase 8A.M5 -- neon.dashboard.target.

Sales/revenue targets used by the Forecast vs Target KPI tile and
by the Sales block "Forecast vs Target" sub-widget. One row per
period (month / quarter / year) per target_type (revenue /
pipeline_value / new_deals).

⚠️ DECISION (M5, marker 1): target_type='revenue' actuals SUM
amount_total over neon.finance.quote rows in state='accepted' whose
write_date falls inside the target's date range. Acceptance is the
revenue-recognition transition in this build; the quote state
machine has no 'won' value (M1-M3 discovery), so 'accepted' is the
canonical mapping locked at gate 1.

⚠️ DECISION (M5, marker 2): write_date is the proxy for the
accept-transition timestamp. neon.finance.quote does NOT carry an
explicit accepted_on audit field today. Polish backlog item filed
for M6: introduce neon.finance.quote.accepted_on so target actuals
become deterministic regardless of subsequent writes (e.g., a
chatter note bumping write_date past the period end would
currently exclude a legitimately-accepted quote from its real
period).

⚠️ DECISION (M5, marker 3): NO new groups. ACLs are
   * neon_core.group_neon_superuser -> 1/1/1/1
   * every other tier (bookkeeper / sales_rep / lead_tech / crew)
     -> 1/0/0/0
The read-only-for-all-tiers grant is MANDATORY: without it,
non-superuser dashboards crash on _kpi_forecast (it reads the
current-period target row). Matches the gate-1 lock and avoids
re-introducing the pattern the P8A hotfix just reaped.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models


_PERIOD_TYPES = [
    ("month", "Month"),
    ("quarter", "Quarter"),
    ("year", "Year"),
]
_TARGET_TYPES = [
    ("revenue", "Revenue"),
    ("pipeline_value", "Pipeline Value"),
    ("new_deals", "New Deals Count"),
]


class NeonDashboardTarget(models.Model):
    _name = "neon.dashboard.target"
    _description = "Dashboard Sales/Revenue Target"
    _order = "date_from desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        required=True,
        default=lambda self: self._default_name(),
        help="Human-readable label. Defaults to "
        "'<Month YYYY> Revenue Target' on create.",
    )
    period = fields.Selection(
        _PERIOD_TYPES, required=True, default="month",
    )
    date_from = fields.Date(
        required=True,
        default=lambda self: self.env["neon.dashboard"]
            ._today_harare().replace(day=1),
    )
    date_to = fields.Date(
        compute="_compute_date_to",
        store=True,
        readonly=False,
        help="Auto-computed from period + date_from. Editable to "
        "support irregular periods (e.g., partial first month). "
        "Not declared required=True so the compute can fill the "
        "value pre-INSERT -- a required+readonly=False+stored "
        "computed field hits the NOT NULL constraint before the "
        "compute fires.",
    )
    target_amount = fields.Monetary(
        required=True, currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency", required=True,
        default=lambda self: self.env.ref(
            "base.USD", raise_if_not_found=False),
        help="Currency the target is denominated in. Actuals are "
        "filtered to quotes/invoices in this currency only.",
    )
    target_type = fields.Selection(
        _TARGET_TYPES, required=True, default="revenue",
    )
    actual_amount = fields.Monetary(
        compute="_compute_actual",
        currency_field="currency_id",
        help="Computed at read time -- always reflects current "
        "underlying quote state.",
    )
    progress_pct = fields.Float(
        compute="_compute_progress",
        digits=(5, 2),
        help="(actual / target) * 100. Zero when target_amount is "
        "zero (defensive division).",
    )
    notes = fields.Text(
        help="Free text for variance context, board commentary, "
        "etc.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("target_amount_positive",
         "CHECK (target_amount > 0)",
         "Target amount must be a positive number."),
        ("date_range_valid",
         "CHECK (date_to >= date_from)",
         "Target end date must be on or after the start date."),
    ]

    @api.model
    def _default_name(self):
        # p8a-hygiene tz: today resolved in Africa/Harare.
        today = self.env["neon.dashboard"]._today_harare()
        return _("%(month)s Revenue Target") % {
            "month": today.strftime("%B %Y"),
        }

    @api.depends("date_from", "period")
    def _compute_date_to(self):
        for rec in self:
            if not rec.date_from or not rec.period:
                continue
            if rec.period == "month":
                rec.date_to = (
                    rec.date_from + relativedelta(months=1, days=-1)
                )
            elif rec.period == "quarter":
                rec.date_to = (
                    rec.date_from + relativedelta(months=3, days=-1)
                )
            elif rec.period == "year":
                rec.date_to = (
                    rec.date_from + relativedelta(years=1, days=-1)
                )

    @api.depends("target_type", "date_from", "date_to", "currency_id")
    def _compute_actual(self):
        """Compute actuals per target_type. All branches use
        write_date as the accept-transition proxy per marker 2."""
        Quote = self.env["neon.finance.quote"].sudo()
        for rec in self:
            if not (rec.date_from and rec.date_to and rec.currency_id):
                rec.actual_amount = 0.0
                continue
            # write_date is a Datetime; date_from/date_to are Dates.
            # Build datetime boundaries: midnight at start, end-of-day
            # at finish, in the company's timezone-neutral UTC.
            dt_from = fields.Datetime.to_string(
                fields.Datetime.to_datetime(rec.date_from))
            dt_to = fields.Datetime.to_string(
                fields.Datetime.to_datetime(rec.date_to)
                + relativedelta(days=1, seconds=-1))
            if rec.target_type == "revenue":
                quotes = Quote.search([
                    ("state", "=", "accepted"),
                    ("write_date", ">=", dt_from),
                    ("write_date", "<=", dt_to),
                    ("currency_id", "=", rec.currency_id.id),
                ])
                rec.actual_amount = sum(quotes.mapped("amount_total"))
            elif rec.target_type == "pipeline_value":
                # Snapshot: current sum of active-state quotes in the
                # configured currency. date range is informational
                # only (UX needs SOMETHING to compare against the
                # target's period label).
                quotes = Quote.search([
                    ("state", "in",
                     ("pending_approval", "approved", "sent")),
                    ("currency_id", "=", rec.currency_id.id),
                ])
                rec.actual_amount = sum(quotes.mapped("amount_total"))
            elif rec.target_type == "new_deals":
                quotes = Quote.search([
                    ("create_date", ">=", dt_from),
                    ("create_date", "<=", dt_to),
                    ("currency_id", "=", rec.currency_id.id),
                ])
                # actual_amount is Monetary but here it's a count
                # rendered into the same field. Trade-off acknowledged
                # at marker 4 below.
                rec.actual_amount = float(len(quotes))
            else:
                rec.actual_amount = 0.0

    # ⚠️ DECISION (M5, marker 4): for target_type='new_deals',
    # actual_amount stores the integer count cast to float and the
    # currency widget renders it as "$N" -- visually odd but
    # functionally correct for the Forecast tile's progress
    # computation. A dedicated actual_count field would be cleaner
    # but adds two columns + two more compute branches for one rare
    # target type. UX polish item for M6.

    @api.depends("actual_amount", "target_amount")
    def _compute_progress(self):
        for rec in self:
            if rec.target_amount:
                rec.progress_pct = (
                    rec.actual_amount / rec.target_amount * 100.0)
            else:
                rec.progress_pct = 0.0
