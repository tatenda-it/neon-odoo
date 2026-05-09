# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    x_covering_letter_active = fields.Boolean(
        string='Show Covering Letter',
        default=False,
        help='When enabled, the quote PDF will include an '
             'introductory paragraph above the line items. The '
             'paragraph content is set in the Covering Letter '
             'field below.',
    )

    x_covering_letter_text = fields.Html(
        string='Covering Letter',
        help='Optional introductory paragraph shown above the '
             'line items on the printed quotation. Use plain '
             'prose; HTML formatting (bold, italic, bullets) is '
             'supported. Auto-fills client name and order '
             'reference when the quote is generated if you use '
             'the placeholders {{partner_name}} and '
             '{{order_ref}} (future: P1.M3.C will add live '
             'rendering of these placeholders).',
        sanitize=True,
        sanitize_tags=True,
        sanitize_attributes=True,
        strip_style=False,
    )
