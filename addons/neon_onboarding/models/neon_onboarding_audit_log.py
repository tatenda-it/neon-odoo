# -*- coding: utf-8 -*-
"""neon.onboarding.audit.log -- append-only audit trail for
onboarding override + transition decisions.

Mirrors the H3=A pattern from Phase 7a M9's assignment_gate_log:
* perm_unlink=0 on every tier in ir.model.access.csv
* unlink() raises UserError defensively (catches sudo bypass)

Reference: docs/phase-7b/schema-sketch.md section 4.3.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


_AUDIT_ACTIONS = [
    ("skip_onboarding", "Skip Onboarding (Admin Override)"),
    ("promote_probationary", "Promoted to Probationary"),
    ("promote_active", "Promoted to Active"),
    ("template_change", "Requirement Template Changed"),
    # M8 -- portal user provisioning on cert_collection entry.
    # Not a state transition (previous_state == new_state);
    # the audit value here is "this was the moment Robin /
    # admin gave the crew member portal access".
    ("portal_user_created", "Portal User Created"),
    # M8 -- portal user upgraded to backend user during
    # promote / skip flow. Captured separately from
    # promote_active / skip_onboarding so the audit trail
    # shows the moment of group elevation.
    ("portal_user_upgraded", "Portal User Upgraded to Backend"),
]


class NeonOnboardingAuditLog(models.Model):
    _name = "neon.onboarding.audit.log"
    _description = "Onboarding Audit Log"
    _inherit = ["mail.thread"]
    _order = "timestamp desc, id desc"

    candidate_id = fields.Many2one(
        "neon.onboarding.candidate",
        string="Candidate",
        required=True,
        ondelete="restrict",
        index=True,
        help="Audit entries outlive deletion attempts on the "
             "parent candidate (ondelete=restrict). M1 also "
             "blocks candidate unlink via perm_unlink=0 in "
             "ir.model.access.csv.",
    )
    action = fields.Selection(
        _AUDIT_ACTIONS,
        string="Action",
        required=True,
    )
    actor_id = fields.Many2one(
        "res.users",
        string="Actor",
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.user.id,
        help="The user who triggered the audited action. "
             "Captured pre-sudo per the hook-sudo-partner-"
             "capture ref doc.",
    )
    reason = fields.Char(
        string="Reason",
        help="Required for skip_onboarding; optional for "
             "auto-transition entries.",
    )
    previous_state = fields.Char(
        string="Previous State",
        required=True,
        help="The candidate.state value before the action.",
    )
    new_state = fields.Char(
        string="New State",
        required=True,
        help="The candidate.state value after the action.",
    )
    timestamp = fields.Datetime(
        string="Timestamp",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )

    @api.constrains("action", "reason")
    def _check_skip_requires_reason(self):
        """skip_onboarding entries must carry a reason --
        Robin needs to know WHY each existing-crew skip
        happened during the Phase 7b bulk-import push.
        """
        for rec in self:
            if rec.action == "skip_onboarding":
                if not (rec.reason and rec.reason.strip()):
                    raise ValidationError(_(
                        "Skip Onboarding audit entries require "
                        "a reason. The wizard populates this; "
                        "do not create the log entry directly."))

    def unlink(self):
        """Defensive belt-and-braces against sudo() bypass.
        perm_unlink=0 already blocks regular users; this
        catches superuser attempts as well.
        """
        raise UserError(_(
            "Onboarding audit log entries are append-only and "
            "cannot be deleted. Correct via a follow-up audit "
            "entry instead."))
