# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartnerBank(models.Model):
    _inherit = "res.partner.bank"

    x_branch_name = fields.Char(
        string="Branch",
        help="Branch name for display on quote / invoice templates "
             "(e.g. 'Arundel').",
    )
