# -*- coding: utf-8 -*-
"""
P3.M6 — Scope Change Tracking.

Lead Tech / Crew Chief logs scope changes on-site DIRECTLY against
the event_job (Q11 refined — fresh on-site context wins over a
hand-off to Sales). Sales Rep later reviews entries in the
'Pending Sales Review' queue and reclassifies the billing_action
from the default 'pending_decision' to one of the 6 concrete
actions.

State machine: logged → reviewed → finalised (+ cancelled from any
non-terminal).

Authority matrix (D4 / D5 in the task spec):
  log:       Sales, Crew Leader, Manager, Crew Chief on this event
             (regular crew member is NOT authorised — escalate)
  review:    Sales, Crew Leader, Manager
  finalise:  Manager only
  cancel:    Manager only

P3.M6 ships pure log only (D6) — invoice_line_id / sale_order_line_id
are placeholders for Phase 8+ auto-generation. No logic touches
them in this milestone.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .commercial_event_job import _GROUP_XMLIDS


_logger = logging.getLogger(__name__)


SCOPE_CHANGE_STATES = [
    ("logged",     "Logged"),
    ("reviewed",   "Reviewed"),
    ("finalised",  "Finalised"),
    ("cancelled",  "Cancelled"),
]
_TERMINAL_STATES = ("finalised", "cancelled")

BILLING_ACTIONS = [
    ("included",         "Included (no extra charge)"),
    ("chargeable",       "Chargeable (will bill)"),
    ("goodwill",         "Goodwill (free, logged)"),
    ("write_off",        "Write-Off (absorbed cost)"),
    ("to_be_quoted",     "To Be Quoted (new quote line)"),
    ("to_be_invoiced",   "To Be Invoiced (append to invoice)"),
    ("pending_decision", "Pending Decision"),
]
_DEFAULT_BILLING = "pending_decision"

SCOPE_CHANGE_TYPES = [
    ("addition",     "Addition"),
    ("modification", "Modification"),
    ("removal",      "Removal"),
    ("replacement",  "Replacement"),
]


class CommercialScopeChange(models.Model):
    _name = "commercial.scope.change"
    _description = "Event Job Scope Change Log Entry"
    _inherit = ["mail.thread", "mail.activity.mixin", "action.centre.mixin"]
    _order = "occurred_at desc, id desc"

    # === Identity ===
    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    # === Related from event_job (denormalised for filtering / search) ===
    commercial_job_id = fields.Many2one(
        related="event_job_id.commercial_job_id",
        store=True,
        readonly=True,
        string="Commercial Job",
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
    currency_id = fields.Many2one(
        related="event_job_id.currency_id",
        readonly=True,
    )

    # === What changed ===
    description = fields.Text(
        string="Description",
        required=True,
        tracking=True,
        help="What was added, modified, removed, or replaced "
        "compared to the original event scope.",
    )
    reason = fields.Text(
        string="Reason",
        help="Why the change was needed (client request, venue "
        "constraint, equipment failure, weather, etc.).",
    )
    scope_change_type = fields.Selection(
        SCOPE_CHANGE_TYPES,
        string="Change Type",
        default="addition",
    )

    # === Timing ===
    occurred_at = fields.Datetime(
        string="Occurred At",
        default=fields.Datetime.now,
        required=True,
        help="When the change actually happened on-site or in the "
        "field — may pre-date logged_at if recorded after the fact.",
    )
    logged_at = fields.Datetime(
        string="Logged At",
        default=fields.Datetime.now,
        readonly=True,
        copy=False,
    )
    logged_by = fields.Many2one(
        "res.users",
        string="Logged By",
        default=lambda self: self.env.user.id,
        readonly=True,
        copy=False,
    )

    # === Billing classification (Q12) ===
    billing_action = fields.Selection(
        BILLING_ACTIONS,
        string="Billing Action",
        default=_DEFAULT_BILLING,
        required=True,
        tracking=True,
    )
    billing_notes = fields.Text(
        string="Billing Notes",
        help="Explanation of the billing decision — why chargeable, "
        "why goodwill, why written off, etc.",
    )
    estimated_value = fields.Monetary(
        string="Estimated Value",
        currency_field="currency_id",
        help="Rough cost estimate for Phase 8 analytics. Sales "
        "finalises the actual figure on the invoice or quote.",
    )

    # === Sales review (Q11 reclassification flow) ===
    reviewed_at = fields.Datetime(string="Reviewed At", readonly=True, copy=False)
    reviewed_by = fields.Many2one(
        "res.users",
        string="Reviewed By",
        readonly=True,
        copy=False,
    )

    # === Finalisation ===
    finalised_at = fields.Datetime(string="Finalised At", readonly=True, copy=False)
    finalised_by = fields.Many2one(
        "res.users",
        string="Finalised By",
        readonly=True,
        copy=False,
    )

    # === State ===
    state = fields.Selection(
        SCOPE_CHANGE_STATES,
        string="State",
        default="logged",
        required=True,
        tracking=True,
        copy=False,
    )

    # === Hooks for future auto-generation (P8+, pure log for now) ===
    invoice_line_id = fields.Many2one(
        "account.move.line",
        string="Invoice Line",
        readonly=True,
        copy=False,
        help="Reserved for Phase 8+ auto-generation. P3.M6 ships "
        "pure log — no logic touches this field yet.",
    )
    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        string="Sale Order Line",
        readonly=True,
        copy=False,
        help="Reserved for Phase 8+ auto-generation. P3.M6 ships "
        "pure log — no logic touches this field yet.",
    )

    # === UI gate booleans (header buttons) ===
    can_review = fields.Boolean(compute="_compute_action_buttons")
    can_finalise = fields.Boolean(compute="_compute_action_buttons")
    can_cancel = fields.Boolean(compute="_compute_action_buttons")

    # ============================================================
    # === Authority helpers (mirror P3.M3 / P3.M5 patterns)
    # ============================================================
    def _user_in_any_group(self, group_keys):
        return any(
            self.env.user.has_group(_GROUP_XMLIDS[k]) for k in group_keys
        )

    def _is_event_crew_chief(self):
        self.ensure_one()
        chief = self.event_job_id.crew_chief_id
        return bool(chief and chief.id == self.env.uid)

    def _user_can_log_scope_change(self):
        """D4 — Sales, Crew Leader, Manager always; Crew Chief on this
        event_job; regular crew (group_neon_jobs_crew without being
        the assigned crew_chief) is NOT authorised."""
        self.ensure_one()
        if self._user_in_any_group(("user", "crew_leader", "manager")):
            return True
        if self._is_event_crew_chief():
            return True
        return False

    def _user_can_log_for_event(self, event_job):
        """Same gate as _user_can_log_scope_change but usable at create
        time, before a record exists. Event-Job dependent (crew_chief
        path needs the event_job to resolve the chief)."""
        if self._user_in_any_group(("user", "crew_leader", "manager")):
            return True
        chief = event_job.sudo().crew_chief_id
        return bool(chief and chief.id == self.env.uid)

    def _user_can_review(self):
        return self._user_in_any_group(("user", "crew_leader", "manager"))

    def _user_can_finalise(self):
        return self._user_in_any_group(("manager",))

    def _user_can_cancel(self):
        return self._user_in_any_group(("manager",))

    # ============================================================
    # === Create / sequence
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            ej_id = vals.get("event_job_id")
            if ej_id:
                ej = self.env["commercial.event.job"].sudo().browse(ej_id)
                if not self._user_can_log_for_event(ej):
                    raise UserError(_(
                        "Crew members cannot log scope changes — "
                        "escalate to the Crew Chief or Lead Tech, who "
                        "will log it on your behalf."
                    ))
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.scope.change")
                    or _("New")
                )
        records = super().create(vals_list)
        # P4.M7 — fire the scope_change Action Centre trigger. The
        # mixin's PREFERRED_ASSIGNEE_FIELDS lookup can't reach
        # event_job_id.lead_tech_id from a scope_change record (no
        # direct lead_tech_id field on this model), so we pass the
        # resolved user explicitly when available.
        for rec in records:
            kwargs = {}
            ej_lead = rec.event_job_id.lead_tech_id
            if ej_lead and ej_lead.exists():
                kwargs["primary_assignee_id"] = ej_lead.id
            try:
                rec._action_centre_create_item("scope_change", **kwargs)
            except Exception as e:
                _logger.warning(
                    "Action Centre scope_change trigger failed for "
                    "%s: %s", rec.name, e,
                )
        return records

    # ============================================================
    # === Computed action gates for the header buttons
    # ============================================================
    @api.depends("state", "billing_action")
    @api.depends_context("uid")
    def _compute_action_buttons(self):
        for rec in self:
            rec.can_review = (
                rec.state == "logged"
                and rec._user_can_review()
            )
            rec.can_finalise = (
                rec.state == "reviewed"
                and rec._user_can_finalise()
            )
            rec.can_cancel = (
                rec.state not in _TERMINAL_STATES
                and rec._user_can_cancel()
            )

    # ============================================================
    # === State transitions
    # ============================================================
    def action_mark_reviewed(self, billing_action=None, billing_notes=None):
        """logged → reviewed. Sales / Crew Leader / Manager. Requires
        a concrete billing_action (not pending_decision) — that's the
        whole point of the Sales review pass."""
        if billing_action is None:
            billing_action = self.env.context.get("default_billing_action")
        if billing_notes is None:
            billing_notes = self.env.context.get("default_billing_notes")
        if not billing_action or billing_action == _DEFAULT_BILLING:
            raise UserError(_(
                "Pick a concrete Billing Action (Included / Chargeable "
                "/ Goodwill / Write-Off / To Be Quoted / To Be Invoiced) "
                "before marking the scope change as Reviewed."
            ))
        valid = {key for key, _label in BILLING_ACTIONS}
        if billing_action not in valid:
            raise UserError(_(
                "Unknown billing action: %s."
            ) % billing_action)
        for rec in self:
            if not rec._user_can_review():
                raise UserError(_(
                    "Only Sales, Crew Leader, or Manager can review a "
                    "scope change."
                ))
            if rec.state != "logged":
                raise UserError(_(
                    "Can only review a scope change in 'Logged' state. "
                    "Current state: %s."
                ) % rec.state)
            vals = {
                "state": "reviewed",
                "billing_action": billing_action,
                "reviewed_at": fields.Datetime.now(),
                "reviewed_by": self.env.user.id,
            }
            if billing_notes:
                vals["billing_notes"] = billing_notes
            rec.sudo().write(vals)
            label = dict(BILLING_ACTIONS).get(billing_action, billing_action)
            rec.sudo().message_post(
                body=_(
                    "Reviewed by %(user)s: billing_action=%(action)s"
                ) % {"user": self.env.user.name, "action": label},
                author_id=self.env.user.partner_id.id,
            )
        return True

    def action_finalise(self):
        """reviewed → finalised. Manager only."""
        for rec in self:
            if not rec._user_can_finalise():
                raise UserError(_(
                    "Only Managers can finalise a scope change."
                ))
            if rec.state != "reviewed":
                raise UserError(_(
                    "Can only finalise a scope change in 'Reviewed' "
                    "state. Current state: %s."
                ) % rec.state)
            rec.sudo().write({
                "state": "finalised",
                "finalised_at": fields.Datetime.now(),
                "finalised_by": self.env.user.id,
            })
            rec.sudo().message_post(
                body=_("Finalised by %s") % self.env.user.name,
                author_id=self.env.user.partner_id.id,
            )
        return True

    def action_cancel(self, reason=None):
        """Any non-terminal → cancelled. Manager only. Reason required."""
        if reason is None:
            reason = self.env.context.get("default_cancel_reason")
        if not reason or not str(reason).strip():
            raise UserError(_(
                "A reason is required when cancelling a scope change — "
                "the audit trail keeps a record of why it was voided."
            ))
        reason = str(reason).strip()
        for rec in self:
            if not rec._user_can_cancel():
                raise UserError(_(
                    "Only Managers can cancel a scope change."
                ))
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "Scope change is already in a terminal state (%s)."
                ) % rec.state)
            rec.sudo().write({"state": "cancelled"})
            rec.sudo().message_post(
                body=_(
                    "Cancelled by %(user)s. Reason: %(reason)s"
                ) % {"user": self.env.user.name, "reason": reason},
                author_id=self.env.user.partner_id.id,
            )
        return True
