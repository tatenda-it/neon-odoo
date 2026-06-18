# -*- coding: utf-8 -*-
"""Collections worklist — the LIVE, team-editable outstanding-payments board.

UNLIKE every other model in this module (inert archives), this one is OWNED by
the collections team: they create / edit / re-status / close items and log
follow-up activities. It is a WORKLIST, NOT general-ledger AR — no account.move,
no ledger posting. The verbatim ``note`` is the source of truth; ``status`` is a
sortable layer over it. Seeded once from the outstanding-payments sheet; then
the team runs it.

Holds debtor amounts + contact phone numbers + escalation notes -> ACL is the
collections team only (sales + director + bookkeeper); crew/operational logins
have no access.
"""
from odoo import fields, models

STATUS = [
    ("promised", "Promised"),
    ("po_submitted", "PO Submitted"),
    ("part_paid", "Part Paid"),
    ("chasing", "Chasing"),
    ("unresponsive", "Unresponsive"),
    ("clearing", "Clearing"),
    ("recovered", "Recovered"),
    ("closed", "Closed"),
]


class NeonCollectionsItem(models.Model):
    _name = "neon.collections.item"
    _description = "Collections Worklist Item (Outstanding Payment)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_year desc, amount_usd desc, id desc"
    _rec_name = "client_name"

    client_name = fields.Char(string="Client", required=True, tracking=True)
    event_name = fields.Char(string="Event / Venue")
    partner_id = fields.Many2one(
        "res.partner", string="Client (linked)", tracking=True,
        help="Conservative match to an existing partner; client_name is kept "
        "verbatim regardless.")
    amount_usd = fields.Float(string="Outstanding USD", tracking=True)
    amount_zwg = fields.Float(string="Outstanding ZWG")
    currency_flag = fields.Char(
        string="Currency Flag",
        help="Verbatim currency annotation needing confirmation "
        "(e.g. the TBWA/BAT 'ZWG Payment' note).")
    contact_name = fields.Char(string="Contact")
    contact_phone = fields.Char(string="Contact Phone")
    sales_rep_raw = fields.Char(string="Sales Rep (source)")
    sales_rep_id = fields.Many2one("res.users", string="Sales Rep")
    status = fields.Selection(
        STATUS, string="Status", default="chasing", tracking=True, index=True)
    note = fields.Text(string="Notes", tracking=True)  # verbatim source of truth
    period_year = fields.Selection(
        [("2025", "2025"), ("2026", "2026")], string="Period", index=True)
    source = fields.Char(string="Source", default="outstanding_sheet")
    active = fields.Boolean(default=True)
