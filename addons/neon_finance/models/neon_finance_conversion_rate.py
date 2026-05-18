# -*- coding: utf-8 -*-
"""
P6.M1 — internal USD/ZiG conversion rate table.

Manually maintained by the bookkeeper (Kudzi) or approver. Each
record carries both the usd_per_zig and zig_per_usd rates so callers
don't have to invert. Conversion rates are dated; the helper
get_active_rate(currency_from, currency_to, on_date) returns the
latest record with effective_date <= on_date.

Why dated rates: ZiG/USD parity is unstable. A quote priced today
in USD and invoiced next month at month-end may need historical
rate lookup for reconciliation, hence one row per change rather
than overwriting a single live rate.
"""
from odoo import _, api, fields, models


class NeonFinanceConversionRate(models.Model):
    _name = "neon.finance.conversion.rate"
    _description = "Finance Conversion Rate"
    _order = "effective_date desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        index=True,
        help="Sequence-prefixed identifier (FX-NNNNNN).",
    )
    sequence_number = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.finance.conversion.rate") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    effective_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
        index=True,
        help="Date this conversion rate takes effect. Lookups choose "
        "the row with the latest effective_date <= the query date.",
    )
    usd_per_zig = fields.Float(
        string="USD per ZiG",
        required=True,
        digits=(12, 6),
        help="How many USD one ZiG buys. Typically a small decimal "
        "given ZiG/USD parity.",
    )
    zig_per_usd = fields.Float(
        string="ZiG per USD",
        required=True,
        digits=(12, 6),
        help="How many ZiG one USD buys. Inverse of usd_per_zig.",
    )
    source_note = fields.Char(
        string="Source",
        help="Where this rate came from — e.g. 'RBZ + 5%', "
        "'market check 09:00', 'Bookkeeper Kudzi'.",
    )
    set_by_id = fields.Many2one(
        "res.users",
        string="Set By",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    set_at = fields.Datetime(
        string="Set At",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )

    _sql_constraints = [
        ("unique_effective_date",
         "UNIQUE (effective_date)",
         "A conversion rate already exists for this effective date."),
        ("check_usd_per_zig_positive",
         "CHECK (usd_per_zig > 0)",
         "usd_per_zig must be strictly positive."),
        ("check_zig_per_usd_positive",
         "CHECK (zig_per_usd > 0)",
         "zig_per_usd must be strictly positive."),
    ]

    @api.depends("sequence_number")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.sequence_number or _("New")

    @api.model
    def get_active_rate(self, currency_from, currency_to, on_date=None):
        """Return the rate to multiply a `currency_from` amount by to
        get the equivalent `currency_to` amount, using the latest
        conversion record with effective_date <= on_date (today if
        not specified).

        Returns 1.0 for same-currency conversion.
        Returns None when no record covers on_date for the requested
        direction, or when an unsupported currency pair is asked for
        (only USD <-> ZWG is modelled here).
        """
        if not currency_from or not currency_to:
            return None
        if currency_from == currency_to:
            return 1.0
        if on_date is None:
            on_date = fields.Date.context_today(self)
        rec = self.sudo().search(
            [("effective_date", "<=", on_date)],
            order="effective_date desc, id desc",
            limit=1,
        )
        if not rec:
            return None
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = (
            self.env.ref("base.ZWG", raise_if_not_found=False)
            or self.env["res.currency"].search(
                [("name", "=", "ZWG")], limit=1)
        )
        if currency_from == usd and currency_to == zwg:
            return rec.zig_per_usd
        if currency_from == zwg and currency_to == usd:
            return rec.usd_per_zig
        return None
