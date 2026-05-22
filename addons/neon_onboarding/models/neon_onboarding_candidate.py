# -*- coding: utf-8 -*-
"""neon.onboarding.candidate -- main onboarding record.

Phase 7b M1 scope. State machine: candidate -> cert_collection
-> probationary -> active. Skip Onboarding wizard provides the
admin override jump straight to active.

M4 extension: collected_cert_ids o2m (reverse of cert.
candidate_id), required_cert_type_ids related-like compute
from template, all_required_certs_satisfied derived from
matching active certs against required types, auto-transition
cert_collection -> probationary when the satisfaction flag
flips True (fired from the cert-side constrains hook in
neon_training).

Reference: docs/phase-7b/schema-sketch.md section 4.1.
"""
import logging

from odoo import api, fields, models, SUPERUSER_ID, _
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
    # Requirement template (M2 -- auto-populated from
    # intended_role; manual override permitted via the form)
    # ============================================================
    requirement_template_id = fields.Many2one(
        "neon.onboarding.requirement.template",
        string="Requirement Template",
        compute="_compute_requirement_template",
        store=True,
        readonly=False,
        tracking=True,
        help="Auto-populated from intended_role when an active "
             "template exists. Can be overridden manually per-"
             "candidate (readonly=False makes the compute a "
             "default, not a lock).",
    )

    @api.depends("intended_role")
    def _compute_requirement_template(self):
        Template = self.env["neon.onboarding.requirement.template"]
        for rec in self:
            if not rec.intended_role:
                rec.requirement_template_id = False
                continue
            template = Template.sudo().search([
                ("intended_role", "=", rec.intended_role),
                ("active", "=", True),
            ], limit=1)
            rec.requirement_template_id = template

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
        compute="_compute_probationary_jobs_completed",
        store=True,
        copy=False,
        help="Count of completed event_jobs the candidate has "
             "worked since their promote_probationary audit "
             "log entry (or since date_started if no audit "
             "entry exists). Recomputes on user_id or state "
             "changes; full recompute triggered manually when "
             "event_job state changes -- a daily cron in M11 "
             "polish handles the refresh-on-event-completion "
             "case.",
    )

    @api.depends("user_id", "state", "audit_log_ids")
    def _compute_probationary_jobs_completed(self):
        """Count completed event_jobs the candidate's user_id
        has been crew on, since the promote_probationary audit
        log timestamp (or date_started fallback).

        Defensive against missing neon_jobs via env.get pattern,
        though in practice neon_jobs is always installed when
        neon_onboarding is (manifest depends).
        """
        Crew = self.env.get("commercial.job.crew")
        for rec in self:
            if (not rec.user_id
                    or rec.state not in (
                        "probationary", "active")
                    or Crew is None):
                rec.probationary_jobs_completed = 0
                continue
            # Find the promote_probationary audit entry to
            # establish the counting cutoff.
            promote_log = rec.audit_log_ids.filtered(
                lambda a: a.action == "promote_probationary"
            ).sorted("timestamp")[:1]
            since = (promote_log.timestamp
                     if promote_log
                     else rec.date_started)
            # Crew rows the candidate's user is on; map to
            # event_jobs; filter completed + within window.
            crew_rows = Crew.sudo().search([
                ("user_id", "=", rec.user_id.id),
            ])
            event_jobs = crew_rows.mapped("job_id.event_job_ids")
            rec.probationary_jobs_completed = len(
                event_jobs.filtered(
                    lambda ej: ej.state == "completed"
                    and ej.event_date
                    and ej.event_date >= (
                        since.date() if since else ej.event_date)
                ))

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
    # M4 -- cert satisfaction + auto-transition logic
    # ============================================================
    collected_cert_ids = fields.One2many(
        "neon.training.certification",
        "candidate_id",
        string="Collected Certifications",
        help="Certifications uploaded for this candidate. "
             "Reverse of neon.training.certification."
             "candidate_id (added in neon_training 17.0.8.1.0).",
    )
    required_cert_type_ids = fields.Many2many(
        "neon.training.certification.type",
        compute="_compute_required_cert_type_ids",
        store=True,
        string="Required Cert Types",
        help="Mirrors requirement_template_id.required_cert_"
             "type_ids; recomputed on template change. Stored "
             "for kanban + form display.",
    )
    all_required_certs_satisfied = fields.Boolean(
        compute="_compute_all_required_certs_satisfied",
        store=True,
        string="All Required Certs Verified",
        help="True when every required cert type has at "
             "least one collected cert in state='active'. "
             "Drives the cert_collection -> probationary "
             "auto-transition via the cert-side constrains "
             "hook in neon_training.",
    )

    @api.depends("requirement_template_id",
                 "requirement_template_id.required_cert_type_ids")
    def _compute_required_cert_type_ids(self):
        for rec in self:
            tmpl = rec.requirement_template_id
            rec.required_cert_type_ids = (
                tmpl.required_cert_type_ids if tmpl else False)

    @api.depends("required_cert_type_ids",
                 "collected_cert_ids",
                 "collected_cert_ids.state",
                 "collected_cert_ids.type_id")
    def _compute_all_required_certs_satisfied(self):
        for rec in self:
            if not rec.required_cert_type_ids:
                rec.all_required_certs_satisfied = False
                continue
            verified_types = rec.collected_cert_ids.filtered(
                lambda c: c.state == "active"
            ).mapped("type_id")
            rec.all_required_certs_satisfied = all(
                req in verified_types
                for req in rec.required_cert_type_ids
            )

    def _transition_to_probationary(self):
        """Automatic transition cert_collection -> probationary.
        Fired by the cert-side constrains hook (in
        neon_training) when the last required cert is verified.
        Writes an audit log entry with action='promote_
        probationary' and actor=SUPERUSER (the transition is
        system-driven, not user-driven).
        """
        self.ensure_one()
        if self.state != "cert_collection":
            return
        prev = self.state
        self.sudo().write({"state": "probationary"})
        self.env["neon.onboarding.audit.log"].sudo().create({
            "candidate_id": self.id,
            "action": "promote_probationary",
            "actor_id": SUPERUSER_ID,
            "reason": "Auto: all required certs verified.",
            "previous_state": prev,
            "new_state": "probationary",
        })
        self.sudo().message_post(body=_(
            "Auto-transitioned to Probationary: all required "
            "certifications verified."))
        _logger.info(
            "neon_onboarding M4: candidate %s auto-advanced "
            "to probationary (all required certs verified).",
            self.display_name)

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
