# -*- coding: utf-8 -*-
"""P5.M4 — Equipment reservation (time-window hold on a unit).

One row per (unit, event_job, window). The reservation lifecycle is
distinct from the unit lifecycle (P5.M2): a unit can be in 'active'
state and simultaneously carry a 'soft_hold' reservation for next
weekend — the reservation tracks intent over a window, the unit
tracks current possession.

LOCKED state machine (mirrors P5.M2 _do_transition pattern):

    soft_hold ──→ confirmed ──→ fulfilled
        │             │
        └──→ cancelled ←──┘

P5.M4 ships MANUAL reservation creation only. Auto-creation on
commercial.event.job revisits in P5.M5 once the equipment-line
model (the list of units a given event needs) lands. The current
event_job model only carries equipment_summary (Text) and
equipment_count (Integer) — there's no list of units to iterate
on event_job create.

Conflict detection: any pair of reservations on the same unit_id
whose [reserve_from, reserve_to) windows overlap, and which are
both in non-terminal state (soft_hold or confirmed), constitute a
conflict. has_conflict is stored + indexed; conflicting_reservation_ids
is a non-stored Many2many compute (perf — recompute on read is
cheaper than maintaining the m2m table). The Action Centre
'equipment_conflict' trigger (P5.M4) fires on conflict create and
auto-closes when the conflict clears.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_STATES = [
    ("soft_hold", "Soft Hold"),
    ("confirmed", "Confirmed"),
    ("fulfilled", "Fulfilled"),
    ("cancelled", "Cancelled"),
]


ALLOWED_TRANSITIONS = {
    "soft_hold": ["confirmed", "cancelled"],
    "confirmed": ["fulfilled", "cancelled"],
    "fulfilled": [],
    "cancelled": [],
}


# Reservation states that still "hold" the unit. Fulfilled means the
# gear was checked out (P5.M5 owns checkout); cancelled means the
# booking dropped. Neither contributes to conflict detection.
_ACTIVE_HOLD_STATES = ("soft_hold", "confirmed")


# Field set that, when written, triggers peer-conflict resync.
_CONFLICT_TRIGGER_FIELDS = frozenset((
    "unit_id", "reserve_from", "reserve_to", "state"))


class NeonEquipmentReservation(models.Model):
    _name = "neon.equipment.reservation"
    _description = "Equipment Reservation"
    _inherit = ["action.centre.mixin", "mail.thread"]
    _order = "reserve_from desc, id desc"

    name = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "neon.equipment.reservation") or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Equipment Unit",
        ondelete="restrict",
        tracking=True,
        help="The physical unit this reservation holds. May be NULL "
        "while the reservation is in soft_hold (P5.M5 auto-creation "
        "spawns unit-less holds at event_job creation; allocation "
        "fills unit_id later). Must be set before transitioning to "
        "confirmed.",
    )
    equipment_line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Equipment Line",
        ondelete="set null",
        index=True,
        help="The planned-equipment line this reservation belongs to "
        "(P5.M5). NULL for manual / standalone reservations.",
    )
    late_return_pending = fields.Boolean(
        default=False,
        tracking=True,
        help="P5.M7 — set by the check-in wizard when a unit is "
        "acknowledged as late-returning (condition='missing', "
        "resolution='returned_late'). Excludes this reservation "
        "from the event_job's has_unresolved_missing closeout "
        "blocker so the event can close while the unit is physically "
        "still out. Cleared when the unit is eventually checked in.",
    )
    product_template_id = fields.Many2one(
        related="unit_id.product_template_id",
        store=True,
        readonly=True,
        string="Product",
    )
    equipment_category_id = fields.Many2one(
        related="unit_id.equipment_category_id",
        store=True,
        readonly=True,
        string="Category",
    )
    state = fields.Selection(
        _STATES,
        default="soft_hold",
        required=True,
        readonly=True,
        tracking=True,
        help="Lifecycle: soft_hold → confirmed → fulfilled, with "
        "cancellation possible from soft_hold or confirmed. "
        "Transitions route through _do_transition / action_* "
        "methods; direct state writes from the UI are blocked.",
    )
    reserve_from = fields.Datetime(
        string="From",
        required=True,
        tracking=True,
        help="Start of the hold window. Defaults to the event job's "
        "prep_start_datetime if set; else event_date 00:00 fallback.",
    )
    reserve_to = fields.Datetime(
        string="To",
        required=True,
        tracking=True,
        help="End of the hold window. Defaults to the event job's "
        "return_eta_datetime if set; else event_date 23:59:59 "
        "fallback.",
    )
    has_conflict = fields.Boolean(
        compute="_compute_conflicts",
        store=True,
        index=True,
        help="True when another open reservation overlaps this one "
        "on the same equipment unit. Drives the equipment_conflict "
        "Action Centre trigger.",
    )
    conflicting_reservation_ids = fields.Many2many(
        "neon.equipment.reservation",
        compute="_compute_conflicts",
        store=False,
        string="Conflicts With",
        help="Other open reservations overlapping this one. Computed "
        "on read (not stored — perf).",
    )
    notes = fields.Text()

    # === P5.M4 — capability flags for button visibility ===
    can_confirm = fields.Boolean(compute="_compute_state_capabilities")
    can_fulfil = fields.Boolean(compute="_compute_state_capabilities")
    can_cancel = fields.Boolean(compute="_compute_state_capabilities")

    _sql_constraints = [
        ("check_dates",
         "CHECK (reserve_from < reserve_to)",
         "Reservation start must be before end."),
    ]

    @api.constrains("state", "unit_id")
    def _check_unit_set_when_active(self):
        """A reservation can sit in soft_hold without a unit assigned
        (P5.M5 auto-creation flow), but any transition to confirmed /
        fulfilled requires a unit. This guard catches direct writes
        that bypass _do_transition."""
        for rec in self:
            if rec.state in ("confirmed", "fulfilled") and not rec.unit_id:
                raise UserError(_(
                    "Reservation %(name)s cannot be %(state)s without "
                    "a unit assigned. Allocate a unit first."
                ) % {"name": rec.name or _("(new)"),
                     "state": rec.state})

    # ============================================================
    # === Computes
    # ============================================================
    @api.depends("state")
    def _compute_state_capabilities(self):
        for rec in self:
            allowed = ALLOWED_TRANSITIONS.get(rec.state, [])
            rec.can_confirm = "confirmed" in allowed
            rec.can_fulfil = "fulfilled" in allowed
            rec.can_cancel = "cancelled" in allowed

    @api.depends("unit_id", "reserve_from", "reserve_to", "state")
    def _compute_conflicts(self):
        for rec in self:
            if (rec.state not in _ACTIVE_HOLD_STATES
                    or not rec.unit_id
                    or not rec.reserve_from
                    or not rec.reserve_to):
                rec.has_conflict = False
                rec.conflicting_reservation_ids = [(5, 0, 0)]
                continue
            domain = [
                ("unit_id", "=", rec.unit_id.id),
                ("state", "in", list(_ACTIVE_HOLD_STATES)),
                ("reserve_from", "<", rec.reserve_to),
                ("reserve_to", ">", rec.reserve_from),
            ]
            if rec.id:
                # Exclude self via NEW-records-safe id check.
                domain.append(("id", "!=", rec.id))
            others = self.sudo().search(domain)
            rec.conflicting_reservation_ids = [(6, 0, others.ids)]
            rec.has_conflict = bool(others)

    # ============================================================
    # === Onchange — default the reservation window from event_job
    # If the event_job carries explicit datetimes (Schedule tab),
    # prefer those. Otherwise fall back to event_date 00:00 ↔ 23:59:59
    # so the reservation has *some* window the user can refine.
    # ============================================================
    @api.onchange("event_job_id")
    def _onchange_event_job_id(self):
        ej = self.event_job_id
        if not ej:
            return
        if not self.reserve_from:
            self.reserve_from = (
                ej.prep_start_datetime
                or (ej.event_date
                    and fields.Datetime.to_datetime(
                        f"{ej.event_date} 00:00:00")))
        if not self.reserve_to:
            self.reserve_to = (
                ej.return_eta_datetime
                or (ej.event_date
                    and fields.Datetime.to_datetime(
                        f"{ej.event_date} 23:59:59")))

    # ============================================================
    # === State machine — _do_transition + action_* methods
    # Mirrors the P5.M2 pattern on neon.equipment.unit. mail.thread
    # tracking on `state` logs the change; no manual message_post
    # needed for the common transitions.
    # ============================================================
    def _do_transition(self, new_state):
        self.ensure_one()
        valid_codes = {code for code, _label
                       in self._fields["state"].selection}
        if new_state not in valid_codes:
            raise UserError(_(
                "Unknown reservation state: %(state)s"
            ) % {"state": new_state})
        old_state = self.state
        if old_state == new_state:
            return True
        allowed = ALLOWED_TRANSITIONS.get(old_state, [])
        if new_state not in allowed:
            raise UserError(_(
                "Illegal reservation transition: %(from)s → %(to)s. "
                "Allowed from %(from)s: %(allowed)s"
            ) % {"from": old_state, "to": new_state,
                 "allowed": allowed})
        self.write({"state": new_state})
        return True

    def action_confirm(self):
        for rec in self:
            rec._do_transition("confirmed")

    def action_fulfil(self):
        """Called by P5.M5 checkout when the gear physically leaves
        the workshop. Closes the reservation."""
        for rec in self:
            rec._do_transition("fulfilled")

    def action_cancel(self):
        for rec in self:
            rec._do_transition("cancelled")

    def action_revert(self):
        """Alias of action_cancel for soft_hold → cancelled. Kept
        for view-button clarity (Cancel vs. Revert reads differently
        depending on whether the reservation was ever confirmed)."""
        for rec in self:
            if rec.state != "soft_hold":
                raise UserError(_(
                    "Revert is only available on soft_hold "
                    "reservations. Use Cancel for confirmed ones."))
            rec._do_transition("cancelled")

    # ============================================================
    # === create / write — Action Centre trigger sync
    # When a reservation is created or its conflict-relevant fields
    # change, re-evaluate the conflict signal for self and any peer
    # reservation on the same unit (peers don't auto-invalidate
    # because @api.depends doesn't cross records).
    # ============================================================
    def _peers_for_conflict_check(self):
        units = self.mapped("unit_id")
        if not units:
            return self
        peers = self.sudo().search([
            ("unit_id", "in", units.ids),
            ("id", "not in", self.ids),
        ])
        return self | peers

    def _sync_conflict_action_items(self):
        for rec in self.sudo():
            if rec.has_conflict and rec.state in _ACTIVE_HOLD_STATES:
                rec._action_centre_create_item("equipment_conflict")
            else:
                rec._action_centre_close_items("equipment_conflict")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        affected = records._peers_for_conflict_check()
        # Peers' has_conflict is stored — Odoo's @api.depends only
        # tracks SELF's fields, so a new reservation does NOT
        # automatically flag peer records for recompute. Call the
        # compute directly; the framework persists stored assignments.
        affected._compute_conflicts()
        affected._sync_conflict_action_items()
        return records

    def write(self, vals):
        res = super().write(vals)
        if _CONFLICT_TRIGGER_FIELDS & set(vals.keys()):
            affected = self._peers_for_conflict_check()
            affected._compute_conflicts()
            affected._sync_conflict_action_items()
        return res
