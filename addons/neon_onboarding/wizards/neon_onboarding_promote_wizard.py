# -*- coding: utf-8 -*-
"""Promote to Active wizard.

Phase 7b M6. Manual promotion only -- Robin/Munashe decide per
candidate. No auto-promote despite probationary_jobs_completed
>= probationary_jobs_target (the ready badge is a visual cue
only).

Activation creates a res.users record if candidate.user_id is
null. Login defaults to contact_email; groups assigned:
  base.group_user
  neon_jobs.group_neon_jobs_crew
  neon_training.group_neon_training_user

Reference: docs/phase-7b/schema-sketch.md sections 6.1 + 6.4.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class NeonOnboardingPromoteWizard(models.TransientModel):
    _name = "neon.onboarding.promote.wizard"
    _description = "Promote Candidate to Active"

    candidate_id = fields.Many2one(
        "neon.onboarding.candidate",
        string="Candidate",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    create_user = fields.Boolean(
        string="Create User Account",
        default=True,
        help="If checked, a res.users record is created using "
             "the candidate's contact_email as login. Crew + "
             "Training User groups assigned. Auto-defaults to "
             "True when the candidate has no user_id; flip off "
             "when linking an existing user manually.",
    )
    proposed_login = fields.Char(
        string="Proposed Login",
        compute="_compute_proposed_login",
        readonly=False,
        store=True,
        help="Defaults to the candidate's contact_email. "
             "Editable in case the email field is empty or "
             "the desired login differs.",
    )
    notes = fields.Text(
        string="Promotion Notes",
        help="Optional context captured on the audit log "
             "entry. Use for rationale, e.g. 'Completed 5 of "
             "3 probationary jobs ahead of schedule'.",
    )
    candidate_state = fields.Selection(
        related="candidate_id.state",
        readonly=True,
    )
    candidate_user_id = fields.Many2one(
        related="candidate_id.user_id",
        readonly=True,
    )
    jobs_completed = fields.Integer(
        related="candidate_id.probationary_jobs_completed",
        readonly=True,
    )
    jobs_target = fields.Integer(
        related="candidate_id.probationary_jobs_target",
        readonly=True,
    )

    @api.depends("candidate_id",
                 "candidate_id.contact_email")
    def _compute_proposed_login(self):
        for rec in self:
            rec.proposed_login = (
                rec.candidate_id.contact_email or False)

    def action_promote(self):
        """Promote to active. Three-step transactional:
        (1) Create res.users if requested + null user_id
        (2) Write state + date_activated on candidate
        (3) Audit log entry
        Each step in same DB transaction; any failure rolls
        back all three.
        """
        self.ensure_one()
        cand = self.candidate_id

        if cand.state != "probationary":
            raise UserError(_(
                "Cannot promote candidate in state '%(state)s'. "
                "The Promote to Active path is gated to "
                "probationary candidates only. Use the Skip "
                "Onboarding wizard if the intent is an admin "
                "override from earlier states."
            ) % {"state": cand.state})

        # Step 1: create user if needed.
        new_user = self.env["res.users"]
        if self.create_user and not cand.user_id:
            login = (self.proposed_login or "").strip()
            if not login:
                raise UserError(_(
                    "A login is required to create a user "
                    "account. Either fill in the candidate's "
                    "contact_email or enter a Proposed Login."))
            existing = self.env["res.users"].sudo().search([
                ("login", "=", login),
            ], limit=1)
            if existing:
                raise UserError(_(
                    "A user with login '%(login)s' already "
                    "exists (id=%(uid)d, name=%(name)s). Link "
                    "the candidate to that user manually, or "
                    "change the Proposed Login to something "
                    "unique."
                ) % {
                    "login": login,
                    "uid": existing.id,
                    "name": existing.name,
                })
            try:
                new_user = self.env["res.users"].sudo().create({
                    "name": cand.name,
                    "login": login,
                    "email": cand.contact_email or False,
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
            except (UserError, ValidationError):
                raise
            except Exception as e:  # noqa: BLE001
                raise UserError(_(
                    "Failed to create user account: %s. Fix "
                    "the underlying issue (login uniqueness, "
                    "group references) and retry.") % str(e))
            cand.sudo().write({"user_id": new_user.id})

        # Step 2: candidate state transition.
        prev = cand.state
        cand.sudo().write({
            "state": "active",
            "date_activated": fields.Datetime.now(),
        })

        # Step 3: audit log.
        reason = self.notes
        if not reason:
            reason = (
                "Manual promotion by %s; jobs_completed=%d/%d"
            ) % (
                self.env.user.login,
                cand.probationary_jobs_completed,
                cand.probationary_jobs_target,
            )
        self.env["neon.onboarding.audit.log"].sudo().create({
            "candidate_id": cand.id,
            "action": "promote_active",
            "actor_id": self.env.user.id,
            "reason": reason,
            "previous_state": prev,
            "new_state": "active",
        })

        cand.sudo().message_post(body=_(
            "Promoted to Active by %(actor)s. Reason: "
            "%(reason)s%(user_created)s"
        ) % {
            "actor": self.env.user.name,
            "reason": reason,
            "user_created": (
                _(". New user account created (login=%s).")
                % new_user.login if new_user else ""),
        })

        _logger.info(
            "neon_onboarding M6: candidate %s promoted to "
            "active by %s (user_created=%s).",
            cand.display_name,
            self.env.user.login,
            bool(new_user))

        return {"type": "ir.actions.act_window_close"}
