# -*- coding: utf-8 -*-
"""SET EXCHANGE RATE -- finance-gated wizard to enter today's USD<->ZWG rate.

Option (a): the entered rate becomes the company's OFFICIAL rate for that date.
On save it writes ONE res.currency.rate row for ZWG (no ledger posting). Because
that row is the official rate for the date, it affects ALL conversions
system-wide for that date -- not only the MIS reports. That is the point of
option (a); it is finance-gated (bookkeeper / approver / accountant only).

RATE DIRECTION (verified against Odoo + the live data): Odoo stores, on the
ZWG res.currency.rate row, `company_rate` = how many ZWG equal ONE USD (e.g.
26.5). The form asks for exactly that -- "1 USD = ___ ZWG" -- so the entry maps
straight to company_rate with no inversion. (`_convert` reads the derived
`rate`, which equals company_rate when the company currency, USD, has rate 1.)
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonSetExchangeRateWizard(models.TransientModel):
    _name = "neon.set.exchange.rate.wizard"
    _description = "Set today's USD/ZWG exchange rate"

    rate_date = fields.Date(
        string="Effective Date", required=True, default=fields.Date.context_today,
        help="The date this becomes the official USD/ZWG rate.")
    usd_to_zwg = fields.Float(
        string="1 USD =", required=True, digits=(16, 6),
        help="How many ZWG equal ONE US Dollar on the effective date. "
             "E.g. if 1 USD = 36.50 ZWG, enter 36.50.")
    current_rate = fields.Float(
        string="Current stored rate", readonly=True, digits=(16, 6),
        help="The ZWG-per-USD rate currently in effect, for reference.")

    @api.model
    def _zwg(self):
        z = self.env["res.currency"].with_context(active_test=False).search(
            [("name", "=", "ZWG")], limit=1)
        if not z:
            raise UserError(_("No ZWG currency is configured on this database."))
        return z

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        zwg = self._zwg()
        today = fields.Date.context_today(self)
        # res.currency.rate (computed on the currency at the context date) is the
        # ZWG-per-USD figure -- i.e. exactly "1 USD = X ZWG".
        res["current_rate"] = zwg.with_context(date=today).rate
        return res

    def action_set_rate(self):
        self.ensure_one()
        if not self.usd_to_zwg or self.usd_to_zwg <= 0:
            raise UserError(_(
                "Enter a positive rate: how many ZWG equal 1 USD (e.g. 36.50)."))
        zwg = self._zwg()
        Rate = self.env["res.currency.rate"]
        existing = Rate.search(
            [("currency_id", "=", zwg.id), ("name", "=", self.rate_date)], limit=1)
        # company_rate = units of THIS currency (ZWG) per 1 company unit (USD) =
        # exactly the "1 USD = X ZWG" the user typed. No inversion.
        if existing:
            existing.write({"company_rate": self.usd_to_zwg})
        else:
            Rate.create({
                "currency_id": zwg.id,
                "name": self.rate_date,
                "company_rate": self.usd_to_zwg,
            })
        return {"type": "ir.actions.act_window_close"}
