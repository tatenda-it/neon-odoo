# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


# State transition matrix per P2.M1 Schema Sketch §3.2.
# Manager group bypasses these — see _check_state_transition.
_STATE_TRANSITIONS = {
    "pending": ("active", "cancelled", "archived"),
    "active": ("completed", "cancelled"),
    "completed": (),
    "cancelled": (),
    "archived": (),
}

# Status-track transition rules. Linear forward progression for
# operational; selectable lateral moves for commercial; mostly
# automated later for finance but covered here for M2 manual UX.
_COMMERCIAL_STATUS_TRANSITIONS = {
    "negotiating": ("won", "lost", "on_hold"),
    "on_hold": ("negotiating", "won", "lost"),
    "won": ("on_hold",),
    "lost": (),
}
_FINANCE_STATUS_TRANSITIONS = {
    "quoted": ("deposit_pending",),
    "deposit_pending": ("deposit_received", "overdue"),
    "deposit_received": ("partial_paid", "fully_paid"),
    "partial_paid": ("fully_paid", "overdue"),
    "fully_paid": (),
    "overdue": ("partial_paid", "fully_paid"),
}
_OPERATIONAL_STATUS_TRANSITIONS = {
    "planning": ("soft_hold", "confirmed"),
    "soft_hold": ("planning", "confirmed"),
    "confirmed": ("pre_event",),
    "pre_event": ("live", "confirmed"),
    "live": ("wrapped",),
    "wrapped": ("done",),
    "done": (),
}


class CommercialJob(models.Model):
    _name = "commercial.job"
    _description = "Commercial Job — central event record (Phase 2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "event_date desc, name desc"

    # === Identity ===
    name = fields.Char(
        string="Job Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    master_contract_id = fields.Many2one(
        "commercial.job.master",
        string="Master Contract",
        ondelete="set null",
        tracking=True,
        help="Optional. For multi-event corporate clients on a master contract.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Client",
        required=True,
        tracking=True,
    )
    crm_lead_id = fields.Many2one(
        "crm.lead",
        string="Source CRM Opportunity",
        ondelete="set null",
        tracking=True,
    )
    sale_order_id = fields.Many2one(
        "sale.order",
        string="Sale Order / Quote",
        ondelete="set null",
        tracking=True,
    )
    invoice_ids = fields.Many2many(
        "account.move",
        string="Invoices",
        compute="_compute_invoice_ids",
        store=False,
    )
    invoice_count = fields.Integer(
        string="Invoice Count",
        compute="_compute_invoice_ids",
    )

    # === Two-state primary lifecycle ===
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("archived", "Archived (Lost)"),
        ],
        string="Lifecycle",
        default="pending",
        required=True,
        tracking=True,
        help="Pending = quote sent, awaiting Won/Lost. "
        "Active = won, Capacity Gate passed, on the operations calendar. "
        "Completed = event delivered. "
        "Cancelled = explicit cancellation. "
        "Archived = lost lead, kept for reporting.",
    )

    # === Three parallel status tracks (within Active) ===
    commercial_status = fields.Selection(
        [
            ("negotiating", "Negotiating"),
            ("won", "Won"),
            ("lost", "Lost"),
            ("on_hold", "On Hold"),
        ],
        string="Commercial Status",
        default="negotiating",
        tracking=True,
    )
    finance_status = fields.Selection(
        [
            ("quoted", "Quoted"),
            ("deposit_pending", "Deposit Pending"),
            ("deposit_received", "Deposit Received"),
            ("partial_paid", "Partially Paid"),
            ("fully_paid", "Fully Paid"),
            ("overdue", "Overdue"),
        ],
        string="Finance Status",
        default="quoted",
        tracking=True,
    )
    operational_status = fields.Selection(
        [
            ("planning", "Planning"),
            ("soft_hold", "Soft Hold"),
            ("confirmed", "Confirmed"),
            ("pre_event", "Pre-event"),
            ("live", "Live"),
            ("wrapped", "Wrapped"),
            ("done", "Done"),
        ],
        string="Operational Status",
        default="planning",
        tracking=True,
    )
    operational_status_color = fields.Integer(
        string="Operational Status Color",
        compute="_compute_operational_status_color",
        store=True,
        help="Odoo palette index (0–11) driven by operational_status. "
        "Mapping (P2.M6 D2): planning=5, soft_hold=2, confirmed=10, "
        "pre_event=3, live=11, wrapped=4, done=7, unset=0.",
    )
    calendar_display_name = fields.Char(
        string="Calendar Tile Label",
        compute="_compute_calendar_display_name",
        store=False,
        help="Used as the calendar tile title via create_name_field. "
        "Prefix by gate_result:\n"
        "  ⚠  reject (pending job, activation blocked)\n"
        "  ▷  warning (active job with non-blocking concerns)\n"
        "  ✓  overridden (manager-approved despite reject)\n"
        "  (none) pass or not_run",
    )

    # === Dates ===
    event_date = fields.Date(
        string="Event Date",
        required=True,
        tracking=True,
        help="Required at pending stage (tentative date OK). "
        "Per Q-S3 — no Commercial Job exists without at least a tentative date.",
    )
    event_end_date = fields.Date(string="Event End Date")
    event_end_date_calendar = fields.Date(
        string="Event End Date (Calendar)",
        compute="_compute_event_end_date_calendar",
        store=True,
        help="Calendar-rendering only. Returns event_end_date when set, "
        "otherwise event_date so single-day events still render. Odoo 17's "
        "calendar widget silently drops events when date_stop is NULL on "
        "Date-type field pairs.",
    )
    soft_hold_until = fields.Date(
        string="Soft Hold Until",
        tracking=True,
        help="Auto-set to today + 7 days at pending creation. "
        "Cleared on activation.",
    )
    soft_hold_extension_count = fields.Integer(
        string="Soft Hold Extensions",
        default=0,
        tracking=True,
        help="Number of times the soft hold has been extended. "
        "Hard cap of 3 (P2.M5 D2).",
    )
    last_expiry_notification_date = fields.Date(
        string="Last Expiry Notification",
        copy=False,
        help="Anchor used by the daily cron to avoid duplicate "
        "soft-hold expiry notifications.",
    )
    soft_hold_state = fields.Selection(
        [
            ("none", "Not applicable"),
            ("active", "Active"),
            ("expiring_soon", "Expiring soon"),
            ("expired", "Expired"),
        ],
        string="Soft Hold Status",
        compute="_compute_soft_hold_state",
        store=True,
        help="Computed from state + soft_hold_until against today. "
        "Stored: refreshed when those fields change or when the daily "
        "cron processes the job. May go stale between cron runs.",
    )

    # === Venue + Room ===
    venue_id = fields.Many2one(
        "res.partner",
        string="Venue",
        required=True,
        domain=[("is_venue", "=", True)],
        tracking=True,
        help="Required at pending stage. Per Q-S3 — must know where, even tentatively.",
    )
    venue_room_id = fields.Many2one(
        "venue.room",
        string="Room",
        domain="[('venue_id', '=', venue_id)]",
        tracking=True,
        help="Specific room within the venue. Optional. "
        "Calendar conflict detection runs at room level when set.",
    )

    # === Equipment summary (high-level for Phase 2; Phase 5 deeper) ===
    equipment_count = fields.Integer(string="Equipment Count")
    equipment_summary = fields.Text(string="Equipment Summary")
    sub_hire_required = fields.Boolean(string="Sub-hire Required", tracking=True)
    logistics_flag = fields.Boolean(string="Logistics Flag", tracking=True)

    # === Crew ===
    crew_assignment_ids = fields.One2many(
        "commercial.job.crew",
        "job_id",
        string="Crew Assignments",
    )
    crew_total_count = fields.Integer(
        string="Crew Total",
        compute="_compute_crew_counts",
    )
    crew_confirmed_count = fields.Integer(
        string="Crew Confirmed",
        compute="_compute_crew_counts",
    )

    # === Money ===
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    quoted_value = fields.Monetary(
        string="Quoted Value",
        currency_field="currency_id",
    )
    deposit_received = fields.Monetary(
        string="Deposit Received",
        currency_field="currency_id",
        help="To be auto-computed from payments in P2.M2+. "
        "Manually editable for now.",
    )

    # === Loss capture ===
    loss_reason = fields.Text(
        string="Loss Reason",
        tracking=True,
        help="Required when state = archived. "
        "Per Robin Q1, Q5 — feeds learnings.",
    )
    lost_to_competitor = fields.Char(string="Lost To Competitor")

    # === Auto-create placeholder tracking (P2.M3) ===
    event_date_is_placeholder = fields.Boolean(
        string="Event Date Is Placeholder",
        default=False,
        copy=False,
        help="Set True when neon_jobs auto-created this row from a CRM lead "
        "without lead.date_deadline. Cleared automatically the first time "
        "event_date is updated.",
    )
    needs_attention = fields.Boolean(
        string="Needs Attention",
        compute="_compute_needs_attention",
        store=True,
        help="True while either event_date or venue_id is still a placeholder. "
        "Drives the warning banner and the tree decoration.",
    )
    needs_attention_reason = fields.Text(
        string="Needs Attention Reason",
        compute="_compute_needs_attention",
        store=True,
    )

    # === Role-aware UI helpers (P2.M7.5) ===
    can_edit_crew = fields.Boolean(
        string="Can Edit Crew Assignments",
        compute="_compute_can_edit_crew",
        store=False,
        help="True if the current user can add/remove/edit crew on this "
        "job. Managers and Crew Leaders qualify; Sales reps (User) and "
        "Crew tier do not.",
    )
    is_my_crew_event = fields.Boolean(
        string="On My Schedule",
        compute="_compute_is_my_crew_event",
        search="_search_is_my_crew_event",
        store=False,
        help="True when the current user has a confirmed crew assignment "
        "on this job. Drives the My Calendar action's domain.",
    )

    # P2.M7.8 — the calling crew member's own assignment row on this job.
    # Powers the "My Assignment" section + confirm/decline buttons on the
    # crew-specific form view. Non-stored, recomputed per request.
    my_assignment_id = fields.Many2one(
        "commercial.job.crew",
        string="My Assignment",
        compute="_compute_my_assignment",
        store=False,
    )
    # role / state are computed directly off crew_assignment_ids rather
    # than related= through my_assignment_id. A related= would force Odoo
    # to reverse-search my_assignment_id (non-stored, depends_context)
    # whenever a crew row's state changes, which triggers a "field should
    # be searchable" warning on every crew write/unlink.
    my_assignment_role = fields.Selection(
        selection=lambda self: self.env["commercial.job.crew"]._fields["role"].selection,
        string="My Role",
        compute="_compute_my_assignment_facets",
    )
    my_assignment_state = fields.Selection(
        selection=lambda self: self.env["commercial.job.crew"]._fields["state"].selection,
        string="My Confirmation",
        compute="_compute_my_assignment_facets",
    )

    # === Capacity Acceptance Gate result ===
    gate_result = fields.Selection(
        [
            ("not_run", "Not Run"),
            ("pass", "Pass"),
            ("warning", "Warning"),
            ("reject", "Reject"),
            ("overridden", "Overridden"),
        ],
        string="Gate Result",
        default="not_run",
        tracking=True,
        help="Capacity Acceptance Gate outcome. "
        "Per v4.1 §8 — runs automatically when state moves to active. "
        "Logic implemented in P2.M4.",
    )
    gate_run_at = fields.Datetime(string="Gate Last Run", tracking=True)
    gate_override_by = fields.Many2one(
        "res.users",
        string="Override By",
        tracking=True,
        help="MD or OD who overrode a reject. Either has authority (Q3).",
    )
    gate_override_reason = fields.Text(string="Override Reason")
    gate_check_log = fields.Text(
        string="Gate Check Log",
        help="JSON-serialized log of the 8 checks and their individual results.",
    )

    # ============================================================
    # === Computed methods
    # ============================================================
    @api.depends("sale_order_id", "sale_order_id.invoice_ids")
    def _compute_invoice_ids(self):
        for rec in self:
            rec.invoice_ids = rec.sale_order_id.invoice_ids if rec.sale_order_id else False
            rec.invoice_count = len(rec.invoice_ids)

    _OPERATIONAL_STATUS_COLORS = {
        "planning": 5,
        "soft_hold": 2,
        "confirmed": 10,
        "pre_event": 3,
        "live": 11,
        "wrapped": 4,
        "done": 7,
    }
    _GATE_TILE_PREFIXES = {
        "reject": "⚠ ",
        "warning": "▷ ",
        "overridden": "✓ ",
    }

    @api.depends("event_date", "event_end_date")
    def _compute_event_end_date_calendar(self):
        for rec in self:
            rec.event_end_date_calendar = rec.event_end_date or rec.event_date

    @api.depends("operational_status")
    def _compute_operational_status_color(self):
        for rec in self:
            rec.operational_status_color = self._OPERATIONAL_STATUS_COLORS.get(
                rec.operational_status, 0
            )

    @api.depends("partner_id", "partner_id.name", "gate_result")
    def _compute_calendar_display_name(self):
        for rec in self:
            base = rec.partner_id.name or _("Untitled")
            prefix = self._GATE_TILE_PREFIXES.get(rec.gate_result, "")
            rec.calendar_display_name = prefix + base

    @api.depends("state", "soft_hold_until")
    def _compute_soft_hold_state(self):
        today = fields.Date.today()
        soon_threshold = fields.Date.add(today, days=3)
        for rec in self:
            if rec.state != "pending" or not rec.soft_hold_until:
                rec.soft_hold_state = "none"
            elif rec.soft_hold_until < today:
                rec.soft_hold_state = "expired"
            elif rec.soft_hold_until <= soon_threshold:
                rec.soft_hold_state = "expiring_soon"
            else:
                rec.soft_hold_state = "active"

    @api.depends("crew_assignment_ids", "crew_assignment_ids.state")
    def _compute_crew_counts(self):
        for rec in self:
            rec.crew_total_count = len(rec.crew_assignment_ids)
            rec.crew_confirmed_count = len(
                rec.crew_assignment_ids.filtered(lambda c: c.state == "confirmed")
            )

    @api.depends_context("uid")
    def _compute_can_edit_crew(self):
        can_edit = (
            self.env.user.has_group("neon_jobs.group_neon_jobs_manager")
            or self.env.user.has_group("neon_jobs.group_neon_jobs_crew_leader")
        )
        for rec in self:
            rec.can_edit_crew = can_edit

    @api.depends_context("uid")
    def _compute_is_my_crew_event(self):
        uid = self.env.uid
        for rec in self:
            rec.is_my_crew_event = any(
                c.user_id.id == uid and c.state == "confirmed"
                for c in rec.crew_assignment_ids
            )

    @api.depends("crew_assignment_ids", "crew_assignment_ids.user_id",
                 "crew_assignment_ids.state")
    @api.depends_context("uid")
    def _compute_my_assignment(self):
        uid = self.env.uid
        for rec in self:
            match = rec.crew_assignment_ids.filtered(
                lambda c: c.user_id.id == uid
            )[:1]
            rec.my_assignment_id = match

    @api.depends("crew_assignment_ids", "crew_assignment_ids.user_id",
                 "crew_assignment_ids.role", "crew_assignment_ids.state")
    @api.depends_context("uid")
    def _compute_my_assignment_facets(self):
        uid = self.env.uid
        for rec in self:
            match = rec.crew_assignment_ids.filtered(
                lambda c: c.user_id.id == uid
            )[:1]
            rec.my_assignment_role = match.role if match else False
            rec.my_assignment_state = match.state if match else False

    @api.model
    def _search_is_my_crew_event(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return []
        matching_ids = self.env["commercial.job.crew"].sudo().search([
            ("user_id", "=", self.env.uid),
            ("state", "=", "confirmed"),
        ]).mapped("job_id.id")
        positive = (operator == "=" and value) or (operator == "!=" and not value)
        return [("id", "in" if positive else "not in", matching_ids)]

    @api.depends("event_date_is_placeholder", "venue_id")
    def _compute_needs_attention(self):
        tbd = self.env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
        tbd_id = tbd.id if tbd else False
        for rec in self:
            reasons = []
            if rec.event_date_is_placeholder:
                reasons.append(_("event date is a placeholder (today + 14 days)"))
            if tbd_id and rec.venue_id and rec.venue_id.id == tbd_id:
                reasons.append(_("venue is the TBD placeholder"))
            rec.needs_attention = bool(reasons)
            rec.needs_attention_reason = (
                _("Set the real values before the Capacity Gate runs: %s.") % "; ".join(reasons)
                if reasons else False
            )

    # ============================================================
    # === Constraints (P2.M1 minimal — full rules live in P2.M2-M5)
    # ============================================================
    @api.constrains("state", "loss_reason")
    def _check_loss_reason_when_archived(self):
        # Managers may archive without loss_reason (Robin Q3 — MD/OD override).
        if self.env.user.has_group("neon_jobs.group_neon_jobs_manager"):
            return
        for rec in self:
            if rec.state == "archived" and not rec.loss_reason:
                raise ValidationError(
                    _("Loss Reason is required when archiving a Commercial Job. "
                      "This data feeds future sales-process learning.")
                )

    @api.constrains("event_date", "event_end_date")
    def _check_event_dates(self):
        for rec in self:
            if rec.event_end_date and rec.event_date and rec.event_end_date < rec.event_date:
                raise ValidationError(_("Event End Date cannot be before Event Date."))

    @api.constrains("venue_room_id", "venue_id")
    def _check_room_belongs_to_venue(self):
        for rec in self:
            if rec.venue_room_id and rec.venue_room_id.venue_id != rec.venue_id:
                raise ValidationError(_("The selected Room does not belong to the selected Venue."))

    # ============================================================
    # === Create
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("commercial.job") or _("New")
                )
            # Auto-set soft_hold_until at pending creation if not provided
            if vals.get("state", "pending") == "pending" and not vals.get("soft_hold_until"):
                vals["soft_hold_until"] = fields.Date.add(
                    fields.Date.today(), days=7
                )
        return super().create(vals_list)

    # ============================================================
    # === Write guard — enforce transition matrix
    # ============================================================
    def _is_jobs_manager(self):
        return self.env.user.has_group("neon_jobs.group_neon_jobs_manager")

    def _check_transition(self, field_label, transitions, old, new):
        if old == new or not old:
            return
        allowed = transitions.get(old, ())
        if new in allowed:
            return
        if self._is_jobs_manager():
            return
        raise UserError(_(
            "Invalid %(label)s transition: %(old)s → %(new)s. "
            "Allowed from %(old)s: %(allowed)s. "
            "Manager override required for any other move."
        ) % {
            "label": field_label,
            "old": old,
            "new": new,
            "allowed": ", ".join(allowed) or "(none — terminal state)",
        })

    def write(self, vals):
        guards = (
            ("state", _("Lifecycle"), _STATE_TRANSITIONS),
            ("commercial_status", _("Commercial Status"), _COMMERCIAL_STATUS_TRANSITIONS),
            ("finance_status", _("Finance Status"), _FINANCE_STATUS_TRANSITIONS),
            ("operational_status", _("Operational Status"), _OPERATIONAL_STATUS_TRANSITIONS),
        )
        for rec in self:
            for field, label, table in guards:
                if field in vals:
                    rec._check_transition(label, table, rec[field], vals[field])
        # Any explicit user-supplied event_date overrides the placeholder flag.
        # If caller also sets the flag (e.g. the auto-create path), respect that.
        if "event_date" in vals and "event_date_is_placeholder" not in vals:
            vals = dict(vals, event_date_is_placeholder=False)
        return super().write(vals)

    # ============================================================
    # === Action buttons — primary lifecycle
    # === (action_activate lives in commercial_job_gate.py — P2.M4)
    # ============================================================
    def action_complete(self):
        self.write({"state": "completed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_archive_lost(self):
        is_manager = self.env.user.has_group("neon_jobs.group_neon_jobs_manager")
        for rec in self:
            if not rec.loss_reason and not is_manager:
                raise UserError(_(
                    "Loss Reason is required before archiving. "
                    "Open the Loss Capture page, fill in why the job was lost, "
                    "then click Archive Lost again."
                ))
            rec.write({"state": "archived"})

    # ============================================================
    # === Onchange — UX helpers
    # ============================================================
    # ============================================================
    # === Soft Hold expiry (P2.M5)
    # ============================================================
    def _soft_hold_activity_user(self):
        """Pick the user for a soft-hold expiry mail.activity.

        Fallback chain (P2.M5 spec):
        1. crm_lead_id.user_id (the salesperson on the lead)
        2. create_uid if it is not the system superuser
        3. First user in group_neon_jobs_manager (by id)
        4. env.user (last resort)
        """
        self.ensure_one()
        if self.crm_lead_id and self.crm_lead_id.user_id:
            return self.crm_lead_id.user_id
        if self.create_uid and self.create_uid.id != SUPERUSER_ID:
            return self.create_uid
        manager_group = self.env.ref(
            "neon_jobs.group_neon_jobs_manager", raise_if_not_found=False
        )
        if manager_group:
            manager = self.env["res.users"].sudo().search(
                [("groups_id", "in", manager_group.id)],
                limit=1,
                order="id",
            )
            if manager:
                return manager
        return self.env.user

    @api.model
    def cron_process_soft_hold_expiry(self):
        """Daily nudge: chatter + mail.activity for pending jobs whose soft
        hold has reached or passed today. Idempotent via
        last_expiry_notification_date."""
        today = fields.Date.today()
        # SQL prefilter on the easy bits; cross-field comparison
        # (last_expiry_notification_date vs soft_hold_until) done in Python.
        candidates = self.search([
            ("state", "=", "pending"),
            ("soft_hold_until", "!=", False),
            ("soft_hold_until", "<=", today),
        ])
        jobs = candidates.filtered(
            lambda j: not j.last_expiry_notification_date
            or j.last_expiry_notification_date < j.soft_hold_until
        )
        if not jobs:
            _logger.info("neon_jobs cron: no soft-hold expiries to notify.")
            return True
        activity_type = self.env.ref(
            "mail.mail_activity_data_todo", raise_if_not_found=False
        )
        ir_model_id = self.env["ir.model"]._get("commercial.job").id
        for job in jobs:
            days_overdue = (today - job.soft_hold_until).days
            if days_overdue == 0:
                summary = _("Soft hold expires today on %s") % job.name
                body = _(
                    "Soft hold expires today — extend, activate, or close."
                )
            else:
                summary = _("Soft hold expired on %s") % job.name
                body = _(
                    "Soft hold expired %d days ago — extend, activate, or close."
                ) % days_overdue
            assignee = job._soft_hold_activity_user()
            job.message_post(body=body)
            self.env["mail.activity"].sudo().create({
                "res_model_id": ir_model_id,
                "res_id": job.id,
                "summary": summary,
                "note": body,
                "date_deadline": fields.Date.add(today, days=3),
                "user_id": assignee.id,
                "activity_type_id": activity_type.id if activity_type else False,
            })
            job.write({"last_expiry_notification_date": today})
            # Recompute stored soft_hold_state so views reflect 'expired'
            # without waiting for another write.
            job.invalidate_recordset(["soft_hold_state"])
            job._compute_soft_hold_state()
        _logger.info(
            "neon_jobs cron: notified %d soft-hold expiries.", len(jobs)
        )
        return True

    # ============================================================
    # === Crew-form thin wrappers (P2.M7.8)
    # Crew users land on commercial.job records via the crew-specific
    # form view. The Confirm / Decline buttons there can't call methods
    # on commercial.job.crew directly, so delegate via my_assignment_id.
    # ============================================================
    def action_confirm_my_assignment(self):
        self.ensure_one()
        if not self.my_assignment_id:
            raise UserError(_("You have no crew assignment on this job."))
        return self.my_assignment_id.action_confirm()

    def action_decline_my_assignment(self):
        self.ensure_one()
        if not self.my_assignment_id:
            raise UserError(_("You have no crew assignment on this job."))
        return self.my_assignment_id.action_open_decline_wizard()

    def action_open_soft_hold_extend_wizard(self):
        self.ensure_one()
        if self.state != "pending":
            raise UserError(_(
                "Soft hold can only be extended on pending jobs."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("Extend Soft Hold"),
            "res_model": "commercial.job.soft_hold.extend.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_job_id": self.id},
        }

    @api.onchange("venue_id")
    def _onchange_venue_id(self):
        if self.venue_room_id and self.venue_room_id.venue_id != self.venue_id:
            self.venue_room_id = False

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        # If partner has an active master contract, suggest it
        if self.partner_id and not self.master_contract_id:
            active_master = self.env["commercial.job.master"].search([
                ("partner_id", "=", self.partner_id.id),
                ("state", "=", "active"),
            ], limit=1)
            if active_master:
                self.master_contract_id = active_master
