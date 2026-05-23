# -*- coding: utf-8 -*-
"""neon.external.training.booking -- booking record + state
machine + notification dispatcher.

Phase 7c M2. State machine + reference auto-gen + cost field
with admin-only group visibility. M3 layers the approval
workflow on top; M4 wires auto-cert issuance on
cert_issued.

State graph:

    draft <-> pending_approval -> booked -> attended -> completed -> cert_issued
                                        |
                                        +-> no_show
                                        |
                                        +-> cancelled (most states)

Transitions are enforced by the action_* methods (Odoo
@api.constrains can't see prior state, so transition
checks live where the user invokes them).
"""
import logging
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


_STATE_SELECTION = [
    ("draft", "Draft"),
    ("pending_approval", "Pending Approval"),
    ("booked", "Booked"),
    ("attended", "Attended"),
    ("completed", "Completed"),
    ("cert_issued", "Cert Issued"),
    ("cancelled", "Cancelled"),
    ("no_show", "No Show"),
]


# Allowed transitions: source -> {valid destinations}.
# Anything not listed here raises UserError.
_ALLOWED_TRANSITIONS = {
    "draft": {"pending_approval", "cancelled"},
    "pending_approval": {"draft", "booked", "cancelled"},
    "booked": {"attended", "no_show", "cancelled"},
    "attended": {"completed", "cancelled"},
    "completed": {"cert_issued", "cancelled"},
    # Terminal-ish; M3+ rules may relax.
    "cert_issued": set(),
    "cancelled": set(),
    "no_show": {"cancelled"},
}


class NeonExternalTrainingBooking(models.Model):
    _name = "neon.external.training.booking"
    _description = "Neon External Training Booking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "scheduled_date desc, id desc"
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    reference = fields.Char(
        string="Reference",
        readonly=True,
        copy=False,
        index=True,
        help="Auto-generated BKG-YYYY-NNN by the booking "
             "sequence at create time.",
    )
    name = fields.Char(
        string="Booking",
        compute="_compute_name",
        store=True,
        help="Display name: reference + course + crew.",
    )

    # ------------------------------------------------------------------
    # Refs
    # ------------------------------------------------------------------
    vendor_id = fields.Many2one(
        "neon.external.training.vendor",
        string="Vendor",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    course_name = fields.Char(
        required=True,
        tracking=True,
    )
    crew_user_id = fields.Many2one(
        "res.users",
        string="Crew Member",
        required=True,
        domain=[("share", "=", False)],
        tracking=True,
    )
    cert_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Cert Type",
        ondelete="set null",
        help="Optional. If set, M4 auto-issues a "
             "neon.training.certification on cert_issued.",
    )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    scheduled_date = fields.Date(
        required=True,
        tracking=True,
    )
    duration_days = fields.Integer(
        default=1,
        tracking=True,
    )
    location = fields.Char(tracking=True)

    # ------------------------------------------------------------------
    # Cost (admin-only visibility via groups attribute)
    # ------------------------------------------------------------------
    cost_amount = fields.Monetary(
        string="Cost",
        currency_field="currency_id",
        default=0.0,
        tracking=True,
        groups="neon_core.group_neon_superuser,"
               "neon_core.group_neon_bookkeeper",
        help="Cost to Neon for this booking. Visible only to "
             "superuser + bookkeeper tiers.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: (
            self.env.company.currency_id.id),
    )

    # ------------------------------------------------------------------
    # Workflow state
    # ------------------------------------------------------------------
    state = fields.Selection(
        _STATE_SELECTION,
        string="Status",
        default="draft",
        tracking=True,
        required=True,
        copy=False,
    )
    date_attended = fields.Date(
        string="Attended On",
        readonly=True,
        copy=False,
    )
    date_completed = fields.Date(
        string="Completed On",
        readonly=True,
        copy=False,
    )

    notes = fields.Text()

    # ------------------------------------------------------------------
    # M3 -- approval workflow audit fields
    # ------------------------------------------------------------------
    approved_by_id = fields.Many2one(
        "res.users",
        string="Approved By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approval_date = fields.Datetime(
        string="Approval Date",
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(
        string="Rejection Reason",
        readonly=True,
        copy=False,
    )

    # ------------------------------------------------------------------
    # M4 -- auto-cert issuance reverse pointer
    # ------------------------------------------------------------------
    issued_cert_id = fields.Many2one(
        "neon.training.certification",
        string="Issued Certificate",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="The neon.training.certification record created "
             "when this booking transitioned to cert_issued. "
             "Populated by action_mark_cert_issued (M4). "
             "Cert outlives the booking -- ondelete=set null.",
    )

    _sql_constraints = [
        ("booking_reference_unique",
         "UNIQUE(reference)",
         "Booking reference must be unique."),
    ]

    # ==================================================================
    # Create / compute
    # ==================================================================
    @api.depends("reference", "course_name", "crew_user_id")
    def _compute_name(self):
        for rec in self:
            crew = (rec.crew_user_id.name
                    if rec.crew_user_id else "(no crew)")
            rec.name = "%s: %s -- %s" % (
                rec.reference or "(new)",
                rec.course_name or "(no course)",
                crew,
            )

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("reference"):
                vals["reference"] = Seq.next_by_code(
                    "neon.external.training.booking"
                ) or "/"
        return super().create(vals_list)

    # ==================================================================
    # Validation
    # ==================================================================
    # ==================================================================
    # M5 -- kanban drag-drop routes state writes through the
    # transition guard
    # ==================================================================
    def write(self, vals):
        """When a write changes the state field, route it
        through the _transition_to guard so invalid jumps
        raise UserError. _transition_to sets a context flag
        so its own write() lands cleanly without re-entry.
        """
        if (
            "state" in vals
            and not self.env.context.get(
                "neon_p7c_internal_transition")
        ):
            new_state = vals["state"]
            for rec in self:
                if rec.state != new_state:
                    # _transition_to handles its own write
                    # of state + any extra_vals; we strip
                    # state from this batch write below.
                    rec._transition_to(new_state)
            vals = {k: v for k, v in vals.items()
                    if k != "state"}
            if not vals:
                return True
        return super().write(vals)

    @api.constrains("cost_amount")
    def _check_cost_non_negative(self):
        for rec in self:
            if (rec.cost_amount or 0.0) < 0:
                raise ValidationError(_(
                    "Cost cannot be negative."))

    # ==================================================================
    # State machine -- transition guard
    # ==================================================================
    def _transition_to(self, new_state, extra_vals=None):
        """Move self to new_state, enforcing the
        _ALLOWED_TRANSITIONS graph. extra_vals merge into
        the write payload (e.g., date_attended)."""
        self.ensure_one()
        vals = dict(extra_vals or {})
        if self.state == new_state:
            # Idempotent no-op; surface as UserError so the
            # caller doesn't double-write.
            raise UserError(_(
                "Booking %s is already in state '%s'."
            ) % (self.reference or "(unsaved)", new_state))
        allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise UserError(_(
                "Cannot transition booking %s from "
                "'%s' to '%s'. Allowed next states: %s."
            ) % (
                self.reference or "(unsaved)",
                self.state, new_state,
                ", ".join(sorted(allowed)) or "(none)",
            ))
        vals["state"] = new_state
        # State transitions sudo() the actual write so crew
        # (read-only ACL via own-row rule) can submit + the
        # workflow methods stay the security boundary --
        # _m3_assert_superuser gates approve/reject; the
        # submit path is open to any user who can read the
        # booking (i.e., owns it via record rule).
        #
        # Context flag prevents the M5 write() override from
        # re-entering the state-machine guard for a write we
        # just authorized.
        self.sudo().with_context(
            neon_p7c_internal_transition=True
        ).write(vals)

    # ------------------------------------------------------------------
    # Public action methods (M2 ships stubs; M3 enriches
    # approval-side wiring).
    # ------------------------------------------------------------------
    def action_submit_for_approval(self):
        self.ensure_one()
        # Past-date guard at submission only.
        if (self.scheduled_date
                and self.scheduled_date < fields.Date.today()):
            raise UserError(_(
                "Cannot submit booking %s for approval -- "
                "scheduled_date %s is in the past."
            ) % (self.reference or "(unsaved)",
                 self.scheduled_date))
        if not self.vendor_id or not self.crew_user_id:
            raise UserError(_(
                "Vendor and Crew Member are required before "
                "submission for approval."))
        self._transition_to("pending_approval")
        # M3: route an activity to each managerial verifier
        # (Robin + Munashe per Phase 7a M7). Deferred import
        # so the module loads cleanly even if neon_training
        # is somehow absent at load time -- see
        # reference_odoo17_deferred_external_dep.md.
        verifiers = self._m3_approval_verifiers()
        # sudo() the chatter + activity creation so crew
        # (read-only ACL) can submit. The submitter identity
        # is captured in the body text below before the
        # sudo() flip.
        submitter_name = self.env.user.name
        if verifiers:
            for verifier in verifiers:
                self.sudo().activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("Approve external training "
                             "booking %s") % (
                                 self.reference or ""),
                    note=_(
                        "Vendor: %(vendor)s\n"
                        "Course: %(course)s\n"
                        "Crew: %(crew)s\n"
                        "Scheduled: %(date)s"
                    ) % {
                        "vendor": self.vendor_id.name,
                        "course": self.course_name,
                        "crew": self.crew_user_id.name,
                        "date": self.scheduled_date,
                    },
                    user_id=verifier.id,
                )
        self.sudo().message_post(body=_(
            "Submitted for approval by %s."
        ) % submitter_name)

    # ------------------------------------------------------------------
    # M3 -- approval / rejection
    # ------------------------------------------------------------------
    @api.model
    def _m3_approval_verifiers(self):
        """Resolve the managerial-verifier res.users
        recordset by reusing Phase 7a M7's
        _CERT_VERIFIER_LOGINS constant. Imported at call
        time so the module loads cleanly if neon_training
        is missing (defensive triple-guard convention)."""
        try:
            from odoo.addons.neon_training.models.\
neon_training_certification import (
                _CERT_VERIFIER_LOGINS as logins,
            )
        except Exception:  # noqa: BLE001
            return self.env["res.users"]
        return self.env["res.users"].sudo().search([
            ("login", "in", list(logins)),
            ("active", "=", True),
        ])

    def _m3_assert_superuser(self):
        """Approve/reject are restricted to the superuser
        tier. The view buttons also gate by groups, but the
        method enforcement here is the security boundary
        (calls via xmlrpc / shell bypass the view)."""
        superuser_group = self.env.ref(
            "neon_core.group_neon_superuser",
            raise_if_not_found=False)
        if (superuser_group
                and self.env.user.id != self.env.ref(
                    "base.user_root").id
                and superuser_group not in
                self.env.user.groups_id):
            from odoo.exceptions import AccessError
            raise AccessError(_(
                "Only Neon Superuser tier members may "
                "approve or reject external training "
                "bookings."))

    def _m3_close_approval_activity(self):
        """Mark this booking's pending approval activity
        complete (so the verifier inbox clears)."""
        act_type = self.env.ref(
            "mail.mail_activity_data_todo",
            raise_if_not_found=False)
        if not act_type:
            return
        activities = self.env["mail.activity"].sudo().search([
            ("res_model", "=", self._name),
            ("res_id", "=", self.id),
            ("activity_type_id", "=", act_type.id),
        ])
        if activities:
            activities.action_feedback(
                feedback="Closed by approval workflow.")

    def action_approve(self):
        self.ensure_one()
        self._m3_assert_superuser()
        approver_name = self.env.user.name
        approver_id = self.env.user.id
        self._transition_to("booked", {
            "approved_by_id": approver_id,
            "approval_date": fields.Datetime.now(),
        })
        self._m3_close_approval_activity()
        self.sudo().message_post(body=_(
            "Approved by %s."
        ) % approver_name)
        # M7 -- notify crew the booking is confirmed.
        self._notify_booking_confirmed()

    def action_reject(self, reason=None):
        """Reject a pending booking. Reason is required;
        the reject wizard passes it in. Transitions back
        to draft so the requester can edit + resubmit."""
        self.ensure_one()
        self._m3_assert_superuser()
        if not (reason and reason.strip()):
            raise UserError(_(
                "A rejection reason is required."))
        rejector_name = self.env.user.name
        self._transition_to("draft", {
            "rejection_reason": reason.strip(),
        })
        self._m3_close_approval_activity()
        self.sudo().message_post(body=_(
            "Rejected by %(user)s. Reason: %(reason)s"
        ) % {"user": rejector_name,
             "reason": reason.strip()})

    def action_open_reject_wizard(self):
        """Button handler that opens the reject wizard
        pre-populated with this booking's id."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Booking"),
            "res_model":
                "neon.external.training.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_booking_id": self.id,
            },
        }

    def action_mark_attended(self):
        self.ensure_one()
        self._transition_to("attended", {
            "date_attended": fields.Date.today(),
        })
        # M7 -- notify crew attendance was recorded.
        self._notify_attendance_recorded()

    def action_mark_completed(self):
        self.ensure_one()
        self._transition_to("completed", {
            "date_completed": fields.Date.today(),
        })

    def action_mark_cert_issued(self):
        """Issue a neon.training.certification for the crew
        member and transition the booking to cert_issued.

        Phase 7c M4 cross-module landing. Defensive triple-
        guard on the cert model: env.get returns None if
        neon_training is missing, in which case we raise
        UserError rather than crash.

        Cert is created with state='active' directly --
        Phase 7a normally walks through pending_verification,
        but external-training certs ARE verified at booking
        approval time (the superuser approved the cost and
        the vendor; the cert is the paperwork artefact).
        """
        self.ensure_one()
        # Idempotency check first: if a cert exists for this
        # booking, raising the "already issued" UserError is
        # more informative than the "state != completed"
        # one (the booking is in 'cert_issued' state precisely
        # because issuance already ran).
        if self.issued_cert_id:
            raise UserError(_(
                "Cert already issued for booking %s: %s. "
                "Cancel the existing cert before re-issuing."
            ) % (self.reference or "(unsaved)",
                 self.issued_cert_id.display_name))
        if self.state != "completed":
            raise UserError(_(
                "Can only issue a cert from 'completed' "
                "state (booking %s is in '%s')."
            ) % (self.reference or "(unsaved)", self.state))
        if not self.cert_type_id:
            raise UserError(_(
                "Cannot issue cert without cert_type_id "
                "set. Either pick the expected cert type on "
                "this booking or leave it at 'completed' "
                "state (no auto-cert)."))

        Cert = self.env.get("neon.training.certification")
        if Cert is None:
            raise UserError(_(
                "neon.training.certification model not "
                "available. Ensure neon_training is "
                "installed before issuing certs."))

        # Approver user identity drives signed_off_by_id;
        # falls back to the current user (the one marking
        # cert_issued) when no approval audit exists yet --
        # i.e., a booking that bypassed the M3 approval
        # workflow.
        signoff_user = (
            self.approved_by_id or self.env.user).id
        cert_vals = {
            "user_id": self.crew_user_id.id,
            "type_id": self.cert_type_id.id,
            "state": "active",
            "date_obtained": (
                self.date_completed or fields.Date.today()),
            "external_booking_id": self.id,
            "signed_off_by_id": signoff_user,
            # Populated unconditionally so cert types whose
            # category.requires_external_trainer would
            # otherwise trip _check_external_trainer_when_
            # required pass cleanly. Harmless on cert types
            # that don't require it.
            "external_trainer_name": self.vendor_id.name,
        }
        cert = Cert.sudo().create(cert_vals)

        # Transition booking to cert_issued + stash the
        # reverse pointer.
        self._transition_to("cert_issued", {
            "issued_cert_id": cert.id,
        })

        # Audit chatter on the booking side. Cert side gets
        # its own create-time chatter from mail.thread.
        self.sudo().message_post(body=_(
            "Cert issued: <a href='#' "
            "data-oe-model='neon.training.certification' "
            "data-oe-id='%(cert_id)d'>%(cert_name)s</a> "
            "via %(vendor)s."
        ) % {
            "cert_id": cert.id,
            "cert_name": cert.display_name,
            "vendor": self.vendor_id.name,
        })
        # M7 -- notify crew the cert is now active.
        self._notify_cert_issued()
        return True

    def action_view_issued_cert(self):
        """Smart-button handler that opens the cert this
        booking produced."""
        self.ensure_one()
        if not self.issued_cert_id:
            raise UserError(_(
                "No cert has been issued for booking %s "
                "yet."
            ) % (self.reference or "(unsaved)"))
        return {
            "type": "ir.actions.act_window",
            "name": _("Issued Certificate"),
            "res_model": "neon.training.certification",
            "res_id": self.issued_cert_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_cancel(self):
        self.ensure_one()
        self._transition_to("cancelled")

    def action_mark_no_show(self):
        self.ensure_one()
        self._transition_to("no_show")

    # ==================================================================
    # M7 -- notification dispatcher + 4 event hooks + 3d cron
    #
    # Pattern follows reference_neon_notification_stub_pattern.md
    # (Phase 7b M12 + Phase 7e M12 precedent). _notify_send is the
    # single override point Phase 9 swaps when wiring actual
    # WhatsApp + email dispatch. The event-specific hooks
    # (_notify_booking_confirmed etc.) stay stable -- their
    # channels=[...] list + body shape are the API contract.
    #
    # Stub marker [Notification stub - Phase 9 will send] uses
    # hyphen-minus per the reference doc; Phase 9's regression
    # smoke greps for that exact substring to confirm the
    # fallback path didn't fire.
    # ==================================================================
    def _notify_send(self, event, channels, subject, body):
        """Stub dispatcher. Phase 9 overrides to send actual
        WhatsApp + email via the dispatch engine.
        """
        self.ensure_one()
        crew_partner = (
            self.crew_user_id.partner_id
            if self.crew_user_id else False)
        crew_email = (crew_partner.email
                      if crew_partner else "(no email)")
        crew_phone = (crew_partner.phone
                      if crew_partner else "(no phone)")
        channel_str = ", ".join(channels)
        full_body = (
            "<p><strong>[Notification stub - Phase 9 will "
            "send]</strong></p>"
            "<p><b>Event:</b> %s</p>"
            "<p><b>Channels:</b> %s</p>"
            "<p><b>To:</b> %s / %s</p>"
            "<hr/>%s"
        ) % (event, channel_str,
             crew_email or "(no email)",
             crew_phone or "(no phone)",
             body)
        # sudo() to bypass per-user ACL on message_post --
        # cron + crew transitions both fire notifications and
        # the sender identity is the booking, not env.user.
        self.sudo().message_post(
            subject=subject,
            body=full_body,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def _notify_booking_confirmed(self):
        """Fires when state -> booked (approval succeeded)."""
        self.ensure_one()
        self._notify_send(
            event="external_booking_confirmed",
            channels=["email", "whatsapp"],
            subject=_(
                "Training booked - %s"
            ) % (self.course_name or ""),
            body=_(
                "<p>Hi %(crew)s,</p>"
                "<p>Your booking for %(course)s with "
                "%(vendor)s is confirmed for %(date)s.</p>"
            ) % {
                "crew": self.crew_user_id.name,
                "course": self.course_name,
                "vendor": self.vendor_id.name,
                "date": self.scheduled_date,
            },
        )

    def _notify_reminder_3d(self):
        """Fires 3 days before scheduled_date via the
        ir.cron in data/neon_external_training_cron.xml."""
        self.ensure_one()
        self._notify_send(
            event="external_booking_reminder_3d",
            channels=["whatsapp"],
            subject=_(
                "Reminder: %s in 3 days"
            ) % (self.course_name or ""),
            body=_(
                "<p>Hi %(crew)s,</p>"
                "<p>Reminder: %(course)s with %(vendor)s "
                "is in 3 days (%(date)s). Location: "
                "%(loc)s.</p>"
            ) % {
                "crew": self.crew_user_id.name,
                "course": self.course_name,
                "vendor": self.vendor_id.name,
                "date": self.scheduled_date,
                "loc": self.location or "TBD",
            },
        )

    def _notify_attendance_recorded(self):
        """Fires when state -> attended."""
        self.ensure_one()
        self._notify_send(
            event="external_booking_attended",
            channels=["email"],
            subject=_(
                "Attendance recorded - %s"
            ) % (self.course_name or ""),
            body=_(
                "<p>Hi %(crew)s,</p>"
                "<p>Your attendance at %(course)s has been "
                "recorded. Complete the training + submit "
                "your cert document to finalize.</p>"
            ) % {
                "crew": self.crew_user_id.name,
                "course": self.course_name,
            },
        )

    def _notify_cert_issued(self):
        """Fires when state -> cert_issued (cert created)."""
        self.ensure_one()
        cert_name = (
            self.issued_cert_id.display_name
            if self.issued_cert_id
            else _("your certification"))
        self._notify_send(
            event="external_booking_cert_issued",
            channels=["email", "whatsapp"],
            subject=_("Cert issued - %s") % cert_name,
            body=_(
                "<p>Hi %(crew)s,</p>"
                "<p>Your %(cert)s from %(vendor)s is now "
                "active in the system. Visible in "
                "/my/training.</p>"
            ) % {
                "crew": self.crew_user_id.name,
                "cert": cert_name,
                "vendor": self.vendor_id.name,
            },
        )

    # ------------------------------------------------------------------
    # M7 cron entry: find bookings exactly 3 days out + fire
    # the reminder notification. Stub mode posts to chatter;
    # Phase 9's _notify_send override will route to actual
    # channels.
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_3d_reminders(self):
        three_days_out = fields.Date.today() + timedelta(
            days=3)
        bookings = self.search([
            ("state", "=", "booked"),
            ("scheduled_date", "=", three_days_out),
        ])
        for booking in bookings:
            booking._notify_reminder_3d()
        _logger.info(
            "3d-reminder cron: notified %d booking(s) for "
            "scheduled_date %s",
            len(bookings), three_days_out)
        return True
