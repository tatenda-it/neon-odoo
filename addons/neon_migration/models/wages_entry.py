# -*- coding: utf-8 -*-
"""Wages REFERENCE records — WEEKLY-LUMP pay per technician (historical).

Inert, faithful: the WEEKLY lump pay only — NO per-job cost split (a weekly lump
spans 2-6 jobs; per-job is an estimate, deferred to Layer-2 analytics, never
persisted). NOT live hr.employee / neon.hr.event.wage / commercial.job.crew.

PAY -> ACL is finance (bookkeeper) + director (superuser) only, tighter than the
all-internal crew roster. Reversible/cleanable (superuser unlink).
"""
from odoo import fields, models


class NeonWagesEntry(models.Model):
    _name = "neon.wages.entry"
    _description = "Wages Entry (Weekly-Lump Reference)"
    _order = "week_date desc, id desc"
    _rec_name = "week_label"

    week_date = fields.Date(string="Week", index=True)  # best-effort; nullable
    week_label = fields.Char(string="Week (label)", required=True)  # verbatim
    crew_member_id = fields.Many2one(
        "neon.crew.member", string="Technician", ondelete="restrict",
        index=True)
    total = fields.Float(string="Weekly Pay")  # the lump; NO per-job split
    currency_code = fields.Char(string="Currency", default="USD")
    paid = fields.Selection(
        [("paid", "Paid"), ("unknown", "Unknown")],
        string="Paid", default="unknown")
    jobs_raw = fields.Text(string="Jobs Covered")  # VERBATIM newline list
    job_ids = fields.Many2many(
        "neon.job.history", "neon_wages_entry_job_rel",
        "wages_id", "job_id", string="Linked Jobs")
    job_link_count = fields.Integer(string="# Linked Jobs")
    source = fields.Char(string="Source", default="wages_sheet", index=True)
    note = fields.Text(string="Note")
    active = fields.Boolean(default=True)
