# -*- coding: utf-8 -*-
"""FamCal job-history REFERENCE records (historical import).

Inert reference of the company calendar (FamCal scrape) — NOT account.move, no
ledger, no operational event-job graph. The job SPINE for the later wages lane
(crew<->job<->pay comes from the wages sheet, NOT from FamCal participants).

Stored VERBATIM (title / notes / participants kept as-is). All 726 events are
stored; reminders/admin are TAGGED (is_job=False) and default-hidden, never
deleted. Conservative client-match: partner_id set only on a high-confidence
title match, else NULL — the raw title is always preserved.

Unlike the finance archives, this is readable by ALL internal users (incl.
sales) — it carries no money. Reversible/cleanable (superuser unlink).
"""
from odoo import fields, models


class NeonJobHistory(models.Model):
    _name = "neon.job.history"
    _description = "Job History (FamCal Reference / Historical Import)"
    _order = "date_start desc, id desc"
    _rec_name = "title"

    date_start = fields.Datetime(string="Start", index=True)
    date_end = fields.Datetime(string="End")
    all_day = fields.Boolean(string="All day")
    is_multiday = fields.Boolean(string="Multi-day")
    title = fields.Char(string="Title", required=True)  # VERBATIM
    location = fields.Char(string="Location")
    notes = fields.Text(string="Notes")  # VERBATIM (equipment specs + contacts)
    created_by = fields.Char(string="Created By")
    event_type = fields.Char(string="Type")
    participants_raw = fields.Text(string="Participants")  # VERBATIM emails

    is_job = fields.Boolean(string="Is Job", default=True, index=True)
    category = fields.Selection(
        [("job", "Job"), ("reminder", "Reminder"), ("admin", "Admin")],
        string="Category", default="job", index=True)

    partner_id = fields.Many2one(
        "res.partner", string="Client", ondelete="set null", index=True)
    partner_match = fields.Selection(
        [("exact", "Exact"), ("strong", "Strong"), ("none", "None")],
        string="Match", default="none")

    source = fields.Char(string="Source", default="famcal_scrape", index=True)
    active = fields.Boolean(default=True)
