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

from odoo import _, api, fields, models
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
        return True

    def action_verify(self):
        """pending_verification -> active (or draft -> active for
        the admin-record-and-verify-in-one-step path). Signoff or
        admin only."""
        self._require_signoff_or_admin("verify")
        for rec in self:
            if rec.state not in ("draft", "pending_verification"):
                raise UserError(_(
                    "Only Draft or Pending Verification certifications "
                    "can be verified (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
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
        for rec in self:
            if rec.state != "suspended":
                raise UserError(_(
                    "Only Suspended certifications can be "
                    "reactivated (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            rec.write({
                "state": "active",
                "suspension_reason": False,
            })
            rec.message_post(body=_(
                "Reactivated by %s.") % self.env.user.name)
        return True

    def action_mark_expired(self):
        """active -> expired. Admin or signoff. Manual transition
        for M2; cron lands in M4 to fire this automatically when
        date_expires passes."""
        self._require_signoff_or_admin("mark expired")
        for rec in self:
            if rec.state != "active":
                raise UserError(_(
                    "Only Active certifications can be marked "
                    "expired (%s is %s).") % (
                        rec.display_name,
                        dict(_CERT_STATES)[rec.state]))
            rec.write({"state": "expired"})
            rec.message_post(body=_(
                "Marked expired by %s.") % self.env.user.name)
        return True
