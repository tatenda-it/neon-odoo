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
from odoo.exceptions import UserError


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

_TERMINAL_STATES = ("cancelled", "released")

# P3.M3 — transition spec table. Each forward transition lists:
#   from:             tuple of source states (only one in practice today)
#   groups:           which Neon Operations group keys may trigger it
#   crew_chief_path:  whether the user can alternatively trigger this
#                     transition by being the crew_chief on the linked job
# Gates (readiness/closeout/lead_tech/crew_chief presence) are evaluated
# per-action since they need access to record fields.
_GROUP_XMLIDS = {
    "user": "neon_jobs.group_neon_jobs_user",
    "crew_leader": "neon_jobs.group_neon_jobs_crew_leader",
    "manager": "neon_jobs.group_neon_jobs_manager",
}
_TRANSITIONS = {
    "planning":           {"from": ("draft",),              "groups": ("user", "crew_leader", "manager"), "crew_chief_path": False},
    "prep":               {"from": ("planning",),           "groups": ("crew_leader", "manager"),         "crew_chief_path": False},
    "ready_for_dispatch": {"from": ("prep",),               "groups": ("crew_leader", "manager"),         "crew_chief_path": False},
    "dispatched":         {"from": ("ready_for_dispatch",), "groups": ("crew_leader", "manager"),         "crew_chief_path": False},
    "in_progress":        {"from": ("dispatched",),         "groups": ("crew_leader", "manager"),         "crew_chief_path": True},
    "strike":             {"from": ("in_progress",),        "groups": ("crew_leader", "manager"),         "crew_chief_path": True},
    "returned":           {"from": ("strike",),             "groups": ("crew_leader", "manager"),         "crew_chief_path": True},
    "completed":          {"from": ("returned",),           "groups": ("crew_leader", "manager"),         "crew_chief_path": False},
    "closed":             {"from": ("completed",),          "groups": ("manager",),                       "crew_chief_path": False},
}


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

    # === P3.M3 — state-machine UI gates ===
    # One Boolean per forward transition + cancel + release. Drives the
    # header buttons' invisible=... attributes. Non-stored; recomputed
    # per request from state + role + gating fields.
    can_move_to_planning = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_prep = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_ready_for_dispatch = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_dispatched = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_in_progress = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_strike = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_returned = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_completed = fields.Boolean(compute="_compute_state_buttons")
    can_move_to_closed = fields.Boolean(compute="_compute_state_buttons")
    can_cancel = fields.Boolean(compute="_compute_state_buttons")
    can_release = fields.Boolean(compute="_compute_state_buttons")

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

    # ============================================================
    # === P3.M3 — State machine
    #
    # Direct state writes via .write({"state": ...}) are blocked unless
    # the caller passes context={"_allow_state_write": True}. All
    # transitions must flow through action_move_to_<state> /
    # action_cancel_event_job / action_release_event_job so the chatter
    # audit and gates run consistently.
    # ============================================================
    def _user_in_any_group(self, group_keys):
        return any(
            self.env.user.has_group(_GROUP_XMLIDS[k]) for k in group_keys
        )

    def _is_crew_chief_of_job(self, commercial_job):
        if not commercial_job:
            return False
        return bool(self.env["commercial.job.crew"].sudo().search([
            ("job_id", "=", commercial_job.id),
            ("user_id", "=", self.env.uid),
            ("is_crew_chief", "=", True),
        ], limit=1))

    def _check_authority(self, target_state, raise_on_fail=True):
        """Authority check for a forward transition. Returns True if
        the calling user may move this record into target_state.
        Raises UserError when raise_on_fail=True and the check fails."""
        self.ensure_one()
        spec = _TRANSITIONS.get(target_state)
        if spec is None:
            if raise_on_fail:
                raise UserError(_(
                    "Unknown transition target: %s."
                ) % target_state)
            return False
        if self.state not in spec["from"]:
            if raise_on_fail:
                raise UserError(_(
                    "Cannot move from %(from)s to %(to)s. Allowed "
                    "source state(s) for %(to)s: %(allowed)s."
                ) % {
                    "from": self.state,
                    "to": target_state,
                    "allowed": ", ".join(spec["from"]),
                })
            return False
        in_group = self._user_in_any_group(spec["groups"])
        is_crew_chief = (
            spec.get("crew_chief_path")
            and self._is_crew_chief_of_job(self.commercial_job_id)
        )
        if not (in_group or is_crew_chief):
            if raise_on_fail:
                allowed = ", ".join(spec["groups"])
                if spec.get("crew_chief_path"):
                    allowed += ", or Crew Chief on this event"
                raise UserError(_(
                    "Only %(allowed)s can move an Event Job to "
                    "%(target)s."
                ) % {"allowed": allowed, "target": target_state})
            return False
        return True

    def _do_transition(self, target):
        """Apply the transition: bypass write-block via context flag,
        set closeout_completed_at if moving to 'closed', post chatter.

        The actual write is elevated via sudo() because crew tier can
        legitimately trigger some transitions (via crew_chief_path) but
        only has read ACL on commercial.event.job. Authority was just
        verified in the calling action method, so the elevation is
        safe. Chatter attribution stays with the real user via
        author_id.
        """
        self.ensure_one()
        old = self.state
        user_partner_id = self.env.user.partner_id.id
        user_name = self.env.user.name
        vals = {"state": target}
        if target == "closed":
            vals["closeout_completed_at"] = fields.Datetime.now()
        self.sudo().with_context(_allow_state_write=True).write(vals)
        self.sudo().message_post(
            body=_(
                "State: %(old)s → %(new)s by %(user)s"
            ) % {"old": old, "new": target, "user": user_name},
            author_id=user_partner_id,
        )

    @api.depends("state", "lead_tech_id", "crew_chief_id",
                 "gear_reconciled", "finance_handoff_complete",
                 "readiness_score", "commercial_job_id")
    @api.depends_context("uid")
    def _compute_state_buttons(self):
        for rec in self:
            # Reset all to False
            rec.can_move_to_planning = False
            rec.can_move_to_prep = False
            rec.can_move_to_ready_for_dispatch = False
            rec.can_move_to_dispatched = False
            rec.can_move_to_in_progress = False
            rec.can_move_to_strike = False
            rec.can_move_to_returned = False
            rec.can_move_to_completed = False
            rec.can_move_to_closed = False
            rec.can_cancel = False
            rec.can_release = False

            # Forward transitions
            for target, spec in _TRANSITIONS.items():
                if rec.state not in spec["from"]:
                    continue
                if not rec._check_authority(target, raise_on_fail=False):
                    continue
                # Per-target gate checks
                if target == "planning" and not rec.lead_tech_id:
                    continue
                if target == "dispatched" and not (rec.crew_chief_id and rec.lead_tech_id):
                    continue
                if target == "closed" and not (rec.gear_reconciled and rec.finance_handoff_complete):
                    continue
                # readiness gate (P3.M4 placeholder — see action method)
                setattr(rec, "can_move_to_" + target, True)

            # Terminal transitions (manager only, from any non-terminal)
            is_mgr = rec.env.user.has_group(_GROUP_XMLIDS["manager"])
            if is_mgr and rec.state not in _TERMINAL_STATES:
                rec.can_cancel = True
                rec.can_release = True

    # ============================================================
    # === Action methods — one per forward transition
    # ============================================================
    def action_move_to_planning(self):
        for rec in self:
            rec._check_authority("planning")
            if not rec.lead_tech_id:
                raise UserError(_(
                    "Lead Tech must be assigned before moving to Planning. "
                    "Set the Lead Tech on the People tab first."
                ))
            rec._do_transition("planning")

    def action_move_to_prep(self):
        for rec in self:
            rec._check_authority("prep")
            rec._do_transition("prep")

    def action_move_to_ready_for_dispatch(self):
        for rec in self:
            rec._check_authority("ready_for_dispatch")
            # P3.M4 will enforce readiness_score >= 70 as a hard block.
            # Until then, log a warning when the score is below the
            # eventual threshold so the audit trail captures it.
            if rec.readiness_score < 70:
                rec.message_post(body=_(
                    "Note: Readiness Score gate at 70 not yet enforced "
                    "(P3.M4 placeholder). Proceeded with "
                    "readiness_score=%s."
                ) % rec.readiness_score)
            rec._do_transition("ready_for_dispatch")

    def action_move_to_dispatched(self):
        for rec in self:
            rec._check_authority("dispatched")
            missing = []
            if not rec.crew_chief_id:
                missing.append(_("Crew Chief must be assigned (mark "
                                 "one crew member as Crew Chief on the "
                                 "Commercial Job's Crew tab)"))
            if not rec.lead_tech_id:
                missing.append(_("Lead Tech must be assigned"))
            if missing:
                raise UserError("\n".join(missing))
            rec._do_transition("dispatched")

    def action_move_to_in_progress(self):
        for rec in self:
            rec._check_authority("in_progress")
            rec._do_transition("in_progress")

    def action_move_to_strike(self):
        for rec in self:
            rec._check_authority("strike")
            rec._do_transition("strike")

    def action_move_to_returned(self):
        for rec in self:
            rec._check_authority("returned")
            rec._do_transition("returned")

    def action_move_to_completed(self):
        for rec in self:
            rec._check_authority("completed")
            rec._do_transition("completed")

    def action_move_to_closed(self):
        for rec in self:
            rec._check_authority("closed")
            missing = []
            if not rec.gear_reconciled:
                missing.append(_("Gear Reconciled"))
            if not rec.finance_handoff_complete:
                missing.append(_("Finance Handoff Complete"))
            if missing:
                raise UserError(_(
                    "Cannot close Event Job — missing closeout "
                    "requirements: %s. (P3.M7 will expand the closeout "
                    "checklist.)"
                ) % ", ".join(missing))
            rec._do_transition("closed")

    def action_cancel_event_job(self):
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "Event Job is already in a terminal state (%s)."
                ) % rec.state)
            if not self.env.user.has_group(_GROUP_XMLIDS["manager"]):
                raise UserError(_("Only Managers can cancel an Event Job."))
            rec._do_transition("cancelled")

    def action_release_event_job(self):
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "Event Job is already in a terminal state (%s)."
                ) % rec.state)
            if not self.env.user.has_group(_GROUP_XMLIDS["manager"]):
                raise UserError(_("Only Managers can release an Event Job."))
            rec._do_transition("released")

    # ============================================================
    # === Write block — protect the audit trail
    # ============================================================
    def write(self, vals):
        if "state" in vals and not self.env.context.get("_allow_state_write"):
            # Allow no-op writes (state already equals target) for ORM
            # cache flushing edge cases. Block anything that would
            # actually change state without going through the action
            # methods.
            if any(rec.state != vals["state"] for rec in self):
                raise UserError(_(
                    "State must be changed via Event Job transition "
                    "action methods (Start Planning, Move to Prep, "
                    "etc.). Direct state writes are blocked to "
                    "preserve the audit trail."
                ))
        return super().write(vals)
