# -*- coding: utf-8 -*-
"""P5.M5 — Equipment line on commercial.event.job.

One row per (event_job, product, planned_qty). Lines drive:
  * Auto-creation of soft_hold reservations on event_job create
    (P5.M4 deferred D3, now delivered).
  * Unit allocation flow — wizard / programmatic action binds
    available units to the line's soft_hold reservations.
  * Bulk checkout — atomic transition of the line's reservations
    from confirmed → fulfilled, units from reserved → checked_out,
    plus a neon.equipment.movement audit row per checkout.

Authority for checkout (Q7): manager, crew_leader, or Crew Chief
for THIS event_job's parent commercial_job. Inline raise on the
action method matches the action_centre_item._user_can_close
shape — no soft-fail booleans.

Line state is computed off reservation states:
  planned   — 0 reservations fulfilled
  partial   — 0 < fulfilled < planned
  fulfilled — fulfilled >= planned
  cancelled — set explicitly by action_cancel (manual line drop)
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


_LINE_STATES = [
    ("planned",   "Planned"),
    ("partial",   "Partial"),
    ("fulfilled", "Fulfilled"),
    ("cancelled", "Cancelled"),
]


class CommercialEventJobEquipmentLine(models.Model):
    _name = "commercial.event.job.equipment.line"
    _description = "Event Job Equipment Line"
    _inherit = ["mail.thread"]
    _order = "event_job_id, sequence, id"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        required=True,
        domain="[('is_workshop_item', '=', True)]",
        tracking=True,
    )
    category_id = fields.Many2one(
        related="product_template_id.equipment_category_id",
        store=True,
        readonly=True,
        string="Category",
    )
    tracking_mode = fields.Selection(
        related="product_template_id.tracking_mode",
        store=True,
        readonly=True,
    )
    quantity_planned = fields.Integer(
        string="Planned Qty",
        required=True,
        default=1,
        tracking=True,
    )
    quantity_checked_out = fields.Integer(
        compute="_compute_quantity_checked_out",
        store=True,
        string="Checked Out",
    )
    quantity_remaining = fields.Integer(
        compute="_compute_quantity_remaining",
        string="Remaining",
    )
    sequence = fields.Integer(default=10)
    notes = fields.Text()
    state = fields.Selection(
        _LINE_STATES,
        compute="_compute_state",
        store=True,
        default="planned",
        tracking=True,
    )
    cancelled_explicit = fields.Boolean(
        default=False,
        readonly=True,
        help="Set by action_cancel; sticky so the compute doesn't "
        "drift back to 'planned' on subsequent reservation edits.",
    )
    reservation_ids = fields.One2many(
        "neon.equipment.reservation",
        "equipment_line_id",
        string="Reservations",
    )

    _sql_constraints = [
        ("quantity_planned_positive",
         "CHECK (quantity_planned > 0)",
         "Planned quantity must be a positive integer."),
    ]

    # ============================================================
    # === ORM lifecycle hooks
    # On create: auto-spawn quantity_planned soft_hold reservations
    # via the existing helper on commercial.event.job (idempotent,
    # NULL unit_id, allocation fills it in later). This covers the
    # common UI flow — adding a line to an existing event_job via
    # the One2many editor. The event_job.create() override handles
    # the pre-seeded path (lines passed inline at job creation).
    #
    # On write: when quantity_planned changes, reconcile the
    # reservation count. Upsize spawns more soft_holds; downsize
    # cancels open (unit-less) soft_holds. Underflow — shrinking
    # below the count of already-allocated reservations — raises
    # UserError before the write applies.
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            try:
                line.event_job_id._autocreate_reservations_for_lines(line)
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "Auto-reservation failed for equipment line %s "
                    "(event_job %s): %s",
                    line.id, line.event_job_id.name, e,
                )
        # B2 D4 -- recompute the conflict engine once per event_job
        # the new lines belong to (debounce the per-line creates
        # within a single multi-create).
        affected_event_ids = set(l.event_job_id.id for l in lines
                                  if l.event_job_id)
        if affected_event_ids:
            lines._b2_recompute_for_events(affected_event_ids,
                                             "requirement_changed")
        return lines

    def write(self, vals):
        # Underflow guard: raise BEFORE the write applies so the line
        # never lands in an inconsistent state. Iterate without sudo
        # so the user sees the error from their context.
        if "quantity_planned" in vals:
            new_qty = vals["quantity_planned"]
            for line in self:
                # P5.M11: count-based (sum quantity). Serial holds are
                # quantity=1 each so this equals the old len() for serial;
                # a quantity COUNT hold contributes its full N.
                allocated_count = sum(line.reservation_ids.filtered(
                    lambda r: r.state in ("confirmed", "fulfilled")
                ).mapped("quantity"))
                if new_qty < allocated_count:
                    raise UserError(_(
                        "Cannot reduce planned quantity on "
                        "%(name)s to %(new)d — %(alloc)d unit(s) "
                        "are already allocated to this line. "
                        "Cancel an allocated reservation first if "
                        "you want to reduce the plan."
                    ) % {
                        "name": line.display_name,
                        "new": new_qty,
                        "alloc": allocated_count,
                    })
        res = super().write(vals)
        if "quantity_planned" in vals:
            for line in self:
                line._reconcile_reservations_to_quantity()
        # B2 D4 -- recompute conflicts when demand-relevant fields
        # change (quantity, product, or explicit cancel flip).
        b2_trigger_keys = {"quantity_planned", "product_template_id",
                            "cancelled_explicit"}
        if b2_trigger_keys & set(vals.keys()):
            affected = set(l.event_job_id.id for l in self
                            if l.event_job_id)
            if affected:
                self._b2_recompute_for_events(
                    affected, "requirement_changed")
        return res

    def unlink(self):
        # Snapshot affected event_jobs BEFORE the rows go away so the
        # B2 recompute can target the right cluster after delete.
        affected = set(l.event_job_id.id for l in self
                        if l.event_job_id)
        res = super().unlink()
        if affected:
            self._b2_recompute_for_events(
                affected, "requirement_changed")
        return res

    def _b2_recompute_for_events(self, event_ids, trigger_reason):
        """Run the B2 conflict engine for each affected event_job.
        Wrapped so a recompute failure never rolls back the demand
        edit that triggered it."""
        try:
            from .neon_equipment_conflict import ConflictEngine
        except Exception:  # noqa: BLE001
            return
        engine = ConflictEngine(self.env)
        EvJ = self.env["commercial.event.job"].sudo()
        for eid in event_ids:
            ev = EvJ.browse(eid).exists()
            if not ev:
                continue
            try:
                engine.run_for_event(ev, trigger_reason=trigger_reason)
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "B2 conflict engine failed on requirement "
                    "change for event %s; alert skipped.", ev.name)

    def _reconcile_reservations_to_quantity(self):
        """Bring the soft_hold reservation count in line with
        quantity_planned. Upsize → spawn more soft_holds via the
        event_job helper. Downsize → cancel open (unit-less)
        soft_holds preferentially. Allocated reservations
        (confirmed / fulfilled / any with unit_id set) are never
        touched here; the underflow check in write() blocks the
        only case where they'd need to be."""
        self.ensure_one()
        # P5.M11: a quantity line carries ONE count reservation -- adjust
        # its quantity rather than spawning/cancelling N rows.
        if self._is_quantity_line():
            res = self.reservation_ids.filtered(
                lambda r: r.state in ("soft_hold", "confirmed", "fulfilled")
            )[:1]
            if res:
                res.sudo().write({"quantity": self.quantity_planned})
            elif self.quantity_planned > 0:
                self.event_job_id._spawn_one_reservation_for_line(
                    self, quantity=self.quantity_planned)
            return
        active = self.reservation_ids.filtered(
            lambda r: r.state in ("soft_hold", "confirmed", "fulfilled"))
        diff = self.quantity_planned - len(active)
        if diff > 0:
            for _i in range(diff):
                self.event_job_id._spawn_one_reservation_for_line(self)
        elif diff < 0:
            open_holds = self.reservation_ids.filtered(
                lambda r: r.state == "soft_hold" and not r.unit_id)
            for hold in open_holds[:abs(diff)]:
                hold._do_transition("cancelled")

    # ============================================================
    # === Computes
    # ============================================================
    @api.depends("reservation_ids.state", "reservation_ids.quantity")
    def _compute_quantity_checked_out(self):
        # P5.M11: count-based -- sum the fulfilled reservations' quantity.
        # Serial holds carry quantity=1 each, so this equals the old
        # len() for serial lines (byte-unchanged); a quantity COUNT hold
        # contributes its N.
        for rec in self:
            rec.quantity_checked_out = sum(
                rec.reservation_ids.filtered(
                    lambda r: r.state == "fulfilled").mapped("quantity"))

    @api.depends("quantity_checked_out", "quantity_planned")
    def _compute_quantity_remaining(self):
        for rec in self:
            rec.quantity_remaining = max(
                rec.quantity_planned - rec.quantity_checked_out, 0)

    @api.depends("quantity_checked_out", "quantity_planned",
                 "cancelled_explicit")
    def _compute_state(self):
        for rec in self:
            if rec.cancelled_explicit:
                rec.state = "cancelled"
            elif rec.quantity_checked_out >= rec.quantity_planned:
                rec.state = "fulfilled"
            elif rec.quantity_checked_out > 0:
                rec.state = "partial"
            else:
                rec.state = "planned"

    # ============================================================
    # === Authority — Q7 checkout authorization
    # Manager, Lead Tech (crew_leader group), or Crew Chief for the
    # parent commercial_job. The crew_chief check goes through the
    # existing _is_crew_chief_of_job helper on commercial.event.job.
    # ============================================================
    def _user_can_checkout(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group("neon_jobs.group_neon_jobs_manager"):
            return True
        if user.has_group("neon_jobs.group_neon_jobs_crew_leader"):
            return True
        ej = self.event_job_id
        if ej and ej._is_crew_chief_of_job(ej.commercial_job_id):
            return True
        return False

    # ============================================================
    # === Unit allocation
    # action_open_allocate_wizard opens the wizard for the UI flow;
    # action_allocate_units is the programmatic path (smoke tests +
    # any future automation) — picks first-available matching units.
    # ============================================================
    def action_open_allocate_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Allocate Units"),
            "res_model": "neon.equipment.allocate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_equipment_line_id": self.id},
        }

    def action_allocate_units(self, units=None):
        """Bind units to this line's unit-less soft_hold reservations.

        units: optional neon.equipment.unit recordset. When None,
        picks the first available units matching product +
        state='active' + no overlapping reservation.

        Returns the recordset of reservations newly bound to a unit.
        """
        self.ensure_one()
        remaining = self.quantity_remaining
        if remaining <= 0:
            raise UserError(_(
                "Line %(name)s is already fully allocated and "
                "checked out."
            ) % {"name": self.display_name})
        if units is None:
            units = self._find_available_units(remaining)
        if len(units) != remaining:
            raise UserError(_(
                "Allocation requires exactly %(need)d unit(s); "
                "got %(got)d. Adjust the selection or the planned "
                "quantity."
            ) % {"need": remaining, "got": len(units)})
        return self._bind_units_to_reservations(units)

    def _find_available_units(self, count):
        """Search for `count` units of product_template_id in state
        'active' whose schedules don't overlap this line's window.
        Returns a recordset of up to `count` units."""
        Unit = self.env["neon.equipment.unit"]
        Reservation = self.env["neon.equipment.reservation"].sudo()
        domain = [
            ("product_template_id", "=", self.product_template_id.id),
            ("state", "=", "active"),
        ]
        # Derive the candidate window from the line's existing
        # reservations (they all share the same window — auto-created
        # from the event_job's prep_start / return_eta).
        sample = self.reservation_ids[:1]
        candidates = Unit.search(domain)
        if not candidates or not sample:
            return candidates[:count]
        # Filter out units with an overlapping reservation in
        # non-terminal state.
        clashing_unit_ids = Reservation.search([
            ("unit_id", "in", candidates.ids),
            ("state", "in", ("soft_hold", "confirmed")),
            ("reserve_from", "<", sample.reserve_to),
            ("reserve_to", ">", sample.reserve_from),
        ]).mapped("unit_id").ids
        free = candidates.filtered(lambda u: u.id not in clashing_unit_ids)
        return free[:count]

    def _bind_units_to_reservations(self, units):
        """Attach the given units to this line's unit-less soft_hold
        reservations and confirm them. Each bound reservation moves
        soft_hold -> confirmed and its unit moves active -> reserved.
        Returns the recordset of reservations updated."""
        self.ensure_one()
        unallocated = self.reservation_ids.filtered(
            lambda r: r.state == "soft_hold" and not r.unit_id)
        if len(units) > len(unallocated):
            raise UserError(_(
                "Cannot bind %(n)d unit(s) to only %(slot)d "
                "open soft_hold reservation(s) on this line."
            ) % {"n": len(units), "slot": len(unallocated)})
        bound = self.env["neon.equipment.reservation"]
        for unit, reservation in zip(units, unallocated):
            reservation.write({"unit_id": unit.id})
            reservation._do_transition("confirmed")
            unit._do_transition("reserved")
            bound |= reservation
        return bound

    # ============================================================
    # === P5.M11 — tracking-aware allocation
    # action_allocate is the UNIFIED entry (WA-6 + Face 1): serial binds
    # units (the P5.M5 path above, unchanged), quantity reserves a COUNT
    # against quantity_on_hand. action_allocate_units (above) is untouched
    # so the serial smokes stay byte-identical.
    # ============================================================
    def _is_quantity_line(self):
        self.ensure_one()
        return (self.product_template_id.tracking_mode
                or "serial") in ("quantity", "batch")

    def _qty_supply(self):
        """Window-relative supply for this line's product, REUSING the B2
        ConflictEngine so the reservation path and the conflict engine
        agree on the same number (qoh binary-blocked for quantity; active
        units minus transferred/non-good for serial). Does NOT subtract
        reservations -- the caller subtracts committed quantity."""
        self.ensure_one()
        from .neon_equipment_conflict import ConflictEngine
        return ConflictEngine(self.env)._available_for_product(
            self.product_template_id.id)

    def _available_qty_for_window(self, reserve_from, reserve_to):
        """How many MORE of this product can be committed for the window,
        EXCLUDING this line's own holds = supply - committed_by_others."""
        self.ensure_one()
        committed = self.env["neon.equipment.reservation"] \
            ._committed_qty_for_product(
                self.product_template_id.id, reserve_from, reserve_to,
                exclude_line_id=self.id)
        return max(0, self._qty_supply() - committed)

    def _short_reason(self, requested, available):
        """Distinguish a true inventory shortfall from a dates clash, for
        an honest 'short' message (WA-6 + Face 1)."""
        self.ensure_one()
        supply = self._qty_supply()
        if supply < requested:
            return _("only %(s)d in inventory (need %(r)d)") % {
                "s": supply, "r": requested}
        return _("%(c)d already committed on these dates "
                 "(%(a)d of %(r)d available)") % {
            "c": max(0, supply - available), "a": available, "r": requested}

    def action_allocate(self, units=None):
        """P5.M11 unified allocation. Returns {ok, allocated, requested,
        available, reason}. Quantity lines reserve a COUNT (all-or-
        nothing); serial lines bind available units (partial OK). NEVER
        raises on a shortfall -- short is a normal outcome the caller
        reports honestly."""
        self.ensure_one()
        if self._is_quantity_line():
            return self._allocate_quantity()
        requested = self.quantity_remaining
        if requested <= 0:
            return {"ok": True, "allocated": 0, "requested": 0,
                    "available": 0, "reason": "already allocated"}
        avail_units = (self._find_available_units(requested)
                       if units is None else units)
        bound = (self._bind_units_to_reservations(avail_units)
                 if avail_units else self.env["neon.equipment.reservation"])
        allocated = len(bound)
        ok = allocated >= requested
        return {"ok": ok, "allocated": allocated, "requested": requested,
                "available": len(avail_units),
                "reason": "bound" if ok
                else self._short_reason(requested, len(avail_units))}

    def _allocate_quantity(self):
        """Confirm this quantity line's single COUNT reservation iff the
        full requested count is available for its window (all-or-nothing;
        partial bulk holds are a noted follow-on). No unit binding."""
        self.ensure_one()
        res = self.reservation_ids.filtered(
            lambda r: r.state == "soft_hold")[:1]
        if not res:
            already = self.reservation_ids.filtered(
                lambda r: r.state in ("confirmed", "fulfilled"))[:1]
            return {"ok": bool(already),
                    "allocated": already.quantity if already else 0,
                    "requested": self.quantity_planned, "available": 0,
                    "reason": "already allocated" if already
                    else "no open reservation"}
        requested = res.quantity
        available = self._available_qty_for_window(
            res.reserve_from, res.reserve_to)
        if available >= requested:
            res._do_transition("confirmed")
            return {"ok": True, "allocated": requested,
                    "requested": requested, "available": available,
                    "reason": "confirmed"}
        return {"ok": False, "allocated": 0, "requested": requested,
                "available": available,
                "reason": self._short_reason(requested, available)}

    # ============================================================
    # === Checkout — Q7 authority + atomic across the line
    # Iterates this line's confirmed reservations; transitions each
    # unit reserved -> checked_out and each reservation confirmed ->
    # fulfilled; creates a neon.equipment.movement row per unit.
    # If any single transition raises, the savepoint rolls back the
    # entire line — all-or-nothing per the spec D5.
    # ============================================================
    def action_checkout(self):
        """Authority check runs in the caller's context (so unauthorised
        users see UserError, not AccessError). The actual transitions
        and movement-record writes run sudo because crew-tier users
        legitimately authorised as Crew Chief don't carry write rights
        on neon.equipment.unit / reservation / movement at the ACL
        level — the authority gate is the access control. actor_uid
        is captured pre-sudo so the audit log attributes to the real
        operator, not the superuser."""
        for rec in self:
            if not rec._user_can_checkout():
                raise UserError(_(
                    "You are not authorised to check out equipment "
                    "for %(event)s. Manager, Lead Tech, or Crew "
                    "Chief on this event only."
                ) % {"event": rec.event_job_id.name})
            rec.sudo()._checkout_atomic(actor_uid=rec.env.uid)
        return True

    def _checkout_atomic(self, actor_uid=None):
        """Per-line atomic checkout. The cursor savepoint ensures
        partial failures roll back: zero movements, zero state
        changes if any one unit raises."""
        self.ensure_one()
        actor_uid = actor_uid or self.env.uid
        actor = self.env["res.users"].sudo().browse(actor_uid)
        Movement = self.env["neon.equipment.movement"].sudo()
        # P5.M11: quantity line -> the confirmed COUNT reservation goes
        # fulfilled + ONE unit-less checkout movement carrying the count.
        # actor_id = the real operator (audit), same discipline as serial.
        if self._is_quantity_line():
            confirmed = self.reservation_ids.filtered(
                lambda r: r.state == "confirmed" and not r.unit_id)
            if not confirmed:
                raise UserError(_(
                    "No confirmed reservation on line %(name)s to check "
                    "out. Allocate first."
                ) % {"name": self.display_name})
            with self.env.cr.savepoint():
                for reservation in confirmed:
                    reservation._do_transition("fulfilled")
                    Movement.create({
                        "product_template_id": self.product_template_id.id,
                        "quantity": reservation.quantity,
                        "event_job_id": self.event_job_id.id,
                        "equipment_line_id": self.id,
                        "reservation_id": reservation.id,
                        "movement_type": "checkout",
                        "actor_id": actor.id,
                        "assignee_id": actor.partner_id.id,
                    })
            return True
        confirmed = self.reservation_ids.filtered(
            lambda r: r.state == "confirmed" and r.unit_id)
        if not confirmed:
            raise UserError(_(
                "No confirmed reservations on line %(name)s to "
                "check out. Allocate units first."
            ) % {"name": self.display_name})
        with self.env.cr.savepoint():
            for reservation in confirmed:
                unit = reservation.unit_id
                unit._do_transition("checked_out")
                reservation._do_transition("fulfilled")
                Movement.create({
                    "unit_id": unit.id,
                    "event_job_id": self.event_job_id.id,
                    "equipment_line_id": self.id,
                    "reservation_id": reservation.id,
                    "movement_type": "checkout",
                    "actor_id": actor.id,
                    "assignee_id": actor.partner_id.id,
                    "from_location_text": unit.workshop_location or "",
                })
        return True

    def action_checkin(self):
        """Open the check-in wizard scoped to this line. Authority
        for opening is the same gate as checkout (Q7). The wizard's
        default_get auto-populates this line's checked_out /
        transferred units."""
        self.ensure_one()
        if not self._user_can_checkout():
            raise UserError(_(
                "You are not authorised to check in equipment for "
                "%(event)s. Manager, Lead Tech, or Crew Chief on "
                "this event only."
            ) % {"event": self.event_job_id.name})
        return {
            "type": "ir.actions.act_window",
            "name": _("Check In Equipment"),
            "res_model": "neon.equipment.checkin.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_event_job_id": self.event_job_id.id,
                "default_line_id": self.id,
            },
        }

    def action_cancel(self):
        """Manually drop the line. Cancels every non-terminal
        reservation and sticks state at 'cancelled'."""
        for rec in self:
            for reservation in rec.reservation_ids.filtered(
                    lambda r: r.state in ("soft_hold", "confirmed")):
                reservation._do_transition("cancelled")
            rec.cancelled_explicit = True
