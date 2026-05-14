# -*- coding: utf-8 -*-
"""P4.M2 — Action Centre integration mixin.

Source models inherit action.centre.mixin to gain three helpers:

  _action_centre_create_item(trigger_type, **kwargs)
      Spawn an item bound to self. Idempotent — open items with the
      same (trigger_type, source) won't duplicate. Respects the
      enabled flag on the trigger config (disabled triggers no-op).

  _action_centre_close_items(trigger_type=None)
      Auto-close items bound to self when their source condition
      clears. Only closes items where is_auto_close_eligible=True
      (alerts with auto_close_when_condition_clears configured);
      tasks stay open for explicit closure.

  _action_centre_get_items(state=None, item_type=None)
      Query helper for source modules that want to inspect their
      bound items (e.g. for status badges on form views).

P4.M2 lands this plumbing; P4.M5+ wires it into the actual Phase
2/3 source models. Nothing in the rest of the addon imports the
mixin yet — that's intentional. The smoke test exercises the
helpers via a synthetic in-memory mixin user.
"""
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


# Module-level registry — kept thin. The DB-side trigger.config rows
# are authoritative for runtime; this dict carries compile-time meta
# that isn't easy to store in a row (default_title template, plus a
# canonical "this is the known set of trigger types").
#
# Source modules can override default_title by passing title=... when
# calling _action_centre_create_item. The template uses Python str.format
# with the source recordset bound to {source}.
TRIGGER_REGISTRY = {
    "capacity_gate": {
        "default_title": "Review capacity gate for {source.name} ({source.partner_id.name})",
    },
    "lost": {
        "default_title": "Review loss of {source.name} — consider follow-up",
    },
    "event_created": {
        "default_title": "Set Lead Tech for {source.name}",
    },
    "readiness_50": {
        "default_title": "Readiness at risk: {source.name} ({source.readiness_score}%)",
    },
    "readiness_70": {
        "default_title": "Address readiness gaps for {source.name} (score {source.readiness_score}%, event {source.event_date})",
    },
    "scope_change": {
        "default_title": "Scope change to review for {source.event_job_id.name}",
    },
    "closeout_overdue": {
        "default_title": "Complete closeout for {source.name} (event date {source.event_date})",
    },
    "sla_passed": {
        "default_title": "Closeout SLA passed on {source.display_name}",
    },
    "feedback_followup": {
        "default_title": "Feedback follow-up required for {source.event_job_id.name}",
    },
    "manual": {
        "default_title": "Manual action item",
    },
}


# P4.M7 Bug A — when the source record carries a "preferred assignee"
# field for the trigger's primary_role, prefer it over leaving the
# slot empty. Only roles with a stable per-record field on at least
# one source model are mapped here. `manager` and `sales` are
# deliberately omitted: there is no manager_id / sales_rep_id on
# commercial.job or commercial.event.job in this addon. The defensive
# `field in self._fields` check makes entries for unknown source
# models safe — they no-op.
PREFERRED_ASSIGNEE_FIELDS = {
    "lead_tech": "lead_tech_id",
    "crew_chief": "crew_chief_id",
}


class ActionCentreMixin(models.AbstractModel):
    _name = "action.centre.mixin"
    _description = "Action Centre Integration Mixin"

    def _action_centre_create_item(self, trigger_type, **kwargs):
        """Spawn an Action Centre item bound to self.

        Returns the action.centre.item record (existing or newly
        created). Returns an empty recordset when the trigger config
        is disabled.

        kwargs override config defaults: title, priority, due_date,
        primary_assignee_id, item_type, primary_role, description,
        tag_ids.
        """
        self.ensure_one()
        Item = self.env["action.centre.item"].sudo()
        Config = self.env["action.centre.trigger.config"].sudo()

        config = Config.search(
            [("trigger_type", "=", trigger_type)], limit=1)
        if not config:
            _logger.warning(
                "action.centre.mixin: no trigger.config for %s; "
                "skipping item creation on %s(%s).",
                trigger_type, self._name, self.id,
            )
            return Item.browse()

        if not config.is_enabled:
            # Disabled trigger — no-op. Returning an empty recordset
            # so callers can chain .id checks without exception.
            return Item.browse()

        existing = Item._find_existing_open_item(
            trigger_type, self._name, self.id)
        if existing:
            return existing

        source_model = self.env["ir.model"].sudo()._get(self._name)
        title = kwargs.get("title") or self._action_centre_render_title(
            trigger_type)
        primary_role = kwargs.get("primary_role", config.primary_role)

        vals = {
            "trigger_type": trigger_type,
            "trigger_config_id": config.id,
            "is_manual": False,
            "title": title,
            "item_type": kwargs.get("item_type") or config.item_type,
            "primary_role": primary_role,
            "priority": kwargs.get("priority") or config.priority,
            "source_model_id": source_model.id,
            "source_id": self.id,
        }
        # P4.M7 Bug A — auto-assign from a preferred source field when
        # the source model exposes one for the trigger's primary_role
        # (e.g. event_job.lead_tech_id for lead_tech). Caller kwargs
        # still win — the explicit override below runs after this.
        preferred_field = PREFERRED_ASSIGNEE_FIELDS.get(primary_role)
        if preferred_field and preferred_field in self._fields:
            candidate = self[preferred_field]
            if candidate and candidate.exists():
                vals["primary_assignee_id"] = candidate.id
        for opt_key in ("due_date", "primary_assignee_id",
                        "description", "tag_ids"):
            if opt_key in kwargs:
                vals[opt_key] = kwargs[opt_key]

        item = Item.create(vals)

        # Post a note on the source if it carries a chatter. Most of
        # our Phase 2/3 source models inherit mail.thread, but the
        # mixin can't assume that universally.
        if hasattr(self, "message_post"):
            self.sudo().message_post(body=_(
                "Action Centre item %(name)s created from "
                "trigger %(trigger)s."
            ) % {"name": item.name, "trigger": trigger_type})

        return item

    def _action_centre_close_items(self, trigger_type=None, force=False):
        """Auto-close eligible open items bound to self.

        Items where is_auto_close_eligible=False (tasks, or alerts
        whose config has auto_close_when_condition_clears=False) are
        left alone by default — they require manual completion.

        force=True bypasses the eligibility filter, for cases where
        the source model can unambiguously decide the task is done
        (e.g. commercial.event.feedback completing its follow-up
        workflow — the user marking follow_up_completed=True is an
        explicit completion signal, not a passive condition clear).

        Returns the recordset of items actually closed.
        """
        self.ensure_one()
        Item = self.env["action.centre.item"].sudo()
        source_model = self.env["ir.model"].sudo()._get(self._name)

        domain = [
            ("source_model_id", "=", source_model.id),
            ("source_id", "=", self.id),
            ("state", "in", ("open", "in_progress")),
        ]
        if not force:
            domain.append(("is_auto_close_eligible", "=", True))
        if trigger_type:
            domain.append(("trigger_type", "=", trigger_type))

        items = Item.search(domain)
        if not items:
            return items

        # Auto-closure flows through the same audit path as manual
        # closure: set closed_by/closed_at, write closure_reason,
        # then cancel via the state-write bypass context. We mark
        # closed_by_id as the OdooBot/superuser because there's no
        # acting user in an auto-close (often called from a cron in
        # P4.M4); chatter still attributes to env.user.
        for item in items:
            old_state = item.state
            item.with_context(_allow_state_write=True).write({
                "state": "cancelled",
                "closed_by_id": self.env.uid,
                "closed_at": fields.Datetime.now(),
                "closure_reason": _(
                    "Auto-closed: source condition cleared."),
            })
            # P4.M7 Bug B — record an auto_closed history row alongside
            # the chatter note. Without this the audit trail showed the
            # state at 'cancelled' but no event entry explaining why.
            item._log_history(
                "auto_closed",
                to_value="cancelled",
                from_value=old_state,
                actor_is_system=True,
                notes=_(
                    "trigger_type=%(t)s; auto-closed because source "
                    "condition cleared."
                ) % {"t": trigger_type or "(any)"},
            )
            item.message_post(body=_(
                "Action Centre item auto-closed because the "
                "source condition cleared."))

        if hasattr(self, "message_post"):
            self.sudo().message_post(body=_(
                "%(n)d Action Centre item(s) auto-closed."
            ) % {"n": len(items)})

        return items

    def _action_centre_chatter_note(self, trigger_type, note):
        """P4.M7 D5 — post a chatter note on every open item bound to
        self and matching trigger_type. Used for "condition cleared"
        signals on triggers that do NOT auto-close (e.g. readiness_70
        task per Q3), so the assignee learns the source recovered.
        """
        self.ensure_one()
        Item = self.env["action.centre.item"].sudo()
        source_model = self.env["ir.model"].sudo()._get(self._name)
        items = Item.search([
            ("trigger_type", "=", trigger_type),
            ("source_model_id", "=", source_model.id),
            ("source_id", "=", self.id),
            ("state", "in", ("open", "in_progress")),
        ])
        for item in items:
            item.message_post(body=note, message_type="comment")
        return items

    def _action_centre_get_items(self, state=None, item_type=None):
        """Return items bound to self, optionally filtered by state
        and/or item_type."""
        self.ensure_one()
        Item = self.env["action.centre.item"].sudo()
        source_model = self.env["ir.model"].sudo()._get(self._name)
        domain = [
            ("source_model_id", "=", source_model.id),
            ("source_id", "=", self.id),
        ]
        if state:
            states = state if isinstance(state, (list, tuple)) else [state]
            domain.append(("state", "in", states))
        if item_type:
            domain.append(("item_type", "=", item_type))
        return Item.search(domain)

    def _action_centre_render_title(self, trigger_type):
        """Format the registry's default_title template. Falls back
        to a plain "Trigger X" string if formatting blows up (e.g.
        the source recordset doesn't have display_name)."""
        spec = TRIGGER_REGISTRY.get(trigger_type) or {}
        template = spec.get("default_title") or _(
            "Action Centre item from %s") % trigger_type
        try:
            return template.format(source=self)
        except Exception:
            _logger.warning(
                "action.centre.mixin: title template for %s could "
                "not be rendered against %s(%s); falling back.",
                trigger_type, self._name, self.id,
            )
            return _("Action item from trigger %s") % trigger_type
