# -*- coding: utf-8 -*-
"""Neon HR R2 — workplace accident / NSSA tracking.

Admin captures the accident; OD/MD reviews; NSSA submission is tracked
with uploaded proof. A HARD 14-day NSSA reporting deadline drives an
Action Centre alert (reuses the neon_jobs Action Centre — trigger
``accident_nssa_14day`` added via selection_add, cron below).

⚠️ DECISION (Gate 1): the NSSA PENALTY is ALERT-ONLY — a flagged
boolean + free-text note, NOT a hard-coded penalty calculation. The
figure/formula stays out until finance/legal confirm it. Confidential
(record rules: OD/MD/Admin + the record owner).
"""
import logging
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

ACCIDENT_STATES = [
    ("captured", "Captured"),
    ("reviewed", "Reviewed (OD/MD)"),
    ("nssa_submitted", "NSSA Submitted"),
    ("closed", "Closed"),
]
NSSA_DEADLINE_DAYS = 14


class NeonHrAccident(models.Model):
    _name = "neon.hr.accident"
    _description = "Neon HR Workplace Accident (NSSA)"
    _inherit = ["mail.thread", "action.centre.mixin"]
    _order = "accident_date desc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        related="employee_id.user_id", store=True, index=True)
    accident_date = fields.Date(
        required=True, default=fields.Date.context_today, tracking=True)
    description = fields.Text(required=True)
    injury_description = fields.Text(string="Injury")
    witnesses = fields.Text(help="Witness names / contact details.")
    attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_accident_attachment_rel",
        "accident_id", "attachment_id", string="Evidence / Photos")
    state = fields.Selection(
        ACCIDENT_STATES, default="captured", required=True,
        tracking=True, index=True)
    reviewed_by_id = fields.Many2one("res.users", readonly=True, tracking=True)

    # ----- NSSA submission tracking -----
    reporting_deadline = fields.Date(
        compute="_compute_deadline", store=True,
        help="Hard NSSA reporting deadline = accident date + 14 days.")
    days_to_deadline = fields.Integer(compute="_compute_days_to_deadline")
    nssa_submission_ref = fields.Char(string="NSSA Submission Ref")
    nssa_submitted_date = fields.Date(readonly=True)
    nssa_proof_attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_accident_nssa_proof_rel",
        "accident_id", "attachment_id", string="NSSA Submission Proof")

    # ⚠️ ALERT-ONLY — no penalty amount/calc until finance/legal confirm.
    penalty_risk = fields.Boolean(
        string="NSSA Penalty Risk",
        help="⚠️ ALERT-ONLY flag. The NSSA penalty figure/formula is "
        "NOT computed here — finance/legal must confirm it before any "
        "amount is shown.")
    penalty_note = fields.Text(
        string="Penalty Note (advisory)",
        help="Free-text advisory only. Do NOT enter a calculated "
        "penalty — pending finance/legal sign-off.")

    @api.depends("accident_date")
    def _compute_deadline(self):
        for rec in self:
            rec.reporting_deadline = (
                rec.accident_date + timedelta(days=NSSA_DEADLINE_DAYS)
                if rec.accident_date else False)

    @api.depends("reporting_deadline")
    @api.depends_context("uid")
    def _compute_days_to_deadline(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_to_deadline = (
                (rec.reporting_deadline - today).days
                if rec.reporting_deadline else 0)

    @api.depends("employee_id", "accident_date")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (
                rec.employee_id.name or _("New"),
                rec.accident_date or "?")

    # ----- state machine -----
    def action_review(self):
        for rec in self:
            if rec.state != "captured":
                raise UserError(_("Only captured accidents can be reviewed."))
            rec.write({"state": "reviewed",
                       "reviewed_by_id": self.env.user.id})
            rec.message_post(body=_("Accident reviewed by %s.")
                             % self.env.user.name)
        return True

    def action_nssa_submit(self):
        for rec in self:
            if rec.state not in ("captured", "reviewed"):
                raise UserError(_("Accident already submitted/closed."))
            if not rec.nssa_submission_ref:
                raise UserError(_(
                    "Enter the NSSA submission reference before marking "
                    "submitted."))
            rec.write({"state": "nssa_submitted",
                       "nssa_submitted_date": fields.Date.context_today(self)})
            rec._action_centre_close_items("accident_nssa_14day", force=True)
            rec.message_post(body=_("NSSA submission recorded (%s).")
                             % rec.nssa_submission_ref)
        return True

    def action_close(self):
        for rec in self:
            rec.state = "closed"
        return True

    # ----- 14-day NSSA deadline alert (Action Centre) -----
    @api.model
    def _cron_accident_nssa_deadline_scan(self):
        """Raise/refresh an Action Centre item for every accident not yet
        NSSA-submitted (HARD 14-day deadline). Idempotent via the mixin.
        Assigned to HR; surfaced to OD/MD (config primary_role)."""
        Config = self.env["action.centre.trigger.config"].sudo()
        cfg = Config.search([("trigger_type", "=", "accident_nssa_14day")],
                            limit=1)
        if not cfg or not cfg.is_enabled:
            return True
        today = fields.Date.context_today(self)
        pending = self.sudo().search([("state", "in", ("captured", "reviewed"))])
        hr_user = self.env["hr.contract"]._neon_hr_alert_assignee()
        created = 0
        for rec in pending:
            days = (rec.reporting_deadline - today).days if rec.reporting_deadline else 0
            if days < 0:
                title = _("OVERDUE %(d)s days: NSSA report for %(e)s "
                          "accident (%(dt)s)") % {
                    "d": abs(days), "e": rec.employee_id.name,
                    "dt": rec.accident_date}
                prio = "urgent"
            else:
                title = _("NSSA report due in %(d)s days: %(e)s accident "
                          "(%(dt)s)") % {
                    "d": days, "e": rec.employee_id.name,
                    "dt": rec.accident_date}
                prio = "high"
            kwargs = {"title": title, "priority": prio,
                      "due_date": datetime.combine(
                          rec.reporting_deadline or today, time())}
            if hr_user:
                kwargs["primary_assignee_id"] = hr_user.id
            try:
                if rec._action_centre_create_item("accident_nssa_14day", **kwargs):
                    created += 1
            except Exception as e:  # noqa: BLE001
                _logger.warning("accident NSSA trigger failed for %s: %s",
                                rec.id, e)
        _logger.info("neon_hr accident NSSA scan: %d pending, %d items.",
                     len(pending), created)
        return True
