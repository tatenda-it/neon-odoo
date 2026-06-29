# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ------------------------------------------------------------------
    # §7.1 intelligence fields (additive; complements native + x_lead_score)
    # ------------------------------------------------------------------
    neon_event_type = fields.Selection(
        [
            ("conference", "Conference"),
            ("awards_dinner", "Awards Dinner"),
            ("launch", "Product Launch"),
            ("expo", "Expo"),
            ("gala", "Gala"),
            ("church", "Church Event"),
            ("roadshow", "Roadshow"),
            ("summit", "Summit"),
            ("agm", "AGM"),
        ],
        string="Event Type",
    )
    neon_sector = fields.Selection(
        [
            ("corporate", "Corporate"),
            ("ngo", "NGO"),
            ("government", "Government"),
            ("social", "High-End Social"),
            ("religious", "Religious"),
            ("education", "Education"),
            ("other", "Other"),
        ],
        string="Sector",
    )
    neon_strategic_value = fields.Selection(
        [
            ("normal", "Normal"),
            ("high_profile", "High-Profile"),
            ("repeat_potential", "Repeat-Potential"),
            ("relationship_building", "Relationship-Building"),
        ],
        string="Strategic Value",
        default="normal",
    )
    # Companion to the existing x_lead_score (1-5). Score itself stays in 2B.
    neon_score_confidence = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")],
        string="Score Confidence",
    )
    neon_competitor_id = fields.Many2one(
        "neon.competitor",
        string="Competitor Mentioned",
        ondelete="set null",
        help="Structured replacement for free-text competitor capture.",
    )
    neon_play_id = fields.Many2one(
        "neon.play", string="Play Used", ondelete="set null"
    )
    neon_event_opportunity_id = fields.Many2one(
        "neon.event.opportunity", string="Event Opportunity", ondelete="set null"
    )
    neon_margin_estimate = fields.Monetary(
        string="Margin Estimate", currency_field="company_currency"
    )
    neon_commercial_quality = fields.Selection(
        [
            ("healthy", "Healthy"),
            ("marginal", "Marginal"),
            ("poor", "Poor"),
            ("unknown", "Unknown"),
        ],
        string="Commercial Quality",
        default="unknown",
    )
    neon_learning_note = fields.Text(string="Learning Note")
    # Extends native won/lost with the brief's fuller taxonomy.
    neon_outcome_tag = fields.Selection(
        [
            ("won", "Won"),
            ("lost", "Lost"),
            ("postponed", "Postponed"),
            ("recycled", "Recycled"),
            ("inactive", "Inactive"),
        ],
        string="Outcome Tag",
    )
    # Next-best-action type (pairs with native activity due dates).
    neon_next_action_type = fields.Selection(
        [
            ("call", "Call"),
            ("quote", "Quote"),
            ("whatsapp", "WhatsApp"),
            ("email", "Email"),
            ("meeting", "Meeting"),
            ("proposal", "Proposal"),
            ("follow_up", "Follow-up"),
        ],
        string="Next Action Type",
    )
    neon_next_action_date = fields.Date(string="Next Action Due")

    # ------------------------------------------------------------------
    # §19 data-quality gate engine (inert until a stage is configured)
    # ------------------------------------------------------------------
    def _neon_check_stage_gate(self, target_stage):
        """Raise if entering `target_stage` with required fields unset.
        No-op unless the stage has neon_gate_active and required fields set.
        """
        if not target_stage or not target_stage.neon_gate_active:
            return
        required = target_stage.neon_required_field_ids
        if not required:
            return
        for lead in self:
            missing = []
            for f in required:
                # Guard against a configured field that no longer exists.
                if f.name not in lead._fields:
                    continue
                if not lead[f.name]:
                    missing.append(f.field_description or f.name)
            if missing:
                raise ValidationError(_(
                    "Cannot move \"%(lead)s\" to stage \"%(stage)s\". "
                    "Required before this stage: %(fields)s.",
                    lead=lead.display_name,
                    stage=target_stage.name,
                    fields=", ".join(missing),
                ))

    def write(self, vals):
        if vals.get("stage_id"):
            target = self.env["crm.stage"].browse(vals["stage_id"])
            self._neon_check_stage_gate(target)
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.stage_id:
                rec._neon_check_stage_gate(rec.stage_id)
        return records
