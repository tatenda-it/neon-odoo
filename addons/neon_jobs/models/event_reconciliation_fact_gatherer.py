# -*- coding: utf-8 -*-
"""P-B5 -- EventReconciliationFactGatherer.

The POST-event fact-gather. Walks a commercial.event.job +:
  * reuses B3's DeploymentPlanFactGatherer for plan-side facts
    (equipment lines, crew, windows, B2 conflict snapshot)
  * pulls the active B3 plan + all B4 sub-hire requests
  * computes equipment condition deltas (units that flipped to
    needs_repair / written_off since the event_date)
  * reads planned cost (neon.finance.quote.amount_total) +
    actual cost (sum of neon.finance.cost.line.amount) via sudo()
    and surfaces the variance

⚠️ DECISION (B5, D3): everything quantitative comes from here.
Claude only narrates. The validator REJECTS any output that
contradicts these facts.

⚠️ DECISION (B5, D4): READ-ONLY. sudo() is used to cross the ACL
boundary into neon_finance (operational tier reading finance
models), never to write. No journal entries, no invoice
modifications, no PO state changes.

⚠️ DECISION (B5, D10): finance reads are via sudo() to match the
dashboard-tile pattern that already crosses this boundary
(reference_owl_dashboard_pattern + neon_finance cross-module ACL).
"""
import json
import logging
from datetime import datetime, timedelta

from .deployment_plan_fact_gatherer import (
    DeploymentPlanFactGatherer,
)


_logger = logging.getLogger(__name__)


class EventReconciliationFactGatherer:
    """One instance per generate() call. Read-only on the env."""

    def __init__(self, env):
        self.env = env
        self._plan_gatherer = DeploymentPlanFactGatherer(env)

    def gather(self, event_job):
        """Return the facts dict for a post-event reconciliation.

        Shape (extends B3's facts dict + adds B5-specific keys):

        {
          # ---- carried from B3 fact-gather ----
          "event_job": {...},
          "venue": {...},
          "partner": {...},
          "lead_tech": {...}, "crew_chief": {...}, "crew": [...],
          "equipment_lines": [...],
          "b2_conflict": {...},
          "crew_call_times": [...],

          # ---- new B5 sections ----
          "plan_snapshot": {                    # B3 plan summary
            "plan_id": int | 0,
            "name": str, "status": str, "revision": int,
            "section_titles": [...],
            "deficits_at_plan_time": int,
          },
          "subhire_snapshot": [                 # B4 active reqs
            {
              "request_id": int, "name": str, "status": str,
              "supplier_name": str,
              "po_name": str | "", "po_state": str | "",
              "line_count": int,
              "qty_short_total": int,
            }, ...
          ],
          "condition_deltas": [                 # B1 condition flips
            {
              "unit_id": int, "serial_number": str,
              "product_name": str,
              "new_status": "needs_repair" | "written_off",
              "noted_after_event": bool,
            }, ...
          ],
          "cost_variance": {                    # planned vs actual
            "planned_total": float,
            "actual_total": float,
            "variance_total": float,
            "currency": str,
            "by_cost_type": [
              {"cost_type": str,
               "amount": float}, ...
            ],
          },
          "event_window_label": str,            # mirrors B4's R5
        }
        """
        base = self._plan_gatherer.gather(event_job)

        plan_snapshot = self._snapshot_active_plan(event_job)
        subhire_snapshot = self._snapshot_subhire_requests(
            event_job)
        condition_deltas = self._gather_condition_deltas(
            event_job)
        cost_variance = self._gather_cost_variance(event_job)

        # Event-window label per validator R5 -- precise when both
        # load-in_start AND load-out_end are set; event_date fall
        # back otherwise. Mirrors B4's SubhireRequestFactGatherer.
        ev = base.get("event_job") or {}
        load_in = ev.get("load_in_start")
        load_out = ev.get("load_out_end")
        if load_in and load_out:
            window_label = "{} -> {}".format(load_in, load_out)
        else:
            start_d = ev.get("event_date") or ""
            end_d = (ev.get("event_end_date")
                      or start_d or "")
            window_label = "{} -> {}".format(start_d, end_d)

        base["plan_snapshot"] = plan_snapshot
        base["subhire_snapshot"] = subhire_snapshot
        base["condition_deltas"] = condition_deltas
        base["cost_variance"] = cost_variance
        base["event_window_label"] = window_label
        return base

    # =================================================================
    # Plan snapshot (B3 active plan)
    # =================================================================
    def _snapshot_active_plan(self, event_job):
        Plan = self.env["neon.deployment.plan"].sudo()
        plan = Plan.search(
            [("event_job_id", "=", event_job.id),
             ("is_active", "=", True)],
            order="revision desc, id desc", limit=1)
        if not plan:
            return {
                "plan_id": 0, "name": "",
                "status": "", "revision": 0,
                "section_titles": [],
                "deficits_at_plan_time": 0,
            }
        section_titles = []
        try:
            payload = (json.loads(plan.plan_json)
                        if plan.plan_json else {})
            for s in (payload.get("sections") or []):
                title = (s or {}).get("title") or ""
                if title:
                    section_titles.append(title)
        except (ValueError, TypeError):
            pass
        return {
            "plan_id": plan.id,
            "name": plan.name or "",
            "status": plan.status or "",
            "revision": int(plan.revision or 0),
            "section_titles": section_titles,
            "deficits_at_plan_time": int(plan.deficit_count or 0),
        }

    # =================================================================
    # Sub-hire snapshot (B4 active requests for this event)
    # =================================================================
    def _snapshot_subhire_requests(self, event_job):
        Request = self.env["neon.subhire.request"].sudo()
        reqs = Request.search(
            [("event_job_id", "=", event_job.id),
             ("status", "not in", ("superseded", "draft"))],
            order="revision desc")
        out = []
        for r in reqs:
            qty_total = sum(
                int(l.qty_short or 0) for l in r.line_ids)
            out.append({
                "request_id": r.id,
                "name": r.name or "",
                "status": r.status or "",
                "supplier_name": (r.supplier_partner_id.name
                                    if r.supplier_partner_id
                                    else ""),
                "po_name": (r.po_draft_id.name
                              if r.po_draft_id else ""),
                "po_state": (r.po_draft_id.state
                              if r.po_draft_id else ""),
                "line_count": len(r.line_ids),
                "qty_short_total": qty_total,
            })
        return out

    # =================================================================
    # Condition deltas (units that flipped post-event)
    # =================================================================
    def _gather_condition_deltas(self, event_job):
        """Find units allocated to this event whose condition_status
        is now needs_repair / written_off + (when timestamps are
        available) whose write_date is AFTER the event date.

        B5 D5 hard rule: this method NEVER mutates condition_status.
        It just reports.
        """
        Line = self.env[
            "commercial.event.job.equipment.line"].sudo()
        lines = Line.search(
            [("event_job_id", "=", event_job.id)])
        # Collect units allocated via equipment_unit_ids on the line.
        unit_ids = set()
        for ln in lines:
            try:
                for u in (ln.equipment_unit_ids or []):
                    unit_ids.add(u.id)
            except Exception:  # noqa: BLE001
                continue
        # Also include any unit currently set on a movement related
        # to this event (movement.event_job_id), if the movement
        # model exists.
        Movement = self.env.get(
            "neon.equipment.movement")
        if Movement is not None:
            mvts = Movement.sudo().search(
                [("event_job_id", "=", event_job.id)])
            for m in mvts:
                # neon.equipment.movement uses .unit_id
                u = getattr(m, "unit_id", False)
                if u:
                    unit_ids.add(u.id)
        if not unit_ids:
            return []
        Unit = self.env["neon.equipment.unit"].sudo()
        units = Unit.browse(list(unit_ids)).exists()
        deltas = []
        ev_date = (event_job.event_date
                    or (event_job.load_out_end.date()
                          if event_job.load_out_end else None))
        for u in units:
            if u.condition_status in ("needs_repair",
                                         "written_off"):
                noted_after = False
                # Use write_date as a coarse signal -- last touched
                # the unit record. If after the event_date, the flip
                # plausibly happened after the event.
                if ev_date and u.write_date:
                    try:
                        noted_after = (
                            u.write_date.date() >= ev_date)
                    except Exception:  # noqa: BLE001
                        noted_after = False
                deltas.append({
                    "unit_id": u.id,
                    "serial_number": u.serial_number or "",
                    "product_name": (
                        u.product_template_id.name or ""),
                    "new_status": u.condition_status,
                    "noted_after_event": bool(noted_after),
                })
        return deltas

    # =================================================================
    # Cost variance (planned vs actual; READ-ONLY)
    # =================================================================
    def _gather_cost_variance(self, event_job):
        """Sum planned-side neon.finance.quote.amount_total (most
        recent accepted quote on the event) vs actual-side
        neon.finance.cost.line.amount aggregate.

        Returns variance_total = actual - planned (positive =
        over-budget).

        ⚠️ DECISION (B5, D4): READ-ONLY. sudo() lets the operational
        tier read the finance models; nothing is ever written.
        """
        Quote = self.env.get("neon.finance.quote")
        CostLine = self.env.get("neon.finance.cost.line")
        if Quote is None or CostLine is None:
            # neon_finance not installed -- skip variance.
            return {
                "planned_total": 0.0, "actual_total": 0.0,
                "variance_total": 0.0, "currency": "USD",
                "by_cost_type": [], "available": False,
            }
        planned = 0.0
        try:
            quotes = Quote.sudo().search(
                [("event_job_id", "=", event_job.id)],
                order="id desc")
            # Prefer the latest non-cancelled quote.
            chosen = False
            for q in quotes:
                state = getattr(q, "state", "")
                if state not in ("cancelled", "rejected"):
                    chosen = q
                    break
            if chosen:
                planned = float(
                    chosen.amount_total or 0.0)
        except Exception:  # noqa: BLE001
            _logger.exception(
                "B5 planned-cost read failed -- continuing with 0.")

        actual = 0.0
        by_type = {}
        try:
            cost_lines = CostLine.sudo().search(
                [("event_job_id", "=", event_job.id)])
            for cl in cost_lines:
                amt = float(cl.amount or 0.0)
                actual += amt
                ct = getattr(cl, "cost_type", "") or "other"
                by_type[ct] = by_type.get(ct, 0.0) + amt
        except Exception:  # noqa: BLE001
            _logger.exception(
                "B5 actual-cost read failed -- continuing with 0.")

        return {
            "planned_total": round(planned, 2),
            "actual_total": round(actual, 2),
            "variance_total": round(actual - planned, 2),
            "currency": "USD",
            "by_cost_type": sorted(
                ({"cost_type": k, "amount": round(v, 2)}
                 for k, v in by_type.items()),
                key=lambda r: r["cost_type"]),
            "available": True,
        }
