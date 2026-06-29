# -*- coding: utf-8 -*-
"""Equipment & Inventory screen — data RPC (virtual model, no records).

Design-deck screen #1, built toward the deck layout over the REAL live
equipment domain in neon_jobs. This is a read-only presentation layer:
no new fields/models on the equipment data, no writes, no security groups.

Pattern mirrors neon.equipment.dashboard (P5.M10): a fieldless @api.model
model hosting the client-action entry point + a single get_screen_data RPC
the OWL component renders. Reuses the neon_jobs groups for access.

DATA TRUTH (Option A, agreed 2026-06-29):
  - Owned / Available are real standing computes on product.template
    (total_units / available_units).
  - "Committed" + the SUB-HIRE / ZERO MARGIN status are window-relative and
    live ONLY in the conflict engine (neon.equipment.conflict.line). We surface
    them from the LATEST conflict run — never fabricated. An item not flagged by
    a run is simply IN STOCK (available>0) or OUT (available<=0).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError


# Short labels + tone for the per-asset state pill (the model's canonical
# 9-state lifecycle; tone drives the pill colour in the OWL template).
_STATE_SHORT = {
    "draft": "Draft", "active": "Active", "reserved": "Reserved",
    "checked_out": "Checked Out", "transferred": "In Transit",
    "returned": "Returned", "maintenance": "Maintenance",
    "damaged": "Damaged", "decommissioned": "Retired",
}
_STATE_TONE = {
    "active": "ok", "reserved": "warn", "checked_out": "warn",
    "transferred": "warn", "returned": "muted", "maintenance": "alert",
    "damaged": "alert", "draft": "muted", "decommissioned": "muted",
}


class NeonEquipmentScreen(models.Model):
    _name = "neon.equipment.screen"
    _description = "Equipment & Inventory Screen (virtual; @api.model RPC only)"

    # No fields. No records ever created. Read-only ACL only.

    # ------------------------------------------------------------------
    @api.model
    def _check_access(self):
        user = self.env.user
        if not (user.has_group("neon_jobs.group_neon_jobs_user")
                or user.has_group("neon_jobs.group_neon_jobs_manager")
                or user.has_group("neon_jobs.group_neon_jobs_crew_leader")):
            raise AccessError(_(
                "You don't have access to the Equipment & Inventory screen."))

    @api.model
    def action_open_equipment_screen(self):
        """Inline-return client action (no persisted ir.actions.client →
        no direct-URL bypass). Bound to the top-level menu's server action."""
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_equipment_screen",
            "name": _("Equipment & Inventory"),
            "target": "current",
        }

    # ------------------------------------------------------------------
    @api.model
    def get_screen_data(self):
        """Single round-trip the OWL component renders. Defence-in-depth:
        re-checks access here even though the action layer also guards."""
        self._check_access()
        conflict = self._latest_conflict()
        status_by_product = self._status_map_from_conflict(conflict)
        return {
            "summary": self._summary(),
            "availability": self._availability_rows(status_by_product),
            "conflict": conflict,
            "assets": self._asset_rows(),
            "last_updated": fields.Datetime.to_string(fields.Datetime.now()),
        }

    # ------------------------------------------------------------------
    # Per-item availability (real standing fields on product.template) +
    # status pill sourced from the latest conflict run (never fabricated).
    # ------------------------------------------------------------------
    @api.model
    def _availability_rows(self, status_by_product):
        Product = self.env["product.template"].sudo()
        prods = Product.search(
            [("is_workshop_item", "=", True)],
            order="name")
        rows = []
        for p in prods:
            owned = p.total_units
            avail = p.available_units
            run_status = status_by_product.get(p.id)
            if run_status == "deficit":
                pill, tone = "SUB-HIRE", "warn"
            elif run_status == "zero_margin":
                pill, tone = "ZERO MARGIN", "alert"
            elif avail > 0:
                pill, tone = "IN STOCK", "ok"
            else:
                pill, tone = "OUT OF STOCK", "alert"
            rows.append({
                "id": p.id,
                "item": p.workshop_name or p.name,
                "category": p.equipment_category_id.name or "—",
                "owned": owned,
                # NOTE: no standing "committed" column on the availability list
                # by design (Option A) — a standing owned-minus-available proxy
                # would misleadingly lump maintenance/damaged in with job-
                # commitment. The truthful, window-relative committed is
                # required_qty on the conflict card.
                "available": avail,
                "rate": p.neon_unit_rate,
                "rate_has_rule": p.neon_unit_rate_has_rule,
                "status": pill,
                "tone": tone,
            })
        return rows

    @api.model
    def _status_map_from_conflict(self, conflict):
        """{product_id: line_status} from the latest run's lines."""
        if not conflict.get("exists"):
            return {}
        return {l["product_id"]: l["status"]
                for l in conflict.get("all_lines", [])}

    # ------------------------------------------------------------------
    # The conflict / sub-hire card — surfaced from the LATEST run as-is.
    # If the run is clear, we say so (no fabricated deficit).
    # ------------------------------------------------------------------
    @api.model
    def _latest_conflict(self):
        Conf = self.env["neon.equipment.conflict"].sudo()
        run = Conf.search([], order="triggered_at desc, id desc", limit=1)
        if not run:
            return {"exists": False}
        all_lines = []
        for l in run.line_ids.sorted(lambda r: (r.sub_hire_priority, r.id)):
            all_lines.append({
                "product_id": l.product_template_id.id,
                "item": l.product_template_id.display_name,
                "category": l.category_id.name or "—",
                "required": l.required_qty,
                "available": l.available_qty,
                "margin": l.margin,
                "deficit": l.deficit_qty,
                "status": l.status,
                "priority": l.sub_hire_priority,
                "events": l.competing_event_ids[:5].mapped("name"),
                "event_count": l.competing_event_count,
            })
        actionable = [l for l in all_lines
                      if l["status"] in ("deficit", "zero_margin")]
        return {
            "exists": True,
            "name": run.name,
            "overall_status": run.overall_status,
            "window_start": (fields.Datetime.to_string(run.window_start)
                             if run.window_start else ""),
            "window_end": (fields.Datetime.to_string(run.window_end)
                           if run.window_end else ""),
            "triggered_at": (fields.Datetime.to_string(run.triggered_at)
                             if run.triggered_at else ""),
            "deficit_count": run.deficit_count,
            "zero_margin_count": run.zero_margin_count,
            "line_count": run.line_count,
            "lines": actionable,     # what the alert card lists
            "all_lines": all_lines,  # full run (feeds the status map)
        }

    # ------------------------------------------------------------------
    # Per-asset register — puts the real per-unit Asset IDs to use.
    # ------------------------------------------------------------------
    @api.model
    def _asset_rows(self, limit=150):
        Unit = self.env["neon.equipment.unit"].sudo()
        units = Unit.search(
            [("active", "=", True)],
            order="product_template_id, serial_number, id",
            limit=limit)
        rows = []
        for u in units:
            rows.append({
                "asset_id": (u.asset_tag or u.serial_number
                             or ("#%s" % u.id)),
                "item": (u.workshop_name
                         or u.product_template_id.display_name),
                "category": u.equipment_category_id.name or "—",
                "state": u.state,
                "state_label": _STATE_SHORT.get(u.state, u.state),
                "tone": _STATE_TONE.get(u.state, "muted"),
            })
        return rows

    @api.model
    def _summary(self):
        Unit = self.env["neon.equipment.unit"].sudo()
        Product = self.env["product.template"].sudo()
        Cat = self.env["neon.equipment.category"].sudo()
        total_assets = Unit.search_count([("active", "=", True)])
        return {
            "total_assets": total_assets,
            "shown_assets": min(total_assets, 150),
            "workshop_items": Product.search_count(
                [("is_workshop_item", "=", True)]),
            "categories": Cat.search_count([]),
        }
