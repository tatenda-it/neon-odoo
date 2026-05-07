# -*- coding: utf-8 -*-
"""
Neon CRM Extensions — res.partner inheritance.

Adds finance-overview fields to contacts. Both fields are manual for
now; a future iteration will compute x_outstanding_balance from Zoho
Books via ir.config_parameter.
"""

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_outstanding_balance = fields.Float(
        string="Outstanding Balance",
        default=0.0,
        help="Outstanding receivable amount. Updated manually by sales "
             "until the Zoho Books bridge is wired up.",
    )

    x_last_invoice_date = fields.Date(
        string="Last Invoice Date",
        help="Date of the most recent invoice issued to this contact.",
    )
