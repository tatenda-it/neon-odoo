# -*- coding: utf-8 -*-
"""
P5.M1 — Equipment Unit (per-physical-item identity).

One row per physical asset. The lifecycle drives reservation
eligibility, repair workflow, and the P5.M9 incident model. For
P5.M1, the state field is a Selection without enforcement — any
transition is allowed. P5.M2 introduces state-machine guards
(action_* methods + _do_transition) bound to ALLOWED_TRANSITIONS.

LOCKED 9-state contract (2026-05-14, supersedes the early Schema
Sketch draft which had 8 with some different codes):

  1. draft          — new, not yet in service
  2. active         — in service, available for reservation
  3. reserved       — held for an upcoming job
  4. checked_out    — with crew on a job, not yet returned
  5. transferred    — in transit between jobs (Q9 cross-job flow)
  6. returned       — back from a job, pending check-in
  7. maintenance    — in maintenance / repair
  8. damaged        — incident-flagged, not yet in maintenance
  9. decommissioned — retired

The early draft used 'enrolled'/'in_repair'/'retired' and omitted
'damaged'; the model's operational codes (draft / maintenance /
decommissioned + damaged) are clearer on the workshop floor and
have been locked as the canonical spec. 'transferred' was added
2026-05-14 to support the Q9 cross-job transfer workflow.

Inherits action.centre.mixin so future workshop triggers
(repair_required, asset_overdue_return, maintenance_due) have a
single hook surface.

Serial-tracked products spawn N units (one per serial). Quantity-
tracked products typically have a single "bulk" unit with serial
left blank and asset_tag carrying the bulk identifier.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_UNIT_STATES = [
    ("draft",          "Draft (new, not yet in service)"),
    ("active",         "Active (in service, available)"),
    ("reserved",       "Reserved (held for upcoming job)"),
    ("checked_out",    "Checked Out (with crew on job)"),
    ("transferred",    "Transferred (in transit between jobs)"),
    ("returned",       "Returned (back, pending check-in)"),
    ("maintenance",    "In Maintenance / Repair"),
    ("damaged",        "Damaged (incident-flagged)"),
    ("decommissioned", "Decommissioned (retired)"),
]


# P5.M2 — Allowed state transitions per source state. Decommissioned
# is terminal under normal authority; the MANAGER_BYPASS dict below
# is the only way out.
ALLOWED_TRANSITIONS = {
    "draft":          ["active", "decommissioned"],
    "active":         ["reserved", "maintenance", "damaged",
                       "decommissioned"],
    "reserved":       ["active", "checked_out", "maintenance"],
    "checked_out":    ["transferred", "returned", "damaged",
                       "maintenance"],
    "transferred":    ["checked_out", "returned"],
    "returned":       ["active", "maintenance", "damaged",
                       "decommissioned"],
    "maintenance":    ["active", "damaged", "decommissioned"],
    "damaged":        ["maintenance", "decommissioned"],
    "decommissioned": [],
}

# P5.M2 — Manager-only reversals that override ALLOWED_TRANSITIONS.
# Currently scoped to write-off reversal (manager realises a
# decommissioned unit is actually fixable). All entries require an
# explicit reason string at the call site.
MANAGER_BYPASS_TRANSITIONS = {
    "decommissioned": ["active", "maintenance"],
}


class NeonEquipmentUnit(models.Model):
    _name = "neon.equipment.unit"
    _description = "Workshop Equipment Unit"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "product_template_id, serial_number, id"

    name = fields.Char(
        compute="_compute_name",
        store=True,
        index=True,
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        required=True,
        ondelete="restrict",
        domain="[('is_workshop_item', '=', True)]",
        tracking=True,
    )
    # === Related convenience fields for filtering / search ===
    equipment_category_id = fields.Many2one(
        related="product_template_id.equipment_category_id",
        store=True,
        readonly=True,
        string="Category",
    )
    workshop_name = fields.Char(
        related="product_template_id.workshop_name",
        store=False,
        readonly=True,
    )
    tracking_mode = fields.Selection(
        related="product_template_id.tracking_mode",
        store=True,
        readonly=True,
    )

    # === Per-unit identity ===
    serial_number = fields.Char(
        string="Serial Number",
        tracking=True,
        help="The manufacturer's serial. Required for serial-tracked "
        "products (P5.M3 enforcement). Blank for quantity-tracked "
        "bulk units.",
    )
    asset_tag = fields.Char(
        string="Asset Tag",
        tracking=True,
        help="Neon's internal asset identifier — e.g. 'NL2', 'AC-014'. "
        "Optional but recommended for floor traceability.",
    )
    workshop_location = fields.Char(
        string="Location",
        tracking=True,
        help="Physical storage location — e.g. shelf, rack, vehicle.",
    )
    state = fields.Selection(
        _UNIT_STATES,
        string="State",
        default="draft",
        required=True,
        readonly=True,
        tracking=True,
        help="State transitions are enforced via the action_* methods "
        "and _do_transition. Direct state writes from the UI are "
        "blocked (readonly); programmatic writes from _do_transition "
        "succeed (Odoo readonly is a UI hint, not a DB constraint).",
    )

    # === Acquisition + accounting ===
    purchase_date = fields.Date(string="Purchase Date")
    purchase_price = fields.Monetary(
        string="Purchase Price",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
    )

    notes = fields.Text()
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ("unique_serial_per_product",
         "UNIQUE (product_template_id, serial_number)",
         "Two units of the same product cannot share a serial number."),
        ("unique_asset_tag",
         "UNIQUE (asset_tag)",
         "Asset tags must be unique across all units."),
    ]

    # ============================================================
    # === P5.M2 — state-machine capability flags
    # Booleans driving view button visibility. Computed off `state`;
    # one boolean per action_* method below. View binds with
    # invisible="not can_<verb>".
    # ============================================================
    can_enroll = fields.Boolean(compute="_compute_state_capabilities")
    can_reserve = fields.Boolean(compute="_compute_state_capabilities")
    can_check_out = fields.Boolean(compute="_compute_state_capabilities")
    can_transfer = fields.Boolean(compute="_compute_state_capabilities")
    can_receive_transfer = fields.Boolean(
        compute="_compute_state_capabilities")
    can_return = fields.Boolean(compute="_compute_state_capabilities")
    can_complete_check_in = fields.Boolean(
        compute="_compute_state_capabilities")
    can_send_to_maintenance = fields.Boolean(
        compute="_compute_state_capabilities")
    can_complete_maintenance = fields.Boolean(
        compute="_compute_state_capabilities")
    can_flag_damaged = fields.Boolean(
        compute="_compute_state_capabilities")
    can_decommission = fields.Boolean(
        compute="_compute_state_capabilities")

    @api.depends("product_template_id.workshop_name",
                 "product_template_id.name",
                 "serial_number", "asset_tag")
    def _compute_name(self):
        for rec in self:
            base = (rec.product_template_id.workshop_name
                    or rec.product_template_id.name
                    or _("(no product)"))
            tag = rec.serial_number or rec.asset_tag
            rec.name = f"{base} #{tag}" if tag else base

    @api.depends("state")
    def _compute_state_capabilities(self):
        for rec in self:
            allowed = ALLOWED_TRANSITIONS.get(rec.state, [])
            rec.can_enroll = (
                "active" in allowed and rec.state == "draft")
            rec.can_reserve = "reserved" in allowed
            rec.can_check_out = (
                "checked_out" in allowed and rec.state == "reserved")
            rec.can_transfer = "transferred" in allowed
            rec.can_receive_transfer = (
                "checked_out" in allowed and rec.state == "transferred")
            rec.can_return = "returned" in allowed
            rec.can_complete_check_in = (
                "active" in allowed and rec.state == "returned")
            rec.can_send_to_maintenance = "maintenance" in allowed
            rec.can_complete_maintenance = (
                "active" in allowed and rec.state == "maintenance")
            rec.can_flag_damaged = "damaged" in allowed
            rec.can_decommission = "decommissioned" in allowed

    # ============================================================
    # === P5.M2 — _do_transition (the sanctioned state-write path)
    # Mirrors the Phase 4 action.centre.item._do_transition pattern,
    # minus the _allow_state_write context (this model has no
    # write() gate) and minus _log_history (P5.M2 keeps audit to
    # chatter only; a separate history model is out of scope per
    # the milestone spec).
    # ============================================================
    def _do_transition(self, new_state, manager_override=False,
                       override_reason=None, vals=None):
        """Validate and execute a state transition.

        :param new_state: target state code (must be one of _UNIT_STATES)
        :param manager_override: if True, permit MANAGER_BYPASS_TRANSITIONS
        :param override_reason: required justification when manager_override
        :param vals: additional fields to write alongside the state change
        :raises UserError: on illegal transition, unknown state, missing
            override reason, or non-manager attempting an override
        :returns: True on success
        """
        self.ensure_one()

        valid_codes = {code for code, _label in self._fields["state"].selection}
        if new_state not in valid_codes:
            raise UserError(_(
                "Unknown state: %(state)s. Valid states: %(valid)s"
            ) % {"state": new_state, "valid": sorted(valid_codes)})

        old_state = self.state
        if old_state == new_state:
            # No-op — same state. Don't post chatter for nothing.
            return True

        allowed = ALLOWED_TRANSITIONS.get(old_state, [])
        if new_state in allowed:
            pass  # legal transition, proceed
        elif manager_override:
            bypass = MANAGER_BYPASS_TRANSITIONS.get(old_state, [])
            if new_state not in bypass:
                raise UserError(_(
                    "Even with manager override, %(from)s → %(to)s is "
                    "not allowed. Manager bypass from %(from)s only "
                    "permits: %(bypass)s"
                ) % {"from": old_state, "to": new_state, "bypass": bypass})
            if not self.env.user.has_group(
                    "neon_jobs.group_neon_jobs_manager"):
                raise UserError(_(
                    "Manager override requires manager group "
                    "membership."
                ))
            if not override_reason or not str(override_reason).strip():
                raise UserError(_(
                    "Manager override requires a justification reason."
                ))
        else:
            raise UserError(_(
                "Illegal state transition: %(from)s → %(to)s. Allowed "
                "transitions from %(from)s: %(allowed)s"
            ) % {"from": old_state, "to": new_state, "allowed": allowed})

        write_vals = {"state": new_state}
        if vals:
            write_vals.update(vals)
        self.write(write_vals)

        if manager_override:
            self.message_post(body=_(
                "Manager override transition: %(from)s → %(to)s. "
                "Reason: %(reason)s"
            ) % {"from": old_state, "to": new_state,
                 "reason": override_reason})
        else:
            self.message_post(body=_(
                "State change: %(from)s → %(to)s"
            ) % {"from": old_state, "to": new_state})

        return True

    # ============================================================
    # === P5.M2 — action_* convenience methods (form-button entry
    # points). Each is a thin wrapper over _do_transition with the
    # appropriate target state. Errors propagate from _do_transition
    # unchanged — illegal source-state attempts raise UserError.
    # ============================================================
    def action_enroll(self):
        """draft → active. Brings a new unit into service."""
        for rec in self:
            rec._do_transition("active")

    def action_reserve(self):
        """active → reserved. Hold for an upcoming job."""
        for rec in self:
            rec._do_transition("reserved")

    def action_check_out(self):
        """reserved → checked_out. The reservation became a live job.
        Active → checked_out is intentionally rejected — every
        checkout must walk through reserved first so the workshop
        floor has a paper trail."""
        for rec in self:
            if rec.state == "active":
                raise UserError(_(
                    "Unit must be reserved before checkout. Reserve "
                    "it first."
                ))
            rec._do_transition("checked_out")

    def action_transfer(self):
        """checked_out → transferred. Q9 cross-job transfer."""
        for rec in self:
            rec._do_transition("transferred")

    def action_receive_transfer(self):
        """transferred → checked_out. Arrived at the new job."""
        for rec in self:
            rec._do_transition("checked_out")

    def action_return(self):
        """checked_out / transferred → returned."""
        for rec in self:
            if rec.state not in ("checked_out", "transferred"):
                raise UserError(_(
                    "Can only return from checked_out or transferred "
                    "state. Current state: %s"
                ) % rec.state)
            rec._do_transition("returned")

    def action_complete_check_in(self):
        """returned → active. Inspection complete, ready for next."""
        for rec in self:
            rec._do_transition("active")

    def action_send_to_maintenance(self):
        """(active / reserved / checked_out / returned / damaged) →
        maintenance."""
        for rec in self:
            rec._do_transition("maintenance")

    def action_complete_maintenance(self):
        """maintenance → active."""
        for rec in self:
            rec._do_transition("active")

    def action_flag_damaged(self):
        """(active / checked_out / returned / maintenance) → damaged.
        Distinct from maintenance because incident triage may not
        yet have decided whether to repair or write off."""
        for rec in self:
            rec._do_transition("damaged")

    def action_decommission(self):
        """any (except reserved) → decommissioned (write-off).
        ALLOWED_TRANSITIONS controls which source states permit
        this; reservation must be released first."""
        for rec in self:
            rec._do_transition("decommissioned")

    def action_recommission_with_override(self, reason, target_state="active"):
        """Manager-only: reverse a decommissioned unit back to
        active or maintenance. Walks through _do_transition with
        manager_override=True; that gate verifies the user has the
        manager group and the reason is non-empty.

        target_state must be one of MANAGER_BYPASS_TRANSITIONS
        ['decommissioned'] — currently {'active', 'maintenance'}."""
        for rec in self:
            rec._do_transition(
                target_state,
                manager_override=True,
                override_reason=reason,
            )

    def action_open_recommission_wizard(self):
        """Form button → opens the recommission wizard so the
        manager can supply target_state + reason."""
        self.ensure_one()
        if self.state != "decommissioned":
            raise UserError(_(
                "Recommission is only available on decommissioned "
                "units. Current state: %s"
            ) % self.state)
        return {
            "type": "ir.actions.act_window",
            "name": _("Recommission Equipment Unit"),
            "res_model": "neon.equipment.recommission.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_equipment_unit_id": self.id},
        }
