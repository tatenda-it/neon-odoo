# -*- coding: utf-8 -*-
"""Neon HR R1b-1 — crew availability signal.

A read-only SQL view: one row per VALIDATED leave = one window during
which that person is UNAVAILABLE. This is the clean availability signal
Operations and the future B10 scheduler consume — we expose the signal
only, NOT a scheduler (R1 scope, item 4).
"""
from odoo import fields, models, tools


class NeonHrAvailability(models.Model):
    _name = "neon.hr.availability"
    _description = "Neon HR Crew Unavailability (from approved leave)"
    _auto = False
    _order = "date_from desc"

    leave_id = fields.Many2one("hr.leave", readonly=True)
    employee_id = fields.Many2one("hr.employee", readonly=True)
    employee_name = fields.Char(readonly=True)
    neon_category_id = fields.Many2one("neon.hr.category", readonly=True)
    holiday_status_id = fields.Many2one("hr.leave.type", readonly=True)
    date_from = fields.Date(readonly=True, string="Unavailable From")
    date_to = fields.Date(readonly=True, string="Unavailable To")
    number_of_days = fields.Float(readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW neon_hr_availability AS (
                SELECT
                    l.id                  AS id,
                    l.id                  AS leave_id,
                    l.employee_id         AS employee_id,
                    e.name                AS employee_name,
                    e.neon_category_id    AS neon_category_id,
                    l.holiday_status_id   AS holiday_status_id,
                    l.request_date_from   AS date_from,
                    l.request_date_to     AS date_to,
                    l.number_of_days      AS number_of_days
                FROM hr_leave l
                JOIN hr_employee e ON e.id = l.employee_id
                WHERE l.state = 'validate'
            )
        """)
