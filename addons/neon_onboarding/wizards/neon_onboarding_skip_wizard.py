# -*- coding: utf-8 -*-
"""Skip Onboarding wizard -- admin override that jumps a
candidate from any state directly to 'active'.

Visibility: superuser tier only (group_neon_superuser) per
Tatenda's design call. Robin + Munashe + Tatenda see the
button; bookkeeper / sales_rep / lead_tech / crew do not.

Captures bypass_reason + bypass_actor_id on the candidate
and writes an audit log entry. Per-sudo partner capture is
unnecessary here because the wizard runs as the triggering
user end-to-end (no bus.bus toasts, no chatter posting on
behalf of others).

Reference: docs/phase-7b/schema-sketch.md section 6.1.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class NeonOnboardingSkipWizard(models.TransientModel):
    _name = "neon.onboarding.skip.wizard"
    _description = "Skip Onboarding (Admin Override)"

    candidate_id = fields.Many2one(
        "neon.onboarding.candidate",
        string="Candidate",
        required=True,
        ondelete="cascade",
    )
    reason = fields.Char(
        string="Bypass Reason",
        required=True,
        help="Why is this candidate skipping onboarding? "
             "e.g., 'Existing crew from pre-Phase-7b deploy, "
             "added 22 May 2026'. Required by audit "
             "constraint.",
    )

    def action_skip(self):
        """Promote candidate to 'active' with bypass metadata
        captured. Writes an audit log entry. Idempotent --
        re-running on an already-active candidate raises a
        UserError (no second skip needed).
        """
        self.ensure_one()
        candidate = self.candidate_id
        if candidate.state == "active":
            raise UserError(_(
                "%s is already in Active state. The Skip "
                "Onboarding override has nothing to do.")
                % candidate.display_name)
        if not (self.reason and self.reason.strip()):
            raise ValidationError(_(
                "A bypass reason is required."))

        previous_state = candidate.state
        candidate.sudo().write({
            "state": "active",
            "bypass_reason": self.reason,
            "bypass_actor_id": self.env.user.id,
            "date_activated": fields.Datetime.now(),
        })

        self.env["neon.onboarding.audit.log"].sudo().create({
            "candidate_id": candidate.id,
            "action": "skip_onboarding",
            "actor_id": self.env.user.id,
            "reason": self.reason,
            "previous_state": previous_state,
            "new_state": "active",
        })

        candidate.sudo().message_post(
            body=_(
                "Onboarding skipped by %(actor)s. Reason: "
                "%(reason)s. Previous state: %(prev)s -> "
                "active."
            ) % {
                "actor": self.env.user.name,
                "reason": self.reason,
                "prev": previous_state,
            })

        _logger.info(
            "neon_onboarding: skip override on %s by %s "
            "(reason=%s, prev_state=%s).",
            candidate.display_name,
            self.env.user.login,
            self.reason, previous_state)

        return {"type": "ir.actions.act_window_close"}
