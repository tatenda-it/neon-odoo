# -*- coding: utf-8 -*-
"""P5.M8 — Ad-hoc stock take creation wizard.

Mirrors the allocate / transfer / checkin wizard pattern: thin UI
collector that delegates to a programmatic helper on the source
model (neon.equipment.stock.take._create_session). Optional
category and location filters narrow the unit set; the default
is "every workshop-floor unit" matching the weekly cron's scope.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonEquipmentStockTakeWizard(models.TransientModel):
    _name = "neon.equipment.stock.take.wizard"
    _description = "Ad-Hoc Stock Take Wizard"

    category_ids = fields.Many2many(
        "neon.equipment.category",
        "neon_equipment_stock_take_wizard_category_rel",
        "wizard_id", "category_id",
        string="Categories",
        help="Limit the session to these categories. Leave empty "
        "for all workshop-floor units.",
    )
    location_text = fields.Char(
        string="Location Contains",
        help="Optional substring filter on unit.workshop_location.",
    )
    scheduled_for = fields.Date(
        string="Scheduled For",
        required=True,
        default=fields.Date.context_today,
    )
    candidate_count = fields.Integer(
        compute="_compute_candidate_count",
        string="Matching Units",
    )

    @api.depends("category_ids", "location_text")
    def _compute_candidate_count(self):
        from ..models.neon_equipment_stock_take import (
            _AUDITABLE_UNIT_STATES,
        )
        Unit = self.env["neon.equipment.unit"].sudo()
        for rec in self:
            domain = [("state", "in", list(_AUDITABLE_UNIT_STATES))]
            if rec.category_ids:
                domain.append(
                    ("equipment_category_id", "in",
                     rec.category_ids.ids))
            if rec.location_text:
                domain.append(
                    ("workshop_location", "ilike", rec.location_text))
            rec.candidate_count = Unit.search_count(domain)

    def action_confirm(self):
        self.ensure_one()
        if self.candidate_count == 0:
            raise UserError(_(
                "No workshop-floor units match the filters. Adjust "
                "the categories / location or clear the filters."))
        session = self.env["neon.equipment.stock.take"]._create_session(
            session_type="ad_hoc",
            scheduled_for=self.scheduled_for,
            category_ids=self.category_ids,
            location_text=self.location_text,
        )
        return {
            "type": "ir.actions.act_window",
            "name": session.name,
            "res_model": "neon.equipment.stock.take",
            "res_id": session.id,
            "view_mode": "form",
            "target": "current",
        }
