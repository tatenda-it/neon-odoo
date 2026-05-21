# -*- coding: utf-8 -*-
"""
P7a.M11 -- event_job in_progress training gate override wizard.

The strictest of the three gating tiers. When a Crew Leader or
Manager clicks "Event Started" (which calls action_move_to_in
_progress), the inherited method evaluates the M8 gate on the
event_job's crew. If any role line is unqualified or needs
_cross_competency AND there is no recent (< 24h) tier_3
override in the assignment_gate_log, this wizard returns
instead of the state transition.

On Confirm:
1. Write one neon.training.assignment_gate_log per (affected
   crew, event_job) pair with gate_tier='tier_3_event_start',
   severity='block' (computed via M9's _TIER_SEVERITY),
   override_reason captured, overridden_by_id=current user,
   overridden_at=now.
2. Schedule a mail.activity TODO on the finance approver group
   (Robin/Munashe per DP5). Tier_3 is the live event moment;
   the approver needs to know IMMEDIATELY for potential
   escalation (replacement crew, client conversation).
3. Re-call action_move_to_in_progress with the
   m11_skip_gate_evaluation context flag so the inherit
   bypasses the gate check and the underlying state transition
   completes.

On Cancel: returns ir.actions.act_window_close. The event_job
stays in 'dispatched' (the prior state). Transient cleanup
handles the wizard row.

DP1 (gate-1): action_move_to_in_progress returns the wizard
act_window, same shape as M10's action_accept hook.

DP6 (gate-1): pending role lines (no user_id) pass through.
M11 fires only on unqualified + needs_cross_competency.

DP10 (gate-1): ACL grants jobs.crew_leader + jobs.manager, NOT
finance roles -- per _TRANSITIONS['in_progress']['groups'] in
neon_jobs the operators are crew_leader and manager. Training
roles also granted for cross-tier read.

DP11 (gate-1): sudo escalation for the gate read; triggering
user partner captured BEFORE sudo per
reference_odoo17_hook_sudo_partner_capture.md.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Mirror of M10's firing set. Pending passes through per DP6.
# Qualified passes trivially.
_TIER_3_FIRING_STATUSES = ("unqualified", "needs_cross_competency")


class NeonTrainingEventStartGateOverrideWizard(models.TransientModel):
    _name = "neon.training.event_start_gate_override_wizard"
    _description = "Event Start Training Gate Override (Tier 3)"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
    )
    target_state = fields.Char(
        string="Target State",
        required=True,
        default="in_progress",
        help="The state the user attempted to transition into. "
        "Captured at wizard-open time so the confirm path knows "
        "which transition to re-fire. Currently always "
        "'in_progress' (M11 is the only tier_3 transition); "
        "future tier_3 expansion (e.g. closeout) would set this "
        "differently.",
    )
    affected_role_line_ids = fields.Many2many(
        "commercial.job.crew",
        "neon_training_event_start_wizard_affected_rel",
        "wizard_id",
        "crew_id",
        string="Affected Role Lines",
        compute="_compute_affected_role_lines",
        store=False,
        help="Crew rows on the event_job's parent commercial.job "
        "with gate_status in (unqualified, needs_cross_competency). "
        "Recomputed live from M8's gate inference engine.",
    )
    affected_summary_html = fields.Html(
        string="Affected Crew Summary",
        compute="_compute_affected_summary",
        store=False,
        sanitize=False,
        help="Rendered list of affected crew with missing certs. "
        "Read-only; for human review in the wizard surface.",
    )
    override_reason = fields.Text(
        string="Override Reason",
        required=True,
        help="Why are you starting the event despite unqualified "
        "crew? This text is recorded on every affected role "
        "line's gate log entry and triggers a TODO on Robin / "
        "Munashe (finance approver) so they can escalate if "
        "needed (replacement crew, client conversation).",
    )

    @api.depends("event_job_id")
    def _compute_affected_role_lines(self):
        """Read the event_job's crew (via parent commercial.job)
        and filter to gate_status in the tier-3 firing set.

        Sudo defensively per DP11 -- the gate compute traverses
        M8's cert-type inference; Crew Leaders carry training
        _user via implied_ids, but defensive sudo is robust to
        future ACL changes (M9 reference doc).
        """
        Crew = self.env["commercial.job.crew"]
        for rec in self:
            if (not rec.event_job_id
                    or not rec.event_job_id.commercial_job_id):
                rec.affected_role_line_ids = Crew
                continue
            crew = rec.event_job_id.commercial_job_id\
                .crew_assignment_ids.sudo()
            rec.affected_role_line_ids = crew.filtered(
                lambda c: c.gate_status in _TIER_3_FIRING_STATUSES)

    @api.depends("affected_role_line_ids")
    def _compute_affected_summary(self):
        """Render an HTML summary so the operator sees exactly
        which crew + which gaps before they commit to the
        override.

        Stricter visual cue than M10: this is the BLOCK tier,
        not the WARN tier. Surface the "Robin/Munashe will be
        notified" hint inline.
        """
        for rec in self:
            if not rec.affected_role_line_ids:
                rec.affected_summary_html = (
                    "<p><em>No affected role lines (gate may "
                    "have cleared mid-flight).</em></p>")
                continue
            rows = []
            for crew in rec.affected_role_line_ids:
                crew_su = crew.sudo()
                user_name = (crew_su.user_id.name
                             or crew_su.partner_id.name
                             or _("(unnamed)"))
                missing = ", ".join(
                    crew_su.gate_missing_certification_ids
                    .mapped("name")
                ) or _("(none)")
                softener_count = len(
                    crew_su.gate_softening_cross_competency_ids)
                status_label = dict(
                    crew_su._fields["gate_status"].selection
                ).get(crew_su.gate_status, crew_su.gate_status)
                if softener_count:
                    softener_phrase = _(
                        " (softened by %d cross-competency "
                        "observation%s)"
                    ) % (softener_count,
                         "" if softener_count == 1 else "s")
                else:
                    softener_phrase = ""
                rows.append(
                    "<li><strong>%(user)s</strong> as "
                    "<em>%(role)s</em> &mdash; %(status)s. "
                    "Missing: %(missing)s.%(soft)s</li>" % {
                        "user":    user_name,
                        "role":    dict(crew_su._fields["role"]
                                       .selection).get(
                            crew_su.role, crew_su.role),
                        "status":  status_label,
                        "missing": missing,
                        "soft":    softener_phrase,
                    })
            rec.affected_summary_html = (
                "<div class='alert alert-danger' role='alert'>"
                "<strong>Tier 3 BLOCK</strong> &mdash; the "
                "event is about to start but crew qualifications "
                "are incomplete. Proceeding will be logged with "
                "severity='block' and notify Robin / Munashe "
                "(finance approver) for potential escalation. "
                "Cross-competency softeners do NOT bypass this "
                "tier.</div>"
                "<p><strong>Affected role lines:</strong></p>"
                "<ul>%s</ul>"
            ) % "".join(rows)

    # ============================================================
    # Actions
    # ============================================================
    def action_confirm_override(self):
        """Fire the tier-3 gate log entries + finance approver
        TODO, then re-call action_move_to_in_progress with the
        bypass context flag to complete the transition.

        Sudo scope: log create + activity_schedule run under
        sudo (training_user-tier operators cannot create on the
        gate_log directly; the audit must land). Triggering
        partner captured BEFORE sudo per DP11.
        """
        self.ensure_one()
        if not self.override_reason or not self.override_reason.strip():
            raise UserError(_(
                "Override reason is required. Type a brief "
                "explanation of why this event is starting "
                "despite training gaps. Robin / Munashe will see "
                "this text on the notification TODO."))

        triggering_user = self.env.user
        triggering_partner = triggering_user.partner_id  # pre-sudo

        if not self.affected_role_line_ids:
            # Defensive: gap may have cleared mid-flight. Skip
            # log writes; just complete the transition.
            return self.event_job_id.with_context(
                m11_skip_gate_evaluation=True
            ).action_move_to_in_progress()

        GateLog = self.env["neon.training.assignment_gate_log"]
        Activity = self.env["mail.activity"]
        now = fields.Datetime.now()
        event_job = self.event_job_id

        log_vals_list = []
        for crew in self.affected_role_line_ids.sudo():
            log_vals_list.append({
                "event_job_id":         event_job.id,
                "crew_id":              crew.id,
                "user_id":              crew.user_id.id,
                "gate_tier":            "tier_3_event_start",
                "gate_status_at_fire":  crew.gate_status,
                "missing_certification_type_ids":
                    [(6, 0, crew.gate_missing_certification_ids.ids)],
                "softening_cross_competency_ids":
                    [(6, 0, crew.gate_softening_cross_competency_ids.ids)],
                "override_reason":  self.override_reason,
                "overridden_by_id": triggering_user.id,
                "overridden_at":    now,
                "fired_at":         now,
                "triggered_by_id":  triggering_user.id,
            })
        GateLog.sudo().create(log_vals_list)

        # DP5: notify the finance approver group via mail.activity
        # TODO on the event_job record. Tier_3 = approver concern
        # (Robin/Munashe). NOT training_admin (separate workflow).
        approver_group = self.env.ref(
            "neon_finance.group_neon_finance_approver",
            raise_if_not_found=False)
        if approver_group and approver_group.users:
            target = approver_group.users.sorted("id")[0]
            existing = Activity.sudo().search([
                ("res_model", "=", "commercial.event.job"),
                ("res_id",    "=", event_job.id),
                ("summary",   "=ilike",
                 "Tier 3 event-start gate override%"),
            ], limit=1)
            if not existing:
                event_job.sudo().activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=target.id,
                    summary=_(
                        "Tier 3 event-start gate override on %s"
                    ) % event_job.display_name,
                    note=_(
                        "Operator %(op)s started this event "
                        "despite training gaps. Reason: "
                        "%(reason)s. Affected role lines: "
                        "%(n)d. Cross-competency softeners did "
                        "NOT bypass the gate. Consider "
                        "escalation: replacement crew, client "
                        "conversation, or Ranganai dispatch. "
                        "See the Training Gate Log tab for "
                        "detail."
                    ) % {
                        "op":     triggering_user.name,
                        "reason": self.override_reason,
                        "n":      len(self.affected_role_line_ids),
                    },
                    date_deadline=fields.Date.context_today(self),
                )

        # Re-call the transition with the bypass flag.
        return event_job.with_context(
            m11_skip_gate_evaluation=True
        ).action_move_to_in_progress()

    def action_cancel(self):
        """Close the wizard without state change. The event_job
        stays in 'dispatched'; transient cleanup handles the
        wizard row.
        """
        self.ensure_one()
        return {"type": "ir.actions.act_window_close"}
