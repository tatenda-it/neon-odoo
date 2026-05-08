# -*- coding: utf-8 -*-
"""
Neon CRM Extensions — res.partner inheritance.

Adds finance-overview fields to contacts. Computed from native Odoo
account.move (out_invoice / out_refund).
"""

from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_outstanding_balance = fields.Monetary(
        string="Outstanding Balance",
        compute="_compute_x_outstanding_balance",
        currency_field="currency_id",
        store=True,
        help="Sum of amount_residual across this partner's posted "
             "customer invoices and refunds.",
    )

    x_last_invoice_date = fields.Date(
        string="Last Invoice Date",
        compute="_compute_x_last_invoice_date",
        store=True,
        help="Invoice date of the partner's most recent posted "
             "customer invoice.",
    )

    @api.depends(
        "invoice_ids",
        "invoice_ids.amount_residual",
        "invoice_ids.state",
    )
    def _compute_x_outstanding_balance(self):
        for partner in self:
            moves = self.env["account.move"].search([
                ("partner_id", "=", partner.id),
                ("move_type", "in", ["out_invoice", "out_refund"]),
                ("state", "=", "posted"),
            ])
            partner.x_outstanding_balance = sum(
                m.amount_residual for m in moves
            )

    @api.depends(
        "invoice_ids",
        "invoice_ids.invoice_date",
        "invoice_ids.state",
    )
    def _compute_x_last_invoice_date(self):
        for partner in self:
            last = self.env["account.move"].search(
                [
                    ("partner_id", "=", partner.id),
                    ("move_type", "=", "out_invoice"),
                    ("state", "=", "posted"),
                ],
                order="invoice_date desc",
                limit=1,
            )
            partner.x_last_invoice_date = last.invoice_date if last else False
