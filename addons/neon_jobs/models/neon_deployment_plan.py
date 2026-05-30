# -*- coding: utf-8 -*-
"""P-B3 -- AI Deployment Plan.

Single-active-per-event model with revision history. Status walks:
  draft -> generated -> reviewed -> final
        \                   \
         \-------------------> superseded (via regenerate)

⚠️ DECISION (B3, D1): new model neon.deployment.plan in neon_jobs
(NOT extending event_job). One active plan per event; regenerate
spawns a new row with revision+1 and the previous moves to
superseded. perm_unlink=0 throughout -- audit-trail discipline.

⚠️ DECISION (B3, D2-D4): generation = Python fact-gather + Claude
narrative + Python validator. Every quantity / name / date in the
output is verified against the gathered facts. A plan that omits
or contradicts a known B2 deficit is REJECTED.

⚠️ DECISION (B3, D6): refuse to generate when event_job.state ==
'draft' -- mirrors B2-DM-2. Demand isn't authoritative until the
event leaves draft.

⚠️ DECISION (B3, D10 trim): no PDF render in this milestone --
on-screen plan_summary_html only. PDF is a fast follow.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


_logger = logging.getLogger(__name__)


_PLAN_STATUSES = [
    ("draft", "Draft"),
    ("generated", "Generated"),
    ("reviewed", "Reviewed"),
    ("final", "Final"),
    ("superseded", "Superseded"),
]

_TERMINAL = ("final", "superseded")


class NeonDeploymentPlan(models.Model):
    _name = "neon.deployment.plan"
    _description = "AI Deployment Plan (B3)"
    _inherit = ["mail.thread"]
    _order = "event_job_id, revision desc, id desc"

    # === Identity ===
    name = fields.Char(
        compute="_compute_name", store=True, readonly=True,
        index=True,
    )
    event_job_id = fields.Many2one(
        "commercial.event.job", required=True, index=True,
        ondelete="cascade", tracking=True,
    )
    revision = fields.Integer(
        required=True, default=1, readonly=True, tracking=True,
        help="Auto-incremented on regenerate. revision=1 is the "
             "first plan; the next regen creates revision=2 and "
             "the previous moves to 'superseded'.",
    )

    # === State machine ===
    status = fields.Selection(
        _PLAN_STATUSES, required=True, default="draft",
        readonly=True, tracking=True, index=True,
    )

    # === Audit timestamps + actors ===
    generated_at = fields.Datetime(readonly=True, tracking=True)
    generated_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    reviewed_at = fields.Datetime(readonly=True, tracking=True)
    reviewed_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    finalised_at = fields.Datetime(readonly=True, tracking=True)
    finalised_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    superseded_at = fields.Datetime(readonly=True, tracking=True)
    superseded_by_plan_id = fields.Many2one(
        "neon.deployment.plan", readonly=True, ondelete="set null",
        help="The newer plan that superseded this one.",
    )

    # === Snapshot of the B2 conflict the plan was generated from ===
    # Snapshot, not live -- so re-running the engine post-hoc doesn't
    # retroactively change what the plan was based on.
    source_conflict_id = fields.Many2one(
        "neon.equipment.conflict", readonly=True,
        ondelete="set null",
        help="The B2 conflict run consumed at generation. Snapshot "
             "pointer -- the plan does NOT live-read this; the "
             "facts at generation time are frozen in plan_json.",
    )
    source_conflict_window_start = fields.Datetime(readonly=True)
    source_conflict_window_end = fields.Datetime(readonly=True)

    # === Generated content ===
    plan_json = fields.Text(
        readonly=True,
        help="Strict-JSON Claude output, validated against the "
             "fact-gather. Stored verbatim.",
    )
    plan_summary_html = fields.Html(
        compute="_compute_plan_summary_html",
        store=True, readonly=True, sanitize=False,
        help="Rendered HTML view of plan_json. The on-screen render "
             "(D10 PDF trim deferred).",
    )
    data_quality_note = fields.Text(
        readonly=True,
        help="Carried verbatim from the B2 payload when load-in/out "
             "is imprecise. Banner above the plan on screen.",
    )

    # === B13 usage snapshot ===
    model_used = fields.Char(readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    latency_ms = fields.Integer(readonly=True)

    # === Error / quarantine state ===
    error_message = fields.Text(readonly=True)
    quarantine_json = fields.Text(
        readonly=True,
        help="On PlanValidationError, the Claude output that "
             "contradicted the facts is parked here for debugging. "
             "Never rendered to users.",
    )

    # === Helpers / display ===
    deficit_count = fields.Integer(
        compute="_compute_counts", store=True, readonly=True)
    is_active = fields.Boolean(
        compute="_compute_is_active", store=True, readonly=True,
        index=True,
        help="True when this plan is the CURRENT one for its event "
             "(not superseded). The UI's 'Deployment Plan' tab on "
             "the event_job uses this to pick which revision to "
             "show.",
    )

    _sql_constraints = [
        ("revision_positive",
         "CHECK (revision > 0)",
         "Plan revision must be a positive integer."),
        ("event_revision_unique",
         "UNIQUE (event_job_id, revision)",
         "A given event_job cannot have two plans with the same "
         "revision number."),
    ]

    # ============================================================
    # Computed
    # ============================================================
    @api.depends("event_job_id.name", "revision")
    def _compute_name(self):
        for rec in self:
            ev_name = (rec.event_job_id.name or "?")
            rec.name = "PLAN-{ev}-r{rev}".format(
                ev=ev_name, rev=rec.revision or 0)

    @api.depends("status")
    def _compute_is_active(self):
        for rec in self:
            rec.is_active = rec.status not in (
                "superseded",) and rec.status != "draft"
            # Note: draft plans are technically 'not active' for the
            # event_job UI tab (which shows the latest GENERATED or
            # later); superseded never shows.

    @api.depends("plan_json")
    def _compute_counts(self):
        import json as _json
        for rec in self:
            count = 0
            if rec.plan_json:
                try:
                    payload = _json.loads(rec.plan_json)
                    count = len(payload.get("deficits") or [])
                except (ValueError, TypeError):
                    count = 0
            rec.deficit_count = count

    @api.depends("plan_json", "data_quality_note", "status")
    def _compute_plan_summary_html(self):
        from .deployment_plan_renderer import (
            render_plan_summary_html,
        )
        for rec in self:
            rec.plan_summary_html = render_plan_summary_html(
                rec.plan_json, rec.data_quality_note,
                rec.status)

    # ============================================================
    # State-machine action buttons (form view)
    # ============================================================
    def action_mark_reviewed(self):
        """generated -> reviewed. Reviewer is the calling user."""
        for rec in self:
            if rec.status != "generated":
                raise UserError(_(
                    "Plan must be in 'Generated' state to mark as "
                    "reviewed. Current status: %(s)s"
                ) % {"s": rec.status})
            rec.sudo().write({
                "status": "reviewed",
                "reviewed_at": fields.Datetime.now(),
                "reviewed_by_id": self.env.uid,
            })
        return True

    def action_mark_final(self):
        """reviewed -> final. Locks the plan; regenerate first to
        replace."""
        for rec in self:
            if rec.status != "reviewed":
                raise UserError(_(
                    "Plan must be in 'Reviewed' state to mark as "
                    "final. Current status: %(s)s"
                ) % {"s": rec.status})
            rec.sudo().write({
                "status": "final",
                "finalised_at": fields.Datetime.now(),
                "finalised_by_id": self.env.uid,
            })
        return True

    def action_unfinalise(self):
        """final -> reviewed. Manager-only (form view's groups_id
        gates the button)."""
        for rec in self:
            if rec.status != "final":
                raise UserError(_(
                    "Plan must be Final to un-finalise. Current: "
                    "%(s)s") % {"s": rec.status})
            rec.sudo().write({
                "status": "reviewed",
                "finalised_at": False,
                "finalised_by_id": False,
            })
        return True

    def action_regenerate(self):
        """Create a new revision; mark this one superseded.
        Refuses if this plan is in 'final' (un-finalise first)."""
        self.ensure_one()
        if self.status == "final":
            raise UserError(_(
                "Un-finalise this plan first before regenerating. "
                "Final plans are locked."))
        from .deployment_plan_generator import (
            DeploymentPlanGenerator,
        )
        new_plan = DeploymentPlanGenerator(self.env).generate_for_event(
            self.event_job_id, replaces=self)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.deployment.plan",
            "res_id": new_plan.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def action_generate_for_event(self, event_job_id):
        """Smart-button entry point from the event_job form. If a
        non-superseded plan already exists, opens it. Otherwise
        generates a new one."""
        EvJ = self.env["commercial.event.job"]
        ev = EvJ.browse(int(event_job_id)).exists()
        if not ev:
            raise UserError(_(
                "Event job not found (id=%(i)s).") % {
                    "i": event_job_id})
        existing = self.search([
            ("event_job_id", "=", ev.id),
            ("status", "not in", ("superseded", "draft")),
        ], order="revision desc", limit=1)
        if existing:
            return {
                "type": "ir.actions.act_window",
                "res_model": "neon.deployment.plan",
                "res_id": existing.id,
                "view_mode": "form",
                "target": "current",
            }
        from .deployment_plan_generator import (
            DeploymentPlanGenerator,
        )
        new_plan = DeploymentPlanGenerator(self.env).generate_for_event(
            ev)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.deployment.plan",
            "res_id": new_plan.id,
            "view_mode": "form",
            "target": "current",
        }
