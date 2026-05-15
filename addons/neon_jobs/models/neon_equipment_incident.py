# -*- coding: utf-8 -*-
"""P5.M9 — Equipment incident.

Loss / theft / accident lifecycle, distinct from the repair_order
workshop fix workflow. An incident triggers an immediate manager-
tier Action Centre alert (incident_open) and walks through
investigation → resolved_recovered / resolved_writeoff /
resolved_claim / cancelled.

The P5.M7 check-in wizard's incident_link resolution path used to
raise a UserError stub; with M9 it creates a real incident in
'open' state with type='loss'. Stock-take lines and unit-form
smart buttons also create incidents via action_open_incident.

Unit state side-effects on resolution:
  resolved_recovered → unit goes damaged / missing → active
  resolved_writeoff  → unit → returned → decommissioned (via the
                                                          unit's own
                                                          state machine)
  resolved_claim     → same as writeoff but requires
                       insurance_claim_ref
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_INCIDENT_TYPES = [
    ("loss",     "Loss"),
    ("theft",    "Theft"),
    ("accident", "Accident"),
    ("water",    "Water Damage"),
    ("fire",     "Fire Damage"),
    ("other",    "Other"),
]


_INCIDENT_STATES = [
    ("open",                 "Open"),
    ("under_investigation",  "Under Investigation"),
    ("resolved_recovered",   "Resolved — Recovered"),
    ("resolved_writeoff",    "Resolved — Write-off"),
    ("resolved_claim",       "Resolved — Insurance Claim"),
    ("cancelled",            "Cancelled — False Alarm"),
]

_RESOLVED_STATES = (
    "resolved_recovered", "resolved_writeoff", "resolved_claim")
_TERMINAL_STATES = _RESOLVED_STATES + ("cancelled",)


_ALLOWED_TRANSITIONS = {
    "open":                 ["under_investigation", "cancelled"],
    "under_investigation":  list(_RESOLVED_STATES) + ["cancelled"],
    "resolved_recovered":   [],
    "resolved_writeoff":    [],
    "resolved_claim":       [],
    "cancelled":            [],
}


class NeonEquipmentIncident(models.Model):
    _name = "neon.equipment.incident"
    _description = "Equipment Incident"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.incident") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Unit",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    incident_type = fields.Selection(
        _INCIDENT_TYPES,
        required=True,
        default="loss",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        _INCIDENT_STATES,
        default="open",
        required=True,
        readonly=True,
        tracking=True,
        index=True,
    )

    # === Source context ===
    source_event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Source Event",
        ondelete="set null",
    )
    source_stock_take_line_id = fields.Many2one(
        "neon.equipment.stock.take.line",
        string="Source Stock-Take Line",
        ondelete="set null",
    )
    source_checkin_movement_id = fields.Many2one(
        "neon.equipment.movement",
        string="Source Check-In",
        ondelete="set null",
        help="The check-in movement that surfaced the incident "
        "(empty when the incident was created via the missing+"
        "incident_link path — no check-in movement is written "
        "in that flow).",
    )

    # === Resolution ===
    description = fields.Text(required=True)
    investigation_notes = fields.Text()
    resolution_notes = fields.Text()
    resolved_at = fields.Datetime(tracking=True, readonly=True)
    resolved_by_id = fields.Many2one(
        "res.users", string="Resolved By", readonly=True)
    repair_order_ids = fields.One2many(
        "neon.equipment.repair.order",
        "incident_id",
        string="Linked Repair Orders",
    )
    estimated_loss_value = fields.Monetary(
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )
    insurance_claim_ref = fields.Char(
        string="Insurance Claim Ref")
    police_report_ref = fields.Char(
        string="Police Report Ref",
        help="For theft cases — external reference.")
    photo = fields.Image(max_width=1920, max_height=1080)

    # ============================================================
    # === State machine
    # ============================================================
    def _do_transition(self, new_state):
        self.ensure_one()
        allowed = _ALLOWED_TRANSITIONS.get(self.state, [])
        if new_state not in allowed:
            raise UserError(_(
                "Illegal incident transition: %(from)s → %(to)s. "
                "Allowed from %(from)s: %(allowed)s"
            ) % {"from": self.state, "to": new_state,
                 "allowed": allowed})
        self.write({"state": new_state})

    def action_investigate(self):
        for rec in self:
            rec._do_transition("under_investigation")

    def action_resolve_recovered(self):
        for rec in self:
            rec.write({
                "resolved_at": fields.Datetime.now(),
                "resolved_by_id": self.env.uid,
            })
            rec._do_transition("resolved_recovered")
            # Walk the unit back to active. ALLOWED_TRANSITIONS on
            # neon.equipment.unit doesn't permit damaged → active
            # directly, so route via maintenance. For missing-but-
            # recovered (checked_out / transferred), walk through
            # returned. Other states stay as-is — managers handle
            # exceptions manually via the unit form.
            unit = rec.unit_id.sudo()
            if unit.state == "damaged":
                unit._do_transition("maintenance")
                unit._do_transition("active")
            elif unit.state in ("checked_out", "transferred"):
                unit._do_transition("returned")
                unit._do_transition("active")
            rec._sync_action_item()

    def action_resolve_writeoff(self, reason=None):
        for rec in self:
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Write-off resolution is manager-only."))
            rec.write({
                "resolved_at": fields.Datetime.now(),
                "resolved_by_id": self.env.uid,
                "resolution_notes": reason or rec.resolution_notes,
            })
            rec._do_transition("resolved_writeoff")
            rec._walk_unit_to_decommissioned()
            rec._sync_action_item()

    def action_resolve_claim(self, claim_ref=None):
        for rec in self:
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Insurance claim resolution is manager-only."))
            if claim_ref:
                rec.insurance_claim_ref = claim_ref
            if not (rec.insurance_claim_ref or "").strip():
                raise UserError(_(
                    "Insurance claim reference is required to "
                    "resolve via claim path."))
            rec.write({
                "resolved_at": fields.Datetime.now(),
                "resolved_by_id": self.env.uid,
            })
            rec._do_transition("resolved_claim")
            rec._walk_unit_to_decommissioned()
            rec._sync_action_item()

    def action_cancel(self):
        for rec in self:
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Incident cancellation is manager-only."))
            rec._do_transition("cancelled")
            rec._sync_action_item()

    def _walk_unit_to_decommissioned(self):
        """Walk the unit through the ALLOWED_TRANSITIONS chain to
        end at decommissioned. checked_out → decommissioned isn't
        a direct allowed step, so we route via returned."""
        unit = self.unit_id.sudo()
        if unit.state in ("checked_out", "transferred"):
            unit._do_transition("returned")
        if unit.state in ("active", "reserved", "returned",
                          "maintenance", "damaged"):
            if unit.state == "active":
                # active → decommissioned is allowed directly
                pass
            elif unit.state == "reserved":
                # reserved doesn't allow → decommissioned; route via
                # returned (managers rarely hit this — reserved
                # write-offs usually go through cancel + re-flow).
                unit._do_transition("returned")
        unit._do_transition("decommissioned")

    # ============================================================
    # === Action Centre wiring
    # incident_open fires real-time on create; auto-closes when
    # state transitions to any terminal state.
    # ============================================================
    def _sync_action_item(self):
        for rec in self.sudo():
            if rec.state in _TERMINAL_STATES:
                # force=True because the trigger config carries
                # item_type='alert' and auto-close should fire
                # on any terminal transition.
                rec._action_centre_close_items(
                    "incident_open", force=True)
            else:
                rec._action_centre_create_item("incident_open")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            try:
                rec._sync_action_item()
            except Exception:  # noqa: BLE001
                # Defensive — incident creation must not be blocked
                # by a downstream Action Centre failure. Matches the
                # pattern from event_job._action_centre_create_item.
                continue
        return records
