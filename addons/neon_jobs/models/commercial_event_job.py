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

    # === P3.M2 — field groups per v4.1 §6 ===
    # Client tab
    partner_email = fields.Char(
        related="partner_id.email",
        string="Client Email",
        readonly=True,
    )
    partner_phone = fields.Char(
        related="partner_id.phone",
        string="Client Phone",
        readonly=True,
    )
    client_notes = fields.Text(
        string="Client Notes",
        help="Lead Tech captures client-specific instructions, "
        "preferences, sensitivities, VIP notes here.",
    )

    # Venue tab
    venue_access_notes = fields.Text(
        string="Venue Access Notes",
        help="Loading dock, lift dimensions, security desk, time "
        "restrictions on access.",
    )
    parking_arrangements = fields.Text(
        string="Parking Arrangements",
    )
    on_site_contact_id = fields.Many2one(
        "res.partner",
        string="On-site Contact",
        help="Venue or client contact present on the day. Phone "
        "number lives on the partner record.",
    )

    # Schedule tab
    prep_start_datetime = fields.Datetime(
        string="Prep Start",
        help="When the team starts staging gear at the workshop.",
    )
    dispatch_datetime = fields.Datetime(
        string="Dispatch Time",
        help="When the convoy leaves the workshop for the venue.",
    )
    strike_start_datetime = fields.Datetime(
        string="Strike Start",
        help="When the team starts breaking down at the venue.",
    )
    return_eta_datetime = fields.Datetime(
        string="Return ETA",
        help="Expected arrival back at the workshop.",
    )

    # Scope tab
    expected_attendee_count = fields.Integer(
        string="Expected Attendees",
        default=0,
        help="Headcount used for risk scoring (P3.M4) and crew size "
        "guidance.",
    )
    scope_complexity = fields.Selection(
        [
            ("simple", "Simple"),
            ("standard", "Standard"),
            ("complex", "Complex"),
        ],
        string="Scope Complexity",
        default="standard",
        help="Operational complexity classification. Drives risk and "
        "checklist gating (P3.M4 / P3.M5).",
    )

    # Finance tab (read-only mirrors of commercial.job money fields)
    quoted_value = fields.Monetary(
        related="commercial_job_id.quoted_value",
        string="Quoted Value",
        readonly=True,
        currency_field="currency_id",
    )
    deposit_received = fields.Monetary(
        related="commercial_job_id.deposit_received",
        string="Deposit Received",
        readonly=True,
        currency_field="currency_id",
    )
    finance_status = fields.Selection(
        related="commercial_job_id.finance_status",
        string="Finance Status",
        readonly=True,
    )
    currency_id = fields.Many2one(
        related="commercial_job_id.currency_id",
        readonly=True,
    )

    # People tab
    crew_total_count = fields.Integer(
        string="Crew Total",
        compute="_compute_crew_counts_for_event",
        help="Total crew on the linked commercial.job (incl. pending).",
    )
    crew_confirmed_count = fields.Integer(
        string="Crew Confirmed",
        compute="_compute_crew_counts_for_event",
    )

    @api.depends("commercial_job_id.crew_assignment_ids",
                 "commercial_job_id.crew_assignment_ids.state")
    def _compute_crew_counts_for_event(self):
        for rec in self:
            assignments = rec.commercial_job_id.crew_assignment_ids
            rec.crew_total_count = len(assignments)
            rec.crew_confirmed_count = len(
                assignments.filtered(lambda c: c.state == "confirmed")
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
