# -*- coding: utf-8 -*-
"""
P5.M10 — Workshop Dashboard (virtual model, no records).

This is a stub model whose purpose is to host the RPC entrypoint
(`get_dashboard_data`) and the per-tile count helpers consumed by
the OWL client action `neon_workshop_dashboard`.

Pattern: no records are ever created. Every method is `@api.model`.
The OWL component RPCs `get_dashboard_data` and renders the dict.
This avoids TransientModel churn on every refresh, singleton
preservation XML, and view-picker ambiguity.

Tile domains live alongside their count helpers so the act_window
records in views/ and the helpers here cannot drift.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class NeonEquipmentDashboard(models.Model):
    _name = "neon.equipment.dashboard"
    _description = "Workshop Dashboard (virtual; @api.model RPC only)"

    # No fields. ACL grants read to manager + crew_leader so they
    # can call get_dashboard_data; no records ever exist.

    # ============================================================
    # === Group-check helper
    # The dashboard is visible only to manager + crew_leader.
    # Centralised so the server-action wrapper and the RPC entry
    # point share one definition.
    # ============================================================
    @api.model
    def _check_dashboard_access(self):
        user = self.env.user
        if not (
            user.has_group("neon_jobs.group_neon_jobs_manager")
            or user.has_group("neon_jobs.group_neon_jobs_crew_leader")
        ):
            raise AccessError(_(
                "You don't have permission to view the workshop "
                "dashboard."))

    # ============================================================
    # === Server-action entry point.
    # Called by the menu's ir.actions.server record. Returns the
    # client-action descriptor INLINE rather than via a persisted
    # ir.actions.client record so there's no direct-URL bypass.
    # ============================================================
    @api.model
    def action_open_workshop_dashboard(self):
        self._check_dashboard_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_workshop_dashboard",
            "name": _("Workshop Overview"),
            "target": "current",
        }

    # ============================================================
    # === Tile 1: active_units — units currently in service
    # ============================================================
    @api.model
    def _count_active_units(self):
        return self.env["neon.equipment.unit"].sudo().search_count(
            [("state", "=", "active")])

    # ============================================================
    # === Tile 2: units_out — units physically with crew
    # ============================================================
    @api.model
    def _count_units_out(self):
        return self.env["neon.equipment.unit"].sudo().search_count(
            [("state", "=", "checked_out")])

    # ============================================================
    # === Tile 2b (B14d): units_in_maintenance — units sitting in
    # state='maintenance'. Distinct from `repair_orders_open` which
    # counts neon.equipment.repair.order workflow records; this is
    # the count of UNITS themselves whose state is maintenance.
    # ============================================================
    @api.model
    def _count_units_in_maintenance(self):
        return self.env["neon.equipment.unit"].sudo().search_count(
            [("state", "=", "maintenance")])

    # ============================================================
    # === Tile 3: reservations_next_7days — active holds whose
    # window opens within the next 7 days.
    # Filter for state IN ('soft_hold','confirmed') only — fulfilled
    # and cancelled don't represent upcoming work.
    # ============================================================
    @api.model
    def _count_reservations_next_7days(self):
        now = fields.Datetime.now()
        return self.env["neon.equipment.reservation"].sudo().search_count([
            ("state", "in", ("soft_hold", "confirmed")),
            ("reserve_from", ">=", now),
            ("reserve_from", "<=", now + timedelta(days=7)),
        ])

    # ============================================================
    # === Tile 4: pending_transfers — transfer_out movements
    # awaiting destination acceptance.
    # ============================================================
    @api.model
    def _count_pending_transfers(self):
        return self.env["neon.equipment.movement"].sudo().search_count(
            [("transfer_state", "=", "pending")])

    # ============================================================
    # === Tile 5: late_returns — reservations flagged late at
    # check-in (unit not yet back).
    # ============================================================
    @api.model
    def _count_late_returns(self):
        return self.env["neon.equipment.reservation"].sudo().search_count(
            [("late_return_pending", "=", True)])

    # ============================================================
    # === Tile 6: equipment_conflicts_open — Action Centre items
    # of trigger_type='equipment_conflict' still active. Widened
    # from spec's state='open' to state IN ('open','in_progress')
    # — items being worked are still open work.
    # ============================================================
    @api.model
    def _count_equipment_conflicts_open(self):
        return self.env["action.centre.item"].sudo().search_count([
            ("trigger_type", "=", "equipment_conflict"),
            ("state", "in", ("open", "in_progress")),
        ])

    # ============================================================
    # === Tile 7: stock_discrepancies_open — unresolved
    # discrepancies from stock take.
    # ============================================================
    @api.model
    def _count_stock_discrepancies_open(self):
        return self.env["neon.equipment.stock.take.line"].sudo().search_count([
            ("has_discrepancy", "=", True),
            ("resolved", "=", False),
        ])

    # ============================================================
    # === Tile 8: repair_orders_open — repairs not yet completed
    # or cancelled. Uses the canonical non-terminal tuple from
    # neon_equipment_repair_order.
    # ============================================================
    @api.model
    def _count_repair_orders_open(self):
        from .neon_equipment_repair_order import _NON_TERMINAL_STATES
        return self.env["neon.equipment.repair.order"].sudo().search_count(
            [("state", "in", _NON_TERMINAL_STATES)])

    # ============================================================
    # === Tile 9: incidents_open — incidents not yet resolved or
    # cancelled. Uses the canonical terminal tuple from
    # neon_equipment_incident (resolved_* + cancelled).
    # ============================================================
    @api.model
    def _count_incidents_open(self):
        from .neon_equipment_incident import _TERMINAL_STATES
        return self.env["neon.equipment.incident"].sudo().search_count(
            [("state", "not in", _TERMINAL_STATES)])

    # ============================================================
    # === Tile 10: high_impact_30d — high-impact discrepancies in
    # the trailing 30 days. Includes resolved (audit count of
    # high-impact events, not an open-queue).
    # ============================================================
    @api.model
    def _count_high_impact_30d(self):
        cutoff = fields.Datetime.now() - timedelta(days=30)
        return self.env["neon.equipment.stock.take.line"].sudo().search_count([
            ("is_high_impact", "=", True),
            ("has_discrepancy", "=", True),
            ("create_date", ">=", cutoff),
        ])

    # ============================================================
    # === RPC: get_dashboard_data
    # Single round-trip the OWL client uses to populate all 10
    # tiles. Returns value + action_id per tile, plus a wall-clock
    # last_updated for the "Last updated" footer.
    # ============================================================
    @api.model
    def get_dashboard_data(self):
        # P5.M10 hotfix: defence-in-depth. The server-action wrapper
        # also enforces the same check, but a caller who bypasses the
        # action layer (direct RPC, scripted client) must still be
        # rejected here.
        self._check_dashboard_access()
        ref = self.env.ref
        return {
            "active_units": {
                "value": self._count_active_units(),
                "action_id": ref("neon_jobs.action_dashboard_active_units").id,
            },
            "units_out": {
                "value": self._count_units_out(),
                "action_id": ref("neon_jobs.action_dashboard_units_out").id,
            },
            "units_in_maintenance": {
                "value": self._count_units_in_maintenance(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_units_in_maintenance").id,
            },
            "reservations_next_7days": {
                "value": self._count_reservations_next_7days(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_reservations_7d").id,
            },
            "pending_transfers": {
                "value": self._count_pending_transfers(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_pending_transfers").id,
            },
            "late_returns": {
                "value": self._count_late_returns(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_late_returns").id,
            },
            "equipment_conflicts_open": {
                "value": self._count_equipment_conflicts_open(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_equipment_conflicts").id,
            },
            "stock_discrepancies_open": {
                "value": self._count_stock_discrepancies_open(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_stock_discrepancies").id,
            },
            "repair_orders_open": {
                "value": self._count_repair_orders_open(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_repair_orders").id,
            },
            "incidents_open": {
                "value": self._count_incidents_open(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_incidents").id,
            },
            "high_impact_30d": {
                "value": self._count_high_impact_30d(),
                "action_id": ref(
                    "neon_jobs.action_dashboard_high_impact_30d").id,
            },
            "last_updated": fields.Datetime.to_string(
                fields.Datetime.now()),
        }
