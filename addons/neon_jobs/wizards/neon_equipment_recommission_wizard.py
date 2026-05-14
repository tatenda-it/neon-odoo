# -*- coding: utf-8 -*-
"""
P5.M2 — Recommission wizard.

Captures the justification reason + target state when a manager
reverses a decommissioned (write-off) unit. The actual transition
walks through neon.equipment.unit._do_transition with
manager_override=True, which enforces the manager-group check and
the non-empty reason at the model layer. The wizard exists to
collect the inputs in a UI flow — it is not the security gate.
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class NeonEquipmentRecommissionWizard(models.TransientModel):
    _name = "neon.equipment.recommission.wizard"
    _description = "Recommission a Decommissioned Equipment Unit (Manager Override)"

    equipment_unit_id = fields.Many2one(
        "neon.equipment.unit",
        required=True,
        ondelete="cascade",
        readonly=True,
    )
    # Must stay in sync with MANAGER_BYPASS_TRANSITIONS['decommissioned']
    # in neon_equipment_unit.py — if that list expands, update here.
    target_state = fields.Selection(
        [
            ("active", "Active"),
            ("maintenance", "In Maintenance"),
        ],
        default="active",
        required=True,
        help="Where to send the unit. Active means it returns to "
        "the available pool; In Maintenance routes it straight to "
        "the repair queue.",
    )
    reason = fields.Text(
        required=True,
        help="Required. Logged to the unit's chatter with the "
        "transition. Be specific — this is the only record of why "
        "the write-off was reversed.",
    )

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_(
                "Reason is required to recommission a decommissioned "
                "unit."
            ))
        self.equipment_unit_id.action_recommission_with_override(
            reason=self.reason,
            target_state=self.target_state,
        )
        return {"type": "ir.actions.act_window_close"}
