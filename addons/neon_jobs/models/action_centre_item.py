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

from .action_centre_trigger_config import TRIGGER_TYPE_SELECTION


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
    # uid-aware authority signal for inline kanban buttons (P4.M3).
    # Mirrors the is_overdue pattern: non-stored compute with
    # depends_context='uid'. _user_can_close is the per-record
    # authority decider; this field surfaces the same answer to the
    # web client so the Start / Mark Done kanban buttons render
    # only for users who can actually drive the transition.
    can_close = fields.Boolean(
        compute="_compute_can_close", store=False,
    )

    # ----- Trigger origin --------------------------------------------
    trigger_type = fields.Selection(
        TRIGGER_TYPE_SELECTION, default="manual", required=True,
    )
    trigger_config_id = fields.Many2one(
        "action.centre.trigger.config",
        string="Trigger Config",
        ondelete="set null",
        readonly=True,
        help="Set automatically when an item is spawned by the "
        "Action Centre mixin from a source model. Manual items "
        "leave this blank.",
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

    # ----- Auto-close eligibility (computed from trigger config) ----
    is_auto_close_eligible = fields.Boolean(
        compute="_compute_is_auto_close_eligible",
        store=True,
    )

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

    @api.depends("primary_assignee_id", "escalated_to_id")
    @api.depends_context("uid")
    def _compute_can_close(self):
        is_manager = self.env.user.has_group(
            "neon_jobs.group_neon_jobs_manager")
        uid = self.env.uid
        for rec in self:
            rec.can_close = bool(
                is_manager
                or (rec.primary_assignee_id and rec.primary_assignee_id.id == uid)
                or (rec.escalated_to_id and rec.escalated_to_id.id == uid)
            )

    @api.depends("item_type", "trigger_config_id",
                 "trigger_config_id.auto_close_when_condition_clears")
    def _compute_is_auto_close_eligible(self):
        for rec in self:
            cfg = rec.trigger_config_id
            rec.is_auto_close_eligible = bool(
                cfg
                and rec.item_type == "alert"
                and cfg.auto_close_when_condition_clears
            )

    @api.model
    def _find_existing_open_item(self, trigger_type, source_model,
                                  source_id):
        """Return the open (or in_progress) item matching the
        trigger + source, if any. Used by the mixin to keep
        repeated trigger fires from spawning duplicate work."""
        SourceModel = self.env["ir.model"].sudo()
        sm = SourceModel._get(source_model)
        if not sm:
            return self.browse()
        return self.sudo().search([
            ("trigger_type", "=", trigger_type),
            ("source_model_id", "=", sm.id),
            ("source_id", "=", source_id),
            ("state", "in", ("open", "in_progress")),
        ], limit=1)

    @api.depends("source_model_id", "source_id")
    def _compute_source_record(self):
        # ir.model is admin-only on this deployment (ir_model_all has
        # perm_read=False; only Administrator inherits read). Sudo the
        # whole M2o read so the truthy check itself doesn't trip ACL
        # and silently drop into the else branch for sales / lead.
        for rec in self:
            sm = rec.sudo().source_model_id
            sid = rec.source_id
            if sm and sid:
                rec.source_record = f"{sm.model},{sid}"
            else:
                rec.source_record = False

    @api.model
    def _role_matches_user(self, role, user):
        """True if the user belongs to the group corresponding to
        the role. crew_chief has no group (per-job assignment), so
        always False for that role."""
        role_to_group = {
            "lead_tech": "neon_jobs.group_neon_jobs_crew_leader",
            "manager": "neon_jobs.group_neon_jobs_manager",
            "sales": "neon_jobs.group_neon_jobs_user",
        }
        grp = role_to_group.get(role)
        return bool(grp and user.has_group(grp))

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
            # Option A — on manual creation, when the item targets the
            # creator's own role, default the assignee to the creator
            # so they can immediately drive the item without a manager
            # hand-off. Trigger-spawned items (is_manual=False) skip
            # this and stay unassigned for role resolution in P4.M4.
            is_manual = vals.get("is_manual", True)
            role = vals.get("primary_role")
            if (
                is_manual
                and not vals.get("primary_assignee_id")
                and role
                and self._role_matches_user(role, self.env.user)
            ):
                vals["primary_assignee_id"] = self.env.uid
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

    def action_open_cancel_wizard(self):
        """Form-button entry point. Opens the cancel wizard so the
        user can enter a closure_reason before action_cancel runs."""
        self.ensure_one()
        if self.state in _TERMINAL_STATES:
            raise UserError(_(
                "This item is already %(state)s."
            ) % {"state": self.state})
        if not self._user_can_cancel():
            raise UserError(_(
                "Only Manager can cancel an Action Centre item."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("Cancel Action Centre Item"),
            "res_model": "action.centre.item.cancel.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_item_id": self.id},
        }

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
    # === P4.M3 — Role-aware menu entry + dashboard tile helper
    # ================================================================
    @api.model
    def action_open_action_centre(self):
        """Role-aware Action Centre entry. Mirrors P3.M8's
        action_open_closeout_queue pattern: returns an act_window
        with default search filters set per the calling user's role.

        - Manager: All Open (every non-terminal item)
        - Crew Leader / Lead Tech: My Lead Tech + Role
        - Sales User: My Sales + Role

        All filters are available in the search panel regardless of
        role; the defaults just save clicks on the common case.
        """
        user = self.env.user
        context = dict(self.env.context)

        if user.has_group("neon_jobs.group_neon_jobs_manager"):
            context["search_default_all_open"] = 1
        elif user.has_group("neon_jobs.group_neon_jobs_crew_leader"):
            context["search_default_my_lead_tech_open"] = 1
        elif user.has_group("neon_jobs.group_neon_jobs_user"):
            context["search_default_my_sales_open"] = 1
        else:
            # Crew-tier fallback: show only what their ir.rule allows
            # (own assignments / creations) — no role default needed.
            context["search_default_my_items"] = 1

        return {
            "type": "ir.actions.act_window",
            "name": _("Action Centre"),
            "res_model": "action.centre.item",
            "view_mode": "kanban,tree,form",
            "context": context,
        }

    @api.model
    def get_dashboard_tile_items(self, limit=5):
        """Return the top N open items for the current user, sorted
        with overdue first, then by due_date ascending (oldest due
        first), then by priority descending. Used by the Operations
        Dashboard 'My Action Items' section.

        Returns a recordset (not a list of dicts) — callers that
        need serialised data can .read() the result.
        """
        uid = self.env.uid
        # Use an SQL-friendly approximation of "overdue first" via
        # due_date ascending — overdue items by definition have the
        # oldest due_dates and bubble to the top. Items with no
        # due_date sort to the end via the NULLS LAST default.
        return self.search(
            [
                ("state", "in", ("open", "in_progress")),
                "|",
                ("primary_assignee_id", "=", uid),
                ("escalated_to_id", "=", uid),
            ],
            order="priority desc, due_date asc, id desc",
            limit=limit,
        )

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
