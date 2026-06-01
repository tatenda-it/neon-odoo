# -*- coding: utf-8 -*-
"""P-B5 -- Post-event reconciliation header.

Lifecycle: draft -> generated -> reviewed -> final.
`superseded` is a branch state set when a newer revision replaces
this one (mirror B3-D7 / B4-D8 single-active-with-revision-supersedes).

The reconciliation is the BACKWARD VIEW: deployment plan (B3) +
sub-hire (B4) were what we INTENDED to do; the reconciliation is
what ACTUALLY happened. Equipment returned + condition deltas, sub-
hires used, deficits that materialised, planned-vs-actual cost
variance (read-only).

⚠️ DECISION (B5, D1): new model neon.event.reconciliation in
neon_jobs (where B3 + B4 live). perm_unlink=0 (audit). Mirror
B3-D7 / B4-D8 supersede pattern.

⚠️ DECISION (B5, D2): post-event state gate -- refuse to generate
unless event_job.state in ('returned', 'completed', 'closed').
'returned' included because gear-back is the operational point we
have data for. Robin veto narrows to ('completed', 'closed').

⚠️ DECISION (B5, D4): READ-ONLY on money. Variance figures are
gathered from sudo() reads on neon.finance.quote +
neon.finance.cost.line and presented as information. B5 NEVER
posts to journals, modifies invoices, or touches any financial
transaction (RED rail held; posting is out of scope).

⚠️ DECISION (B5, D5): condition_status flips are flagged via
chatter + mail.activity on the workshop manager, never auto-
written. Equipment condition is a human/workshop action.

⚠️ DECISION (B5, D9): generation is LAZY -- no auto-trigger even
when the event hits 'completed'. Explicit "Generate Reconciliation"
button keeps the human in the loop.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


_RECON_STATUSES = [
    ("draft", "Draft"),
    ("generated", "Generated"),
    ("reviewed", "Reviewed"),
    ("final", "Final"),
    ("superseded", "Superseded"),
]


# Per gate-1 D2: events become eligible for reconciliation once the
# gear is physically back ('returned') or the event is closed out.
_POST_EVENT_STATES = ("returned", "completed", "closed")


class NeonEventReconciliation(models.Model):
    _name = "neon.event.reconciliation"
    _description = "Post-event reconciliation (B5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
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
             "first; next regen creates revision=2 and the prior "
             "moves to 'superseded'.",
    )

    # === Lifecycle ===
    status = fields.Selection(
        _RECON_STATUSES, required=True, default="draft",
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
    superseded_by_recon_id = fields.Many2one(
        "neon.event.reconciliation", readonly=True,
        ondelete="set null",
        help="The newer reconciliation that superseded this one.",
    )

    # === Snapshot pointers (don't live-read; facts frozen in JSON) ===
    source_plan_id = fields.Many2one(
        "neon.deployment.plan", readonly=True,
        ondelete="set null",
        help="The B3 plan active at reconciliation time. "
             "Snapshot pointer only -- facts are frozen in facts_json.",
    )
    source_subhire_request_ids = fields.Many2many(
        "neon.subhire.request",
        "neon_recon_subhire_rel",
        "recon_id", "request_id",
        string="Source sub-hire requests",
        readonly=True,
        help="B4 sub-hire requests active for this event at "
             "reconciliation time.",
    )

    # === Generated content ===
    facts_json = fields.Text(
        readonly=True,
        help="Python-gathered facts (planned vs actual, condition "
             "deltas, sub-hire outcomes, variance). The validator "
             "compares the Claude output against this.",
    )
    summary_json = fields.Text(
        readonly=True,
        help="Strict-JSON Claude output, validated against facts. "
             "Stored verbatim.",
    )
    summary_html = fields.Html(
        compute="_compute_summary_html",
        store=True, readonly=True, sanitize=False,
        help="Rendered HTML view of summary_json. On-screen render "
             "(no PDF -- defer per B3/B4 precedent).",
    )
    data_quality_note = fields.Text(
        readonly=True,
        help="Carried verbatim from B2 when load-in/out is "
             "imprecise. Banner above the recon on screen.",
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
        help="On ReconValidationError, the Claude output that "
             "contradicted the facts is parked here for debugging. "
             "Never rendered to users.",
    )

    # === Derived flags ===
    written_off_count = fields.Integer(
        compute="_compute_counts", store=True, readonly=True,
        help="Units flagged as written_off in the facts. Drives "
             "the workshop-alert chatter post on finalise.",
    )
    needs_repair_count = fields.Integer(
        compute="_compute_counts", store=True, readonly=True,
    )
    cost_variance_total = fields.Float(
        compute="_compute_counts", store=True, readonly=True,
        help="Sum of (actual - planned) variance for the event "
             "in USD. Positive means over-budget. INFORMATIONAL "
             "only -- B5 does not post anywhere.",
    )
    is_active = fields.Boolean(
        compute="_compute_is_active", store=True, readonly=True,
        index=True,
        help="True when this reconciliation is the CURRENT one "
             "for its event (not superseded).",
    )

    _sql_constraints = [
        ("revision_positive",
         "CHECK (revision >= 1)",
         "Revision must be a positive integer."),
        ("revision_unique_per_event",
         "UNIQUE (event_job_id, revision)",
         "Each event can only have one reconciliation per "
         "revision number."),
    ]

    # =================================================================
    # Computes
    # =================================================================
    @api.depends("event_job_id", "revision")
    def _compute_name(self):
        for rec in self:
            if rec.event_job_id and rec.revision:
                rec.name = "RECON-{ev}-R{r}".format(
                    ev=rec.event_job_id.id, r=rec.revision)
            else:
                rec.name = "RECON-draft"

    @api.depends("status")
    def _compute_is_active(self):
        for rec in self:
            rec.is_active = rec.status not in ("superseded",)

    @api.depends("facts_json")
    def _compute_counts(self):
        import json
        for rec in self:
            try:
                facts = (json.loads(rec.facts_json)
                          if rec.facts_json else {})
            except (ValueError, TypeError):
                facts = {}
            condition_deltas = (facts.get("condition_deltas")
                                  or [])
            rec.written_off_count = sum(
                1 for d in condition_deltas
                if d.get("new_status") == "written_off")
            rec.needs_repair_count = sum(
                1 for d in condition_deltas
                if d.get("new_status") == "needs_repair")
            variance = (facts.get("cost_variance") or {})
            rec.cost_variance_total = float(
                variance.get("variance_total") or 0.0)

    @api.depends("summary_json", "facts_json", "status")
    def _compute_summary_html(self):
        from .event_reconciliation_renderer import (
            render_reconciliation_html,
        )
        for rec in self:
            rec.summary_html = render_reconciliation_html(
                rec.summary_json or "",
                rec.facts_json or "",
                rec.status,
                rec.data_quality_note or "")

    # =================================================================
    # Lifecycle actions
    # =================================================================
    def action_mark_reviewed(self):
        for rec in self:
            if rec.status != "generated":
                raise UserError(_(
                    "Only generated reconciliations can be marked "
                    "reviewed. Current: %(s)s") % {"s": rec.status})
            rec.sudo().write({
                "status": "reviewed",
                "reviewed_at": fields.Datetime.now(),
                "reviewed_by_id": self.env.uid,
            })
        return True

    def action_mark_final(self):
        """reviewed -> final. On finalise, post a workshop chatter
        message + activity if any units were flagged as
        needs_repair / written_off (D5 -- never auto-flip the
        condition_status itself).
        """
        for rec in self:
            if rec.status != "reviewed":
                raise UserError(_(
                    "Only reviewed reconciliations can be marked "
                    "final. Current: %(s)s") % {"s": rec.status})
            rec.sudo().write({
                "status": "final",
                "finalised_at": fields.Datetime.now(),
                "finalised_by_id": self.env.uid,
            })
            rec._post_workshop_alert_on_finalise()
        return True

    def action_regenerate(self):
        """Spawn a new revision; this one becomes 'superseded' once
        the new one persists. Refused on 'superseded' -- already
        superseded by something else."""
        self.ensure_one()
        if self.status == "superseded":
            raise UserError(_(
                "This reconciliation is already superseded by "
                "%(n)s. Open the active one and regenerate from "
                "there.") % {
                    "n": (self.superseded_by_recon_id.name
                           or "(unknown)")})
        from .event_reconciliation_generator import (
            EventReconciliationGenerator,
        )
        new_rec = EventReconciliationGenerator(
            self.env).generate_for_event(
            self.event_job_id, replaces=self)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.event.reconciliation",
            "res_id": new_rec.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def action_generate_for_event(self, event_job_id):
        """Entry point for the server-action wrapper bound to the
        event_job form. Returns ir.action navigating to the new
        reconciliation."""
        Event = self.env["commercial.event.job"]
        ev = Event.browse(int(event_job_id)).exists()
        if not ev:
            raise UserError(_(
                "Event job %(i)s not found.") % {
                    "i": event_job_id})
        from .event_reconciliation_generator import (
            EventReconciliationGenerator,
        )
        rec = EventReconciliationGenerator(
            self.env).generate_for_event(ev)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.event.reconciliation",
            "res_id": rec.id,
            "view_mode": "form",
            "target": "current",
        }

    def _post_workshop_alert_on_finalise(self):
        """D5: post a chatter message + activity for the workshop
        manager when units need attention. NEVER flips
        condition_status itself."""
        for rec in self:
            if not (rec.written_off_count
                     or rec.needs_repair_count):
                continue
            import json
            try:
                facts = (json.loads(rec.facts_json)
                          if rec.facts_json else {})
            except (ValueError, TypeError):
                facts = {}
            deltas = facts.get("condition_deltas") or []
            flagged = [d for d in deltas
                       if d.get("new_status") in (
                           "needs_repair", "written_off")]
            if not flagged:
                continue
            body_lines = [_(
                "<strong>Workshop alert from reconciliation "
                "%(n)s:</strong> %(c)d unit(s) flagged for "
                "review:") % {
                    "n": rec.name,
                    "c": len(flagged),
                }]
            body_lines.append("<ul>")
            for d in flagged:
                body_lines.append(
                    "<li>{u} ({p}): suggested "
                    "<em>{s}</em></li>".format(
                        u=d.get("serial_number", "?"),
                        p=d.get("product_name", "?"),
                        s=d.get("new_status", "?")))
            body_lines.append("</ul>")
            body_lines.append(_(
                "<p><strong>Action:</strong> a Workshop user "
                "must review + flip the condition_status "
                "manually on each unit. B5 does NOT auto-flip "
                "condition.</p>"))
            rec.message_post(
                body="".join(body_lines),
                message_type="comment",
            )
            # Also schedule a TODO on the workshop manager group.
            workshop_manager_group = self.env.ref(
                "neon_jobs.group_neon_jobs_manager",
                raise_if_not_found=False)
            if workshop_manager_group:
                manager = (workshop_manager_group.users[:1]
                            if workshop_manager_group.users
                            else False)
                if manager:
                    try:
                        rec.activity_schedule(
                            "mail.mail_activity_data_todo",
                            user_id=manager.id,
                            summary=_(
                                "Review %(c)d unit(s) "
                                "flagged by reconciliation") % {
                                    "c": len(flagged)},
                            note=_(
                                "Reconciliation %(n)s flagged "
                                "units for condition review. "
                                "Flip condition_status manually "
                                "if confirmed.") % {
                                    "n": rec.name})
                    except Exception:  # noqa: BLE001
                        _logger.exception(
                            "B5 workshop activity_schedule "
                            "failed -- chatter post stands.")
