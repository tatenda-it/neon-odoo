# -*- coding: utf-8 -*-
"""
P7a.M10 -- quote-accept training gate override wizard.

When a sales rep clicks Accept on a quote whose event_job has
crew with gate_status in (unqualified, needs_cross_competency),
the inherited action_accept returns this wizard instead of
moving the quote to 'accepted' directly. The wizard requires an
override_reason, then on Confirm:

1. Writes one neon.training.assignment_gate_log per (affected
   crew, event_job) pair with gate_tier='tier_2_quote_accept',
   severity='warn' (computed), override_reason captured,
   overridden_by_id = current user, overridden_at = now.
2. Schedules a mail.activity TODO on the finance approver group
   for downstream visibility (DP2 routing).
3. Calls the inherited helper _continue_action_accept() on the
   quote, which delegates to super().action_accept() to complete
   the original accept semantic (state -> accepted, invoice
   schedule materialisation, etc.).

Cancel closes the wizard without state change (transient cleanup
handles the wizard row itself).

DP1 -- single override_reason for the quote as a whole. Same
text written to every affected log row.

DP6 -- a quote has exactly one event_job (verified at gate-1
discovery: neon.finance.quote.event_job_id is required Many2one
to commercial.event.job). The affected crew set is
quote.event_job_id.commercial_job_id.crew_assignment_ids
filtered by gate_status not in ('qualified', 'pending').
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Gate statuses that trigger the tier-2 warn fire. 'pending' is
# explicitly excluded per DP4 -- M11 (event_start) catches "still
# no user assigned on event day".
_TIER_2_FIRING_STATUSES = ("unqualified", "needs_cross_competency")


class NeonTrainingQuoteGateOverrideWizard(models.TransientModel):
    _name = "neon.training.quote_gate_override_wizard"
    _description = "Quote Accept Training Gate Override"

    quote_id = fields.Many2one(
        "neon.finance.quote",
        string="Quote",
        required=True,
        ondelete="cascade",
    )
    affected_role_line_ids = fields.Many2many(
        "commercial.job.crew",
        "neon_training_quote_gate_wizard_affected_rel",
        "wizard_id",
        "crew_id",
        string="Affected Role Lines",
        compute="_compute_affected_role_lines",
        store=False,
        help="Crew rows on the quote's event_job whose gate_"
        "status is 'unqualified' or 'needs_cross_competency'. "
        "Recomputed live from M8's gate inference engine.",
    )
    affected_summary_html = fields.Html(
        string="Affected Crew Summary",
        compute="_compute_affected_summary",
        store=False,
        sanitize=False,
        help="Rendered list of '{crew_name} on {event_name}: "
        "missing {cert_names}, softened by N cross-competency "
        "observations'. Read-only display field.",
    )
    override_reason = fields.Text(
        string="Override Reason",
        required=True,
        help="Why are you proceeding with this quote despite "
        "training gaps? This text is recorded on every affected "
        "role line's gate log entry and appears in the audit "
        "search filter 'Overridden'. Finance approvers see this "
        "via mail.activity TODO on quote acceptance.",
    )

    @api.depends("quote_id")
    def _compute_affected_role_lines(self):
        """Read the quote's crew (via parent commercial.job) and
        filter to gate_status in the tier-2 firing set.

        Sudo defensively per DP8 + the M9 reference: the gate
        compute traverses M8's cert-type inference, and although
        sales reps DO carry training_user (verified gate-1),
        wizard rendering should not depend on the live user's
        ACL profile (a session that loses the group mid-flight
        would otherwise fail silently). Cheap insurance.
        """
        Crew = self.env["commercial.job.crew"]
        for rec in self:
            if not rec.quote_id or not rec.quote_id.event_job_id:
                rec.affected_role_line_ids = Crew
                continue
            crew = rec.quote_id.event_job_id.commercial_job_id\
                .crew_assignment_ids.sudo()
            rec.affected_role_line_ids = crew.filtered(
                lambda c: c.gate_status in _TIER_2_FIRING_STATUSES)

    @api.depends("affected_role_line_ids")
    def _compute_affected_summary(self):
        """Render an HTML summary so the wizard form shows the
        sales rep exactly which crew + which gaps. The actual
        log records persist this data structurally; the HTML
        here is for the human reading the wizard.
        """
        for rec in self:
            if not rec.affected_role_line_ids:
                rec.affected_summary_html = (
                    "<p><em>No affected role lines.</em></p>")
                continue
            rows = []
            for crew in rec.affected_role_line_ids:
                crew_su = crew.sudo()
                user_name = (crew_su.user_id.name
                             or crew_su.partner_id.name
                             or _("(unnamed)"))
                event_name = (crew_su.job_id.name
                              or _("(unnamed event)"))
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
                    "<em>%(role)s</em> on %(event)s &mdash; "
                    "%(status)s. Missing: %(missing)s.%(soft)s"
                    "</li>" % {
                        "user":    user_name,
                        "role":    dict(crew_su._fields["role"]
                                       .selection).get(
                            crew_su.role, crew_su.role),
                        "event":   event_name,
                        "status":  status_label,
                        "missing": missing,
                        "soft":    softener_phrase,
                    })
            rec.affected_summary_html = (
                "<p>The following role lines require an override "
                "reason before this quote can be accepted:</p>"
                "<ul>%s</ul>"
                "<p class='text-muted'>Tier 2 (warn). Quote "
                "acceptance proceeds after you provide a reason; "
                "M11 (event start) is the strict block tier.</p>"
            ) % "".join(rows)

    # ============================================================
    # Actions
    # ============================================================
    def action_confirm_override(self):
        """Fire the tier-2 gate log entries, schedule the finance
        approver TODO, then delegate to the quote's
        _continue_action_accept helper to complete the standard
        acceptance.

        Sudo scope: log create + activity_schedule run as sudo
        (training_user sales reps don't have create on the gate
        log; M9 followed the same pattern). Triggering user
        partner captured BEFORE sudo escalation per
        reference_odoo17_hook_sudo_partner_capture.md.
        """
        self.ensure_one()
        if not self.override_reason or not self.override_reason.strip():
            raise UserError(_(
                "Override reason is required. Type a brief "
                "explanation of why you are proceeding with "
                "training gaps on this quote."))

        triggering_user = self.env.user
        triggering_partner = triggering_user.partner_id  # pre-sudo

        if not self.affected_role_line_ids:
            # Defensive: if all gaps were cleared between wizard
            # open and confirm (someone else verified a cert in
            # parallel), skip the log writes and finish the
            # accept. The audit shouldn't record a fire that no
            # longer applies.
            return self.quote_id.sudo()._continue_action_accept()

        GateLog = self.env["neon.training.assignment_gate_log"]
        Activity = self.env["mail.activity"]
        now = fields.Datetime.now()
        event_job = self.quote_id.event_job_id

        log_vals_list = []
        for crew in self.affected_role_line_ids.sudo():
            log_vals_list.append({
                "event_job_id":         event_job.id,
                "crew_id":              crew.id,
                "user_id":              crew.user_id.id,
                "gate_tier":            "tier_2_quote_accept",
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

        # DP2: notify the finance approver group via mail.activity
        # TODO on the quote record. Same pattern as M5/M7 routing.
        approver_group = self.env.ref(
            "neon_finance.group_neon_finance_approver",
            raise_if_not_found=False)
        if approver_group and approver_group.users:
            target = approver_group.users.sorted("id")[0]
            existing = Activity.sudo().search([
                ("res_model", "=", "neon.finance.quote"),
                ("res_id",    "=", self.quote_id.id),
                ("summary",   "=ilike",
                 "Tier 2 training-gate override%"),
            ], limit=1)
            if not existing:
                self.quote_id.sudo().activity_schedule(
                    "mail.mail_activity_data_todo",
                    user_id=target.id,
                    summary=_(
                        "Tier 2 training-gate override on quote "
                        "%s") % self.quote_id.name,
                    note=_(
                        "Sales rep %(rep)s overrode the training "
                        "gate to accept this quote. Reason: "
                        "%(reason)s. Affected role lines: %(n)d. "
                        "See the Training Gate Log tab on the "
                        "event_job for detail."
                    ) % {
                        "rep":    triggering_user.name,
                        "reason": self.override_reason,
                        "n":      len(self.affected_role_line_ids),
                    },
                    date_deadline=fields.Date.context_today(self),
                )

        # Complete the original action_accept logic.
        return self.quote_id.sudo()._continue_action_accept(
            triggering_partner=triggering_partner)

    def action_cancel(self):
        """Close the wizard without state change. The quote
        stays in 'sent' (or whatever prior state); transient
        cleanup handles the wizard row.

        Returns the standard close action so the form modal
        dismisses cleanly.
        """
        self.ensure_one()
        return {"type": "ir.actions.act_window_close"}
