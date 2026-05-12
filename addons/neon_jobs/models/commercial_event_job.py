# -*- coding: utf-8 -*-
"""
P3.M1 — Event Job model. The operational execution layer that turns
a Confirmed commercial.job into a delivered event: people, gear,
times, dispatch, on-site execution, return, closeout.

Auto-created when commercial.job state moves to 'active' (see
commercial.job.write() hook). Lead Tech can flag
has_operational_scope=False for quote-only orders that don't need
execution. State machine (P3.M3) and Readiness Score compute
(P3.M4) land in subsequent milestones; this milestone establishes
the schema, security, and basic UI only.
"""
from odoo import _, api, fields, models


_EVENT_JOB_STATES = [
    ("draft", "Draft"),
    ("planning", "Planning"),
    ("prep", "Prep"),
    ("ready_for_dispatch", "Ready for Dispatch"),
    ("dispatched", "Dispatched"),
    ("in_progress", "In Progress"),
    ("strike", "Strike"),
    ("returned", "Returned"),
    ("completed", "Completed"),
    ("closed", "Closed"),
    ("cancelled", "Cancelled"),
    ("released", "Released"),
]


class CommercialEventJob(models.Model):
    _name = "commercial.event.job"
    _description = "Event Job — operational execution layer (Phase 3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "event_date desc, name desc"

    # === Identity ===
    name = fields.Char(
        string="Event Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    commercial_job_id = fields.Many2one(
        "commercial.job",
        string="Commercial Job",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    has_operational_scope = fields.Boolean(
        string="Has Operational Scope",
        default=True,
        tracking=True,
        help="Uncheck for quote-only orders that don't need crew or "
        "equipment execution. Lead Tech sets this when reviewing the "
        "auto-created event job after the commercial job is activated.",
    )
    active = fields.Boolean(default=True)

    # === Related from commercial.job (denormalised for filtering) ===
    partner_id = fields.Many2one(
        related="commercial_job_id.partner_id",
        string="Client",
        store=True,
        readonly=True,
    )
    event_date = fields.Date(
        related="commercial_job_id.event_date",
        store=True,
        readonly=True,
    )
    event_end_date = fields.Date(
        related="commercial_job_id.event_end_date",
        store=True,
        readonly=True,
    )
    venue_id = fields.Many2one(
        related="commercial_job_id.venue_id",
        string="Venue",
        store=True,
        readonly=True,
    )
    venue_room_id = fields.Many2one(
        related="commercial_job_id.venue_room_id",
        string="Room",
        store=True,
        readonly=True,
    )

    # === Operational state ===
    state = fields.Selection(
        _EVENT_JOB_STATES,
        string="State",
        default="draft",
        required=True,
        tracking=True,
        help="Operational lifecycle of the event execution. "
        "State transitions and authority rules land in P3.M3.",
    )

    # === Operational owners ===
    lead_tech_id = fields.Many2one(
        "res.users",
        string="Lead Tech",
        tracking=True,
        help="Designated Lead Tech. Required once state has moved past "
        "draft (enforced in P3.M3).",
    )
    crew_chief_id = fields.Many2one(
        "res.users",
        string="Crew Chief",
        compute="_compute_crew_chief",
        store=True,
        help="Per-event chief, derived from the commercial.job.crew "
        "assignment flagged is_crew_chief. May be the Lead Tech "
        "themselves for smaller events.",
    )

    # === Readiness Score (P3.M4 will compute these) ===
    readiness_score = fields.Float(string="Readiness Score", default=0.0)
    readiness_dimension_finance = fields.Float(string="Readiness — Finance", default=0.0)
    readiness_dimension_equipment = fields.Float(string="Readiness — Equipment", default=0.0)
    readiness_dimension_crew = fields.Float(string="Readiness — Crew", default=0.0)
    readiness_dimension_schedule_venue = fields.Float(
        string="Readiness — Schedule/Venue", default=0.0)
    readiness_dimension_checklist = fields.Float(string="Readiness — Checklist", default=0.0)
    readiness_dimension_risk = fields.Float(string="Readiness — Risk", default=0.0)

    # === Equipment (placeholder for Phase 5 integration) ===
    equipment_summary = fields.Text(
        string="Equipment Summary",
        help="Free-form for now; Phase 5 introduces per-item movement "
        "records linked to event_job.",
    )
    equipment_count = fields.Integer(
        related="commercial_job_id.equipment_count",
        readonly=True,
    )
    sub_hire_required = fields.Boolean(
        related="commercial_job_id.sub_hire_required",
        readonly=True,
    )
    logistics_flag = fields.Boolean(
        related="commercial_job_id.logistics_flag",
        readonly=True,
    )

    # === Operational notes ===
    lead_tech_notes = fields.Text(string="Lead Tech Notes")
    crew_observations = fields.Text(string="Crew Observations")
    client_feedback = fields.Text(string="Client Feedback")
    incidents_log = fields.Text(
        string="Incidents Log",
        help="Free-form incident notes. Phase 4 replaces this with a "
        "structured incident model.",
    )

    # === Closeout checkpoints (P3.M7 will expand) ===
    gear_reconciled = fields.Boolean(default=False, tracking=True)
    finance_handoff_complete = fields.Boolean(default=False, tracking=True)
    closeout_completed_at = fields.Datetime(
        string="Closeout Completed At",
        readonly=True,
    )

    @api.depends("commercial_job_id.crew_assignment_ids.is_crew_chief",
                 "commercial_job_id.crew_assignment_ids.user_id")
    def _compute_crew_chief(self):
        for rec in self:
            if not rec.commercial_job_id:
                rec.crew_chief_id = False
                continue
            chief = rec.commercial_job_id.crew_assignment_ids.filtered(
                lambda c: c.is_crew_chief
            )[:1]
            rec.crew_chief_id = chief.user_id if chief else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.event.job")
                    or _("New")
                )
        return super().create(vals_list)

    # ============================================================
    # === Smart-button navigation back to source
    # ============================================================
    def action_open_commercial_job(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Commercial Job"),
            "res_model": "commercial.job",
            "view_mode": "form",
            "res_id": self.commercial_job_id.id,
            "target": "current",
        }
