# -*- coding: utf-8 -*-
"""P5.M8 — Stock take line (per-unit attestation).

Each line is a snapshot of one unit at session-create time
(expected_state + expected_location) plus the auditor's findings
at attestation time (found_state + found_location + condition).
A discrepancy is any mismatch between expected and found, or a
poor/damaged condition reading. High-impact-category lines that
land with a discrepancy fire the stock_take_high_impact Action
Centre alert immediately; standard-category discrepancies log via
chatter only.

The model inherits action.centre.mixin so it can spawn / close the
high-impact item directly. Mail.thread carries the attestation
chatter.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Mirror neon.equipment.unit._UNIT_STATES — these are the codes
# the auditor sees on the form. Imported lazily inside the callable
# to avoid model load-order coupling. Odoo passes the calling
# model recordset as the single positional argument.
def _unit_state_selection(_model):
    from .neon_equipment_unit import _UNIT_STATES
    return _UNIT_STATES


_CONDITIONS = [
    ("good",    "Good"),
    ("fair",    "Fair"),
    ("poor",    "Poor"),
    ("damaged", "Damaged"),
]


class NeonEquipmentStockTakeLine(models.Model):
    _name = "neon.equipment.stock.take.line"
    _description = "Stock Take Line"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "stock_take_id, sequence, id"

    stock_take_id = fields.Many2one(
        "neon.equipment.stock.take",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Unit",
        required=True,
        index=True,
        ondelete="restrict",
    )
    product_template_id = fields.Many2one(
        related="unit_id.product_template_id",
        store=True,
        readonly=True,
        string="Product",
    )
    category_id = fields.Many2one(
        related="unit_id.equipment_category_id",
        store=True,
        readonly=True,
        string="Category",
    )

    # === Snapshot at session create ===
    expected_state = fields.Selection(
        selection=_unit_state_selection,
        string="Expected State",
        readonly=True,
    )
    expected_location = fields.Char(
        string="Expected Location",
        readonly=True,
    )

    # === Attestation fields (filled at audit time) ===
    attested = fields.Boolean(
        default=False, tracking=True, index=True)
    attested_at = fields.Datetime(tracking=True, readonly=True)
    attested_by_id = fields.Many2one(
        "res.users", string="Attested By", readonly=True)
    found_state = fields.Selection(
        selection=_unit_state_selection,
        string="Found State",
    )
    found_location = fields.Char(string="Found Location")
    physical_condition = fields.Selection(
        _CONDITIONS,
        string="Condition",
    )
    notes = fields.Text()

    # === Resolution (for discrepancy reconciliation) ===
    resolved = fields.Boolean(
        default=False,
        tracking=True,
        help="Set when a manager has investigated and reconciled "
        "the discrepancy. Auto-closes the associated Action Centre "
        "item if one was raised.",
    )
    resolved_at = fields.Datetime(tracking=True, readonly=True)
    resolved_by_id = fields.Many2one(
        "res.users", string="Resolved By", readonly=True)
    resolution_notes = fields.Text()

    # === Computed flags ===
    has_discrepancy = fields.Boolean(
        compute="_compute_has_discrepancy",
        store=True,
        index=True,
    )
    is_high_impact = fields.Boolean(
        compute="_compute_is_high_impact",
        store=True,
        index=True,
    )

    @api.depends("attested", "found_state", "expected_state",
                 "found_location", "expected_location",
                 "physical_condition")
    def _compute_has_discrepancy(self):
        for rec in self:
            if not rec.attested:
                rec.has_discrepancy = False
                continue
            state_diff = (
                rec.found_state
                and rec.found_state != rec.expected_state)
            location_diff = (
                rec.found_location
                and rec.found_location != (rec.expected_location or ""))
            condition_bad = rec.physical_condition in ("damaged", "poor")
            rec.has_discrepancy = bool(
                state_diff or location_diff or condition_bad)

    @api.depends("unit_id.equipment_category_id.is_high_impact")
    def _compute_is_high_impact(self):
        for rec in self:
            rec.is_high_impact = bool(
                rec.unit_id.equipment_category_id.is_high_impact)

    # ============================================================
    # === Attestation action
    # Single entry point: writes the attestation fields atomically
    # and routes the discrepancy signal. High-impact + discrepancy
    # fires the Action Centre alert; standard discrepancy logs via
    # chatter only.
    # ============================================================
    def action_attest(self, found_state=None, found_location=None,
                      physical_condition=None, notes=None):
        for rec in self:
            if rec.attested:
                raise UserError(_(
                    "Line %(name)s is already attested. Edit the "
                    "fields directly if you need to amend."
                ) % {"name": rec.display_name})
            vals = {
                "attested": True,
                "attested_at": fields.Datetime.now(),
                "attested_by_id": self.env.uid,
            }
            if found_state is not None:
                vals["found_state"] = found_state
            elif not rec.found_state:
                vals["found_state"] = rec.expected_state
            if found_location is not None:
                vals["found_location"] = found_location
            if physical_condition is not None:
                vals["physical_condition"] = physical_condition
            if notes is not None:
                vals["notes"] = notes
            rec.write(vals)
            rec._sync_high_impact_action_item()
        return True

    def _sync_high_impact_action_item(self):
        """Fire or close the stock_take_high_impact Action Centre
        alert based on the line's current state. Idempotency by
        the mixin: dedupes by (trigger_type, source_model, source_id)."""
        for rec in self.sudo():
            if (rec.has_discrepancy
                    and rec.is_high_impact
                    and not rec.resolved):
                rec._action_centre_create_item("stock_take_high_impact")
            else:
                # Auto-close uses force=True because the trigger
                # config carries item_type='task' and the mixin's
                # default close only fires for alerts — same shape
                # P5.M6 transfer flow established.
                rec._action_centre_close_items(
                    "stock_take_high_impact", force=True)

    def action_resolve(self, notes=None):
        for rec in self:
            if not rec.has_discrepancy:
                raise UserError(_(
                    "Line %(name)s has no discrepancy to resolve."
                ) % {"name": rec.display_name})
            rec.write({
                "resolved": True,
                "resolved_at": fields.Datetime.now(),
                "resolved_by_id": self.env.uid,
                "resolution_notes": notes or rec.resolution_notes,
            })
            rec._sync_high_impact_action_item()
        return True

    # ============================================================
    # === write() — re-run high-impact sync on attestation /
    # resolution-relevant edits. Keeps the Action Centre item in
    # sync if a user edits found_state etc. after first attestation.
    # ============================================================
    def write(self, vals):
        res = super().write(vals)
        sync_triggers = {
            "attested", "found_state", "found_location",
            "physical_condition", "resolved"}
        if sync_triggers & set(vals.keys()):
            for rec in self.filtered(lambda l: l.attested):
                rec._sync_high_impact_action_item()
        return res
