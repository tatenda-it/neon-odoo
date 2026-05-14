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
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .action_centre_trigger_config import TRIGGER_TYPE_SELECTION


_logger = logging.getLogger(__name__)

# P4.M4 — cap on automatic escalation. After three escalation
# cycles the cron stops trying; managers can still reassign
# manually. Future enhancement: per-trigger.config override.
_MAX_ESCALATION_LEVEL = 3

# Mirrors the role → group resolution used by _role_matches_user
# elsewhere in this file. Centralised so the escalation resolver
# stays in sync. crew_chief deliberately omitted — it's a per-job
# designation with no group.
_ROLE_TO_GROUP = {
    "lead_tech": "neon_jobs.group_neon_jobs_crew_leader",
    "manager": "neon_jobs.group_neon_jobs_manager",
    "sales": "neon_jobs.group_neon_jobs_user",
}


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

    # ----- History (P4.M4 — append-only audit trail) -----------------
    history_ids = fields.One2many(
        "action.centre.item.history", "item_id",
        string="History", readonly=True,
    )

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
    # === P4.M4 — history helper (delegates to history model's
    #             classmethod, which is the only sanctioned write
    #             path on the append-only audit log)
    # ================================================================
    def _log_history(self, event_type, to_value, from_value=None,
                     actor_id=None, actor_is_system=False, notes=None):
        self.ensure_one()
        return self.env["action.centre.item.history"].log_event(
            self.id, event_type, to_value,
            from_value=from_value,
            actor_id=actor_id,
            actor_is_system=actor_is_system,
            notes=notes,
        )

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
        records = super().create(vals_list)
        # P4.M4 — log the inaugural history row. State at creation
        # is always 'open' (the model's default), so to_value is
        # the literal 'open'. Bypassed if the caller already wrote
        # a non-default state, which shouldn't happen via the
        # public API since direct state writes are blocked.
        for rec in records:
            rec._log_history("created", to_value=rec.state)
        return records

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
        # P4.M4 — append history row alongside chatter. Chatter is
        # for humans skimming; history is for queries, reporting,
        # and forensic accountability.
        self._log_history("state_change", to_value=target, from_value=old)

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
        # P4.M4 — capture OLD primary_assignee_id per record before
        # super().write() lands, so we can log the reassignment with
        # accurate from_value names. Also enforces the reassign
        # authority gate (manager-only).
        reassignment_log = []
        if "primary_assignee_id" in vals:
            new_val = vals["primary_assignee_id"]
            new_user = self.env["res.users"].sudo().browse(new_val) if new_val else None
            for rec in self:
                cur_val = rec.primary_assignee_id.id or False
                if new_val != cur_val:
                    if not rec._user_can_reassign():
                        raise UserError(_(
                            "Only Manager can reassign an Action "
                            "Centre item."
                        ))
                    old_name = (
                        rec.primary_assignee_id.name
                        if rec.primary_assignee_id else _("(unassigned)")
                    )
                    new_name = new_user.name if new_user else _("(unassigned)")
                    reassignment_log.append((rec.id, old_name, new_name))
        result = super().write(vals)
        # Now log the reassignments — context flag distinguishes
        # cron-driven escalation from user-driven reassignment, so
        # the history reads as 'escalated' vs 'reassigned' as
        # appropriate.
        is_escalation = self.env.context.get("_force_escalated_flag")
        event_type = "escalated" if is_escalation else "reassigned"
        actor_is_system = bool(is_escalation)
        for item_id, old_name, new_name in reassignment_log:
            self.browse(item_id)._log_history(
                event_type, to_value=new_name, from_value=old_name,
                actor_is_system=actor_is_system,
            )
        return result

    # ================================================================
    # === P4.M4 — Escalation resolution + cron jobs
    # ================================================================
    def _resolve_escalation_user(self, role):
        """Find a user in the group corresponding to `role`.

        First-found-by-id-asc for determinism. Future enhancement:
        prefer the least-loaded user (fewest open action items) per
        D4 spec. The simpler form is fine for the milestone — load
        balancing is a P4.M6+ refinement once we have real cross-
        event volume.

        Returns a res.users record or empty recordset.
        """
        self.ensure_one()
        group_xmlid = _ROLE_TO_GROUP.get(role)
        if not group_xmlid:
            return self.env["res.users"]
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            return self.env["res.users"]
        # Exclude the current assignee + the system user so escalation
        # actually moves the work to a fresh face.
        exclude_ids = []
        if self.primary_assignee_id:
            exclude_ids.append(self.primary_assignee_id.id)
        candidates = self.env["res.users"].sudo().search(
            [
                ("groups_id", "in", group.id),
                ("active", "=", True),
                ("id", "not in", exclude_ids),
                ("id", "!=", self.env.ref("base.user_root").id),
            ],
            order="id asc",
            limit=1,
        )
        return candidates

    def _resolve_escalation(self):
        """Perform one escalation step on self. Called by the cron.

        Algorithm per D4:
          1. Resolve next user via trigger_config.escalated_to_role
          2. If no candidate: write 'escalation_failed' history,
             leave assignee untouched.
          3. Otherwise: bump escalation_level, set escalated_at +
             escalated_to_id, reassign primary_assignee_id to the
             new user. The write() override picks up the assignee
             change and logs 'escalated' (via the
             _force_escalated_flag context).
        """
        self.ensure_one()
        cfg = self.trigger_config_id
        if not cfg or not cfg.escalated_to_role:
            self._log_history(
                "escalation_failed",
                to_value=_("(no escalation role configured)"),
                actor_is_system=True,
            )
            return False
        new_user = self._resolve_escalation_user(cfg.escalated_to_role)
        if not new_user:
            self._log_history(
                "escalation_failed",
                to_value=_("(no user in role %s)") % cfg.escalated_to_role,
                actor_is_system=True,
                notes=_("Escalation skipped — no active user found "
                        "in role %s.") % cfg.escalated_to_role,
            )
            return False
        # Sudo: cron runs as base.user_root, and the write() override's
        # _user_can_reassign gate would otherwise refuse. The
        # _force_escalated_flag tells write() to log 'escalated'
        # rather than 'reassigned'.
        self.sudo().with_context(_force_escalated_flag=True).write({
            "primary_assignee_id": new_user.id,
            "escalated_to_id": new_user.id,
            "escalated_at": fields.Datetime.now(),
            "escalation_level": self.escalation_level + 1,
        })
        return True

    @api.model
    def _cron_check_escalations(self):
        """Hourly cron — find items whose escalation window has
        elapsed and escalate them.

        Due check: MAX(create_date, escalated_at) + escalation_minutes
        < now. This is the idempotency trick — once an item is
        escalated, escalated_at = now, so the next cron run can't
        re-escalate it until another escalation_minutes elapses.

        Skip items already at _MAX_ESCALATION_LEVEL.
        """
        now = fields.Datetime.now()
        # Pull all open/in-progress items with a trigger_config that
        # has escalation_minutes > 0 and we're under the cap. The
        # per-item due check happens in Python because Datetime
        # arithmetic in domains is awkward and the candidate set
        # should be small enough that this is fine.
        candidates = self.sudo().search([
            ("state", "in", ("open", "in_progress")),
            ("trigger_config_id", "!=", False),
            ("trigger_config_id.escalation_minutes", ">", 0),
            ("escalation_level", "<", _MAX_ESCALATION_LEVEL),
        ])
        escalated_count = 0
        skipped_count = 0
        for item in candidates:
            cfg = item.trigger_config_id
            reference = item.escalated_at or item.create_date
            if not reference:
                skipped_count += 1
                continue
            elapsed_minutes = (now - reference).total_seconds() / 60.0
            if elapsed_minutes < cfg.escalation_minutes:
                skipped_count += 1
                continue
            try:
                if item._resolve_escalation():
                    escalated_count += 1
            except Exception:
                _logger.exception(
                    "action.centre.item %s: escalation failed",
                    item.name,
                )
        _logger.info(
            "Action Centre escalation cron: %d candidates inspected, "
            "%d escalated, %d skipped (window not elapsed).",
            len(candidates), escalated_count, skipped_count,
        )
        return True

    @api.model
    def _cron_evaluate_time_based_triggers(self):
        """Daily cron — dispatch to per-trigger evaluators living on
        the source models. The cron lives here so the schedule is
        centralised; per-trigger logic lives on the source so each
        evaluator owns its data shape (P4.M5+ split pattern).

        Currently dispatched:
          * closeout_overdue (P4.M5) → commercial.event.job
          * sla_passed (P4.M7) → commercial.event.job
          * feedback_followup backfill (P4.M7) → commercial.event.feedback
        """
        EventJob = self.env["commercial.event.job"].sudo()
        Feedback = self.env["commercial.event.feedback"].sudo()
        Config = self.env["action.centre.trigger.config"].sudo()

        # closeout_overdue — only run if the config is enabled
        cfg_closeout = Config.search(
            [("trigger_type", "=", "closeout_overdue")], limit=1)
        if cfg_closeout and cfg_closeout.is_enabled:
            try:
                EventJob._evaluate_closeout_overdue_trigger()
            except Exception:
                _logger.exception(
                    "Action Centre closeout_overdue evaluator raised")

        # sla_passed — 14-day escalation tier above closeout_overdue
        cfg_sla = Config.search(
            [("trigger_type", "=", "sla_passed")], limit=1)
        if cfg_sla and cfg_sla.is_enabled:
            try:
                EventJob._evaluate_sla_passed_trigger()
            except Exception:
                _logger.exception(
                    "Action Centre sla_passed evaluator raised")

        # feedback_followup backfill — catch records the real-time
        # create()/write() hooks missed (data migrations, etc.)
        cfg_feedback = Config.search(
            [("trigger_type", "=", "feedback_followup")], limit=1)
        if cfg_feedback and cfg_feedback.is_enabled:
            try:
                Feedback._evaluate_feedback_followup_backfill()
            except Exception:
                _logger.exception(
                    "Action Centre feedback_followup backfill raised")

        return True
