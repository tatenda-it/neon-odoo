# -*- coding: utf-8 -*-
"""P5.M5 — Unit allocation wizard.

Surfaces available units for a planned equipment line so the user
can hand-pick which physical units to bind. Programmatic allocation
also exists on the line itself (action_allocate_units) for smoke
tests and any automation flow — the wizard delegates to that path
once the user has confirmed a selection.

Atomic-clarity rule: len(selected_unit_ids) must equal the line's
quantity_remaining. Partial allocations create harder-to-reason-
about line states; the user can re-open the wizard to allocate
the rest after a first pass.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonEquipmentAllocateWizard(models.TransientModel):
    _name = "neon.equipment.allocate.wizard"
    _description = "Allocate Equipment Units to a Line"

    equipment_line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Line",
        required=True,
        readonly=True,
    )
    event_job_id = fields.Many2one(
        related="equipment_line_id.event_job_id",
        readonly=True,
    )
    product_template_id = fields.Many2one(
        related="equipment_line_id.product_template_id",
        readonly=True,
    )
    quantity_remaining = fields.Integer(
        related="equipment_line_id.quantity_remaining",
        readonly=True,
    )
    available_unit_ids = fields.Many2many(
        "neon.equipment.unit",
        compute="_compute_available_unit_ids",
        string="Available Units",
    )
    selected_unit_ids = fields.Many2many(
        "neon.equipment.unit",
        "neon_equipment_allocate_wizard_selected_rel",
        "wizard_id", "unit_id",
        string="Selected Units",
        help="Pick units to bind to this line's soft_hold reservations.",
    )

    @api.depends("equipment_line_id")
    def _compute_available_unit_ids(self):
        for rec in self:
            line = rec.equipment_line_id
            if not line:
                rec.available_unit_ids = False
                continue
            # Defer to the line's own helper so wizard and
            # programmatic paths see identical availability.
            rec.available_unit_ids = line._find_available_units(
                count=10_000)  # large cap — wizard shows all candidates

    def action_confirm(self):
        self.ensure_one()
        line = self.equipment_line_id
        remaining = line.quantity_remaining
        if len(self.selected_unit_ids) != remaining:
            raise UserError(_(
                "Select exactly %(need)d unit(s); you selected "
                "%(got)d. Atomic allocation requires the count to "
                "match the line's remaining quantity."
            ) % {"need": remaining, "got": len(self.selected_unit_ids)})
        line.action_allocate_units(units=self.selected_unit_ids)
        return {"type": "ir.actions.act_window_close"}
