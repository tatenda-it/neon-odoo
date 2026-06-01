# -*- coding: utf-8 -*-
"""P-B4 -- Sub-hire request line.

One line per B2 deficit/zero_margin product. Mirrors the
B3 deployment.plan deficit-array shape but persisted as a proper
Odoo o2m so the values can be queried + linked to the PO line.
"""
from odoo import api, fields, models


class NeonSubhireRequestLine(models.Model):
    _name = "neon.subhire.request.line"
    _description = "Sub-hire request line"
    _order = "request_id, sub_hire_priority, id"

    request_id = fields.Many2one(
        "neon.subhire.request", required=True, index=True,
        ondelete="cascade",
    )
    product_template_id = fields.Many2one(
        "product.template", required=True, index=True,
        ondelete="restrict",
    )
    qty_short = fields.Integer(
        required=True,
        help="Mirrors B2's deficit_qty for this product. The "
             "validator enforces an exact match against the "
             "source conflict line.",
    )
    event_window = fields.Char(
        required=True,
        help="Per validator R5: precise '<load_in_start_iso> -> "
             "<load_out_end_iso>' when both set, else fallback "
             "'<event_date> -> <event_end_date or event_date>'.",
    )
    competing_event_names_csv = fields.Char(
        help="Comma-separated names of the other event jobs that "
             "compete for the same product. Validated as a SUBSET "
             "of B2's set.",
    )
    sub_hire_priority = fields.Integer(
        default=0, index=True,
        help="Lower = more urgent. Inherited from the matching "
             "B2 conflict.line.",
    )
    brief = fields.Text(
        help="Claude's narrative for this line -- 1-2 sentences "
             "the user includes in the supplier enquiry.",
    )
    po_line_id = fields.Many2one(
        "purchase.order.line",
        string="PO Draft Line",
        readonly=True, ondelete="set null",
        help="Set when the Approve action creates the PO draft. "
             "Confirming/editing the PO line is via the standard "
             "Purchase Orders menu.",
    )
