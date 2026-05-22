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
    # M7 extension -- parallel to M6 Promote wizard. Skip
    # paths frequently apply to candidates with no user_id
    # yet (e.g., bulk-import of existing crew). Adding the
    # user creation option here mirrors the M6 surface.
    create_user = fields.Boolean(
        string="Create User Account",
        default=True,
        help="If checked, a res.users record is created with "
             "Crew + Training User groups. Required when the "
             "candidate has no linked user yet (which is the "
             "typical Skip case -- pre-existing crew being "
             "bulk-imported). Auto-defaults False via the "
             "candidate form button context when user_id is "
             "already set.",
    )
    proposed_login = fields.Char(
        string="Proposed Login",
        compute="_compute_proposed_login",
        readonly=False,
        store=True,
        help="Defaults to the candidate's contact_email. "
             "Editable when the email is missing or admin "
             "wants a non-email-shaped login.",
    )
    notes = fields.Text(
        string="Skip Notes",
        help="Optional context appended to the audit log "
             "reason. Use for additional rationale not "
             "covered by the required Bypass Reason -- e.g., "
             "'Existing crew from pre-deploy 21 May 2026'.",
    )
    candidate_user_id = fields.Many2one(
        related="candidate_id.user_id",
        readonly=True,
    )
    candidate_state = fields.Selection(
        related="candidate_id.state",
        readonly=True,
    )

    @api.depends("candidate_id",
                 "candidate_id.contact_email")
    def _compute_proposed_login(self):
        for rec in self:
            rec.proposed_login = (
                rec.candidate_id.contact_email or False)

    def action_skip(self):
        """Promote candidate to 'active' with bypass metadata
        captured. Writes an audit log entry. Idempotent --
        re-running on an already-active candidate raises a
        UserError (no second skip needed).

        M7 extension: optional res.users creation when
        create_user=True and candidate.user_id is null. Same
        groups assignment as M6 Promote wizard (base +
        jobs_crew + training_user; temp password).
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

        # M7 step 1: create OR upgrade user.
        # M8 added the portal-user-at-cert_collection pattern;
        # candidate.user_id may already point at a portal-only
        # user even though state is 'cert_collection'. In that
        # case the skip wizard UPGRADES groups (strips portal,
        # adds backend) instead of creating fresh.
        new_user = self.env["res.users"]
        upgraded_user = self.env["res.users"]
        if self.create_user and not candidate.user_id:
            login = (self.proposed_login or "").strip()
            if not login:
                raise UserError(_(
                    "Cannot create a user account without a "
                    "login. Either set the candidate's "
                    "contact_email or fill in Proposed Login "
                    "before skipping."))
            existing = self.env["res.users"].sudo().search([
                ("login", "=", login),
            ], limit=1)
            if existing:
                raise UserError(_(
                    "A user with login '%(login)s' already "
                    "exists (id=%(uid)d, name=%(name)s). "
                    "Link the candidate to that user "
                    "manually, or change the Proposed Login "
                    "to something unique."
                ) % {
                    "login": login,
                    "uid": existing.id,
                    "name": existing.name,
                })
            new_user = self.env["res.users"].sudo().create({
                "name": candidate.name,
                "login": login,
                "email": candidate.contact_email or False,
                "password": "Neon2026!",
                "groups_id": [(6, 0, [
                    self.env.ref("base.group_user").id,
                    self.env.ref(
                        "neon_jobs.group_neon_jobs_crew"
                    ).id,
                    self.env.ref(
                        "neon_training."
                        "group_neon_training_user"
                    ).id,
                ])],
            })
            candidate.sudo().write({"user_id": new_user.id})
        elif self.create_user and candidate.user_id:
            # M8 upgrade path: portal user -> backend user.
            portal_grp = self.env.ref(
                "base.group_portal",
                raise_if_not_found=False)
            existing_user = candidate.user_id
            if portal_grp and portal_grp in existing_user.groups_id:
                existing_user.sudo().write({
                    "groups_id": [
                        (3, portal_grp.id),
                        (4, self.env.ref(
                            "base.group_user").id),
                        (4, self.env.ref(
                            "neon_jobs.group_neon_jobs_crew"
                        ).id),
                        (4, self.env.ref(
                            "neon_training."
                            "group_neon_training_user"
                        ).id),
                    ],
                })
                upgraded_user = existing_user
                # Audit log for the upgrade -- separate from
                # the skip_onboarding entry so the audit
                # trail captures both moments.
                self.env["neon.onboarding.audit.log"].sudo().create({
                    "candidate_id": candidate.id,
                    "action": "portal_user_upgraded",
                    "actor_id": self.env.user.id,
                    "reason": (
                        "Portal user upgraded to backend "
                        "during Skip Onboarding: " +
                        existing_user.login),
                    "previous_state": previous_state,
                    "new_state": previous_state,
                })

        # M7 step 2: candidate state transition.
        candidate.sudo().write({
            "state": "active",
            "bypass_reason": self.reason,
            "bypass_actor_id": self.env.user.id,
            "date_activated": fields.Datetime.now(),
        })

        # M7 step 3: audit log -- compose reason with the
        # required field + optional notes + origin state
        # marker. Audit action stays 'skip_onboarding' to
        # preserve the Skip-vs-Promote distinction (M6 uses
        # 'promote_active' for its path).
        audit_reason = self.reason
        if self.notes:
            audit_reason += " -- Notes: " + self.notes
        audit_reason += (
            " -- Skipped from state: " + previous_state)
        self.env["neon.onboarding.audit.log"].sudo().create({
            "candidate_id": candidate.id,
            "action": "skip_onboarding",
            "actor_id": self.env.user.id,
            "reason": audit_reason,
            "previous_state": previous_state,
            "new_state": "active",
        })

        candidate.sudo().message_post(
            body=_(
                "Onboarding skipped by %(actor)s. Reason: "
                "%(reason)s. Previous state: %(prev)s -> "
                "active.%(user_created)s"
            ) % {
                "actor": self.env.user.name,
                "reason": self.reason,
                "prev": previous_state,
                "user_created": (
                    _(" New user account created (login=%s).")
                    % new_user.login if new_user else ""),
            })

        # M12 notification stub. sudo() so the message_post
        # author lookup uses SUPERUSER (which has an email);
        # test-fixture triggering users may not.
        candidate.sudo()._notify_skipped(self.reason)

        _logger.info(
            "neon_onboarding M7: skip override on %s by %s "
            "(reason=%s, prev_state=%s, user_created=%s).",
            candidate.display_name,
            self.env.user.login,
            self.reason, previous_state, bool(new_user))

        return {"type": "ir.actions.act_window_close"}
