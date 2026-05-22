# -*- coding: utf-8 -*-
"""
P7a.M2 -- Certification Record (Schema Sketch section 2.3).

The per-person certification record. Append-only audit discipline
(H3=A): no perm_unlink for any group, even training_admin.
Corrections happen via state transitions (suspend / re-cert with
new record) rather than deletes.

State machine: draft -> pending_verification -> active ->
expired / suspended. Reactivation from suspended is admin-only.
'expired' is set automatically via cron once date_expires passes
(cron lands in M4; M2 ships the state value + manual transition
only).

Reference pattern: neon_finance.quote (Phase 6 M2). Inline state
validation per action method; mail.thread + mail.activity.mixin
for chatter and activity scheduling.
"""
import logging

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


# State machine -------------------------------------------------------
_CERT_STATES = [
    ("draft",                 "Draft"),
    ("pending_verification",  "Pending Verification"),
    ("active",                "Active"),
    ("expired",               "Expired"),
    ("suspended",             "Suspended"),
]

# 'expired' is auto via cron (M4); 'suspended' is manual admin override.
# Reactivation: suspended -> active via action_reactivate (admin only).
# expired -> active requires a NEW cert record (audit discipline H3=A).
_TERMINAL_STATES = ("expired", "suspended")


# Skill level options across all skill_level_modes (union per the
# gate-1 DECISION marker #3). @api.constrains validates the chosen
# level matches the type's effective_skill_level_mode.
_LEVEL_OPTIONS = [
    # binary
    ("pass",       "Pass"),
    ("fail",       "Fail"),
    # tiered_3
    ("basic",      "Basic"),
    ("standard",   "Standard"),
    ("expert",     "Expert"),
    # custom (Role Tier)
    ("lead_tech",  "Lead Tech"),
    ("tech",       "Tech"),
    ("runner",     "Runner"),
    ("driver",     "Driver"),
]

_LEVELS_BY_MODE = {
    "binary":   {"pass", "fail"},
    "tiered_3": {"basic", "standard", "expert"},
    "custom":   {"lead_tech", "tech", "runner", "driver"},
}


# P7a.M7 -- shared sign_off_authority -> group_xmlid mapping.
# Consumed by:
#   - _resolve_cc_partners (M5; renewal-notification CC list)
#   - _resolve_verify_authority_partners (M7; verify-TODO target)
#   - future M8 assignment-gate routing
# Single source of truth for the C1=D mixed-authority routing
# decisions. Update here, every consumer follows.
#
# Routing per Phase 7 ANSWERS document + walkthrough:
#   lead_tech         -> Ranganai (and any other Lead Tech)
#   od_md             -> Robin + Munashe (and any other approver)
#   external_trainer  -> admin tier (no internal trainer; admin
#                                    coordinates externally)
#   self_with_peer    -> admin tier (M7 defer; real peer mechanism
#                                    is Phase 11 polish)
_SIGN_OFF_AUTHORITY_GROUP = {
    "lead_tech":        "neon_jobs.group_neon_jobs_crew_leader",
    "od_md":            "neon_finance.group_neon_finance_approver",
    "external_trainer": "neon_training.group_neon_training_admin",
    "self_with_peer":   "neon_training.group_neon_training_admin",
}

# Phase 11 routing narrowing (post-neon_core landing):
# Cert verification ALWAYS routes to managerial superusers
# regardless of cert type's sign_off_authority field. The
# field stays on cert type as documentation (what kind of
# cert this is) but the verification step is universally
# managerial -- either Robin or Munashe can sign. Tatenda
# is explicitly excluded from this list (developer-superuser,
# not managerial). Action_verify's authority gate still
# consumes _SIGN_OFF_AUTHORITY_GROUP, as does M5's renewal
# CC broadcast via _resolve_cc_partners.
#
# Reference: .claude/reference_neon_cert_verification_routing.md
_CERT_VERIFIER_LOGINS = (
    "robin@neonhiring.co.zw",
    "munashe@neonhiring.co.zw",
)


class NeonTrainingCertification(models.Model):
    _name = "neon.training.certification"
    _description = "Training Certification Record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "state, date_expires desc, user_id"

    # ============================================================
    # Identity + scope
    # ============================================================
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The certified person. Org-wide per A2=B -- crew, "
        "office staff, freelancers all eligible.",
    )
    type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Certification Type",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    category_id = fields.Many2one(
        "neon.training.certification.category",
        string="Category",
        related="type_id.category_id",
        store=True,
        index=True,
        readonly=True,
    )

    # ============================================================
    # Level (skill grading) -- union Selection per DECISION #3
    # ============================================================
    level = fields.Selection(
        _LEVEL_OPTIONS,
        string="Level",
        tracking=True,
        help="Skill level. Valid options depend on the type's "
        "effective_skill_level_mode: binary = Pass/Fail; tiered_3 "
        "= Basic/Standard/Expert; custom = Lead Tech/Tech/Runner/"
        "Driver. @api.constrains enforces the mapping.",
    )
    effective_skill_level_mode = fields.Selection(
        related="type_id.effective_skill_level_mode",
        store=True,
        readonly=True,
    )
    # P7a.M3 -- narrows the level dropdown to the subset valid for
    # the current type's effective_skill_level_mode. Consumed by the
    # neon_dynamic_selection JS widget on the form view via
    # options="{'available_field': 'available_levels'}".
    # Comma-separated key list (e.g. "pass,fail" or "basic,standard,
    # expert"). Empty when type_id is unset -- widget falls back to
    # showing all 9 options so the user can still see the choices
    # without picking a type first.
    available_levels = fields.Char(
        string="Available Levels (widget hint)",
        compute="_compute_available_levels",
        help="Internal field consumed by the level dropdown's "
        "neon_dynamic_selection widget. Not rendered directly.",
    )

    # ============================================================
    # State machine
    # ============================================================
    state = fields.Selection(
        _CERT_STATES,
        required=True,
        default="draft",
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )

    # ============================================================
    # Dates
    # ============================================================
    date_obtained = fields.Date(
        string="Date Obtained",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="When the certification was earned. Cannot be in the "
        "future.",
    )
    date_expires = fields.Date(
        string="Date Expires",
        compute="_compute_date_expires",
        store=True,
        index=True,
        help="Computed as date_obtained + type_id.validity_months. "
        "When validity_months is 0 the certification has no expiry "
        "and this field stays empty.",
    )

    # ============================================================
    # P7a.M4 -- expiry window computed fields. Non-stored: recompute
    # on read, no overnight recompute storm. M5 reads expiry_urgency
    # to pick the right mail template; M4 only exposes the field.
    # ============================================================
    days_to_expiry = fields.Integer(
        string="Days to Expiry",
        compute="_compute_expiry_window",
        help="Days until date_expires (negative if past). 0 when "
        "date_expires is empty -- callers should check is_expiring_"
        "soon / expiry_urgency rather than days_to_expiry directly.",
    )
    is_expiring_soon = fields.Boolean(
        string="Expiring Soon",
        compute="_compute_expiry_window",
        help="True when an active cert expires within 90 days. "
        "Drives the user form badge + list-view warning decoration.",
    )
    expiry_urgency = fields.Selection(
        [
            ("none",      "None"),
            ("warn_90",   "Warning (90 days)"),
            ("warn_30",   "Warning (30 days)"),
            ("warn_7",    "Warning (7 days)"),
            ("expired",   "Expired"),
        ],
        string="Expiry Urgency",
        compute="_compute_expiry_window",
        help="Tier of urgency for renewal reminders. Empty / never-"
        "expires certs map to 'none'. M5 reads this to dispatch "
        "the matching mail.template.",
    )
    # P7a.M5 -- idempotency tracking for the dispatch cron. Records
    # the most-urgent tier for which a notification has been sent.
    # The cron skips records whose current expiry_urgency equals
    # last_notification_sent_urgency (no re-dispatch on the same
    # tier). When the urgency tier escalates (warn_90 -> warn_30 ->
    # warn_7) a new notification fires and this field updates.
    #
    # Reset triggers (see write() override): state transition out of
    # 'active', date_obtained edit, type_id swap (which changes
    # validity_months and may change date_expires). All three
    # signal a fresh notification cycle.
    last_notification_sent_urgency = fields.Selection(
        [
            ("warn_90",   "Warning (90 days)"),
            ("warn_30",   "Warning (30 days)"),
            ("warn_7",    "Warning (7 days)"),
        ],
        string="Last Notification Tier Sent",
        readonly=True,
        copy=False,
        help="Tracks the highest urgency tier already notified. "
        "Cron compares against expiry_urgency and only dispatches "
        "when the cert escalates to a more-urgent tier.",
    )

    # ============================================================
    # Sign-off + verification
    # ============================================================
    signed_off_by_id = fields.Many2one(
        "res.users",
        string="Signed-Off By",
        ondelete="restrict",
        tracking=True,
        help="Internal verifier -- e.g. Lead Tech for equipment, "
        "OD/MD for role tier. Populated when the cert was confirmed "
        "internally (not by an external trainer).",
    )
    external_trainer_name = fields.Char(
        string="External Trainer / Institution",
        tracking=True,
        help="Populated when sign-off authority is external_trainer "
        "(Safety + Driver Licence types). Either this OR "
        "signed_off_by_id must be set when the type's category "
        "requires_external_trainer is True.",
    )
    certificate_attachment_ids = fields.Many2many(
        "ir.attachment",
        "neon_training_cert_attachment_rel",
        "cert_id",
        "attachment_id",
        string="Certificate Attachments",
        help="PDFs or photos of the issued certificate. Per B3=C "
        "(self-upload + admin verify), crew can attach their own "
        "documents in pending_verification state; admin reviews "
        "and confirms authenticity before transitioning to active.",
    )
    verified = fields.Boolean(
        string="Verified",
        default=False,
        tracking=True,
        help="Set to True by action_verify(). Only admin or signoff "
        "tier can flip this. False on a newly self-uploaded cert "
        "until reviewed.",
    )
    verified_by_id = fields.Many2one(
        "res.users",
        string="Verified By",
        readonly=True,
        ondelete="restrict",
        tracking=True,
    )
    verified_at = fields.Datetime(
        string="Verified At",
        readonly=True,
        tracking=True,
    )

    # ============================================================
    # Notes + compliance
    # ============================================================
    notes = fields.Text(string="Notes")
    regulatory_reference = fields.Char(
        string="Regulatory Reference",
        tracking=True,
        help="Statutory reference number for Safety category certs "
        "(NSSA work-at-heights cert #, ZERA electrical authorisation "
        "#, etc.). Used in A3=C compliance reports.",
    )
    # P7a.M7 -- promotion source link. Populated only when the cert
    # was created from a cross-competency observation via
    # action_promote_to_cert. readonly=True post-creation (the
    # field is set by the promote action, not user-editable;
    # @api.constrains prevents the values from drifting away from
    # the source after creation).
    source_cross_competency_id = fields.Many2one(
        "neon.training.cross_competency",
        string="Source Observation",
        ondelete="restrict",
        readonly=True,
        copy=False,
        help="When set, this cert was promoted from the linked "
        "cross-competency observation. Read-only; user_id and "
        "type_id remain consistent with the source per the "
        "post-promotion constraint.",
    )

    # ============================================================
    # Helpers / display
    # ============================================================
    suspension_reason = fields.Text(
        string="Suspension Reason",
        readonly=True,
        help="Captured when action_suspend() is called. Cleared on "
        "reactivation.",
    )

    _sql_constraints = []  # all rules are Python-level (see _check_*)

    # ============================================================
    # Computes
    # ============================================================
    @api.depends("date_obtained", "type_id.validity_months")
    def _compute_date_expires(self):
        from dateutil.relativedelta import relativedelta
        for rec in self:
            months = rec.type_id.validity_months or 0
            if rec.date_obtained and months > 0:
                rec.date_expires = rec.date_obtained + relativedelta(
                    months=months)
            else:
                rec.date_expires = False

    @api.depends("date_expires", "state")
    def _compute_expiry_window(self):
        """P7a.M4 -- single compute that fills days_to_expiry,
        is_expiring_soon, and expiry_urgency. Three derived facets
        of the same date arithmetic; one compute saves three
        recompute passes per read.

        State note: expiry_urgency='expired' is set when the
        underlying state is already 'expired' OR when the record is
        active-but-past-date_expires (cron about to flip it). The
        form badge and list decorations show 'Expired' uniformly in
        either case so the user sees consistent UX whether the cron
        has run yet or not.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.date_expires:
                rec.days_to_expiry = 0
                rec.is_expiring_soon = False
                rec.expiry_urgency = "none"
                continue
            delta = (rec.date_expires - today).days
            rec.days_to_expiry = delta
            rec.is_expiring_soon = 0 < delta <= 90
            if rec.state == "expired" or delta <= 0:
                rec.expiry_urgency = "expired"
            elif delta <= 7:
                rec.expiry_urgency = "warn_7"
            elif delta <= 30:
                rec.expiry_urgency = "warn_30"
            elif delta <= 90:
                rec.expiry_urgency = "warn_90"
            else:
                rec.expiry_urgency = "none"

    @api.depends("type_id.effective_skill_level_mode",
                 "type_id.category_id.skill_level_mode")
    def _compute_available_levels(self):
        """Comma-separated list of level keys valid for the record's
        current type. Consumed by the neon_dynamic_selection widget
        on the form view. Empty when type_id is unset (widget then
        shows all 9 options so users can pick a level before locking
        a type)."""
        for rec in self:
            if not rec.type_id:
                rec.available_levels = ""
                continue
            mode = (rec.type_id.effective_skill_level_mode
                    or rec.type_id.category_id.skill_level_mode)
            allowed = sorted(_LEVELS_BY_MODE.get(mode, set()))
            rec.available_levels = ",".join(allowed)

    def _compute_display_name(self):
        """DECISION #2: meaningful display name for chatter, M2O
        display, breadcrumbs. Format: 'User -- Type -- Date'."""
        for rec in self:
            parts = []
            if rec.user_id:
                parts.append(rec.user_id.name)
            if rec.type_id:
                parts.append(rec.type_id.name)
            if rec.date_obtained:
                parts.append(fields.Date.to_string(rec.date_obtained))
            rec.display_name = " -- ".join(parts) or _("New Certification")

    # ============================================================
    # Constraints
    # ============================================================
    @api.constrains("user_id", "type_id", "state")
    def _check_unique_active_per_user_type(self):
        """A user can hold exactly one ACTIVE certification per type.
        Old expired/suspended/draft rows allowed alongside (audit
        trail). New cert supersedes old via the state machine: when
        a re-cert is issued, the prior 'active' should already be
        'expired' (auto-expiry) or 'suspended' (manual). DECISION #4.
        """
        for rec in self:
            if rec.state != "active":
                continue
            duplicates = self.sudo().search([
                ("user_id", "=", rec.user_id.id),
                ("type_id", "=", rec.type_id.id),
                ("state", "=", "active"),
                ("id", "!=", rec.id),
            ])
            if duplicates:
                raise ValidationError(_(
                    "%(user)s already holds an active "
                    "%(type)s certification (record %(rid)s). "
                    "Suspend or expire the existing record before "
                    "activating a new one.") % {
                        "user": rec.user_id.name,
                        "type": rec.type_id.name,
                        "rid": duplicates[0].id,
                    })

    @api.constrains("date_obtained")
    def _check_date_obtained_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_obtained and rec.date_obtained > today:
                raise ValidationError(_(
                    "Date obtained cannot be in the future "
                    "(got %s on %s).") % (
                        rec.date_obtained, rec.display_name))

    @api.constrains("level", "type_id")
    def _check_level_matches_mode(self):
        for rec in self:
            if not rec.level:
                continue  # level optional on draft / pending
            mode = (rec.type_id.effective_skill_level_mode
                    or rec.type_id.category_id.skill_level_mode)
            allowed = _LEVELS_BY_MODE.get(mode, set())
            if rec.level not in allowed:
                raise ValidationError(_(
                    "Level '%(level)s' is not valid for "
                    "%(type)s (mode: %(mode)s). Allowed: %(allowed)s."
                ) % {
                    "level": rec.level,
                    "type": rec.type_id.name,
                    "mode": mode,
                    "allowed": ", ".join(sorted(allowed)) or "(none)",
                })

    @api.constrains("external_trainer_name", "signed_off_by_id",
                    "type_id", "state")
    def _check_external_trainer_when_required(self):
        """When a category requires_external_trainer is True, the
        record must carry external_trainer_name OR signed_off_by_id
        before it can leave the draft state."""
        for rec in self:
            if rec.state == "draft":
                continue  # don't validate during initial entry
            if not rec.type_id.category_id.requires_external_trainer:
                continue
            if not rec.external_trainer_name and not rec.signed_off_by_id:
                raise ValidationError(_(
                    "Type %(type)s requires an external trainer. "
                    "Set External Trainer / Institution or Signed-Off "
                    "By before moving %(name)s out of draft.") % {
                        "type": rec.type_id.name,
                        "name": rec.display_name,
                    })

    @api.constrains("date_obtained", "verified_at")
    def _check_date_obtained_le_verified_at(self):
        for rec in self:
            if rec.date_obtained and rec.verified_at:
                if rec.verified_at.date() < rec.date_obtained:
                    raise ValidationError(_(
                        "Verified-at (%(va)s) cannot be earlier "
                        "than date obtained (%(do)s) on %(name)s.") % {
                            "va": rec.verified_at,
                            "do": rec.date_obtained,
                            "name": rec.display_name,
                        })

    # P7a.M7 -- source-of-truth consistency between a promoted cert
    # and its originating cross-competency observation. The promote
    # action seeds user_id + type_id from the source; this guard
    # prevents post-creation drift.
    @api.constrains("source_cross_competency_id", "user_id", "type_id")
    def _check_source_cross_competency_consistency(self):
        for rec in self:
            src = rec.source_cross_competency_id
            if not src:
                continue
            if rec.user_id != src.user_id:
                raise ValidationError(_(
                    "Promoted certification %(name)s: user_id "
                    "(%(cert_user)s) must match the source "
                    "observation's user_id (%(src_user)s).") % {
                        "name": rec.display_name,
                        "cert_user": rec.user_id.name,
                        "src_user": src.user_id.name,
                    })
            if rec.type_id != src.certification_type_id:
                raise ValidationError(_(
                    "Promoted certification %(name)s: type_id "
                    "(%(cert_type)s) must match the source "
                    "observation's certification_type_id "
                    "(%(src_type)s).") % {
                        "name": rec.display_name,
                        "cert_type": rec.type_id.name,
                        "src_type": src.certification_type_id.name,
                    })

    # ============================================================
    # P7a.M4 -- state='expired' is automatic-only.
    # ============================================================
    def write(self, vals):
        """Block manual writes that set state='expired' (DECISION
        #6 = DP3 strict). The cron and the protected
        _action_force_expire are the legitimate paths -- they both
        run as SUPERUSER_ID so this guard skips them. Manual UI or
        ORM writes from any other user raise UserError telling them
        to use Suspend instead.

        Implemented as a write() override rather than @api.constrains
        because the constraint receives the full mutated state and
        cannot distinguish "user set state=expired" from "user did
        something else AND the record happened to be expired before".
        write() sees the incoming vals dict directly.
        """
        if (vals.get("state") == "expired"
                and self.env.uid != SUPERUSER_ID):
            raise UserError(_(
                "Certification expiry is set automatically by the "
                "daily cron. To deactivate a certification manually, "
                "use Suspend instead -- it captures a reason in the "
                "audit trail and stays distinct from time-driven "
                "expiry."))
        # P7a.M5 -- reset triggers for last_notification_sent_
        # urgency. When state transitions out of 'active', or when
        # date_obtained / type_id changes (validity_months changes
        # via the type swap), the notification cycle restarts. The
        # next cron pass evaluates the (possibly new) expiry_
        # urgency and re-fires if it lands in a warn tier.
        resets_notification = (
            ("state" in vals and vals["state"] != "active")
            or "date_obtained" in vals
            or "type_id" in vals
        )
        if resets_notification and "last_notification_sent_urgency" not in vals:
            vals = dict(vals, last_notification_sent_urgency=False)
        return super().write(vals)

    # ============================================================
    # P7a.M5 -- TODO discard on renewal (DP2)
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        """When a new ACTIVE cert lands for a (user, type) pair
        that already has stale active TODOs from a prior record,
        mark those TODOs done via action_feedback (preserves
        chatter audit; vs unlink which destroys the trail).

        Most M2-style creates start at state='draft' so this hook
        no-ops -- the discard only fires when a brand-new record
        is created at state='active' (admin-record-and-verify-in-
        one-step path from M2). The far more common path is
        action_verify on an existing record, which doesn't change
        the (user, type) pair so doesn't trigger discard.

        For action_verify on a SECOND cert (renewal pattern: prior
        expired/suspended, new one verified), the .write() that
        transitions to active doesn't change (user, type) either.
        The polish item M5.b is to add a similar discard hook on
        action_verify's transition for the renewal case. M5 ships
        the create-time hook; verify-time hook tracked as polish.
        """
        records = super().create(vals_list)
        for rec in records:
            if rec.state != "active" or not rec.user_id or not rec.type_id:
                continue
            # Find any other ACTIVE cert with open TODOs for same
            # (user, type) -- the new record supersedes them. The
            # unique-active constraint elsewhere ensures at most
            # one OTHER active record exists at write time;
            # action_feedback runs on its activity_ids.
            prior = self.sudo().search([
                ("id", "!=", rec.id),
                ("user_id", "=", rec.user_id.id),
                ("type_id", "=", rec.type_id.id),
                ("state", "=", "active"),
            ])
            if not prior:
                continue
            for p in prior:
                if p.activity_ids:
                    feedback = _(
                        "Cert renewed by record %(new_id)s "
                        "(date_obtained %(obt)s). "
                        "Auto-closing renewal TODO."
                    ) % {
                        "new_id": rec.id,
                        "obt": fields.Date.to_string(rec.date_obtained),
                    }
                    p.activity_ids.action_feedback(feedback=feedback)
                    p.last_notification_sent_urgency = False
        return records

    # ============================================================
    # Onchanges
    # ============================================================
    @api.onchange("type_id")
    def _onchange_type_id(self):
        """When the type changes, clear level if the new type's
        skill_level_mode no longer accepts the current value.
        DECISION #3 refinement: log the prior level to chatter so
        the audit trail captures the auto-clear."""
        for rec in self:
            if not rec.type_id or not rec.level:
                continue
            mode = (rec.type_id.effective_skill_level_mode
                    or rec.type_id.category_id.skill_level_mode)
            if rec.level not in _LEVELS_BY_MODE.get(mode, set()):
                # Log to chatter before clearing -- gate-1 refinement.
                if rec.id:  # only post when record exists
                    rec.message_post(body=_(
                        "Level '%(old)s' cleared because the type "
                        "changed to %(type)s (mode: %(mode)s). "
                        "Pick a level valid for the new type."
                    ) % {
                        "old": dict(_LEVEL_OPTIONS).get(
                            rec.level, rec.level),
                        "type": rec.type_id.name,
                        "mode": mode,
                    })
                rec.level = False

    # ============================================================
    # State transitions -- inline validation per DECISION #1
    # ============================================================
    def _require_signoff_or_admin(self, action):
        if not (self.env.user.has_group(
                "neon_training.group_neon_training_signoff")
                or self.env.user.has_group(
                "neon_training.group_neon_training_admin")):
            raise AccessError(_(
                "Only Sign-Off or Admin users may %s "
                "certifications.") % action)

    def _require_admin(self, action):
        if not self.env.user.has_group(
                "neon_training.group_neon_training_admin"):
            raise AccessError(_(
                "Only Admin users may %s certifications.") % action)

    def action_submit_for_verification(self):
        """draft -> pending_verification. Available to the record
        owner (training_user) or any signoff/admin. Used when the
        crew member self-uploads a certificate and is ready for
        admin review."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_(
                    "Only draft certifications can be submitted "
                    "for verification (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            # The crew member can submit their own; signoff/admin
            # can submit anyone's. ACL + ir.rule handle the access
            # check; we add a method-level check for non-owner
            # non-signoff calls.
            if (rec.user_id != self.env.user
                    and not self.env.user.has_group(
                        "neon_training.group_neon_training_signoff")
                    and not self.env.user.has_group(
                        "neon_training.group_neon_training_admin")):
                raise AccessError(_(
                    "You can only submit your own certifications "
                    "for verification."))
            rec.write({"state": "pending_verification"})
            rec.message_post(body=_("Submitted for verification."))
            # P7a.M7 -- fire authority-routed verification TODO.
            rec._create_verification_todo()
        return True

    def _create_verification_todo(self):
        """P7a.M7 -- schedule a mail.activity TODO on the
        authority-routed user (via _resolve_verify_authority_
        partners + _SIGN_OFF_AUTHORITY_GROUP).

        Dedup: searches existing mail.activity for the same
        (res_model, res_id, summary ilike 'Verify%'); skips if
        found. Matches the M5/M6 dedup pattern.

        DP4 fallback handling: when the authority group is empty,
        the helper returns (admin_user, fallback_applied=True,
        original_group_xmlid). Post a chatter note about the
        fallback so production deploy can detect the gap and
        provision the right user.

        Returns True on creation, False on dedup-skip or empty
        recipient.
        """
        self.ensure_one()
        existing = self.env["mail.activity"].sudo().search([
            ("res_model", "=", "neon.training.certification"),
            ("res_id", "=", self.id),
            ("summary", "=ilike", "Verify%"),
        ], limit=1)
        if existing:
            return False

        target, fallback_applied, group_xmlid = (
            self._resolve_verify_authority_partners())
        if not target:
            _logger.info(
                "neon.training.certification: no verifier "
                "available for %s (authority=%s, group=%s); TODO "
                "skipped.", self.display_name,
                self.type_id.sign_off_authority, group_xmlid)
            # Deploy-gap chatter: under the Phase 11 override the
            # only way to land here is for both managerial
            # superusers (Robin + Munashe) to be missing from the
            # DB. Post a chatter note so the gap is detectable.
            self.sudo().message_post(
                subject=_("Verifier routing gap"),
                body=_(
                    "No managerial superusers available to verify "
                    "this certification. Expected one of: %s. "
                    "Provision Robin or Munashe and re-submit "
                    "for verification."
                ) % ", ".join(_CERT_VERIFIER_LOGINS))
            return False

        from datetime import timedelta
        deadline = fields.Date.context_today(self) + timedelta(days=7)
        self.sudo().activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=target.id,
            summary=_("Verify %(type)s certification for %(user)s") % {
                "type": self.type_id.name,
                "user": self.user_id.name,
            },
            note=_(
                "Cert: %(name)s\nState: %(state)s\n"
                "Date obtained: %(obt)s\nAuthority: %(auth)s"
            ) % {
                "name": self.display_name,
                "state": dict(_CERT_STATES)[self.state],
                "obt": (
                    fields.Date.to_string(self.date_obtained)
                    if self.date_obtained else "-"),
                "auth": self.type_id.sign_off_authority or "-",
            },
            date_deadline=deadline,
        )

        # Phase 11: subscribe ALL managerial verifiers as
        # followers so both Robin and Munashe see the cert in
        # their followed records / receive chatter notifications.
        # Either can complete action_verify; dual signoff not
        # required.
        all_verifiers = self.env["res.users"].sudo().search([
            ("login", "in", list(_CERT_VERIFIER_LOGINS)),
            ("active", "=", True),
        ])
        if all_verifiers:
            self.sudo().message_subscribe(
                partner_ids=all_verifiers.partner_id.ids)
        return True

    def action_verify(self):
        """pending_verification -> active (or draft -> active for
        the admin-record-and-verify-in-one-step path).

        P7a.M7 authority hardening (DECISION marker #9): the
        verifier must hold the authority group matching the cert
        type's sign_off_authority, OR be in
        group_neon_training_admin (admin override), OR be
        SUPERUSER_ID. Per-type authority routing per C1=D from the
        Phase 7 Open Questions:

          lead_tech         -> neon_jobs.group_neon_jobs_crew_leader
          od_md             -> neon_finance.group_neon_finance_approver
          external_trainer  -> neon_training.group_neon_training_admin
          self_with_peer    -> neon_training.group_neon_training_admin

        Admin bypass (and SUPERUSER) preserves emergency edits
        when the proper authority is unavailable -- e.g. Ranganai
        out of office, or production deploy before crew_leader
        users exist.
        """
        self._require_signoff_or_admin("verify")
        user = self.env.user
        is_admin = (
            user.has_group("neon_training.group_neon_training_admin")
            or user.id == SUPERUSER_ID)
        for rec in self:
            if rec.state not in ("draft", "pending_verification"):
                raise UserError(_(
                    "Only Draft or Pending Verification certifications "
                    "can be verified (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            # M7 authority gate.
            if not is_admin:
                authority = rec.type_id.sign_off_authority
                required_group_xmlid = (
                    _SIGN_OFF_AUTHORITY_GROUP.get(authority))
                if (required_group_xmlid
                        and not user.has_group(required_group_xmlid)):
                    raise UserError(_(
                        "Only %(authority)s authority can verify "
                        "%(type)s certifications. Contact a user in "
                        "%(group)s, or have an admin override.") % {
                            "authority": dict(
                                rec.type_id._fields[
                                    "sign_off_authority"].selection
                            ).get(authority, authority),
                            "type": rec.type_id.name,
                            "group": required_group_xmlid,
                        })
            rec.write({
                "state": "active",
                "verified": True,
                "verified_by_id": self.env.user.id,
                "verified_at": fields.Datetime.now(),
            })
            rec.message_post(body=_(
                "Verified by %s. Now active.") % self.env.user.name)
        return True

    def action_suspend(self):
        """active -> suspended. Admin only. Reason captured via
        context['suspension_reason'] (or surfaced via a wizard
        when the form button is wired)."""
        self._require_admin("suspend")
        reason = (self.env.context.get("suspension_reason") or "").strip()
        if not reason:
            raise UserError(_(
                "A suspension reason is required. Pass via context "
                "{'suspension_reason': '...'}."))
        for rec in self:
            if rec.state != "active":
                raise UserError(_(
                    "Only Active certifications can be suspended "
                    "(%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            rec.write({
                "state": "suspended",
                "suspension_reason": reason,
            })
            rec.message_post(body=_(
                "Suspended by %(user)s. Reason: %(reason)s"
            ) % {"user": self.env.user.name, "reason": reason})
        return True

    def action_reactivate(self):
        """suspended -> active. Admin only. Used when a suspension
        is lifted (e.g. clarification on the original concern)."""
        self._require_admin("reactivate")
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state != "suspended":
                raise UserError(_(
                    "Only Suspended certifications can be "
                    "reactivated (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            # P7a.M4 DECISION #7: block reactivation when the cert
            # has already aged out. Forces a fresh record with a new
            # date_obtained -- preserves the audit trail and keeps
            # the unique-active-per-(user,type) constraint honest.
            if rec.date_expires and rec.date_expires <= today:
                raise UserError(_(
                    "Cannot reactivate %s -- its date_expires "
                    "(%s) has passed. Create a new certification "
                    "record with a fresh date_obtained instead.") % (
                        rec.display_name, rec.date_expires))
            rec.write({
                "state": "active",
                "suspension_reason": False,
            })
            rec.message_post(body=_(
                "Reactivated by %s.") % self.env.user.name)
        return True

    def _action_force_expire(self):
        """P7a.M4 -- internal cron-only expiry transition. Reserved
        for _cron_expire_certifications and emergency superuser use.
        NOT exposed on the form (DP3 = strict per gate-1). Manual
        admin deactivation goes through action_suspend; legitimate
        time-based expiry goes through the cron which calls this.

        Skips suspended records (admin override trumps time) and
        records with no expiry (validity_months = 0). Idempotent on
        already-expired records.
        """
        if self.env.uid != SUPERUSER_ID:
            raise AccessError(_(
                "_action_force_expire is reserved for the daily "
                "cron (running as superuser) and emergency "
                "interventions. Use action_suspend for manual "
                "deactivation."))
        for rec in self:
            if rec.state in ("expired", "suspended"):
                continue
            if not rec.date_expires:
                continue
            rec.write({"state": "expired"})
            rec.message_post(body=_(
                "Auto-expired by cron -- date_expires (%s) passed."
            ) % rec.date_expires)

    @api.model
    def _cron_expire_certifications(self):
        """Daily expiry sweep. Active certs whose date_expires has
        passed flip to 'expired' and the transition is recorded in
        chatter. Mirrors neon_finance.quote._cron_expire_quotes.

        Suspended records and never-expires records (validity_months
        = 0) are skipped -- suspended takes precedence over time, and
        never-expires has no expiry to evaluate.

        Idempotent: re-running within the same day matches nothing
        new. Race window with admin suspend is narrow and acceptable
        for daily cadence (gate-1 DP1 = c).
        """
        today = fields.Date.context_today(self)
        expiring = self.sudo().search([
            ("state", "=", "active"),
            ("date_expires", "!=", False),
            ("date_expires", "<=", today),
        ])
        if not expiring:
            _logger.info(
                "neon.training.certification: no certs to expire "
                "today (%s).", today)
            return 0
        # Per-record write so message_post fires for each (audit
        # trail per H3=A). Bulk write would lose the per-record
        # chatter entry that downstream M5 reminders rely on.
        expiring.sudo()._action_force_expire()
        # Per-category breakdown for the cron log -- useful for
        # observability ("how many safety vs equipment certs auto-
        # expired today").
        by_category = {}
        for rec in expiring:
            cat = rec.category_id.code or "unknown"
            by_category[cat] = by_category.get(cat, 0) + 1
        _logger.info(
            "neon.training.certification: expired %d cert(s) on "
            "%s. By category: %s",
            len(expiring), today,
            ", ".join(f"{k}={v}" for k, v in sorted(by_category.items())),
        )
        return len(expiring)

    # ============================================================
    # P7a.M5 -- renewal notification dispatch
    # ============================================================
    _TEMPLATE_BY_URGENCY = {
        "warn_90": "neon_training.template_cert_expiring_90d",
        "warn_30": "neon_training.template_cert_expiring_30d",
        "warn_7":  "neon_training.template_cert_expiring_7d",
    }

    def _resolve_cc_partners(self):
        """Return the recipient partners that should be CC'd on a
        renewal notification, derived from the type's sign_off_
        authority. M5 introduced this helper; M7 refactored it to
        consume the shared _SIGN_OFF_AUTHORITY_GROUP constant.

        M5 distinction vs M7's _resolve_verify_authority_partners:
        M5 returns ALL members of the authority group (broadcast
        CC); M7 returns a single user (TODO targeting). Both share
        the authority -> group mapping.

        external_trainer and self_with_peer return empty res.partner
        for M5 (external trainer is a non-Odoo party; self_with_peer
        cert holder is already the email_to recipient -- no extra CC
        needed). The constant maps both to admin for M7's TODO path,
        but renewal CC stays empty here.

        Returns res.partner recordset (possibly empty).
        """
        self.ensure_one()
        authority = self.type_id.sign_off_authority
        # Renewal CCs go only to lead_tech and od_md. external_trainer
        # + self_with_peer return empty (admin doesn't need a renewal
        # CC; the cert holder is the email_to recipient).
        if authority not in ("lead_tech", "od_md"):
            return self.env["res.partner"]
        group_xmlid = _SIGN_OFF_AUTHORITY_GROUP.get(authority)
        if not group_xmlid:
            return self.env["res.partner"]
        grp = self.env.ref(group_xmlid, raise_if_not_found=False)
        return grp.users.partner_id if grp else self.env["res.partner"]

    def _resolve_verify_authority_partners(self):
        """Phase 11 override (post-neon_core): cert verification
        ALWAYS routes to managerial superusers regardless of cert
        type's sign_off_authority. Either verifier can sign; dual
        signoff is NOT required.

        Picks the first verifier alphabetically by login as the
        deterministic TODO assignee. Caller (_create_verification_
        todo) subscribes BOTH verifiers as followers so both
        receive chatter notifications.

        Returns (target_user, fallback_applied, group_xmlid),
        signature preserved for caller compatibility:
          target_user      -- first verifier in _CERT_VERIFIER_
                              LOGINS by login order, empty
                              recordset if neither exists on
                              this DB
          fallback_applied -- always False under the override
                              (no group-based fallback semantics;
                              verifiers are explicit logins)
          group_xmlid      -- sentinel "cert_verifier_managerial"
                              (not a real group xmlid; used in
                              chatter when verifiers are absent
                              so deploy-gap detection still works)
        """
        self.ensure_one()
        verifiers = self.env["res.users"].sudo().search([
            ("login", "in", list(_CERT_VERIFIER_LOGINS)),
            ("active", "=", True),
        ])
        empty_user = self.env["res.users"]
        if not verifiers:
            return empty_user, False, "cert_verifier_managerial"
        return (verifiers.sorted("login")[0], False,
                "cert_verifier_managerial")

    def _dispatch_renewal_notification(self):
        """Per-record dispatch: send the mail.template matching the
        current expiry_urgency + schedule a mail.activity TODO on
        the cert holder.

        Idempotency contract: caller checks last_notification_sent_
        urgency != expiry_urgency before invoking. This method
        always sends + always writes last_notification_sent_urgency.

        Returns True on success, False when no template matches
        (e.g. urgency='none' or 'expired' -- caller should filter).
        """
        self.ensure_one()
        tpl_xmlid = self._TEMPLATE_BY_URGENCY.get(self.expiry_urgency)
        if not tpl_xmlid:
            return False
        tpl = self.env.ref(tpl_xmlid, raise_if_not_found=False)
        if not tpl:
            _logger.warning(
                "Missing mail.template %s for cert %s (urgency=%s).",
                tpl_xmlid, self.display_name, self.expiry_urgency)
            return False
        # Send email -- mail.template.send_mail handles partner
        # resolution + queue.
        cc_partners = self._resolve_cc_partners()
        partner_ids = [self.user_id.partner_id.id]
        partner_ids.extend(cc_partners.ids)
        tpl.sudo().send_mail(
            self.id,
            force_send=False,
            email_values={
                "recipient_ids": [(6, 0, partner_ids)],
            },
        )
        # Schedule TODO activity on cert holder. Reuses the
        # activity_schedule helper from mail.activity.mixin per the
        # Phase 6 pattern (cost_line.py:243).
        summary = _(
            "Renew %(type)s certification -- expires %(date)s"
        ) % {
            "type": self.type_id.name,
            "date": fields.Date.to_string(self.date_expires),
        }
        self.activity_schedule(
            "mail.mail_activity_data_todo",
            user_id=self.user_id.id,
            summary=summary,
            date_deadline=self.date_expires,
        )
        # Record dispatch tier for idempotency.
        self.sudo().write({
            "last_notification_sent_urgency": self.expiry_urgency,
        })
        return True

    @api.model
    def _cron_dispatch_renewal_notifications(self):
        """Daily dispatch sweep. Picks up active certs whose
        expiry_urgency has escalated since the last notification
        and fires the matching mail.template + TODO.

        Idempotency:
          - last_notification_sent_urgency == current_urgency -> SKIP
          - last_notification_sent_urgency != current_urgency
            (escalation tier change OR first-time) -> DISPATCH
          - state transitions out of 'active' OR validity_months /
            date_obtained changes -> field reset by write() override
            (next cycle re-dispatches if still warn_*)

        Search filter excludes 'none' and 'expired'. M4's expiry
        cron transitions active -> expired separately; the order
        between the two crons does not affect correctness (M5's
        filter excludes 'expired' even if M4 has not yet run --
        the expiry_urgency compute returns 'expired' for past
        date_expires regardless of state).
        """
        active_with_urgency = self.sudo().search([
            ("state", "=", "active"),
            ("expiry_urgency", "in", ("warn_90", "warn_30", "warn_7")),
        ])
        if not active_with_urgency:
            _logger.info(
                "neon.training.certification: no renewal "
                "notifications to dispatch today.")
            return 0
        # Filter to records that haven't been notified on the
        # current tier yet (idempotency at the field level).
        to_dispatch = active_with_urgency.filtered(
            lambda c: c.last_notification_sent_urgency != c.expiry_urgency)
        if not to_dispatch:
            _logger.info(
                "neon.training.certification: %d cert(s) in warn "
                "tier but all already notified on current tier.",
                len(active_with_urgency))
            return 0
        sent = 0
        by_tier = {}
        for rec in to_dispatch:
            if rec._dispatch_renewal_notification():
                sent += 1
                by_tier[rec.expiry_urgency] = (
                    by_tier.get(rec.expiry_urgency, 0) + 1)
        _logger.info(
            "neon.training.certification: dispatched %d renewal "
            "notification(s). By tier: %s",
            sent,
            ", ".join(f"{k}={v}" for k, v in sorted(by_tier.items())),
        )
        return sent
