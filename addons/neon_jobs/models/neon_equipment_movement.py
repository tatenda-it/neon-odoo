# -*- coding: utf-8 -*-
"""P5.M5 — Equipment movement audit log.

One row per physical event in a unit's life: checkout, transfer,
check-in, stock adjustment, write-off. Append-only; rows are
created by the source flow (P5.M5 wires checkout; P5.M6 wires
transfer; P5.M7 wires check-in) and never updated or unlinked
outside the maintenance context flag.

P5.M6 extends this with transfer_state, destination_event_job_id,
and the self-referential transfer_out_movement_id used by
transfer_in records to point back at the originating transfer_out
(both acceptance companions and decline-return reversals link
via this FK).

Location is currently a Char placeholder. Building a proper
neon.workshop.location master is out of scope — the existing Char
field workshop_location on neon.equipment.unit is the canonical
source for from_location_text at checkout / transfer time.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_MOVEMENT_TYPES = [
    ("checkout",     "Checkout (workshop → job)"),
    ("transfer_out", "Transfer Out (job → in-transit)"),
    ("transfer_in",  "Transfer In (in-transit → job)"),
    ("checkin",      "Check-In (job → workshop)"),
    ("stock_adjust", "Stock Adjustment"),
    ("write_off",    "Write-Off"),
]


_CONDITIONS = [
    ("good",    "Good"),
    ("fair",    "Fair"),
    ("poor",    "Poor"),
    ("damaged", "Damaged"),
    ("missing", "Missing"),
]


_TRANSFER_STATES = [
    ("pending",  "Pending Acceptance"),
    ("accepted", "Accepted"),
    ("declined", "Declined"),
    ("expired",  "Expired"),  # reserved — current P5.M6 cron only spawns
                              # the action.centre.item; state stays pending
                              # until a human accepts/declines. Explicit
                              # expire could be a future cleanup.
]


# P5.M6 — fields a destination user is allowed to write on a movement
# record beyond approved_by_id / approved_at (which the existing
# approval flow uses).
_TRANSFER_WRITE_PERMITTED = {"transfer_state", "decline_reason"}


class NeonEquipmentMovement(models.Model):
    _name = "neon.equipment.movement"
    _description = "Equipment Movement (audit log)"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.movement") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Unit",
        required=True,
        index=True,
        ondelete="restrict",
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        index=True,
        ondelete="set null",
        help="For checkout / transfer_out: the source event_job. "
        "For transfer_in / checkin: the destination / workshop side.",
    )
    equipment_line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Line",
        ondelete="set null",
    )
    reservation_id = fields.Many2one(
        "neon.equipment.reservation",
        string="Reservation",
        ondelete="set null",
    )
    movement_type = fields.Selection(
        _MOVEMENT_TYPES,
        required=True,
        index=True,
    )
    actor_id = fields.Many2one(
        "res.users",
        string="Actor",
        required=True,
        default=lambda self: self.env.uid,
    )
    assignee_id = fields.Many2one(
        "res.partner",
        string="Assignee",
        help="Person receiving / handling the unit at this movement.",
    )
    from_location_text = fields.Char(
        string="From Location",
        help="Char placeholder; structured location model deferred.",
    )
    to_location_text = fields.Char(
        string="To Location",
    )
    condition_at_event = fields.Selection(
        _CONDITIONS,
        string="Condition",
    )
    photo = fields.Image(
        max_width=1920, max_height=1080,
        help="Optional at checkout (Q8); mandatory at check-in "
        "(P5.M7 enforces).",
    )
    notes = fields.Text()
    requires_approval = fields.Boolean(
        default=False,
        help="P5.M6 sets this on transfers awaiting manager sign-off.",
    )
    approved_by_id = fields.Many2one("res.users", string="Approved By")
    approved_at = fields.Datetime()

    # === P5.M6 — transfer flow ===
    transfer_state = fields.Selection(
        _TRANSFER_STATES,
        string="Transfer Status",
        tracking=True,
        help="Lifecycle of a pending transfer. Only meaningful when "
        "movement_type='transfer_out'.",
    )
    destination_event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Destination Event",
        ondelete="set null",
        index=True,
        help="Where this unit is heading. Set on transfer_out at "
        "initiation; reused on transfer_in companion records for "
        "navigation.",
    )
    transfer_out_movement_id = fields.Many2one(
        "neon.equipment.movement",
        string="Origin Transfer-Out",
        ondelete="set null",
        help="On a transfer_in record, points back at the originating "
        "transfer_out (whether the result was an accept-companion or "
        "a decline-return).",
    )
    transfer_in_movement_ids = fields.One2many(
        "neon.equipment.movement",
        "transfer_out_movement_id",
        string="Transfer-In Companions",
    )
    decline_reason = fields.Text(
        help="Optional explanation supplied by the destination user "
        "when declining a transfer.",
    )

    # ============================================================
    # === Append-only enforcement
    # Movements are an audit log — once written, they don't change
    # except via an explicit maintenance context flag set by support
    # (similar to the action.centre.item.history pattern). P5.M6 also
    # legitimately writes transfer_state via accept/decline flows;
    # those are permitted without the maintenance flag.
    # ============================================================
    def write(self, vals):
        if not self.env.context.get("_allow_movement_write"):
            permitted = {"approved_by_id", "approved_at"
                         } | _TRANSFER_WRITE_PERMITTED
            extra = set(vals.keys()) - permitted
            if extra:
                raise UserError(_(
                    "Equipment movement records are append-only. "
                    "Cannot update fields: %(fields)s. Pass "
                    "_allow_movement_write=True in the context for "
                    "maintenance writes."
                ) % {"fields": sorted(extra)})
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get("_allow_movement_write"):
            raise UserError(_(
                "Equipment movement records are append-only and "
                "cannot be deleted. Pass _allow_movement_write=True "
                "for maintenance unlinks."
            ))
        return super().unlink()

    # ============================================================
    # === P5.M6 — Accept / Decline transfer
    # Both actions are guarded by destination authority + the
    # movement being a pending transfer_out. The accept and decline
    # paths share authority + state validation but diverge on what
    # they create: accept spawns a destination-side reservation +
    # companion transfer_in; decline reverses the unit to source +
    # posts a chatter note + creates a decline-return transfer_in
    # linked back via transfer_out_movement_id.
    # ============================================================
    def _validate_pending_transfer(self):
        self.ensure_one()
        if self.movement_type != "transfer_out":
            raise UserError(_(
                "Accept / Decline applies to transfer_out movements "
                "only. %(name)s is a %(type)s record."
            ) % {"name": self.name, "type": self.movement_type})
        if self.transfer_state not in ("pending", "expired"):
            raise UserError(_(
                "Transfer %(name)s is already %(state)s; cannot "
                "accept or decline again."
            ) % {"name": self.name, "state": self.transfer_state})

    def _check_destination_authority(self):
        self.ensure_one()
        dest = self.destination_event_job_id
        if not dest:
            raise UserError(_(
                "Transfer %(name)s has no destination event job; "
                "cannot accept or decline."
            ) % {"name": self.name})
        if not dest._user_can_accept_transfer():
            raise UserError(_(
                "You are not authorised to accept or decline "
                "transfers for %(event)s. Manager, Lead Tech, or "
                "Crew Chief on this event only."
            ) % {"event": dest.name})

    def action_accept_transfer(self):
        for rec in self:
            rec._validate_pending_transfer()
            rec._check_destination_authority()
            rec.sudo()._accept_atomic(actor_uid=rec.env.uid)
        return True

    def _accept_atomic(self, actor_uid=None):
        """Per-movement atomic accept. Transitions unit, creates a
        new fulfilled reservation on the destination, creates a
        companion transfer_in movement, stamps transfer_state, and
        auto-closes any open transfer_pending action.centre.item."""
        self.ensure_one()
        actor_uid = actor_uid or self.env.uid
        actor = self.env["res.users"].sudo().browse(actor_uid)
        unit = self.unit_id
        dest = self.destination_event_job_id
        Reservation = self.env["neon.equipment.reservation"].sudo()
        Movement = self.env["neon.equipment.movement"].sudo()
        with self.env.cr.savepoint():
            unit._do_transition("checked_out")
            # New fulfilled reservation on the destination so the
            # unit's "current event_job" is always the latest
            # fulfilled reservation.
            rf, rt = dest._reservation_window_for_autocreate()
            new_res = Reservation.create({
                "event_job_id": dest.id,
                "unit_id": unit.id,
                "reserve_from": rf or fields.Datetime.now(),
                "reserve_to": rt or fields.Datetime.now(),
                "state": "fulfilled",
            })
            Movement.create({
                "unit_id": unit.id,
                "event_job_id": dest.id,
                "reservation_id": new_res.id,
                "movement_type": "transfer_in",
                "actor_id": actor.id,
                "assignee_id": actor.partner_id.id,
                "transfer_out_movement_id": self.id,
                "from_location_text": self.to_location_text or "",
                "to_location_text": self.to_location_text or "",
            })
            self.write({"transfer_state": "accepted"})
        # force=True because the trigger config carries item_type='task'
        # per spec, and the mixin's auto-close defaults to alerts only.
        # Accept/decline is an explicit condition-cleared signal.
        self._action_centre_close_items("transfer_pending", force=True)
        return True

    # ============================================================
    # === Cron evaluator — fires the transfer_pending Action Centre
    # trigger for transfer_out movements that have been awaiting
    # destination acceptance for more than 24 hours. Idempotency
    # comes from the mixin (dedupes by source_model+source_id);
    # the cron simply re-runs daily and only spawns items for
    # movements that don't already have an open one. State on the
    # movement stays 'pending' — only the action.centre.item
    # escalation surfaces the delay. Explicit 'expired' stamping
    # is reserved for a future cleanup pass.
    # ============================================================
    @api.model
    def _evaluate_transfer_pending_trigger(self):
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        candidates = self.sudo().search([
            ("movement_type", "=", "transfer_out"),
            ("transfer_state", "=", "pending"),
            ("create_date", "<", cutoff),
        ])
        for mv in candidates:
            try:
                mv._action_centre_create_item("transfer_pending")
            except Exception:  # noqa: BLE001
                # Don't let a single bad row poison the rest of the
                # cron pass — match the defensive pattern used by
                # event_job's autocreate hook.
                continue
        return candidates

    def action_decline_transfer(self, reason=None):
        for rec in self:
            rec._validate_pending_transfer()
            rec._check_destination_authority()
            rec.sudo()._decline_atomic(
                actor_uid=rec.env.uid, reason=reason)
        return True

    def _decline_atomic(self, actor_uid=None, reason=None):
        """Per-movement atomic decline. Unit returns to checked_out
        on the source (its source-side fulfilled reservation is
        still the latest, so the unit's 'current event_job' is
        unchanged from before the transfer). Creates a transfer_in
        movement marked as a decline-return, posts chatter on the
        source event_job, auto-closes the transfer_pending item."""
        self.ensure_one()
        actor_uid = actor_uid or self.env.uid
        actor = self.env["res.users"].sudo().browse(actor_uid)
        unit = self.unit_id
        source = self.event_job_id
        Movement = self.env["neon.equipment.movement"].sudo()
        with self.env.cr.savepoint():
            unit._do_transition("checked_out")
            Movement.create({
                "unit_id": unit.id,
                # transfer_in's event_job_id records WHERE the unit
                # ended up — for declines, that's back at the source.
                "event_job_id": source.id,
                "reservation_id": self.reservation_id.id,
                "movement_type": "transfer_in",
                "actor_id": actor.id,
                "assignee_id": actor.partner_id.id,
                "transfer_out_movement_id": self.id,
                "from_location_text": self.to_location_text or "",
                "to_location_text": self.from_location_text or "",
                "notes": _("Decline-return: %(reason)s") % {
                    "reason": reason or _("(no reason given)")},
            })
            self.write({
                "transfer_state": "declined",
                "decline_reason": reason or False,
            })
        if source and hasattr(source, "message_post"):
            source.sudo().message_post(body=_(
                "Transfer of %(unit)s to %(dest)s was declined by "
                "%(user)s. Unit is back in your possession."
            ) % {
                "unit": unit.display_name,
                "dest": self.destination_event_job_id.display_name,
                "user": actor.name,
            })
        # force=True because the trigger config carries item_type='task'
        # per spec, and the mixin's auto-close defaults to alerts only.
        # Accept/decline is an explicit condition-cleared signal.
        self._action_centre_close_items("transfer_pending", force=True)
        return True
