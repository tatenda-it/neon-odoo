# -*- coding: utf-8 -*-
"""P4.M4 — Append-only audit log for Action Centre items.

Every state change, reassignment, escalation, auto-close, and
escalation failure on an action.centre.item produces a row here.
The log is system-only: even Administrator cannot tamper with
existing rows. New rows are inserted exclusively via the
log_event() classmethod, which the item model's _log_history
helper calls from its action methods and cron jobs.

The append-only invariant is what gives the audit trail its
forensic value: a "Lost the change record" defence becomes
structurally impossible without dropping into raw SQL.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_EVENT_TYPE_SELECTION = [
    ("created", "Created"),
    ("state_change", "State Change"),
    ("reassigned", "Reassigned"),
    ("escalated", "Escalated"),
    ("auto_closed", "Auto-closed"),
    ("escalation_failed", "Escalation Failed"),
]


class ActionCentreItemHistory(models.Model):
    _name = "action.centre.item.history"
    _description = "Action Centre Item History"
    _order = "event_at desc, id desc"
    _rec_name = "event_type"

    item_id = fields.Many2one(
        "action.centre.item", required=True, index=True,
        ondelete="cascade",
    )
    event_type = fields.Selection(
        _EVENT_TYPE_SELECTION, required=True, index=True,
    )
    from_value = fields.Char(
        help="Prior value (e.g. previous state or previous "
        "assignee name). Optional — meaning depends on event_type.",
    )
    to_value = fields.Char(
        required=True,
        help="New value after the event.",
    )
    actor_id = fields.Many2one(
        "res.users", string="Actor",
        help="The user who triggered the event. Null when "
        "actor_is_system=True (cron auto-escalation, auto-close).",
    )
    actor_is_system = fields.Boolean(
        default=False,
        help="True when the event was triggered by the system "
        "(cron job, trigger evaluation) rather than a user.",
    )
    notes = fields.Text()
    event_at = fields.Datetime(
        default=fields.Datetime.now, readonly=True, required=True,
        index=True,
    )

    @api.model
    def log_event(self, item_id, event_type, to_value,
                  from_value=None, actor_id=None,
                  actor_is_system=False, notes=None):
        """Insert a history row. The only sanctioned write path
        on this model.

        item_id may be an int or a recordset (browse'd); we
        normalise to int. Returns the created history record.
        """
        if hasattr(item_id, "id"):
            item_id = item_id.id
        vals = {
            "item_id": item_id,
            "event_type": event_type,
            "to_value": to_value or "",
            "from_value": from_value,
            "actor_is_system": actor_is_system,
            "notes": notes,
        }
        if actor_id is not None:
            vals["actor_id"] = (
                actor_id.id if hasattr(actor_id, "id") else actor_id
            )
        elif not actor_is_system:
            vals["actor_id"] = self.env.uid
        # sudo() because non-admin callers (sales / lead writing
        # their own items) still need the history row to land.
        # The append-only block on write/unlink protects integrity;
        # creation via this classmethod is the sanctioned path.
        return self.sudo().create(vals)

    def write(self, vals):
        # P4.M4 D8 — append-only. Even Administrator cannot edit
        # an existing history row. Mutation defeats the audit
        # trail's purpose.
        raise UserError(_(
            "Action Centre history rows are append-only and "
            "cannot be modified."
        ))

    def unlink(self):
        # Same reasoning as write(). Cascade-from-item-unlink is
        # the only path that actually removes rows, and that's
        # the ondelete='cascade' on item_id (a SQL-level cascade,
        # not an ORM call into this method).
        raise UserError(_(
            "Action Centre history rows are append-only and "
            "cannot be deleted."
        ))
