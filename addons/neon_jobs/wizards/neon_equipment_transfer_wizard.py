# -*- coding: utf-8 -*-
"""P5.M6 — Equipment transfer wizard.

Initiates a cross-event transfer of N units from a source event_job
to a destination event_job. Authority is enforced on the source
model (commercial.event.job._initiate_transfer); the wizard is just
UI collection. action_confirm delegates to the source model so the
gate logic stays in one place.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Same definition as commercial_event_job._EVENT_JOB_TERMINAL_FOR_TRANSFER;
# duplicated here so the wizard view's domain can reference a static
# tuple at view-arch time without importing across model files.
_DESTINATION_BLOCKED_STATES = (
    "cancelled", "released", "completed", "closed")


class NeonEquipmentTransferWizard(models.TransientModel):
    _name = "neon.equipment.transfer.wizard"
    _description = "Initiate Equipment Transfer"

    source_event_job_id = fields.Many2one(
        "commercial.event.job",
        string="From",
        required=True,
        readonly=True,
    )
    candidate_unit_ids = fields.Many2many(
        "neon.equipment.unit",
        compute="_compute_candidate_unit_ids",
        string="Available Units",
    )
    unit_ids = fields.Many2many(
        "neon.equipment.unit",
        "neon_equipment_transfer_wizard_unit_rel",
        "wizard_id", "unit_id",
        string="Units to Transfer",
    )
    destination_event_job_id = fields.Many2one(
        "commercial.event.job",
        string="To",
        required=True,
        domain="[('id', '!=', source_event_job_id),"
        " ('state', 'not in', %s)]" % (
            list(_DESTINATION_BLOCKED_STATES),),
    )
    notes = fields.Text(
        help="Optional context for the transfer — handover "
        "instructions, gear quirks, etc.",
    )

    @api.depends("source_event_job_id")
    def _compute_candidate_unit_ids(self):
        Unit = self.env["neon.equipment.unit"]
        Reservation = self.env["neon.equipment.reservation"].sudo()
        for rec in self:
            if not rec.source_event_job_id:
                rec.candidate_unit_ids = False
                continue
            # Units in 'checked_out' state on this source event_job.
            # Derived via the fulfilled reservation linking unit ↔
            # event_job (unit has no direct event_job pointer).
            fulfilled = Reservation.search([
                ("event_job_id", "=", rec.source_event_job_id.id),
                ("state", "=", "fulfilled"),
            ])
            unit_ids = fulfilled.mapped("unit_id").filtered(
                lambda u: u.state == "checked_out").ids
            rec.candidate_unit_ids = Unit.browse(unit_ids)

    def action_confirm(self):
        self.ensure_one()
        if not self.unit_ids:
            raise UserError(_(
                "Select at least one unit to transfer."))
        # Authority + atomicity live on the source event_job. The
        # wizard is a thin UI layer.
        self.source_event_job_id._initiate_transfer(
            units=self.unit_ids,
            destination=self.destination_event_job_id,
        )
        return {"type": "ir.actions.act_window_close"}
