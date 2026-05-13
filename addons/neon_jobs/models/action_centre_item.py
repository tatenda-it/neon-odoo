# -*- coding: utf-8 -*-
"""P4.M1 — Action Centre Core.

Central proactive-task / alert engine. A single unified model stores
both ad-hoc tasks ("follow up with venue") and system-generated alerts
("crew unconfirmed 48h before event"). The item_type field
distinguishes the two; the lifecycle and ACT-NNNNNN sequence are
shared.

P4.M1 lays the foundation only:
  * model + ACT sequence + basic views + menu
  * 4-state lifecycle (open → in_progress → done → cancelled)
  * polymorphic source reference (mail.activity pattern)
  * role-based primary assignment slot (resolution lands in P4.M4)
  * placeholder fields for trigger_config / escalation / history
    that subsequent milestones populate

Out of scope here: trigger registry (P4.M2), the abstract mixin
(P4.M2), auto-creation from Phase 2/3 events (P4.M5+), escalation
crons (P4.M4), audit history (P4.M4), dashboard tile (P4.M3),
notification channels (P4.5).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_GROUP_XMLIDS = {
    "user": "neon_jobs.group_neon_jobs_user",
    "crew_leader": "neon_jobs.group_neon_jobs_crew_leader",
    "manager": "neon_jobs.group_neon_jobs_manager",
    "crew": "neon_jobs.group_neon_jobs_crew",
}

_STATES = [
    ("open", "Open"),
    ("in_progress", "In Progress"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
]

_TERMINAL_STATES = ("done", "cancelled")


class ActionCentreItem(models.Model):
    _name = "action.centre.item"
    _description = "Action Centre Item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, due_date asc, id desc"
    _rec_name = "name"

    # ----- Identity --------------------------------------------------
    name = fields.Char(
        compute="_compute_name", store=True, index=True,
    )
    sequence_number = fields.Char(readonly=True, copy=False, index=True)
    item_type = fields.Selection(
        [("task", "Task"), ("alert", "Alert")],
        required=True, default="task", tracking=True,
    )
    state = fields.Selection(
        _STATES, required=True, default="open",
        tracking=True, index=True,
    )

    # ----- Content ---------------------------------------------------
    title = fields.Char(required=True, tracking=True)
    description = fields.Text()

    # ----- Urgency ---------------------------------------------------
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"),
         ("high", "High"), ("urgent", "Urgent")],
        default="medium", required=True, tracking=True,
    )
    due_date = fields.Datetime(tracking=True)
    is_overdue = fields.Boolean(
        compute="_compute_is_overdue", store=False,
    )

    # ----- Trigger origin (P4.M2 will extend) ------------------------
    trigger_type = fields.Selection(
        [("manual", "Manual")],
        default="manual", required=True,
    )
    # trigger_config_id placeholder — the model lands in P4.M2.
    # Storing as a plain Integer means we don't need to declare a
    # comodel that doesn't exist yet; P4.M2 swaps it for a real M2o.
    trigger_config_id = fields.Integer(
        string="Trigger Config (P4.M2)", readonly=True,
    )
    is_manual = fields.Boolean(default=True, readonly=True)

    # ----- Source reference (Q18 — mail.activity pattern) -----------
    source_model_id = fields.Many2one(
        "ir.model", ondelete="cascade",
        domain=[("transient", "=", False)],
    )
    source_id = fields.Integer()
    source_record = fields.Reference(
        selection="_source_record_selection",
        compute="_compute_source_record", store=False,
        string="Source",
    )

    # ----- Assignment ------------------------------------------------
    primary_role = fields.Selection(
        [("lead_tech", "Lead Tech"),
         ("manager", "Manager"),
         ("sales", "Sales"),
         ("crew_chief", "Crew Chief")],
    )
    primary_assignee_id = fields.Many2one(
        "res.users", string="Primary Assignee", tracking=True,
    )
    escalated_at = fields.Datetime(readonly=True)
    escalated_to_id = fields.Many2one(
        "res.users", string="Escalated To", readonly=True,
    )
    escalation_level = fields.Integer(default=0, readonly=True)

    # ----- Creation + closure ---------------------------------------
    created_by_id = fields.Many2one(
        "res.users", string="Created By", readonly=True,
        default=lambda self: self.env.user,
    )
    closed_by_id = fields.Many2one(
        "res.users", string="Closed By", readonly=True,
    )
    closed_at = fields.Datetime(readonly=True)
    closure_reason = fields.Text()

    # ----- Channels (Q19 slot for P4.5) -----------------------------
    notification_channels = fields.Char(default="in_app")

    # ----- Auto-close (P4.M2 will compute) --------------------------
    is_auto_close_eligible = fields.Boolean(default=False)

    # ----- Grouping --------------------------------------------------
    parent_item_id = fields.Many2one(
        "action.centre.item", ondelete="set null", index=True,
    )
    child_item_ids = fields.One2many(
        "action.centre.item", "parent_item_id",
    )

    # ----- Categorization -------------------------------------------
    tag_ids = fields.Many2many("action.centre.item.tag")

    # ----- Archive ---------------------------------------------------
    active = fields.Boolean(default=True, tracking=True)

    # ================================================================
    # === Selections + computes
    # ================================================================
    @api.model
    def _source_record_selection(self):
        models_ = self.env["ir.model"].sudo().search(
            [("transient", "=", False)])
        return [(m.model, m.name) for m in models_]

    @api.depends("sequence_number")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.sequence_number or _("New")

    @api.depends("due_date", "state")
    @api.depends_context("uid")
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(
                rec.due_date
                and rec.state not in _TERMINAL_STATES
                and rec.due_date < now
            )

    @api.depends("source_model_id", "source_id")
    def _compute_source_record(self):
        # ir.model is admin-only. Sudo the model-name read so the
        # Reference field can render for non-admin users (sales / lead).
        for rec in self:
            if rec.source_model_id and rec.source_id:
                model_name = rec.source_model_id.sudo().model
                rec.source_record = "%s,%s" % (model_name, rec.source_id)
            else:
                rec.source_record = False

    # ================================================================
    # === Authority helpers — P3.M3 pattern
    # ================================================================
    def _user_in_any_group(self, group_keys):
        return any(
            self.env.user.has_group(_GROUP_XMLIDS[k]) for k in group_keys
        )

    def _user_can_close(self):
        """Primary assignee, escalated_to, or manager."""
        self.ensure_one()
        if self._user_in_any_group(("manager",)):
            return True
        uid = self.env.uid
        return (
            (self.primary_assignee_id and self.primary_assignee_id.id == uid)
            or (self.escalated_to_id and self.escalated_to_id.id == uid)
        )

    def _user_can_reassign(self):
        return self._user_in_any_group(("manager",))

    def _user_can_cancel(self):
        """Manager only (Q16)."""
        self.ensure_one()
        return self._user_in_any_group(("manager",))

    # ================================================================
    # === Sequence + create
    # ================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("sequence_number"):
                vals["sequence_number"] = self.env["ir.sequence"].next_by_code(
                    "action.centre.item"
                ) or _("New")
        return super().create(vals_list)

    # ================================================================
    # === State transition methods
    #
    # Mirrors P3.M3 pattern: direct .write({"state": ...}) is blocked
    # unless the caller passes context={"_allow_state_write": True}.
    # All transitions flow through action_* methods so chatter audit
    # and authority checks run consistently.
    # ================================================================
    def _do_transition(self, target, extra_vals=None):
        self.ensure_one()
        old = self.state
        vals = {"state": target}
        if extra_vals:
            vals.update(extra_vals)
        self.sudo().with_context(_allow_state_write=True).write(vals)
        self.sudo().message_post(
            body=_(
                "State: %(old)s → %(new)s by %(user)s"
            ) % {"old": old, "new": target, "user": self.env.user.name},
            author_id=self.env.user.partner_id.id,
        )

    def action_mark_in_progress(self):
        for rec in self:
            if rec.state != "open":
                raise UserError(_(
                    "Only Open items can be marked In Progress."
                ))
            if not rec._user_can_close():
                raise UserError(_(
                    "Only the assignee, the escalated user, or a "
                    "Manager can move this item to In Progress."
                ))
            rec._do_transition("in_progress")

    def action_mark_done(self):
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "This item is already %(state)s."
                ) % {"state": rec.state})
            if not rec._user_can_close():
                raise UserError(_(
                    "Only the assignee, the escalated user, or a "
                    "Manager can close this item."
                ))
            rec._do_transition("done", {
                "closed_by_id": self.env.uid,
                "closed_at": fields.Datetime.now(),
            })

    def action_cancel(self, reason=None):
        reason = reason or self.env.context.get("closure_reason")
        for rec in self:
            if rec.state in _TERMINAL_STATES:
                raise UserError(_(
                    "This item is already %(state)s."
                ) % {"state": rec.state})
            if not rec._user_can_cancel():
                raise UserError(_(
                    "Only Manager can cancel an Action Centre item."
                ))
            if not reason:
                raise UserError(_(
                    "A closure reason is required to cancel."
                ))
            rec._do_transition("cancelled", {
                "closed_by_id": self.env.uid,
                "closed_at": fields.Datetime.now(),
                "closure_reason": reason,
            })

    # ================================================================
    # === Write block — protect audit + enforce reassign authority
    # ================================================================
    def write(self, vals):
        if "state" in vals and not self.env.context.get("_allow_state_write"):
            # Allow no-op writes (state already equals target) for ORM
            # cache flushing edge cases.
            if any(rec.state != vals["state"] for rec in self):
                raise UserError(_(
                    "State must be changed via Action Centre item "
                    "action methods (Mark In Progress, Mark Done, "
                    "Cancel). Direct state writes are blocked to "
                    "preserve the audit trail."
                ))
        if "primary_assignee_id" in vals:
            for rec in self:
                # Compare new vs current; allow no-op writes
                new_val = vals["primary_assignee_id"]
                cur_val = rec.primary_assignee_id.id or False
                if new_val != cur_val and not rec._user_can_reassign():
                    raise UserError(_(
                        "Only Manager can reassign an Action Centre "
                        "item."
                    ))
        return super().write(vals)
