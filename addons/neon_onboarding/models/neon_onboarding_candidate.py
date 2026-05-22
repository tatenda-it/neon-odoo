# -*- coding: utf-8 -*-
"""neon.onboarding.candidate -- main onboarding record.

Phase 7b M1 scope. State machine: candidate -> cert_collection
-> probationary -> active. Skip Onboarding wizard provides the
admin override jump straight to active.

Reference: docs/phase-7b/schema-sketch.md section 4.1.
"""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


_CANDIDATE_STATES = [
    ("candidate", "Candidate"),
    ("cert_collection", "Cert Collection"),
    ("probationary", "Probationary"),
    ("active", "Active"),
]


_INTENDED_ROLES = [
    ("driver", "Driver"),
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
    ("runner", "Runner"),
]


class NeonOnboardingCandidate(models.Model):
    _name = "neon.onboarding.candidate"
    _description = "Onboarding Candidate"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "state asc, date_started desc, id desc"

    # ============================================================
    # Identity + contact
    # ============================================================
    name = fields.Char(
        string="Full Name",
        required=True,
        tracking=True,
        help="Display name (e.g., 'Arnold Mukandatsama').",
    )
    intended_role = fields.Selection(
        _INTENDED_ROLES,
        string="Intended Role",
        required=True,
        tracking=True,
        help="Drives requirement template selection from M2. "
             "Probationary candidates are downgraded to runner "
             "regardless of this field until activation.",
    )
    contact_phone = fields.Char(
        string="Contact Phone",
        required=True,
        tracking=True,
        help="Mandatory for WhatsApp dispatch (Phase 9). "
             "Include country code, e.g. +263...",
    )
    contact_email = fields.Char(
        string="Contact Email",
        tracking=True,
        help="Optional. If set, becomes res.users.login on "
             "activation; otherwise a login is generated.",
    )
    emergency_contact_name = fields.Char(
        string="Emergency Contact Name",
    )
    emergency_contact_phone = fields.Char(
        string="Emergency Contact Phone",
    )
    photo = fields.Binary(
        string="Photo",
        attachment=True,
        help="Crew profile photo. Cropped to 64px circle on "
             "kanban cards (M3).",
    )

    # ============================================================
    # State machine
    # ============================================================
    state = fields.Selection(
        _CANDIDATE_STATES,
        string="State",
        default="candidate",
        required=True,
        tracking=True,
        index=True,
        help="See schema-sketch section 3 transitions table.",
    )

    # ============================================================
    # User linkage (set on activation)
    # ============================================================
    user_id = fields.Many2one(
        "res.users",
        string="User Account",
        ondelete="restrict",
        tracking=True,
        copy=False,
        help="Linked res.users record. Populated at activation; "
             "null while pre-active. Skip wizard creates the "
             "user record when this candidate has none.",
    )

    # ============================================================
    # Dates
    # ============================================================
    date_started = fields.Datetime(
        string="Started",
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
    )
    date_activated = fields.Datetime(
        string="Activated",
        readonly=True,
        copy=False,
        tracking=True,
        help="Set when state transitions to 'active'.",
    )

    # ============================================================
    # Probationary tracking (M1 stub; M5 converts to computed)
    # ============================================================
    probationary_jobs_target = fields.Integer(
        string="Probationary Jobs Target",
        default=3,
        help="Manager-overridable default per DP1.",
    )
    probationary_jobs_completed = fields.Integer(
        string="Probationary Jobs Completed",
        default=0,
        copy=False,
        help="M1 stub -- plain Integer. M5 converts to computed "
             "from commercial.job.crew + job.state='completed'.",
    )

    # ============================================================
    # Override metadata
    # ============================================================
    bypass_reason = fields.Char(
        string="Bypass Reason",
        copy=False,
        help="Required when bypass_actor_id is set. Populated "
             "by Skip Onboarding wizard.",
    )
    bypass_actor_id = fields.Many2one(
        "res.users",
        string="Bypass Actor",
        copy=False,
        ondelete="restrict",
        help="Superuser who triggered Skip Onboarding override.",
    )

    # ============================================================
    # Audit trail reverse relation
    # ============================================================
    audit_log_ids = fields.One2many(
        "neon.onboarding.audit.log",
        "candidate_id",
        string="Audit Log",
        readonly=True,
    )

    # ============================================================
    # SQL + Python constraints
    # ============================================================
    _sql_constraints = [
        ("candidate_user_id_unique",
         "unique(user_id)",
         "A candidate is linked to at most one user account."),
    ]

    @api.constrains("bypass_actor_id", "bypass_reason")
    def _check_bypass_pair(self):
        """Either both are set or both are null -- never one
        without the other. Skip wizard always populates both;
        only manual edits can desync them.
        """
        for rec in self:
            has_actor = bool(rec.bypass_actor_id)
            has_reason = bool(rec.bypass_reason
                              and rec.bypass_reason.strip())
            if has_actor != has_reason:
                raise ValidationError(_(
                    "Bypass actor and bypass reason must be set "
                    "together. Use the Skip Onboarding wizard "
                    "instead of editing these fields directly."))

    @api.constrains("state", "user_id")
    def _check_active_requires_user(self):
        """state='active' requires user_id. Cannot be active
        without a backing res.users record.
        """
        for rec in self:
            if rec.state == "active" and not rec.user_id:
                raise ValidationError(_(
                    "An active candidate must have a linked "
                    "user account. Set user_id before "
                    "transitioning to Active, or use the Skip "
                    "Onboarding wizard which creates the user."))
