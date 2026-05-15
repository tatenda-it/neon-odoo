# -*- coding: utf-8 -*-
"""P5.M8 — Equipment stock take.

Weekly Tuesday-06:00 reconciliation: a cron auto-creates a 'scheduled'
session with one line per workshop-floor unit (active / reserved /
maintenance / returned / damaged). Auditors walk the workshop, attest
the actual state + location + condition of each unit; discrepancies
are flagged and, for high-impact categories (Sound / Visual /
Lighting / Laptops by seed), escalate to the manager via an Action
Centre alert.

Ad-hoc sessions (filtered by category or location) are spawned
through neon.equipment.stock.take.wizard. The state machine
(pending → in_progress → completed / cancelled) follows the same
shape as the P5.M2 unit / P5.M4 reservation models.
"""
from datetime import date, datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_STATES = [
    ("pending",     "Pending"),
    ("in_progress", "In Progress"),
    ("completed",   "Completed"),
    ("cancelled",   "Cancelled"),
]


_SESSION_TYPES = [
    ("scheduled", "Scheduled (weekly cron)"),
    ("ad_hoc",    "Ad-Hoc (manual)"),
]


# Unit states the auditor can physically verify in the workshop.
# Excludes:
#   draft         — admin entry, no physical presence yet
#   checked_out   — at a venue, not in the workshop
#   transferred   — in transit between events
#   decommissioned — retired
_AUDITABLE_UNIT_STATES = (
    "active", "reserved", "maintenance", "returned", "damaged")


_ALLOWED_TRANSITIONS = {
    "pending":     ["in_progress", "cancelled"],
    "in_progress": ["completed", "cancelled"],
    "completed":   [],
    "cancelled":   [],
}


class NeonEquipmentStockTake(models.Model):
    _name = "neon.equipment.stock.take"
    _description = "Equipment Stock Take Session"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.stock.take") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    scheduled_for = fields.Date(
        string="Scheduled For",
        required=True,
        index=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    session_type = fields.Selection(
        _SESSION_TYPES,
        required=True,
        default="ad_hoc",
        tracking=True,
    )
    state = fields.Selection(
        _STATES,
        required=True,
        default="pending",
        readonly=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        "neon.equipment.stock.take.line",
        "stock_take_id",
        string="Lines",
    )
    started_by_id = fields.Many2one(
        "res.users", string="Started By", tracking=True, readonly=True)
    started_at = fields.Datetime(tracking=True, readonly=True)
    completed_at = fields.Datetime(tracking=True, readonly=True)
    completed_by_id = fields.Many2one(
        "res.users", string="Completed By", readonly=True)
    notes = fields.Text()

    # === Computed summary counts ===
    line_count = fields.Integer(
        compute="_compute_summary", store=True)
    attested_count = fields.Integer(
        compute="_compute_summary", store=True)
    discrepancy_count = fields.Integer(
        compute="_compute_summary", store=True)
    high_impact_discrepancy_count = fields.Integer(
        compute="_compute_summary", store=True)

    @api.depends("line_ids", "line_ids.attested",
                 "line_ids.has_discrepancy", "line_ids.is_high_impact")
    def _compute_summary(self):
        for rec in self:
            lines = rec.line_ids
            rec.line_count = len(lines)
            rec.attested_count = len(
                lines.filtered(lambda l: l.attested))
            disc = lines.filtered(lambda l: l.has_discrepancy)
            rec.discrepancy_count = len(disc)
            rec.high_impact_discrepancy_count = len(
                disc.filtered(lambda l: l.is_high_impact))

    # ============================================================
    # === State machine
    # ============================================================
    def _do_transition(self, new_state):
        self.ensure_one()
        allowed = _ALLOWED_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise UserError(_(
                "Illegal stock-take transition: %(from)s → %(to)s. "
                "Allowed from %(from)s: %(allowed)s"
            ) % {"from": self.state, "to": new_state,
                 "allowed": allowed})
        vals = {"state": new_state}
        now = fields.Datetime.now()
        if new_state == "in_progress":
            vals.update({"started_by_id": self.env.uid,
                         "started_at": now})
        elif new_state == "completed":
            vals.update({"completed_by_id": self.env.uid,
                         "completed_at": now})
        self.write(vals)
        return True

    def action_start(self):
        for rec in self:
            rec._do_transition("in_progress")

    def action_complete(self):
        for rec in self:
            unattested = rec.line_ids.filtered(lambda l: not l.attested)
            if unattested:
                raise UserError(_(
                    "Cannot complete stock take %(name)s — %(n)d "
                    "line(s) still unattested. Attest every line "
                    "(or use 'Attest All As Expected') before "
                    "completing."
                ) % {"name": rec.display_name, "n": len(unattested)})
            rec._do_transition("completed")

    def action_cancel(self):
        for rec in self:
            rec._do_transition("cancelled")

    # ============================================================
    # === Bulk attestation
    # "Attest All As Expected" — for the case where the auditor
    # has done a physical sweep and confirms everything matches
    # the snapshot. Manager-only via the view's groups= modifier;
    # the confirm dialog is also on the button. Idempotent: lines
    # already attested are left alone.
    # ============================================================
    def action_attest_all_as_expected(self):
        for rec in self:
            if rec.state not in ("pending", "in_progress"):
                raise UserError(_(
                    "Bulk attestation is only available on pending "
                    "or in-progress sessions. %(name)s is %(state)s."
                ) % {"name": rec.display_name, "state": rec.state})
            unattested = rec.line_ids.filtered(lambda l: not l.attested)
            now = fields.Datetime.now()
            for line in unattested:
                line.write({
                    "attested": True,
                    "attested_at": now,
                    "attested_by_id": self.env.uid,
                    "found_state": line.expected_state,
                    "found_location": line.expected_location,
                })
            if unattested:
                rec.message_post(body=_(
                    "Bulk-attested %(n)d line(s) as matching the "
                    "expected snapshot."
                ) % {"n": len(unattested)})

    # ============================================================
    # === Programmatic session creation
    # _create_session is the shared entry point for the cron, the
    # wizard, and any future automation. Filters arg shape:
    #   category_ids: recordset of neon.equipment.category (empty
    #     = no category filter)
    #   location_text: optional Char substring match on
    #     unit.workshop_location
    # ============================================================
    @api.model
    def _create_session(self, session_type="ad_hoc",
                        scheduled_for=None, category_ids=None,
                        location_text=None):
        if scheduled_for is None:
            scheduled_for = fields.Date.context_today(self)
        Unit = self.env["neon.equipment.unit"].sudo()
        domain = [("state", "in", list(_AUDITABLE_UNIT_STATES))]
        if category_ids:
            domain.append(
                ("equipment_category_id", "in", category_ids.ids))
        if location_text:
            domain.append(("workshop_location", "ilike", location_text))
        units = Unit.search(domain)
        session = self.create({
            "session_type": session_type,
            "scheduled_for": scheduled_for,
        })
        Line = self.env["neon.equipment.stock.take.line"].sudo()
        line_vals = []
        for idx, unit in enumerate(units):
            line_vals.append({
                "stock_take_id": session.id,
                "sequence": (idx + 1) * 10,
                "unit_id": unit.id,
                "expected_state": unit.state,
                "expected_location": unit.workshop_location or "",
            })
        if line_vals:
            Line.create(line_vals)
        session.message_post(body=_(
            "Stock take session created with %(n)d line(s) to "
            "verify (session_type=%(type)s)."
        ) % {"n": len(line_vals), "type": session_type})
        return session

    # ============================================================
    # === Tuesday 06:00 cron — weekly scheduled session
    # Idempotent: skips if a pending / in-progress scheduled session
    # already exists with scheduled_for=today. Match the defensive
    # pattern of the existing Action Centre time-based triggers.
    # ============================================================
    @api.model
    def _cron_create_weekly_session(self):
        today = fields.Date.context_today(self)
        existing = self.sudo().search([
            ("session_type", "=", "scheduled"),
            ("scheduled_for", "=", today),
            ("state", "in", ("pending", "in_progress")),
        ], limit=1)
        if existing:
            return existing
        session = self._create_session(
            session_type="scheduled", scheduled_for=today)
        return session
