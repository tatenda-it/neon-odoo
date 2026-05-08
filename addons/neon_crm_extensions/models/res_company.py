# -*- coding: utf-8 -*-
"""
Neon CRM Extensions — res.company inheritance.

Adds Zimbabwe Revenue Authority identifiers to the company record.
These fields print on tax invoices and are used by ZIMRA-bound
integrations.
"""

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    x_zimra_tin = fields.Char(
        string="ZIMRA TIN",
        help="Zimbabwe Revenue Authority Tax Identification "
             "Number. Appears on tax invoices.",
    )
    x_zimra_bpn = fields.Char(
        string="ZIMRA BPN / Vendor #",
        help="Zimbabwe Revenue Authority Business Partner "
             "Number, used for government supplier "
             "transactions.",
    )
