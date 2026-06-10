# -*- coding: utf-8 -*-
"""P5.M7 — Equipment check-in wizard.

Captures condition + damage photo + missing-item resolution at the
moment units physically return from an event. Atomic batch: any
single failure (missing required photo, unresolved missing, etc.)
rolls back the whole wizard without writing any movements.

Authority for opening the wizard is enforced on the source method
(commercial.event.job.equipment.line.action_checkin /
commercial.event.job.action_checkin_all_equipment). action_confirm
re-checks for defense-in-depth, then sudo-escalates for the actual
writes — same gate-then-sudo pattern used by the P5.M5 checkout and
P5.M6 transfer flows.

State transitions per condition (D5):

  good / fair          → checked_out → returned → active
  poor + maintenance   → checked_out → maintenance (direct)
  poor + no maint.     → checked_out → returned → active
  damaged              → checked_out → damaged (direct)
  missing returned_late → no state change; reservation flagged
  missing write_off    → checked_out → returned → decommissioned
  missing incident     → UserError stub (P5.M9 deferred)
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_CONDITIONS = [
    ("good",    "Good"),
    ("fair",    "Fair"),
    ("poor",    "Poor (needs minor service)"),
    ("damaged", "Damaged"),
    ("missing", "Missing"),
]


_RESOLUTION_PATHS = [
    ("returned_late", "Returned Late (expected back)"),
    ("write_off",     "Write Off (genuinely lost)"),
    ("incident_link", "Link to Incident (P5.M9)"),
]


_PHOTO_REQUIRED_CONDITIONS = ("damaged", "poor", "missing")
_RESOLUTION_REQUIRED_CONDITIONS = ("missing",)


class NeonEquipmentCheckinWizard(models.TransientModel):
    _name = "neon.equipment.checkin.wizard"
    _description = "Equipment Check-In Wizard"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        readonly=True,
    )
    line_id = fields.Many2one(
        "commercial.event.job.equipment.line",
        string="Line (scoped)",
        readonly=True,
        help="Set when the wizard was opened from a single line. "
        "NULL when opened from the event_job header (bulk path).",
    )
    to_location_text = fields.Char(
        string="Return Location",
        default="Workshop A",
        help="Where the gear physically lands at check-in. Free "
        "text — structured location master is deferred.",
    )
    checkin_line_ids = fields.One2many(
        "neon.equipment.checkin.wizard.line",
        "wizard_id",
        string="Units to Check In",
    )

    @api.model
    def default_get(self, fields_list):
        """Auto-populate checkin_line_ids when an event_job (and
        optionally a line) is in the context. Picks up every unit
        currently in checked_out / transferred state on the event
        via fulfilled reservations."""
        vals = super().default_get(fields_list)
        event_job_id = (
            vals.get("event_job_id")
            or self.env.context.get("default_event_job_id"))
        line_id = (
            vals.get("line_id")
            or self.env.context.get("default_line_id"))
        if not event_job_id:
            return vals
        Reservation = self.env["neon.equipment.reservation"].sudo()
        base = [("event_job_id", "=", event_job_id),
                ("state", "=", "fulfilled")]
        if line_id:
            base.append(("equipment_line_id", "=", line_id))
        line_vals = []
        # Serial: one wizard line per checked-out / transferred unit.
        # Dedupe in case a unit somehow has two fulfilled reservations.
        seen_unit_ids = set()
        for res in Reservation.search(base + [
                ("unit_id.state", "in", ("checked_out", "transferred"))]):
            if res.unit_id.id in seen_unit_ids:
                continue
            seen_unit_ids.add(res.unit_id.id)
            line_vals.append((0, 0, {
                "unit_id": res.unit_id.id,
                "product_template_id": res.unit_id.product_template_id.id,
                "reservation_id": res.id,
                "quantity": res.quantity,
                "condition_at_event": "good",
            }))
        # P5.M11 quantity: one wizard line per unit-less COUNT reservation
        # (held against quantity_on_hand; no unit state to inspect).
        for res in Reservation.search(base + [("unit_id", "=", False)]):
            line_vals.append((0, 0, {
                "reservation_id": res.id,
                "product_template_id": res.product_template_id.id,
                "quantity": res.quantity,
                "condition_at_event": "good",
            }))
        if line_vals:
            vals["checkin_line_ids"] = line_vals
        return vals

    def action_confirm(self):
        self.ensure_one()
        if not self.checkin_line_ids:
            raise UserError(_(
                "No units to check in — the event has no checked-out "
                "or transferred equipment."))
        # Defence-in-depth authority recheck. Source action methods
        # already gated this, but a direct API call to the wizard
        # would bypass that — re-validate here.
        if not self.event_job_id._user_can_checkin():
            raise UserError(_(
                "You are not authorised to check in equipment for "
                "%(event)s. Manager, Lead Tech, or Crew Chief on "
                "this event only."
            ) % {"event": self.event_job_id.name})

        # Pre-validate every line before any writes — collect errors
        # so the user sees all problems at once instead of one at a
        # time. P5.M9: incident_link is now a real workflow (no
        # longer a stub), so no pre-validation error there.
        photo_missing = []
        resolution_missing = []
        for line in self.checkin_line_ids:
            label = (line.unit_id.display_name
                     or line.product_template_id.display_name)
            if line.requires_photo and not line.photo:
                photo_missing.append(label)
            # P5.M11: a quantity COUNT line is unit-less and resolves a
            # damaged/missing SUBSET by decrement, not a per-unit
            # resolution_path -- so it never blocks on resolution_missing.
            if (line.unit_id and line.requires_resolution
                    and not line.resolution_path):
                resolution_missing.append(label)
        errors = []
        if photo_missing:
            errors.append(_(
                "Photo required for damaged / poor / missing items: "
                "%(units)s"
            ) % {"units": ", ".join(photo_missing)})
        if resolution_missing:
            errors.append(_(
                "Resolution required for missing items: %(units)s"
            ) % {"units": ", ".join(resolution_missing)})
        if errors:
            raise UserError("\n\n".join(errors))

        actor_uid = self.env.uid
        with self.env.cr.savepoint():
            for line in self.checkin_line_ids:
                line.sudo()._process_checkin(actor_uid)
        return {"type": "ir.actions.act_window_close"}


class NeonEquipmentCheckinWizardLine(models.TransientModel):
    _name = "neon.equipment.checkin.wizard.line"
    _description = "Equipment Check-In Wizard Line"

    wizard_id = fields.Many2one(
        "neon.equipment.checkin.wizard",
        required=True,
        ondelete="cascade",
    )
    unit_id = fields.Many2one(
        "neon.equipment.unit",
        string="Unit",
        help="P5.M11: OPTIONAL — set for a serial per-unit check-in; a "
        "quantity COUNT check-in is unit-less (product + quantity).",
    )
    product_template_id = fields.Many2one(
        "product.template",
        string="Product",
        readonly=True,
        help="P5.M11 — set in default_get (the unit's product for serial, "
        "the reservation's product for a quantity COUNT line).",
    )
    quantity = fields.Integer(
        string="Quantity", default=1,
        help="P5.M11 — count being checked in (1 for a serial unit).",
    )
    damaged_qty = fields.Integer(
        string="Damaged Qty", default=0,
        help="P5.M11 — for a quantity COUNT check-in: how many of the "
        "count are damaged / missing. Drives a stock_adjust movement + "
        "a quantity_on_hand decrement (audited by actor).",
    )
    current_state = fields.Selection(
        related="unit_id.state",
        readonly=True,
        string="Current State",
    )
    reservation_id = fields.Many2one(
        "neon.equipment.reservation",
        string="Source Reservation",
        readonly=True,
        help="The fulfilled reservation linking this unit to the "
        "event_job (where it physically came from).",
    )
    condition_at_event = fields.Selection(
        _CONDITIONS,
        string="Condition",
        required=True,
        default="good",
    )
    send_to_maintenance = fields.Boolean(
        default=False,
        help="Only relevant when condition='poor'. When ticked, the "
        "unit moves directly to maintenance instead of being "
        "returned to active service.",
    )
    photo = fields.Image(
        max_width=1920, max_height=1080,
        help="Required for damaged / poor / missing items (Q8). "
        "Optional for good / fair.",
    )
    notes = fields.Text()
    requires_photo = fields.Boolean(
        compute="_compute_requires_photo",
    )
    requires_resolution = fields.Boolean(
        compute="_compute_requires_resolution",
    )
    resolution_path = fields.Selection(
        _RESOLUTION_PATHS,
        string="Resolution",
        help="Required when condition='missing'. Drives the unit's "
        "final state at check-in.",
    )
    resolution_notes = fields.Text(
        string="Resolution Notes",
    )

    @api.depends("condition_at_event")
    def _compute_requires_photo(self):
        for rec in self:
            rec.requires_photo = (
                rec.condition_at_event in _PHOTO_REQUIRED_CONDITIONS)

    @api.depends("condition_at_event")
    def _compute_requires_resolution(self):
        for rec in self:
            rec.requires_resolution = (
                rec.condition_at_event in _RESOLUTION_REQUIRED_CONDITIONS)

    def _process_checkin(self, actor_uid):
        """Per-line check-in. Runs inside the wizard's savepoint —
        any unhandled raise rolls back the whole batch."""
        self.ensure_one()
        Movement = self.env["neon.equipment.movement"].sudo()
        # P5.M11 — quantity COUNT check-in (unit-less). good/fair: just a
        # checkin movement, no quantity_on_hand change. damaged/missing/
        # poor with a damaged_qty: a stock_adjust movement + decrement
        # quantity_on_hand by that count (actor-audited -- it changes
        # every future availability answer). Repair-restores-qoh is a
        # noted follow-on, not this milestone.
        if not self.unit_id and self.product_template_id:
            prod = self.product_template_id.sudo()
            ej = self.wizard_id.event_job_id.sudo()
            src = self.reservation_id.sudo()
            cond_q = self.condition_at_event
            dmg = (max(0, self.damaged_qty or 0)
                   if cond_q in ("damaged", "missing", "poor") else 0)
            Movement.create({
                "product_template_id": prod.id,
                "quantity": self.quantity,
                "event_job_id": ej.id,
                "equipment_line_id": (
                    src.equipment_line_id.id if src else False),
                "reservation_id": src.id if src else False,
                "movement_type": "checkin",
                "actor_id": actor_uid,
                "condition_at_event": cond_q,
                "to_location_text": (
                    self.wizard_id.to_location_text or "Workshop A"),
                "photo": self.photo or False,
                "notes": self.notes or "",
            })
            if dmg > 0:
                old_qoh = prod.quantity_on_hand or 0
                new_qoh = max(0, old_qoh - dmg)
                prod.write({"quantity_on_hand": new_qoh})
                Movement.create({
                    "product_template_id": prod.id,
                    "quantity": dmg,
                    "event_job_id": ej.id,
                    "movement_type": "stock_adjust",
                    "actor_id": actor_uid,
                    "condition_at_event": cond_q,
                    "notes": _(
                        "P5.M11 damaged/missing at check-in: on-hand "
                        "%(old)d -> %(new)d (-%(d)d). %(n)s") % {
                        "old": old_qoh, "new": new_qoh, "d": dmg,
                        "n": self.resolution_notes or ""},
                })
            return
        unit = self.unit_id.sudo()
        cond = self.condition_at_event
        event_job = self.wizard_id.event_job_id.sudo()
        Reservation = self.env["neon.equipment.reservation"].sudo()

        source_res = self.reservation_id.sudo()
        # Fallback if the wizard line was built without a reservation
        # link (manual add or upstream gap) — derive it.
        if not source_res:
            source_res = Reservation.search([
                ("event_job_id", "=", event_job.id),
                ("unit_id", "=", unit.id),
                ("state", "=", "fulfilled"),
            ], limit=1, order="reserve_from desc, id desc")

        # Missing path: never creates a check-in movement (the unit
        # didn't physically come back). Drives reservation flag or
        # write-off chain instead.
        if cond == "missing":
            if self.resolution_path == "returned_late":
                if source_res:
                    source_res.write({"late_return_pending": True})
                event_job.message_post(body=_(
                    "Unit %(unit)s flagged as returned-late pending "
                    "by %(actor)s. Closeout permitted; reconcile "
                    "when the unit is physically returned."
                ) % {
                    "unit": unit.display_name,
                    "actor": self.env["res.users"].sudo().browse(
                        actor_uid).name,
                })
                return
            elif self.resolution_path == "write_off":
                unit._do_transition("returned")
                unit._do_transition("decommissioned")
                Movement.create({
                    "unit_id": unit.id,
                    "event_job_id": event_job.id,
                    "equipment_line_id": (
                        source_res.equipment_line_id.id
                        if source_res else False),
                    "reservation_id": (
                        source_res.id if source_res else False),
                    "movement_type": "write_off",
                    "actor_id": actor_uid,
                    "from_location_text": unit.workshop_location or "",
                    "condition_at_event": "missing",
                    "notes": self.resolution_notes or "",
                })
                return
            elif self.resolution_path == "incident_link":
                # P5.M9 — incident_link now creates a real
                # neon.equipment.incident in 'open' state with
                # type='loss'. The unit stays in checked_out (the
                # investigation drives subsequent state changes
                # via the incident's resolve_* actions). The
                # source reservation gets late_return_pending=True
                # so closeout can still proceed while the
                # investigation runs.
                Incident = self.env[
                    "neon.equipment.incident"].sudo()
                Incident.create({
                    "unit_id": unit.id,
                    "incident_type": "loss",
                    "source_event_job_id": event_job.id,
                    "description": self.resolution_notes or _(
                        "Reported from check-in on %(event)s: "
                        "unit missing at venue."
                    ) % {"event": event_job.display_name},
                })
                if source_res:
                    source_res.write({"late_return_pending": True})
                event_job.message_post(body=_(
                    "Incident opened on %(unit)s by %(actor)s "
                    "(missing at check-in). Closeout permitted; "
                    "investigation continues."
                ) % {
                    "unit": unit.display_name,
                    "actor": self.env["res.users"].sudo().browse(
                        actor_uid).name,
                })
                return

        # Non-missing path: transition unit + create check-in movement.
        if cond == "damaged":
            unit._do_transition("damaged")
        elif cond == "poor" and self.send_to_maintenance:
            unit._do_transition("maintenance")
        else:
            # good / fair / poor-without-maintenance: walk through
            # 'returned' so the audit captures the inspection moment.
            unit._do_transition("returned")
            unit._do_transition("active")

        # Clear any stale late_return_pending flag — the unit has
        # physically come back, so the closeout blocker exception
        # no longer applies.
        if source_res and source_res.late_return_pending:
            source_res.write({"late_return_pending": False})

        Movement.create({
            "unit_id": unit.id,
            "event_job_id": event_job.id,
            "equipment_line_id": (
                source_res.equipment_line_id.id
                if source_res else False),
            "reservation_id": (
                source_res.id if source_res else False),
            "movement_type": "checkin",
            "actor_id": actor_uid,
            "from_location_text": unit.workshop_location or "",
            "to_location_text": (
                self.wizard_id.to_location_text or "Workshop A"),
            "condition_at_event": cond,
            "photo": self.photo or False,
            "notes": self.notes or "",
        })
