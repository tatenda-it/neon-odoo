# -*- coding: utf-8 -*-
"""Neon HR R3a — driver licences (fleet controls).

A licence record on an employee. A "driver" is NOT a separate category
(per the questionnaire): any employee holding a CURRENT (non-expired)
licence IS a driver. Licence expiry drives an Action Centre alert
(reuses the neon_jobs Action Centre — trigger ``licence_expiry`` added
via selection_add in action_centre_ext.py, cron below). The alert lead
time is configurable via ``ir.config_parameter
neon_hr.licence_expiry_lead_days`` (default 30).

⚠️ DECISION (Gate 1): ``licence_class`` is CAPTURED now (Zimbabwe
classes) but the crew-assignment gate does NOT match on class in R3a —
it fires only when a driver-role crew member holds NO valid licence at
all. Class-match logic + the authoritative ZW class list are deferred
to R3b.

Confidential (Q28 pattern): owner + OD/MD + HR Admin; perm_unlink=0.
"""
import logging
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_LICENCE_LEAD_DAYS = 30
LICENCE_LEAD_PARAM = "neon_hr.licence_expiry_lead_days"

# Zimbabwe driver-licence classes — DATA CAPTURE ONLY in R3a (the gate
# does not match on class yet, see module docstring). 'other' is a
# catch-all; the authoritative list is locked at R3b.
LICENCE_CLASS_SELECTION = [
    ("class_1", "Class 1 — Heavy / articulated"),
    ("class_2", "Class 2 — Heavy goods vehicles"),
    ("class_3", "Class 3 — Light motor vehicles"),
    ("class_4", "Class 4 — Motorcycles"),
    ("class_5", "Class 5 — Tractors / plant"),
    ("other", "Other / Foreign"),
]


class NeonHrLicence(models.Model):
    _name = "neon.hr.licence"
    _description = "Neon HR Driver Licence"
    _inherit = ["mail.thread", "action.centre.mixin"]
    _order = "expiry_date asc, id desc"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade",
        index=True, tracking=True)
    employee_user_id = fields.Many2one(
        "res.users", related="employee_id.user_id", store=True,
        index=True, string="Employee User")
    licence_class = fields.Selection(
        LICENCE_CLASS_SELECTION, string="Licence Class", tracking=True,
        help="Zimbabwe licence class. Captured for the record; the R3a "
        "assignment gate does NOT match on class (deferred to R3b).")
    licence_number = fields.Char(tracking=True)
    issuing_authority = fields.Char(default="VID Zimbabwe")
    issue_date = fields.Date(tracking=True)
    expiry_date = fields.Date(tracking=True)
    attachment_ids = fields.Many2many(
        "ir.attachment", "neon_hr_licence_attachment_rel",
        "licence_id", "attachment_id", string="Scan / Evidence")
    state = fields.Selection(
        [("valid", "Valid"),
         ("expiring", "Expiring Soon"),
         ("expired", "Expired")],
        compute="_compute_state", store=True, tracking=True, index=True)
    is_expired = fields.Boolean(compute="_compute_state", store=True)
    days_to_expiry = fields.Integer(compute="_compute_days_to_expiry")
    notes = fields.Text()

    @api.model
    def _licence_lead_days(self):
        """Configurable alert/expiring-state lead window (default 30)."""
        val = self.env["ir.config_parameter"].sudo().get_param(
            LICENCE_LEAD_PARAM)
        try:
            return int(val) if val else DEFAULT_LICENCE_LEAD_DAYS
        except (TypeError, ValueError):
            return DEFAULT_LICENCE_LEAD_DAYS

    @api.depends("expiry_date")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=self._licence_lead_days())
        for rec in self:
            if not rec.expiry_date:
                # No expiry recorded -> treat as valid (some licences
                # carry no expiry; the alert simply never fires).
                rec.state = "valid"
                rec.is_expired = False
            elif rec.expiry_date < today:
                rec.state = "expired"
                rec.is_expired = True
            elif rec.expiry_date <= horizon:
                rec.state = "expiring"
                rec.is_expired = False
            else:
                rec.state = "valid"
                rec.is_expired = False

    @api.depends("expiry_date")
    @api.depends_context("uid")
    def _compute_days_to_expiry(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_to_expiry = (
                (rec.expiry_date - today).days if rec.expiry_date else 0)

    @api.depends("employee_id", "licence_class", "licence_number")
    def _compute_display_name(self):
        classes = dict(LICENCE_CLASS_SELECTION)
        for rec in self:
            label = classes.get(rec.licence_class) or _("Licence")
            rec.display_name = "%s — %s" % (
                rec.employee_id.name or _("New"), label)

    # ----- licence-expiry alert (Action Centre) ---------------------
    @api.model
    def _cron_licence_expiry_scan(self):
        """Daily — raise/refresh a ``licence_expiry`` Action Centre item
        for every licence expiring within the configurable lead window
        (and for already-expired licences). Idempotent via the mixin.
        Also nudges licence + competency stored states so today-driven
        transitions land without a user write."""
        Config = self.env["action.centre.trigger.config"].sudo()
        cfg = Config.search(
            [("trigger_type", "=", "licence_expiry")], limit=1)
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=self._licence_lead_days())
        created = 0
        if cfg and cfg.is_enabled:
            licences = self.sudo().search([
                ("expiry_date", "!=", False),
                ("expiry_date", "<=", horizon)])
            hr_user = self.env["hr.contract"]._neon_hr_alert_assignee()
            for lic in licences:
                days = (lic.expiry_date - today).days
                emp = lic.employee_id.name or _("employee")
                if days < 0:
                    title = _("EXPIRED %(d)s days ago: %(e)s driver "
                              "licence (expired %(dt)s)") % {
                        "d": abs(days), "e": emp, "dt": lic.expiry_date}
                    prio = "urgent"
                else:
                    title = _("Driver licence expires in %(d)s days: "
                              "%(e)s (expires %(dt)s)") % {
                        "d": days, "e": emp, "dt": lic.expiry_date}
                    prio = "high"
                kwargs = {"title": title, "priority": prio,
                          "due_date": datetime.combine(
                              lic.expiry_date, time())}
                if hr_user:
                    kwargs["primary_assignee_id"] = hr_user.id
                try:
                    if lic._action_centre_create_item(
                            "licence_expiry", **kwargs):
                        created += 1
                except Exception as e:  # noqa: BLE001
                    _logger.warning(
                        "licence_expiry trigger failed for %s: %s",
                        lic.id, e)
            _logger.info("neon_hr licence scan: %d in window, %d items.",
                         len(licences), created)
        # nudge stored states (today-driven transitions)
        self._cron_refresh_states()
        self.env["neon.hr.employee.competency"].sudo()._cron_refresh_states()
        return True

    @api.model
    def _cron_refresh_states(self):
        recs = self.sudo().search([("expiry_date", "!=", False)])
        if recs:
            recs.modified(["expiry_date"])
            recs._compute_state()
        return True
