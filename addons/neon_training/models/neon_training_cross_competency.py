# -*- coding: utf-8 -*-
"""
P7a.M6 -- Cross-competency record (Schema Sketch section 2.4).

Captures real-world demonstrated competency on event_jobs without
requiring a formal certification. Robin's A4 framing: 'Data
analytics should also record if someone has been tested in other
field and has done job successfully.'

Example: Bob runs the MA3 console at the Standard Bank dinner;
Ranganai observes and records a cross-competency for (Bob, MA3
Console, that event). Bob does not gain a formal MA3 certification
but the system has structured evidence that he can operate one
under live conditions.

Downstream use (M9-M11): the layered assignment-gate logic checks
cross-competency records when a crew member lacks a required cert.
A matching cross-competency record DOWNGRADES the gate severity
by one tier (block -> warn, warn -> info). Schema sketch section
4.4.

Audit-trail discipline (H3=A): perm_unlink=0 for every group.
Corrections via new records, never via delete.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_PERFORMANCE_RATINGS = [
    ("below_expectation",    "Below Expectation"),
    ("met_expectation",      "Met Expectation"),
    ("exceeded_expectation", "Exceeded Expectation"),
]


class NeonTrainingCrossCompetency(models.Model):
    _name = "neon.training.cross_competency"
    _description = "Cross-Competency Demonstration Record"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "demonstrated_at desc, user_id"

    # ============================================================
    # Identity
    # ============================================================
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The person who demonstrated competency on this event.",
    )
    certification_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Competency",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The certification type this competency maps to (e.g. "
        "MA3 Console). A cross-competency does NOT grant a formal "
        "cert -- it records evidence of capability for downstream "
        "gate-downgrade logic in M9-M11.",
    )
    category_id = fields.Many2one(
        "neon.training.certification.category",
        string="Category",
        related="certification_type_id.category_id",
        store=True,
        index=True,
        readonly=True,
    )
    demonstrated_through_event_id = fields.Many2one(
        "commercial.event.job",
        string="Event",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The event_job where the competency was demonstrated. "
        "Restricting ondelete preserves the audit trail.",
    )
    event_partner_id = fields.Many2one(
        "res.partner",
        string="Event Client",
        related="demonstrated_through_event_id.commercial_job_id.partner_id",
        store=True,
        readonly=True,
        help="Client of the event where competency was demonstrated. "
        "Enables 'demonstrated competency at $client' reports.",
    )

    # ============================================================
    # Observation
    # ============================================================
    demonstrated_at = fields.Date(
        string="Demonstrated On",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
        help="When the competency was observed. Must fall within "
        "the event date range -7 days / +90 days (late recording "
        "OK; early observation tolerated).",
    )
    observed_by_id = fields.Many2one(
        "res.users",
        string="Observed By",
        required=True,
        default=lambda self: self._default_observed_by_id(),
        ondelete="restrict",
        tracking=True,
        help="The Lead Tech / signoff-authorised user who observed "
        "the demonstration. Constraint: must hold training_signoff "
        "or training_admin group.",
    )
    performance_rating = fields.Selection(
        _PERFORMANCE_RATINGS,
        string="Performance",
        required=True,
        default="met_expectation",
        tracking=True,
        help="Calibrated against the role's expected level. "
        "'Exceeded' = clearly better than the bar; 'Met' = at the "
        "bar; 'Below' = under bar but still operationally useful "
        "(captured for the audit + future training plan).",
    )
    notes = fields.Text(
        string="Notes",
        required=True,
        help="Specifics of the demonstration: what was the task, "
        "what was their level of comfort, anything observed about "
        "how they handled edge cases. Required to make the record "
        "actionable -- a structured competency observation without "
        "notes is just a checkbox.",
    )
    leads_to_certification = fields.Boolean(
        string="Promote to Cert?",
        default=False,
        tracking=True,
        help="Flag for follow-up: should this observation trigger "
        "a formal certification draft for review? M6 shipped the "
        "flag; M7 wires the actual promote-to-cert mechanism via "
        "action_promote_to_cert.",
    )
    # P7a.M7 -- reverse linkage to the cert(s) that were promoted
    # from this observation. Used by is_promoted to gate the
    # 'Promote' button visibility (hide after promotion to prevent
    # duplicates). One2many because the constraint allows only one
    # cert per source, but the relation shape is naturally o2m.
    promoted_cert_ids = fields.One2many(
        "neon.training.certification",
        "source_cross_competency_id",
        string="Promoted Certifications",
    )
    is_promoted = fields.Boolean(
        string="Already Promoted",
        compute="_compute_is_promoted",
        help="True when this observation has been promoted to a "
        "formal certification draft. Drives form-view button "
        "visibility -- the Promote action is hidden after first "
        "promotion to prevent duplicates.",
    )

    @api.depends("promoted_cert_ids")
    def _compute_is_promoted(self):
        for rec in self:
            rec.is_promoted = bool(rec.promoted_cert_ids)

    # ============================================================
    # Display
    # ============================================================
    def _compute_display_name(self):
        """Format: 'User -- Competency -- Date'. Matches the pattern
        on neon.training.certification for consistent chatter +
        M2O display rendering."""
        for rec in self:
            parts = []
            if rec.user_id:
                parts.append(rec.user_id.name)
            if rec.certification_type_id:
                parts.append(rec.certification_type_id.name)
            if rec.demonstrated_at:
                parts.append(fields.Date.to_string(rec.demonstrated_at))
            rec.display_name = " -- ".join(parts) or _(
                "New Cross-Competency")

    # ============================================================
    # Defaults
    # ============================================================
    @api.model
    def _default_observed_by_id(self):
        """Default the observer to the current user if they hold
        training_signoff or training_admin. Else False (the form's
        required attribute forces the user to pick someone)."""
        user = self.env.user
        if (user.has_group("neon_training.group_neon_training_signoff")
                or user.has_group(
                    "neon_training.group_neon_training_admin")):
            return user.id
        return False

    # ============================================================
    # Onchange -- soft user_id filter from event crew (DP3)
    # ============================================================
    @api.onchange("demonstrated_through_event_id")
    def _onchange_event_id_suggest_crew(self):
        """Soft suggestion: filter user_id picker to the event's
        assigned crew members (those with an Odoo login). Returns
        a domain that the form view applies as an autocomplete
        narrowing -- Lead Tech can still override (the constraint
        layer doesn't enforce membership; M9-M11 gating reads
        cross-competency records regardless of crew formality).

        Path: event_job -> commercial_job -> crew_assignment_ids
        -> user_id. Freelancers (partner_id only, no user_id) are
        excluded from the suggestion because cross-competency is
        per-user (needs an Odoo identity for portal access in
        Phase 7b).

        If no crew is assigned yet OR the path resolution fails,
        return no domain (fall through to unrestricted picker).
        """
        for rec in self:
            if not rec.demonstrated_through_event_id:
                return
            try:
                crew = rec.demonstrated_through_event_id.commercial_job_id\
                    .crew_assignment_ids
                user_ids = crew.mapped("user_id").ids
            except Exception:
                user_ids = []
            if user_ids:
                return {"domain": {"user_id": [("id", "in", user_ids)]}}
            return

    # ============================================================
    # Constraints
    # ============================================================
    _sql_constraints = [
        ("unique_user_type_event",
         "UNIQUE (user_id, certification_type_id, "
         "demonstrated_through_event_id)",
         "A cross-competency record already exists for this user, "
         "competency, and event. Edit the existing record (notes "
         "and rating are writeable by signoff/admin) instead of "
         "creating a duplicate."),
    ]

    @api.constrains("demonstrated_at")
    def _check_demonstrated_at_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.demonstrated_at and rec.demonstrated_at > today:
                raise ValidationError(_(
                    "Demonstrated date cannot be in the future "
                    "(got %s on %s).") % (
                        rec.demonstrated_at, rec.display_name))

    @api.constrains("observed_by_id")
    def _check_observed_by_authority(self):
        """observed_by_id must hold training_signoff or
        training_admin -- competence judgements come from
        authorised observers. ACL gates record creation too but
        this constraint catches direct ORM writes that might
        sidestep the form's default."""
        for rec in self:
            if not rec.observed_by_id:
                continue
            obs = rec.observed_by_id
            if not (obs.has_group(
                        "neon_training.group_neon_training_signoff")
                    or obs.has_group(
                        "neon_training.group_neon_training_admin")):
                raise ValidationError(_(
                    "Observer %(name)s is not authorised to record "
                    "cross-competency observations. Lead Tech "
                    "(signoff) or admin authority required.") % {
                        "name": obs.name})

    @api.constrains("demonstrated_at",
                    "demonstrated_through_event_id")
    def _check_demonstrated_within_event_range(self):
        """demonstrated_at must fall within the event's date range
        with a -7 day lead-in (early observations OK) and +90 day
        late-recording tolerance.

        If event_end_date is null, fall back to event_date as the
        upper anchor. If both are null (shouldn't happen given
        event_date is required upstream), the check is skipped
        defensively.
        """
        from datetime import timedelta
        for rec in self:
            if not rec.demonstrated_at:
                continue
            event = rec.demonstrated_through_event_id
            if not event:
                continue
            anchor_start = event.event_date
            anchor_end = event.event_end_date or event.event_date
            if not anchor_start:
                continue  # defensive; event without dates can't
                          # anchor the range
            lower = anchor_start - timedelta(days=7)
            upper = anchor_end + timedelta(days=90)
            if not (lower <= rec.demonstrated_at <= upper):
                raise ValidationError(_(
                    "Demonstrated date %(at)s is outside the event "
                    "window (%(lower)s to %(upper)s; event ran "
                    "%(start)s to %(end)s, with -7d / +90d "
                    "tolerance).") % {
                        "at": rec.demonstrated_at,
                        "lower": lower,
                        "upper": upper,
                        "start": anchor_start,
                        "end": anchor_end,
                    })

    # P7a.M7 -- field-lock after promotion. Once a cert has been
    # created from this observation, the user_id and certification
    # _type_id become source-of-truth values that the cert constraint
    # also enforces. Changing them here would orphan the cert OR
    # cause a constraint violation on the cert side. Block at the
    # source.
    @api.constrains("user_id", "certification_type_id",
                    "promoted_cert_ids")
    def _check_no_field_changes_after_promotion(self):
        for rec in self:
            if not rec.promoted_cert_ids:
                continue
            for cert in rec.promoted_cert_ids:
                if cert.user_id != rec.user_id:
                    raise ValidationError(_(
                        "Cannot change user_id on observation "
                        "%(name)s -- it has been promoted to "
                        "certification %(cert)s. Source-of-truth "
                        "locked.") % {
                            "name": rec.display_name,
                            "cert": cert.display_name,
                        })
                if cert.type_id != rec.certification_type_id:
                    raise ValidationError(_(
                        "Cannot change certification_type_id on "
                        "observation %(name)s -- it has been "
                        "promoted to certification %(cert)s. "
                        "Source-of-truth locked.") % {
                            "name": rec.display_name,
                            "cert": cert.display_name,
                        })

    # ============================================================
    # P7a.M7 -- promote to certification draft
    # ============================================================
    def action_promote_to_cert(self):
        """Create a draft cert record from this observation (DP2).

        Constraints:
        - leads_to_certification must be True (only flagged
          observations are promotable)
        - cannot re-promote: is_promoted must be False (one cert
          per observation)

        Returns ir.actions.act_window opening the new draft cert
        so the user can complete date_obtained, attachments, and
        external_trainer_name before submitting for verification.
        """
        self.ensure_one()
        if not self.leads_to_certification:
            raise UserError(_(
                "Observation %s is not flagged for cert promotion. "
                "Set 'Promote to Cert?' to True first, then retry.") % (
                    self.display_name,))
        if self.is_promoted:
            existing = self.promoted_cert_ids[0]
            raise UserError(_(
                "Observation %(name)s has already been promoted to "
                "certification %(cert)s. Open that draft to complete "
                "it, or create a fresh observation for a new "
                "promotion.") % {
                    "name": self.display_name,
                    "cert": existing.display_name,
                })

        Cert = self.env["neon.training.certification"]
        new_cert = Cert.sudo().create({
            "user_id": self.user_id.id,
            "type_id": self.certification_type_id.id,
            "state": "draft",
            "source_cross_competency_id": self.id,
            "notes": _(
                "Promoted from cross-competency observation on "
                "%(event)s (%(date)s). Observed by %(observer)s. "
                "Performance: %(rating)s.\n\n"
                "Original notes:\n%(notes)s"
            ) % {
                "event": self.demonstrated_through_event_id.display_name,
                "date": fields.Date.to_string(self.demonstrated_at),
                "observer": self.observed_by_id.name,
                "rating": dict(
                    self._fields["performance_rating"].selection
                ).get(self.performance_rating, self.performance_rating),
                "notes": self.notes,
            },
        })

        # Chatter on both ends so the linkage is discoverable.
        self.message_post(body=_(
            "Promoted to certification draft "
            "<a href='#' data-oe-model='neon.training.certification' "
            "data-oe-id='%(id)s'>%(name)s</a>"
        ) % {
            "id": new_cert.id,
            "name": new_cert.display_name,
        })
        new_cert.message_post(body=_(
            "Created from cross-competency observation on "
            "%(event)s dated %(date)s, observed by %(observer)s."
        ) % {
            "event": self.demonstrated_through_event_id.display_name,
            "date": fields.Date.to_string(self.demonstrated_at),
            "observer": self.observed_by_id.name,
        })

        # Open the new draft for the user to complete.
        return {
            "type": "ir.actions.act_window",
            "name": _("Promoted Certification Draft"),
            "res_model": "neon.training.certification",
            "res_id": new_cert.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_promoted_certs(self):
        """Open the cert(s) promoted from this observation. Called
        from the 'Already Promoted' badge on the form view."""
        self.ensure_one()
        certs = self.promoted_cert_ids
        if not certs:
            return False
        if len(certs) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": _("Promoted Certification"),
                "res_model": "neon.training.certification",
                "res_id": certs[0].id,
                "view_mode": "form",
                "target": "current",
            }
        return {
            "type": "ir.actions.act_window",
            "name": _("Promoted Certifications"),
            "res_model": "neon.training.certification",
            "domain": [("id", "in", certs.ids)],
            "view_mode": "tree,form",
            "target": "current",
        }
