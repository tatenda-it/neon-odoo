# -*- coding: utf-8 -*-
"""
P7a.M10 -- neon.finance.quote inherit for tier-2 (warn) gating.

When action_accept fires on a quote whose event_job has crew in
gate_status 'unqualified' or 'needs_cross_competency', the
inherited method short-circuits and returns the override wizard
instead of moving the quote to 'accepted'. The wizard captures
the override reason, writes assignment_gate_log records, and
then calls _continue_action_accept to complete the original
acceptance semantic.

DP3 (gate-1): hook ONLY action_accept. Direct write
({'state': 'accepted'}) and migration scripts bypass the gate.
This is intentional -- P6.M7 migration uses the bypass path.
Polish item logged for Phase 11: promote to write override if
production audit shows the migration path being misused for
actual quote acceptances.

DP8 (gate-1): apply sudo() defensively on the gate read mirror
of M9. Capture triggering user's partner BEFORE sudo per
reference_odoo17_hook_sudo_partner_capture.md.

DP4 (gate-1): pending role lines (no user assigned) pass
through the tier-2 gate. M11 (event_start) catches "still no
user on event day" as the strict block.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


# Mirror of the wizard's firing set. Centralised here so both
# the gate evaluator and the wizard fan-out use the same enum.
_TIER_2_FIRING_STATUSES = ("unqualified", "needs_cross_competency")


class NeonFinanceQuote(models.Model):
    _inherit = "neon.finance.quote"

    def _evaluate_quote_training_gate(self):
        """Return the recordset of commercial.job.crew rows whose
        gate_status indicates a tier-2 fire (unqualified or
        needs_cross_competency). Empty result means the quote
        can accept cleanly without the wizard.

        Pending crew (no user_id assigned) pass through per DP4.
        Qualified crew pass through trivially. Only firing
        statuses surface.

        Sudo defensively per DP8 -- the gate compute traverses
        cert-type records which sales reps DO carry training_user
        access on, but defensive sudo follows the M9 pattern and
        is robust to future ACL changes.
        """
        self.ensure_one()
        Crew = self.env["commercial.job.crew"]
        if not self.event_job_id:
            return Crew
        crew = self.event_job_id.commercial_job_id\
            .crew_assignment_ids.sudo()
        return crew.filtered(
            lambda c: c.gate_status in _TIER_2_FIRING_STATUSES)

    def action_accept(self):
        """Inherited. Tier-2 short-circuit: if any role line on
        this quote's event_job has a firing gate_status, open
        the override wizard instead of accepting.

        When the wizard confirms, it calls _continue_action
        _accept which delegates to super().action_accept() with
        the same self -- bypassing this inherit on the second
        pass via a context flag.

        DP9 (gate-1 verified): P6 quote smokes seed event_jobs
        without crew. affected is empty -> wizard never opens
        -> super delegates normally -> P6 tests pass.
        """
        # Context bypass for the wizard's second-pass call. The
        # wizard's _continue_action_accept sets this flag so the
        # gate doesn't re-evaluate (it just fired the log + TODO
        # already).
        if self.env.context.get("m10_skip_gate_evaluation"):
            return super().action_accept()

        # Multi-record action_accept: process per record. If any
        # record needs the wizard, return for the first such
        # record (multi-record wizards are out-of-scope for M10;
        # batch quote-accept is not a real user flow). Others
        # delegate as normal.
        for rec in self:
            # Only evaluate when the quote is in the state that
            # action_accept legally fires from. Other states
            # would raise inside super() with the existing error
            # message; we don't pre-empt that error path.
            if rec.state != "sent":
                continue
            affected = rec._evaluate_quote_training_gate()
            if affected:
                return {
                    "type":      "ir.actions.act_window",
                    "name":      _("Training Gate Override"),
                    "res_model": "neon.training."
                                 "quote_gate_override_wizard",
                    "view_mode": "form",
                    "target":    "new",
                    "context":   {
                        "default_quote_id":       rec.id,
                        "default_override_reason": "",
                    },
                }
        # No firing crew -> delegate to super for all records.
        return super().action_accept()

    def _continue_action_accept(self, triggering_partner=None):
        """Wizard re-entry. Bypasses the M10 gate (already fired
        the log + activity) and calls super().action_accept()
        via the m10_skip_gate_evaluation context flag.

        triggering_partner is captured by the wizard BEFORE its
        sudo escalation; not currently consumed here (no toast
        on tier-2 -- the wizard itself was the surface), but the
        arg is reserved for M11 which may need to route a final
        success toast back to the sales rep.
        """
        self.ensure_one()
        return self.with_context(
            m10_skip_gate_evaluation=True).action_accept()
