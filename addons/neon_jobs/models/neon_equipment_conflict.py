# -*- coding: utf-8 -*-
"""P-B2 -- Conflict Detection Engine.

Persisted conflict-run records (header + line) + the rules-based
engine that computes them. Deterministic; NO LLM, NO network.

⚠️ DECISION (B2, D1): two models -- `neon.equipment.conflict` (header,
one row per engine run) and `neon.equipment.conflict.line` (detail,
one row per flagged product within that run). Both perm_unlink=0
(audit-trail rule from CLAUDE.md).

⚠️ DECISION (B2, D2): the engine reads
`commercial.event.job.effective_overlap_start / end` -- a B2-LAYER
stored compute on event_job, distinct from B1's
`occupation_start / end` (which is workshop-transit-widened and
stays frozen as B1's contract). When `load_in_start` AND
`load_out_end` are both set, effective = exactly those; when blank,
fallback to `event_date 00:00 -> (event_end_date or event_date) +
1 day 06:00`. Conservative (over-counting) fallback per gate-1
policy.

⚠️ DECISION (B2, D3): availability is WINDOW-RELATIVE and simple:
  available = total_owned_for_product
              - units_in_state='transferred' (= sub_hired_out)
              - units_with_condition_status != 'good'
We do NOT subtract non-overlapping reservations: any reservation
that overlaps the current cluster's window has its source event IN
the cluster (counted in `required_qty`), so subtracting it would
double-count. Reservations for events OUTSIDE the cluster window
don't reduce availability for THIS cluster -- those windows have
their own independent runs.

⚠️ DECISION (B2, D4): recompute is window-scoped. When event X
triggers a recompute, the engine builds the cluster of overlapping
events around X, sums per-product demand, and writes one
`conflict.line` per product that is at deficit / zero-margin / below
threshold. Global re-run is a manual button + a daily 06:00
backstop cron.

⚠️ DECISION (B2, D5): alerts reuse the existing `equipment_conflict`
trigger_type (already in TRIGGER_TYPE_SELECTION + already seeded
with a config row). Source_model is `product.template`,
source_id = product_template.id -- STABLE across re-runs, so the
Action Centre's natural dedup-by-(trigger, source_model, source_id)
gives us idempotency for free. The existing per-reservation
equipment_conflict path uses source_model='neon.equipment.reservation'
so there's no source-id collision; both alert kinds coexist.

⚠️ DECISION (B2, D6): the sub-hire priority list is exposed as
ordered `conflict.line` records via the header form (no separate
view / no PO drafting -- that's B4). Priority rank stored as
`sub_hire_priority` Integer on each line; sort = (soonest
overlapping event_start, then largest deficit_qty).

⚠️ DECISION (B2, D7 trim): only the OPERATIONS dashboard variant
gets the conflicts panel this milestone. Director can MD-peek
operations to see it. MD still receives the rule-8 alert.

⚠️ DECISION (B2, D8): a soft data-quality nudge fires when an event
job is confirmed without load-in/out windows. Reuses the Action
Centre with a new low-priority TASK trigger
`load_window_missing` so the team is nudged to fill in precise
windows (which collapses the conservative fallback in D2).
"""
import logging
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


_OVERALL_STATUS = [
    ("clear", "Clear"),
    ("zero_margin", "Zero Margin"),
    ("deficit", "Deficit"),
]
_LINE_STATUS = [
    ("surplus", "Surplus"),
    ("below_threshold", "Below Low-Stock Threshold"),
    ("zero_margin", "Zero Margin"),
    ("deficit", "Deficit"),
]
_TRIGGER_REASONS = [
    ("event_confirmed", "Event job confirmed"),
    ("requirement_changed", "Equipment requirement changed"),
    ("manual", "Manual run"),
    ("cron", "Daily backstop cron"),
]

# States that mean a unit is physically GONE from the workshop pool
# (sub-hired out, in transit, in maintenance, damaged, decommissioned).
# checked_out and transferred imply the unit is at / heading to a venue.
_UNIT_UNAVAILABLE_STATES_HARD = (
    "transferred", "decommissioned",
)

# Default fallback for effective overlap window (used when all four
# load_in/out fields are blank). Models the typical "overnight strike"
# pattern -- gear remains at the venue overnight into the morning.
_FALLBACK_START_HOUR = 0   # 00:00 on event_date
_FALLBACK_END_DAYS_AFTER = 1
_FALLBACK_END_HOUR = 6    # 06:00 next day after (event_end_date or event_date)


def _fallback_overlap_window(rec):
    """Conservative window for an event job with no precise load
    fields. Returns (start_dt, end_dt) or (False, False) if no
    event_date at all."""
    if not rec.event_date:
        return (False, False)
    start = datetime.combine(rec.event_date, time(_FALLBACK_START_HOUR, 0))
    upper_day = (rec.event_end_date or rec.event_date) + timedelta(
        days=_FALLBACK_END_DAYS_AFTER)
    end = datetime.combine(upper_day, time(_FALLBACK_END_HOUR, 0))
    return (start, end)


# ============================================================
# CONFLICT HEADER
# ============================================================
class NeonEquipmentConflict(models.Model):
    _name = "neon.equipment.conflict"
    _description = "Equipment Conflict Run (B2)"
    _inherit = ["mail.thread"]
    _order = "triggered_at desc, id desc"

    name = fields.Char(
        required=True, default=lambda self: _("Conflict run"),
        readonly=True, copy=False, tracking=True,
    )
    triggered_at = fields.Datetime(
        required=True, default=fields.Datetime.now,
        readonly=True, index=True,
    )
    trigger_reason = fields.Selection(
        _TRIGGER_REASONS, required=True, default="manual",
        readonly=True, tracking=True,
    )
    triggered_by_event_id = fields.Many2one(
        "commercial.event.job", readonly=True, ondelete="set null",
        help="The event job whose confirm / requirement change "
        "triggered this run, when applicable.",
    )
    window_start = fields.Datetime(
        readonly=True,
        help="Earliest effective_overlap_start across the events in "
        "the cluster this run evaluated.",
    )
    window_end = fields.Datetime(
        readonly=True,
        help="Latest effective_overlap_end across the events in the "
        "cluster.",
    )
    overall_status = fields.Selection(
        _OVERALL_STATUS, required=True, default="clear",
        readonly=True, tracking=True, index=True,
    )
    line_ids = fields.One2many(
        "neon.equipment.conflict.line", "conflict_id",
        string="Conflict Lines",
    )
    line_count = fields.Integer(
        compute="_compute_line_counts", store=True,
    )
    deficit_count = fields.Integer(
        compute="_compute_line_counts", store=True,
    )
    zero_margin_count = fields.Integer(
        compute="_compute_line_counts", store=True,
    )
    alert_dispatched_at = fields.Datetime(
        readonly=True,
        help="Stamp when this run's alerts hit the Action Centre. "
        "NULL on a 'clear' run.",
    )

    @api.depends("line_ids.status")
    def _compute_line_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.deficit_count = len(rec.line_ids.filtered(
                lambda l: l.status == "deficit"))
            rec.zero_margin_count = len(rec.line_ids.filtered(
                lambda l: l.status == "zero_margin"))

    # --- public entry points wired to UI buttons + cron ----------

    @api.model
    def cron_run_global(self):
        """B2 D4 -- daily backstop cron. Wraps ConflictEngine.run_global
        so the ir_cron entry can call it via a plain @api.model
        reference."""
        return ConflictEngine(self.env).run_global(
            trigger_reason="cron")

    def action_recompute_around_trigger(self):
        """Manual button on the conflict form -- recomputes around
        triggered_by_event_id if set, else does a global run."""
        self.ensure_one()
        engine = ConflictEngine(self.env)
        if self.triggered_by_event_id:
            return engine.run_for_event(
                self.triggered_by_event_id,
                trigger_reason="manual")
        return engine.run_global(trigger_reason="manual")

    @api.model
    def action_recompute_global(self):
        """Manager-tier 'Recompute All' button on the tree view."""
        return ConflictEngine(self.env).run_global(
            trigger_reason="manual")


# ============================================================
# CONFLICT LINE
# ============================================================
class NeonEquipmentConflictLine(models.Model):
    _name = "neon.equipment.conflict.line"
    _description = "Equipment Conflict Line"
    _order = "sub_hire_priority, id"

    conflict_id = fields.Many2one(
        "neon.equipment.conflict", required=True,
        ondelete="cascade", index=True,
    )
    product_template_id = fields.Many2one(
        "product.template", required=True, index=True,
        ondelete="restrict",
    )
    category_id = fields.Many2one(
        "neon.equipment.category",
        related="product_template_id.equipment_category_id",
        store=True, readonly=True,
    )
    required_qty = fields.Integer(required=True)
    available_qty = fields.Integer(required=True)
    margin = fields.Integer(required=True, index=True)
    deficit_qty = fields.Integer(
        required=True, default=0,
        help="max(0, required - available)",
    )
    status = fields.Selection(
        _LINE_STATUS, required=True, index=True,
    )
    competing_event_ids = fields.Many2many(
        "commercial.event.job",
        "neon_eq_conflict_line_event_rel",
        "line_id", "event_job_id",
        string="Competing event jobs",
        help="The specific event jobs whose demand contributes to "
        "required_qty for this product in this run.",
    )
    competing_event_count = fields.Integer(
        compute="_compute_competing_event_count", store=True,
    )
    sub_hire_priority = fields.Integer(
        default=0, index=True,
        help="Rank within the run for B4's sub-hire drafting. "
        "Lower = more urgent. Sorted by soonest competing-event "
        "start, then largest deficit_qty.",
    )
    earliest_competing_start = fields.Datetime(
        compute="_compute_earliest_competing_start", store=True,
    )

    @api.depends("competing_event_ids")
    def _compute_competing_event_count(self):
        for rec in self:
            rec.competing_event_count = len(rec.competing_event_ids)

    @api.depends("competing_event_ids.effective_overlap_start")
    def _compute_earliest_competing_start(self):
        for rec in self:
            starts = [e.effective_overlap_start
                      for e in rec.competing_event_ids
                      if e.effective_overlap_start]
            rec.earliest_competing_start = min(starts) if starts else False


# ============================================================
# ENGINE
# ============================================================
class ConflictEngine:
    """Stateless engine. One run per call. Read-only on input
    models, writes only neon.equipment.conflict[.line] and AC
    items via the helper below."""

    def __init__(self, env):
        self.env = env
        self.EventJob = env["commercial.event.job"].sudo()
        self.Line = env["commercial.event.job.equipment.line"].sudo()
        self.Unit = env["neon.equipment.unit"].sudo()
        self.Conflict = env["neon.equipment.conflict"].sudo()
        self.ConflictLine = env[
            "neon.equipment.conflict.line"].sudo()

    # --- public entry points ----------------------------------------

    def run_for_event(self, event_job, trigger_reason="manual"):
        """Run the engine around the cluster touching ``event_job``."""
        cluster = self._cluster_around(event_job)
        return self._run(cluster, trigger_reason=trigger_reason,
                          triggered_by=event_job)

    def run_global(self, trigger_reason="cron", lookahead_days=30):
        """Run for every event job whose effective_overlap_start is
        within the next ``lookahead_days``. Used by the cron + the
        manual 'Recompute All' button."""
        now = fields.Datetime.now()
        horizon = now + timedelta(days=lookahead_days)
        upcoming = self.EventJob.search([
            ("effective_overlap_start", "!=", False),
            ("effective_overlap_start", "<=", horizon),
            ("effective_overlap_end", ">=", now),
            ("state", "not in",
             ("cancelled", "released", "closed")),
        ])
        # Cluster by overlap -- if two upcoming events overlap, one
        # run covers both. Walk the set, taking unprocessed events.
        processed = set()
        last_conflict = self.Conflict.browse()
        for ev in upcoming:
            if ev.id in processed:
                continue
            cluster = self._cluster_around(ev)
            processed.update(cluster.ids)
            last_conflict |= self._run(
                cluster, trigger_reason=trigger_reason,
                triggered_by=ev)
        return last_conflict

    # --- cluster building ------------------------------------------

    def _cluster_around(self, event_job):
        """All events whose effective_overlap_window intersects
        ``event_job``'s. Includes event_job itself. Excludes
        terminal-state event jobs."""
        if (not event_job.effective_overlap_start
                or not event_job.effective_overlap_end):
            return event_job
        cluster_ids = {event_job.id}
        frontier = {event_job.id}
        terminal = ("cancelled", "released", "closed", "draft")
        while frontier:
            seed = self.EventJob.browse(list(frontier))
            min_start = min(e.effective_overlap_start for e in seed)
            max_end = max(e.effective_overlap_end for e in seed)
            extras = self.EventJob.search([
                ("id", "not in", list(cluster_ids)),
                ("state", "not in", terminal),
                ("effective_overlap_start", "<=", max_end),
                ("effective_overlap_end", ">=", min_start),
            ])
            frontier = set(extras.ids) - cluster_ids
            cluster_ids |= frontier
        return self.EventJob.browse(list(cluster_ids))

    # --- engine core ------------------------------------------------

    def _run(self, cluster, trigger_reason, triggered_by=None):
        if not cluster:
            return self.Conflict.browse()
        window_start = min(
            (e.effective_overlap_start for e in cluster
             if e.effective_overlap_start),
            default=False,
        )
        window_end = max(
            (e.effective_overlap_end for e in cluster
             if e.effective_overlap_end),
            default=False,
        )

        demand_by_product = self._aggregate_demand(cluster)
        # Touch every product that has demand AND every product that
        # has a low_stock_threshold > 0 (we may flag those even on
        # zero demand if available drops below threshold).
        thresh_products = self.env["product.template"].sudo().search([
            ("equipment_category_id.low_stock_threshold", ">", 0),
            ("is_workshop_item", "=", True),
        ])
        product_ids = (set(demand_by_product.keys())
                        | set(thresh_products.ids))

        lines_vals = []
        priority_seed = []  # (earliest_start, -deficit, idx) tuples
        for pid in product_ids:
            required = demand_by_product.get(pid, {}).get("qty", 0)
            competing_ids = list(demand_by_product.get(pid, {}).get(
                "events", set()))
            available = self._available_for_product(pid)
            margin = available - required
            deficit_qty = max(0, required - available)
            category = self.env["product.template"].browse(
                pid).equipment_category_id
            threshold = category.low_stock_threshold or 0
            below_threshold = (
                threshold > 0 and available <= threshold)

            if margin < 0:
                status = "deficit"
            elif margin == 0 and required > 0:
                status = "zero_margin"
            elif below_threshold and required > 0:
                status = "below_threshold"
            else:
                # Skip pure-surplus lines with no demand and no
                # threshold trigger -- avoids 100s of "neutral" rows
                # per run on a populated workshop.
                if required == 0 and not below_threshold:
                    continue
                status = "surplus"

            # earliest_start placeholder; computed compute fills the
            # stored field, but we also use it for the priority seed
            # so the engine can sort lines BEFORE they hit the DB.
            cluster_starts = [
                self.EventJob.browse(eid).effective_overlap_start
                for eid in competing_ids
            ]
            cluster_starts = [s for s in cluster_starts if s]
            earliest = min(cluster_starts) if cluster_starts else (
                window_start or fields.Datetime.now())

            lines_vals.append({
                "product_template_id": pid,
                "required_qty": required,
                "available_qty": available,
                "margin": margin,
                "deficit_qty": deficit_qty,
                "status": status,
                "competing_event_ids": [(6, 0, competing_ids)],
            })
            priority_seed.append((earliest, -deficit_qty,
                                   len(lines_vals) - 1))

        # Sort + assign sub_hire_priority before write.
        priority_seed.sort()
        for rank, (_e, _d, idx) in enumerate(priority_seed, start=1):
            lines_vals[idx]["sub_hire_priority"] = rank

        if not lines_vals:
            overall = "clear"
        elif any(v["status"] == "deficit" for v in lines_vals):
            overall = "deficit"
        elif any(v["status"] == "zero_margin" for v in lines_vals):
            overall = "zero_margin"
        else:
            overall = "clear"

        run_name = "CONF-{stamp}".format(
            stamp=fields.Datetime.now().strftime("%Y%m%d-%H%M%S"))
        conflict = self.Conflict.create({
            "name": run_name,
            "trigger_reason": trigger_reason,
            "triggered_by_event_id": (
                triggered_by.id if triggered_by else False),
            "window_start": window_start,
            "window_end": window_end,
            "overall_status": overall,
            "line_ids": [(0, 0, v) for v in lines_vals],
        })
        if overall != "clear":
            self._dispatch_alerts(conflict)
        else:
            # If the run is clear, close any open per-product
            # equipment_conflict items for products we just verified
            # as clear. We CANNOT bulk-close here without re-reading
            # the AC items keyed by product; conservatively close
            # nothing (the AC item's own resolution path handles it).
            pass
        return conflict

    # --- demand aggregation ----------------------------------------

    def _aggregate_demand(self, cluster):
        """Returns {product_template_id: {'qty': int, 'events': set(ids)}}"""
        result = {}
        lines = self.Line.search([
            ("event_job_id", "in", cluster.ids),
            ("state", "not in", ("cancelled",)),
            ("cancelled_explicit", "=", False),
        ])
        for line in lines:
            pid = line.product_template_id.id
            if not pid:
                continue
            slot = result.setdefault(
                pid, {"qty": 0, "events": set()})
            slot["qty"] += int(line.quantity_planned or 0)
            slot["events"].add(line.event_job_id.id)
        return result

    # --- availability ----------------------------------------------

    def _available_for_product(self, product_id):
        """D3 -- window-relative availability per gate-1.

        SERIAL products (B2 original behaviour, UNCHANGED):
            available = total_owned
                        - units in state='transferred' (sub-hired)
                        - units with condition_status != 'good'

        QUANTITY / BATCH products (B14c D2 + D3):
            available = max(0, product.quantity_on_hand
                              - (quantity_on_hand if the single
                                 representing unit is hard-unavailable
                                 or non-good, else 0))
            i.e. quantity products store the count on the product;
            their single unit row is binary (all-or-nothing) for
            sub-hired / non-good state. A future enhancement could
            model fractional sub-hires for bulk SKUs (⚠️ B14c D3:
            flagged, not implemented this milestone).

        Does NOT subtract reservations (overlapping reservations
        come in via required_qty; non-overlapping reservations are
        irrelevant to this cluster).
        """
        Product = self.env["product.template"].sudo()
        product = Product.browse(product_id).exists()
        if not product:
            return 0
        tm = product.tracking_mode or "serial"
        units = self.Unit.search([
            ("product_template_id", "=", product_id),
            ("active", "=", True),
        ])
        if tm in ("quantity", "batch"):
            qoh = int(product.quantity_on_hand or 0)
            if not units:
                return max(0, qoh)
            # Binary unavailability: if ANY representing unit is
            # hard-unavailable or non-good, treat the whole on-
            # hand count as unavailable. Quantity products
            # canonically have ONE unit row; defensive against
            # multiple rows by checking the union.
            blocked = bool(units.filtered(
                lambda u: u.state in _UNIT_UNAVAILABLE_STATES_HARD
                           or u.condition_status != "good"))
            return 0 if blocked else max(0, qoh)
        # SERIAL path (unchanged behaviour)
        total = len(units)
        if not total:
            return 0
        sub_hired_out = len(units.filtered(
            lambda u: u.state in _UNIT_UNAVAILABLE_STATES_HARD))
        non_good = len(units.filtered(
            lambda u: u.condition_status != "good"))
        # A unit can be both sub-hired-out AND non-good (rare; both
        # exclude). Avoid double-subtracting via set intersection.
        either = units.filtered(
            lambda u: u.state in _UNIT_UNAVAILABLE_STATES_HARD
                       or u.condition_status != "good")
        return max(0, total - len(either))

    # --- alert dispatch (idempotent) -------------------------------

    def _dispatch_alerts(self, conflict):
        """Create one Action Centre item per deficit/zero-margin
        product. Source is the PRODUCT (stable across re-runs) so
        the mixin's dedup-by-(trigger, source_model, source_id)
        gives free idempotency.

        Reuses the existing 'equipment_conflict' trigger_type (per
        gate-1 D5 revised). The existing per-reservation path uses
        source_model='neon.equipment.reservation' so there's no
        source-id collision.
        """
        Item = self.env["action.centre.item"].sudo()
        Config = self.env["action.centre.trigger.config"].sudo()
        config = Config.search(
            [("trigger_type", "=", "equipment_conflict")], limit=1)
        if not config or not config.is_enabled:
            return Item.browse()
        ProductIrModel = self.env["ir.model"].sudo()._get(
            "product.template")
        flagged = conflict.line_ids.filtered(
            lambda l: l.status in ("deficit", "zero_margin"))
        if not flagged:
            return Item.browse()
        # Group lines by product so we get one AC item per product
        # (the line.competing_event_ids gives the full story in the
        # item description).
        created = Item.browse()
        for line in flagged:
            pid = line.product_template_id.id
            existing = Item._find_existing_open_item(
                "equipment_conflict", "product.template", pid)
            if existing:
                continue
            comp_names = ", ".join(
                e.name for e in line.competing_event_ids[:4])
            if line.competing_event_count > 4:
                comp_names += "..."
            descr = _(
                "Equipment shortfall: %(prod)s requires %(req)s but "
                "%(avail)s available (margin %(margin)s, deficit "
                "%(def_qty)s) across %(n)s competing events: "
                "%(events)s."
            ) % {
                "prod": line.product_template_id.display_name,
                "req": line.required_qty,
                "avail": line.available_qty,
                "margin": line.margin,
                "def_qty": line.deficit_qty,
                "n": line.competing_event_count,
                "events": comp_names,
            }
            vals = {
                "trigger_type": "equipment_conflict",
                "trigger_config_id": config.id,
                "is_manual": False,
                "title": _("Equipment deficit: %(prod)s") % {
                    "prod": line.product_template_id.display_name},
                "item_type": config.item_type or "alert",
                "primary_role": config.primary_role or "manager",
                "priority": "high",
                "source_model_id": ProductIrModel.id,
                "source_id": pid,
                "description": descr,
            }
            created |= Item.create(vals)
        if created:
            conflict.sudo().write({
                "alert_dispatched_at": fields.Datetime.now(),
            })
        return created
