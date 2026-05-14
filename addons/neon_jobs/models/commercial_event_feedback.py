# -*- coding: utf-8 -*-
"""
P3.M7 — Multi-channel Client Feedback.

Replaces the free-form client_feedback Text field on
commercial.event.job with a structured record per feedback
event. Multiple records per event_job allowed (Q15 — 3-channel
approach: email survey + phone + in-person).

No state machine. Records are captured once, may trigger a
follow-up workflow (is_follow_up_required + follow_up_owner),
but the feedback itself doesn't transition.

Authority to log: Sales / Crew Leader / Manager (D6). Regular
crew tier sees feedback on their own events via row-level rule
but cannot create.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .commercial_event_job import _GROUP_XMLIDS


_logger = logging.getLogger(__name__)


FEEDBACK_CHANNELS = [
    ("email_survey", "Email Survey"),
    ("phone",        "Phone Call"),
    ("in_person",    "In Person"),
    ("written",      "Written / Letter"),
]
FEEDBACK_SENTIMENTS = [
    ("positive", "Positive"),
    ("neutral",  "Neutral"),
    ("negative", "Negative"),
    ("mixed",    "Mixed"),
]


class CommercialEventFeedback(models.Model):
    _name = "commercial.event.feedback"
    _description = "Event Client Feedback Record"
    _inherit = ["mail.thread", "mail.activity.mixin", "action.centre.mixin"]
    _order = "captured_at desc, id desc"

    # === Identity ===
    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    # === Related from event_job ===
    commercial_job_id = fields.Many2one(
        related="event_job_id.commercial_job_id",
        store=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related="event_job_id.partner_id",
        store=True,
        readonly=True,
        string="Client",
    )
    event_date = fields.Date(
        related="event_job_id.event_date",
        store=True,
        readonly=True,
    )

    # === Capture metadata ===
    channel = fields.Selection(
        FEEDBACK_CHANNELS,
        string="Channel",
        required=True,
        default="phone",
        tracking=True,
    )
    captured_by = fields.Many2one(
        "res.users",
        string="Captured By",
        default=lambda self: self.env.user.id,
        readonly=True,
        copy=False,
    )
    captured_at = fields.Datetime(
        string="Captured At",
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
    )

    # === Content ===
    feedback_text = fields.Text(
        string="Feedback",
        required=True,
        tracking=True,
        help="The client's actual words / paraphrased account.",
    )
    sentiment = fields.Selection(
        FEEDBACK_SENTIMENTS,
        string="Sentiment",
        default="neutral",
        tracking=True,
        help="Manual classification — Phase 8 may layer NLP on top.",
    )
    rating = fields.Integer(
        string="Rating (1-5)",
        help="Numeric score from a survey. Leave 0 when not applicable.",
    )

    # === Follow-up workflow ===
    is_follow_up_required = fields.Boolean(
        string="Follow-up Required",
        default=False,
        tracking=True,
    )
    follow_up_owner = fields.Many2one(
        "res.users",
        string="Follow-up Owner",
        help="Who should chase the follow-up — typically Sales Rep or "
        "Manager. Required when is_follow_up_required=True.",
    )
    follow_up_notes = fields.Text(string="Follow-up Notes")
    follow_up_completed = fields.Boolean(
        string="Follow-up Completed",
        default=False,
        tracking=True,
    )
    follow_up_completed_at = fields.Datetime(
        string="Follow-up Completed At",
        readonly=True,
        copy=False,
    )
    follow_up_completed_by = fields.Many2one(
        "res.users",
        string="Follow-up Completed By",
        readonly=True,
        copy=False,
    )

    # === UI gates ===
    can_complete_follow_up = fields.Boolean(compute="_compute_action_buttons")

    @api.depends("is_follow_up_required", "follow_up_completed")
    @api.depends_context("uid")
    def _compute_action_buttons(self):
        for rec in self:
            rec.can_complete_follow_up = (
                rec.is_follow_up_required
                and not rec.follow_up_completed
                and rec._user_in_any_group(("manager",))
            )

    # === Authority helpers ===
    def _user_in_any_group(self, group_keys):
        return any(
            self.env.user.has_group(_GROUP_XMLIDS[k]) for k in group_keys
        )

    def _user_can_log_feedback(self):
        """Sales / Crew Leader / Manager (D6). Regular crew cannot
        log client feedback."""
        return self._user_in_any_group(("user", "crew_leader", "manager"))

    @api.constrains("rating")
    def _check_rating_range(self):
        for rec in self:
            if rec.rating and (rec.rating < 0 or rec.rating > 5):
                raise UserError(_(
                    "Rating must be between 0 (n/a) and 5. Got: %s"
                ) % rec.rating)

    @api.constrains("is_follow_up_required", "follow_up_owner")
    def _check_follow_up_owner(self):
        for rec in self:
            if rec.is_follow_up_required and not rec.follow_up_owner:
                raise UserError(_(
                    "Follow-up requires an owner. Assign a Follow-up "
                    "Owner (typically Sales Rep or Manager) before "
                    "saving."
                ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            ej_id = vals.get("event_job_id")
            if ej_id and not self._user_can_log_feedback():
                raise UserError(_(
                    "Only Sales, Crew Leader, or Manager can log "
                    "client feedback. Crew members should escalate."
                ))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.event.feedback")
                    or _("New")
                )
        records = super().create(vals_list)
        # P4.M7 — fire feedback_followup when the feedback record is
        # captured with is_follow_up_required=True. Per D2, prefer
        # the per-record follow_up_owner over role resolution.
        for rec in records:
            if rec.is_follow_up_required:
                kwargs = {}
                if rec.follow_up_owner and rec.follow_up_owner.exists():
                    kwargs["primary_assignee_id"] = rec.follow_up_owner.id
                try:
                    rec._action_centre_create_item(
                        "feedback_followup", **kwargs)
                except Exception as e:
                    _logger.warning(
                        "Action Centre feedback_followup trigger "
                        "failed for %s: %s", rec.name, e,
                    )
        return records

    def write(self, vals):
        # P4.M7 — flip / completion hooks. We need to compare against
        # the pre-write state for each record, so snapshot before
        # super().write(). The mixin's idempotency keeps repeated
        # writes (e.g. setting follow_up_completed=True alongside
        # other field changes) safe.
        flips_to_required = self.env["commercial.event.feedback"]
        if vals.get("is_follow_up_required") is True:
            flips_to_required = self.filtered(
                lambda r: not r.is_follow_up_required
            )
        # Auto-close cases: follow_up_completed flipping to True, OR
        # is_follow_up_required being explicitly cleared.
        closes_followup = self.env["commercial.event.feedback"]
        if (
            vals.get("follow_up_completed") is True
            or vals.get("is_follow_up_required") is False
        ):
            closes_followup = self
        result = super().write(vals)
        for rec in flips_to_required:
            kwargs = {}
            if rec.follow_up_owner and rec.follow_up_owner.exists():
                kwargs["primary_assignee_id"] = rec.follow_up_owner.id
            try:
                rec._action_centre_create_item(
                    "feedback_followup", **kwargs)
            except Exception as e:
                _logger.warning(
                    "Action Centre feedback_followup trigger (write) "
                    "failed for %s: %s", rec.name, e,
                )
        for rec in closes_followup:
            try:
                # force=True: feedback_followup is a task so the
                # mixin's default eligibility filter would skip it,
                # but follow_up_completed=True is the source's
                # explicit "this is done" signal.
                rec._action_centre_close_items(
                    "feedback_followup", force=True)
            except Exception as e:
                _logger.warning(
                    "Action Centre feedback_followup auto-close "
                    "failed for %s: %s", rec.name, e,
                )
        return result

    @api.model
    def _evaluate_feedback_followup_backfill(self):
        """P4.M7 — catch records whose feedback_followup trigger was
        missed by the real-time create()/write() hooks (e.g. records
        loaded by a data migration, or created before the addon was
        upgraded). Search the last 30 days for is_follow_up_required
        records with no open item, fire the trigger. Mixin idempotency
        skips any record that already has an open item.
        """
        cutoff = fields.Date.today() - timedelta(days=30)
        pending = self.sudo().search([
            ("is_follow_up_required", "=", True),
            ("follow_up_completed", "=", False),
            ("create_date", ">=", cutoff),
        ])
        created = 0
        for fb in pending:
            kwargs = {}
            if fb.follow_up_owner and fb.follow_up_owner.exists():
                kwargs["primary_assignee_id"] = fb.follow_up_owner.id
            try:
                item = fb._action_centre_create_item(
                    "feedback_followup", **kwargs)
                if item:
                    created += 1
            except Exception as e:
                _logger.warning(
                    "feedback_followup backfill failed for %s: %s",
                    fb.name, e,
                )
        _logger.info(
            "Action Centre feedback_followup backfill: %d candidates, "
            "%d items created/refreshed.",
            len(pending), created,
        )
        return True

    def action_complete_follow_up(self, notes=None):
        """Manager marks the follow-up workflow done. Captures who +
        when so the audit trail shows who closed the loop."""
        if notes is None:
            notes = self.env.context.get("default_follow_up_notes")
        for rec in self:
            if not rec._user_in_any_group(("manager",)):
                raise UserError(_(
                    "Only Managers can mark a follow-up complete."
                ))
            if not rec.is_follow_up_required:
                raise UserError(_(
                    "No follow-up was required on this feedback."
                ))
            if rec.follow_up_completed:
                raise UserError(_(
                    "Follow-up already marked complete on %s."
                ) % rec.follow_up_completed_at)
            vals = {
                "follow_up_completed": True,
                "follow_up_completed_at": fields.Datetime.now(),
                "follow_up_completed_by": self.env.user.id,
            }
            if notes:
                vals["follow_up_notes"] = notes
            rec.sudo().write(vals)
            rec.sudo().message_post(
                body=_("Follow-up completed by %s") % self.env.user.name,
                author_id=self.env.user.partner_id.id,
            )
        return True
