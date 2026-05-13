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
from datetime import timedelta

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

# P3.M4 — readiness aggregation table. Weights total 1.0 per v4.1
# Q4. dim_field is the stored Float on the model that mirrors the
# individual score (0 when N/A, so the form has something to show).
# Order is the order rendered in the Quality tab breakdown.
_READINESS_DIMENSIONS = (
    # key,             label,            weight, method,                          dim_field
    ("finance",        "Finance",        0.20, "_compute_dim_finance",            "readiness_dimension_finance"),
    ("equipment",      "Equipment",      0.25, "_compute_dim_equipment",          "readiness_dimension_equipment"),
    ("crew",           "Crew",           0.20, "_compute_dim_crew",               "readiness_dimension_crew"),
    ("schedule_venue", "Schedule/Venue", 0.15, "_compute_dim_schedule_venue",     "readiness_dimension_schedule_venue"),
    ("checklist",      "Checklist",      0.10, "_compute_dim_checklist",          "readiness_dimension_checklist"),
    ("risk",           "Risk",           0.10, "_compute_dim_risk",               "readiness_dimension_risk"),
)
# P3.M4 — readiness_state derivation thresholds (Q5).
_READINESS_STATE_THRESHOLDS = (
    (90.0, "ready"),
    (70.0, "watchlist"),
    (50.0, "at_risk"),
)
_READINESS_PASS_THRESHOLD = 70.0
_READINESS_OVERRIDE_GROUPS = ("crew_leader", "manager")


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
        default=lambda self: self._default_lead_tech_id(),
        tracking=True,
        help="Designated Lead Tech. Required once state has moved past "
        "draft (enforced in P3.M3). Auto-defaults to the first active "
        "user in neon_jobs.group_neon_jobs_crew_leader at create time, "
        "so personnel changes don't need code edits.",
    )

    @api.model
    def _default_lead_tech_id(self):
        """Pick the current Lead Tech / Crew Leader at create time.

        Dynamic group lookup rather than a hardcoded user id, so when
        the role moves between people (Ranganai today, somebody else
        tomorrow) the model picks up the new person automatically.
        Returns False gracefully if no crew_leader user exists yet —
        the field remains required at the state machine level
        (draft → planning), not at create.
        """
        group = self.env.ref(
            "neon_jobs.group_neon_jobs_crew_leader",
            raise_if_not_found=False,
        )
        if not group:
            return False
        user = self.env["res.users"].search(
            [("groups_id", "in", group.id), ("active", "=", True)],
            limit=1,
            order="id asc",
        )
        return user.id if user else False
    crew_chief_id = fields.Many2one(
        "res.users",
        string="Crew Chief",
        compute="_compute_crew_chief",
        store=True,
        help="Per-event chief, derived from the commercial.job.crew "
        "assignment flagged is_crew_chief. May be the Lead Tech "
        "themselves for smaller events.",
    )

    # === Readiness Score (P3.M4 — 6 weighted dimensions, proportional rescale) ===
    # All 10 readiness fields share one compute (_compute_readiness_score)
    # so the math runs in a single pass and the form never shows a stale
    # aggregate vs. its components.
    readiness_score = fields.Float(
        string="Readiness Score",
        compute="_compute_readiness_score",
        store=True,
        help="Weighted aggregate of 6 dimensions, rescaled to 100% "
        "across the dimensions whose data is currently available.",
    )
    readiness_dimension_finance = fields.Float(
        string="Readiness — Finance",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_dimension_equipment = fields.Float(
        string="Readiness — Equipment",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_dimension_crew = fields.Float(
        string="Readiness — Crew",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_dimension_schedule_venue = fields.Float(
        string="Readiness — Schedule/Venue",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_dimension_checklist = fields.Float(
        string="Readiness — Checklist",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_dimension_risk = fields.Float(
        string="Readiness — Risk",
        compute="_compute_readiness_score",
        store=True,
    )
    readiness_state = fields.Selection(
        [
            ("ready", "Ready"),
            ("watchlist", "Watchlist"),
            ("at_risk", "At Risk"),
            ("not_ready", "Not Ready"),
        ],
        string="Readiness State",
        compute="_compute_readiness_score",
        store=True,
        help="Derived from readiness_score: >=90 ready, >=70 "
        "watchlist, >=50 at_risk, <50 not_ready.",
    )
    readiness_dimensions_available = fields.Char(
        string="Dimensions Contributing",
        compute="_compute_readiness_score",
        store=True,
        help="Comma-separated list of dimensions whose data is "
        "currently available. The aggregate score is rescaled to "
        "100% across this subset (proportional rescale).",
    )
    readiness_breakdown = fields.Text(
        string="Readiness Breakdown",
        compute="_compute_readiness_score",
        store=True,
        help="Human-readable per-dimension explanation for the "
        "current Readiness Score.",
    )

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

    # === P3.M5 — Checklists (9 instances per event_job) ===
    checklist_ids = fields.One2many(
        "commercial.event.job.checklist",
        "event_job_id",
        string="Checklists",
    )

    # === P3.M6 — Scope Changes ===
    scope_change_ids = fields.One2many(
        "commercial.scope.change",
        "event_job_id",
        string="Scope Changes",
    )
    scope_change_count = fields.Integer(
        string="Scope Change Count",
        compute="_compute_scope_change_count",
    )

    def _compute_scope_change_count(self):
        for rec in self:
            rec.scope_change_count = len(rec.scope_change_ids)

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
    can_move_to_ready_for_dispatch_with_override = fields.Boolean(compute="_compute_state_buttons")
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
        records = super().create(vals_list)
        # P3.M5 — eagerly create one checklist instance per type
        # (snapshotting from each template's items) so the event_job
        # opens with its 9 checklists already populated.
        for rec in records:
            rec._create_event_job_checklists()
        return records

    def _create_event_job_checklists(self):
        """Idempotent: if instances already exist for this event_job,
        skip. Otherwise loop the 9 templates by type, copy items
        into instance items (snapshotting name/sequence/photo_required).
        Runs sudo because crew-tier auto-creation paths may not have
        write access on the new template models."""
        from .commercial_checklist_template import (
            CHECKLIST_TYPE_ORDER, CHECKLIST_TYPE_TO_ROLE,
        )
        ChecklistModel = self.env["commercial.event.job.checklist"].sudo()
        ItemModel = self.env["commercial.event.job.checklist.item"].sudo()
        TemplateModel = self.env["commercial.checklist.template"].sudo()
        for rec in self:
            if rec.checklist_ids:
                continue
            templates = {
                t.type: t
                for t in TemplateModel.search([("active", "=", True)])
            }
            for idx, ctype in enumerate(CHECKLIST_TYPE_ORDER):
                template = templates.get(ctype)
                instance = ChecklistModel.create({
                    "event_job_id": rec.id,
                    "type": ctype,
                    "template_id": template.id if template else False,
                    "ownership_role": CHECKLIST_TYPE_TO_ROLE.get(ctype, "lead_tech"),
                    "sequence": (idx + 1) * 10,
                })
                if template:
                    for ti in template.item_ids.filtered("active"):
                        ItemModel.create({
                            "checklist_id": instance.id,
                            "template_item_id": ti.id,
                            "sequence": ti.sequence,
                            "name": ti.name,
                            "photo_required": ti.photo_required,
                        })

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

    def action_open_scope_changes(self):
        """P3.M6 — smart-button entry into this event_job's scope
        changes, filtered to just this event_job's records."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Scope Changes"),
            "res_model": "commercial.scope.change",
            "view_mode": "tree,form,kanban",
            "domain": [("event_job_id", "=", self.id)],
            "context": {
                "default_event_job_id": self.id,
                "search_default_event_job_id": self.id,
            },
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
            rec.can_move_to_ready_for_dispatch_with_override = False
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
                # P3.M4 readiness hard gate. Below threshold the regular
                # button hides; the Override button surfaces instead.
                if target == "ready_for_dispatch" and rec.readiness_score < _READINESS_PASS_THRESHOLD:
                    continue
                setattr(rec, "can_move_to_" + target, True)

            # P3.M4 override path — only when the regular button is
            # suppressed by the score gate. Authority is the same as
            # the regular transition (crew_leader or manager).
            if (
                rec.state == "prep"
                and rec.readiness_score < _READINESS_PASS_THRESHOLD
                and rec._user_in_any_group(_READINESS_OVERRIDE_GROUPS)
            ):
                rec.can_move_to_ready_for_dispatch_with_override = True

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
            # P3.M4 — hard readiness gate. Below 70 the transition is
            # blocked; Manager / Crew Leader can override via
            # action_move_to_ready_for_dispatch_with_override.
            if rec.readiness_score < _READINESS_PASS_THRESHOLD:
                raise UserError(_(
                    "Readiness Score is %(score).1f, below the "
                    "%(threshold).0f threshold required to move to "
                    "Ready for Dispatch. Improve the score (confirm "
                    "crew, lock the venue, raise the deposit), or "
                    "use the 'Move to Ready (Override)' action — "
                    "requires Manager or Crew Leader."
                ) % {
                    "score": rec.readiness_score,
                    "threshold": _READINESS_PASS_THRESHOLD,
                })
            rec._do_transition("ready_for_dispatch")

    def action_move_to_ready_for_dispatch_with_override(self, reason):
        """P3.M4 override path. Manager or Crew Leader may move a
        prep-state Event Job to Ready for Dispatch even when the
        readiness gate is below threshold, provided a written reason.
        Reason is logged to chatter, attributed to the acting user.
        """
        if not reason or not str(reason).strip():
            raise UserError(_(
                "Override reason is required — the audit trail keeps "
                "a record of who accepted the risk and why."
            ))
        reason = str(reason).strip()
        for rec in self:
            rec._check_authority("ready_for_dispatch")
            if not rec._user_in_any_group(_READINESS_OVERRIDE_GROUPS):
                raise UserError(_(
                    "Only Managers or Crew Leaders can override the "
                    "Readiness Score gate."
                ))
            score = rec.readiness_score
            # Log the override BEFORE the transition so even if the
            # transition raised for some other reason, the audit trail
            # shows the attempt.
            rec.sudo().message_post(
                body=_(
                    "Readiness Override by %(user)s: "
                    "score=%(score).1f (below %(threshold).0f), "
                    "reason: %(reason)s"
                ) % {
                    "user": rec.env.user.name,
                    "score": score,
                    "threshold": _READINESS_PASS_THRESHOLD,
                    "reason": reason,
                },
                author_id=rec.env.user.partner_id.id,
            )
            rec._do_transition("ready_for_dispatch")
        return True

    def action_open_readiness_override_wizard(self):
        """UI entry: opens the override wizard so the user can capture
        their reason and confirm. Tests call the override action
        directly with a reason argument."""
        self.ensure_one()
        if self.state != "prep":
            raise UserError(_(
                "Readiness override only applies when the Event Job "
                "is in Prep state."
            ))
        if not self._user_in_any_group(_READINESS_OVERRIDE_GROUPS):
            raise UserError(_(
                "Only Managers or Crew Leaders can override the "
                "Readiness Score gate."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("Override Readiness Gate"),
            "res_model": "commercial.event.job.readiness.override.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_event_job_id": self.id},
        }

    def action_recompute_readiness(self):
        """Manual recompute escape hatch. Useful when underlying data
        that the depends graph can't track changes (other event_jobs'
        crew assignments feed the risk crew_gaps component)."""
        for rec in self:
            rec._populate_readiness()
        return True

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
    # === P3.M4 — Readiness Score
    #
    # Six dimensions, each contributes 0–100 to its weighted slot;
    # dimensions whose data isn't available yet return None and are
    # excluded from the aggregate (the remaining weights are scaled
    # back up to 100% — proportional rescale, v4.1 §Q5 wording).
    #
    # Per-dimension contract:
    #   dict {"score": float | None, "breakdown": str}
    #     score = None         → N/A, exclude from aggregate
    #     score 0..100         → contributes (score * weight)
    #   breakdown always populated for the Quality tab.
    # ============================================================
    def _compute_dim_finance(self):
        """Finance dimension. Deposit-ratio with finance_status modifier.
        Returns None when there is no quote to compare against — a
        zero-value 'job' usually means data has not been entered yet,
        and a zero score there would unfairly drag the aggregate
        down."""
        self.ensure_one()
        quoted = self.commercial_job_id.quoted_value or 0.0
        deposit = self.commercial_job_id.deposit_received or 0.0
        if quoted <= 0:
            return {
                "score": None,
                "breakdown": _("No quoted value on the Commercial Job — "
                               "Finance dimension cannot be evaluated."),
            }
        ratio = max(0.0, min(1.0, deposit / quoted))
        score = ratio * 100.0
        status = self.commercial_job_id.finance_status
        if status == "overdue":
            score -= 30.0
        elif status == "fully_paid":
            score += 30.0
        score = max(0.0, min(100.0, score))
        return {
            "score": score,
            "breakdown": _(
                "Deposit %(pct).0f%% of quote (%(deposit)s / %(quoted)s), "
                "finance_status=%(status)s"
            ) % {
                "pct": ratio * 100.0,
                "deposit": deposit,
                "quoted": quoted,
                "status": status or "—",
            },
        }

    def _compute_dim_equipment(self):
        """Equipment dimension. Phase 5 ships per-item readiness
        checks; until then, a non-empty equipment_summary is read as
        'data exists but unverified' (neutral 50pts). Empty summary
        returns N/A so it doesn't drag a fresh draft below threshold."""
        self.ensure_one()
        if self.equipment_summary and self.equipment_summary.strip():
            return {
                "score": 50.0,
                "breakdown": _(
                    "Equipment summary present — Phase 5 will replace "
                    "this with per-item readiness checks."
                ),
            }
        return {
            "score": None,
            "breakdown": _(
                "No equipment summary yet — N/A. Phase 5 ships the "
                "per-item readiness check that drives this dimension."
            ),
        }

    def _compute_dim_crew(self):
        """Crew dimension. Confirmation ratio + crew_chief + lead_tech
        bonuses. Zero crew assigned is genuinely Not Ready (score=0,
        not N/A) — by the time we're scoring an event, somebody should
        be assigned."""
        self.ensure_one()
        total = self.crew_total_count
        if total == 0:
            return {
                "score": 0.0,
                "breakdown": _("No crew assigned — confirmation ratio "
                               "is 0/0, dimension fails."),
            }
        confirmed = self.crew_confirmed_count
        score = (confirmed / total) * 100.0
        if self.crew_chief_id:
            score += 10.0
        if self.lead_tech_id:
            score += 10.0
        score = max(0.0, min(100.0, score))
        return {
            "score": score,
            "breakdown": _(
                "Crew %(conf)d/%(tot)d confirmed; crew_chief=%(chief)s; "
                "lead_tech=%(lead)s"
            ) % {
                "conf": confirmed,
                "tot": total,
                "chief": self.crew_chief_id.name if self.crew_chief_id else "—",
                "lead": self.lead_tech_id.name if self.lead_tech_id else "—",
            },
        }

    def _compute_dim_schedule_venue(self):
        """Schedule/Venue dimension. Future-date base, venue lock,
        room lock. Past event → 0 (the 'ready' concept is moot for an
        event that's already over)."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        event_date = self.event_date
        if not event_date:
            return {
                "score": 0.0,
                "breakdown": _("Event date is not set."),
            }
        if event_date < today:
            return {
                "score": 0.0,
                "breakdown": _(
                    "Event date %s is in the past — readiness concept "
                    "does not apply."
                ) % event_date,
            }
        score = 50.0
        bits = [_("event date %s set (in future)") % event_date]
        tbd = self.env.ref(
            "neon_jobs.partner_tbd_venue", raise_if_not_found=False
        )
        if self.venue_id and (not tbd or self.venue_id.id != tbd.id):
            score += 25.0
            bits.append(_("venue locked"))
        else:
            bits.append(_("venue is TBD / placeholder"))
        if self.venue_room_id:
            score += 25.0
            bits.append(_("room locked"))
        else:
            bits.append(_("no room"))
        return {
            "score": score,
            "breakdown": "; ".join(str(b) for b in bits),
        }

    def _compute_dim_checklist(self):
        """Checklist dimension (P3.M5). Average completion_ratio
        across the event_job's non-N/A checklists, scaled to 100.
        N/A checklists are excluded from the average so a 'this
        client_handover doesn't apply' decision steps out cleanly
        rather than boosting the score."""
        self.ensure_one()
        all_lists = self.checklist_ids
        if not all_lists:
            return {
                "score": None,
                "breakdown": _("No checklists on this event yet — N/A."),
            }
        active = all_lists.filtered(lambda c: c.state != "na")
        if not active:
            return {
                "score": None,
                "breakdown": _(
                    "All %d checklists marked N/A — dimension excluded."
                ) % len(all_lists),
            }
        avg_ratio = sum(c.completion_ratio for c in active) / len(active)
        score = avg_ratio * 100.0
        na_count = len(all_lists) - len(active)
        na_note = (" (%d N/A excluded)" % na_count) if na_count else ""
        return {
            "score": score,
            "breakdown": _(
                "Avg completion %(pct).0f%% across %(n)d active "
                "checklist(s)%(na)s"
            ) % {"pct": score, "n": len(active), "na": na_note},
        }

    # ----- Risk dimension — 6 components -----------------------------
    # b/c/e have real compute; a/d/f are N/A placeholders until their
    # underlying systems exist (incident model, weather integration,
    # Phase 5 equipment maintenance).
    def _risk_open_incidents(self):
        # Phase 4 introduces the structured incident model. Until then
        # there is no record to query.
        return (None, _("Open incidents: N/A (no incident model yet)"))

    def _risk_new_venue(self):
        self.ensure_one()
        if not self.venue_id:
            return (None, _("New venue: N/A (no venue on the job)"))
        tbd = self.env.ref(
            "neon_jobs.partner_tbd_venue", raise_if_not_found=False
        )
        if tbd and self.venue_id.id == tbd.id:
            return (None, _("New venue: N/A (venue is the TBD placeholder)"))
        prior = self.env["commercial.job"].sudo().search_count([
            ("venue_id", "=", self.venue_id.id),
            ("id", "!=", self.commercial_job_id.id),
        ])
        score = 100.0 if prior >= 1 else 0.0
        return (score, _(
            "New venue: %(n)d prior event(s) at %(v)s — %(verdict)s"
        ) % {
            "n": prior,
            "v": self.venue_id.name or "?",
            "verdict": "known venue" if prior >= 1 else "first-ever booking",
        })

    def _risk_new_client(self):
        self.ensure_one()
        if not self.partner_id:
            return (None, _("New client: N/A (no client on the job)"))
        prior = self.env["commercial.job"].sudo().search_count([
            ("partner_id", "=", self.partner_id.id),
            ("id", "!=", self.commercial_job_id.id),
        ])
        score = 100.0 if prior >= 1 else 0.0
        return (score, _(
            "New client: %(n)d prior job(s) for %(p)s — %(verdict)s"
        ) % {
            "n": prior,
            "p": self.partner_id.name or "?",
            "verdict": "established client" if prior >= 1 else "first job for this client",
        })

    def _risk_weather(self):
        # Outdoor-event weather alerts. No weather integration yet.
        return (None, _("Weather: N/A (no weather integration yet)"))

    def _risk_crew_gaps(self):
        """% days in the 7-day pre-event window where one of this
        event's confirmed crew is already booked on another event."""
        self.ensure_one()
        event_date = self.event_date
        if not event_date:
            return (None, _("Crew gaps: N/A (no event date)"))
        crew_users = self.commercial_job_id.crew_assignment_ids.filtered(
            lambda c: c.state == "confirmed"
        ).mapped("user_id")
        if not crew_users:
            return (None, _("Crew gaps: N/A (no confirmed crew yet)"))
        window_start = event_date - timedelta(days=7)
        window_end = event_date - timedelta(days=1)
        conflicting = self.env["commercial.job.crew"].sudo().search([
            ("user_id", "in", crew_users.ids),
            ("state", "=", "confirmed"),
            ("job_id", "!=", self.commercial_job_id.id),
            ("job_event_date", ">=", window_start),
            ("job_event_date", "<=", window_end),
        ])
        conflict_days = {a.job_event_date for a in conflicting}
        n_conflict = len(conflict_days)
        score = max(0.0, 100.0 - (n_conflict / 7.0 * 100.0))
        return (score, _(
            "Crew gaps: %(n)d/7 pre-event days with a conflicting "
            "confirmed assignment on another job"
        ) % {"n": n_conflict})

    def _risk_equipment_repair(self):
        # Phase 5 — flag equipment recently sent for repair.
        return (None, _("Equipment repair flags: N/A (Phase 5)"))

    _RISK_COMPONENTS = (
        ("open_incidents",  "_risk_open_incidents"),
        ("new_venue",       "_risk_new_venue"),
        ("new_client",      "_risk_new_client"),
        ("weather",         "_risk_weather"),
        ("crew_gaps",       "_risk_crew_gaps"),
        ("equipment_repair", "_risk_equipment_repair"),
    )

    def _compute_dim_risk(self):
        """Risk dimension. Average of available components. All six
        components N/A → whole dimension N/A."""
        self.ensure_one()
        rows = []
        scored = []
        for label, method_name in self._RISK_COMPONENTS:
            score, breakdown = getattr(self, method_name)()
            rows.append((label, score, breakdown))
            if score is not None:
                scored.append(score)
        if not scored:
            return {
                "score": None,
                "breakdown": _(
                    "Risk: all 6 components are placeholders awaiting "
                    "later phases."
                ),
            }
        avg = sum(scored) / len(scored)
        bits = [
            "%s=%s" % (
                label,
                "%.0f" % score if score is not None else "N/A",
            )
            for label, score, _bk in rows
        ]
        return {
            "score": avg,
            "breakdown": _(
                "Risk avg of %(n)d available component(s): %(detail)s"
            ) % {"n": len(scored), "detail": "; ".join(bits)},
        }

    # ----- Aggregator -------------------------------------------------
    @api.depends(
        "state",
        "commercial_job_id.quoted_value",
        "commercial_job_id.deposit_received",
        "commercial_job_id.finance_status",
        "commercial_job_id.crew_assignment_ids",
        "commercial_job_id.crew_assignment_ids.state",
        "commercial_job_id.crew_assignment_ids.is_crew_chief",
        "lead_tech_id",
        "crew_chief_id",
        "event_date",
        "venue_id",
        "venue_room_id",
        "equipment_summary",
        "partner_id",
        "checklist_ids.state",
        "checklist_ids.completion_ratio",
    )
    def _compute_readiness_score(self):
        for rec in self:
            rec._populate_readiness()

    def _populate_readiness(self):
        """Run all 6 dimensions, aggregate with proportional rescale,
        then write the 10 readiness fields in one pass.

        Split out from the @api.depends compute so the Recompute
        Readiness button can call it directly. The button case writes
        to DB; the depends case populates cache (Odoo decides which
        based on the calling stack)."""
        self.ensure_one()
        weighted_sum = 0.0
        available_weight = 0.0
        available_labels = []
        breakdown_lines = []
        dim_field_values = {}

        for key, label, weight, method_name, dim_field in _READINESS_DIMENSIONS:
            result = getattr(self, method_name)()
            score = result["score"]
            breakdown = result["breakdown"]
            pct = int(round(weight * 100))
            if score is None:
                dim_field_values[dim_field] = 0.0
                breakdown_lines.append(
                    "- %s (weight %d%%) — N/A: %s" % (label, pct, breakdown)
                )
                continue
            clamped = max(0.0, min(100.0, float(score)))
            dim_field_values[dim_field] = clamped
            weighted_sum += clamped * weight
            available_weight += weight
            available_labels.append(label)
            breakdown_lines.append(
                "- %s (weight %d%%): %.0f/100 — %s" % (
                    label, pct, clamped, breakdown,
                )
            )

        if available_weight > 0:
            aggregate = weighted_sum * (1.0 / available_weight)
        else:
            aggregate = 0.0
        aggregate = round(aggregate, 1)

        state = "not_ready"
        for threshold, name in _READINESS_STATE_THRESHOLDS:
            if aggregate >= threshold:
                state = name
                break

        for fname, fval in dim_field_values.items():
            self[fname] = fval
        self.readiness_score = aggregate
        self.readiness_state = state
        self.readiness_dimensions_available = (
            ", ".join(available_labels) if available_labels else ""
        )
        self.readiness_breakdown = "\n".join(breakdown_lines)

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
