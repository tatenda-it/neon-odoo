# -*- coding: utf-8 -*-
"""Event Jobs screen (design-deck #3) — data RPC (virtual model, no records).

Over the REAL commercial.event.job EXECUTION layer (NOT commercial.job — that's
the sales/calendar spine the Operations Calendar used). Read-only presentation:
no new fields/models, no writes. Blessed neon_screens pattern (same as
neon.equipment.screen / neon.operations.screen). Reads under the user's own ACL.

STATUS PILL mapping (deck CONFIRMED/SOFT HOLD/TBC/INVOICED/CLOSED) — all REAL
existing fields, derived here (no new state invented):
  - CLOSED    = event.job.state in (closed, completed)            [execution done]
  - INVOICED  = parent commercial.job.finance_status in (deposit_received,
                partial_paid, fully_paid)                          [billing underway]
  - CONFIRMED = parent operational_status == confirmed
  - SOFT HOLD = parent operational_status == soft_hold
  - TBC       = parent operational_status == planning             [to be confirmed]
Precedence top→down (most-advanced wins). The deck's filter tabs
All/Confirmed/Soft Hold/TBC filter on this derived pill (client-side).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_INVOICED_FIN = ("deposit_received", "partial_paid", "fully_paid")


class NeonEventJobsScreen(models.Model):
    _name = "neon.event.jobs.screen"
    _description = "Event Jobs Screen (virtual; @api.model RPC only)"

    @api.model
    def _check_access(self):
        u = self.env.user
        if not (u.has_group("neon_jobs.group_neon_jobs_user")
                or u.has_group("neon_jobs.group_neon_jobs_manager")
                or u.has_group("neon_jobs.group_neon_jobs_crew_leader")):
            raise AccessError(_(
                "You don't have access to the Event Jobs screen."))

    @api.model
    def action_open_event_jobs_screen(self):
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_event_jobs_screen",
            "name": _("Event Jobs"),
            "target": "current",
        }

    @api.model
    def _status(self, ej):
        cj = ej.commercial_job_id
        if ej.state in ("closed", "completed"):
            return ("CLOSED", "dark")
        if cj.finance_status in _INVOICED_FIN:
            return ("INVOICED", "info")
        op = cj.operational_status
        if op == "confirmed":
            return ("CONFIRMED", "ok")
        if op == "soft_hold":
            return ("SOFT HOLD", "warn")
        if op == "planning":
            return ("TBC", "muted")
        return ((op or "—").replace("_", " ").upper(), "muted")

    @api.model
    def get_data(self):
        self._check_access()
        EJ = self.env["commercial.event.job"]
        jobs = EJ.search(
            [("active", "=", True)],
            order="event_date desc, name desc", limit=300)
        rows = []
        counts = {"all": 0}
        for ej in jobs:
            cj = ej.commercial_job_id
            pill, tone = self._status(ej)
            dates = fields.Date.to_string(ej.event_date) if ej.event_date else ""
            if ej.event_end_date and ej.event_end_date != ej.event_date:
                dates += " → " + fields.Date.to_string(ej.event_end_date)
            val = cj.quoted_value or 0.0
            rows.append({
                "id": ej.id,
                "job_id": ej.name,
                "event": ej.partner_id.display_name or cj.name or "—",
                "venue": ej.venue_id.display_name or "—",
                "dates": dates or "—",
                "crew": cj.crew_total_count,
                "value": "{:,.0f}".format(val),
                "currency": (cj.currency_id.symbol or "$"),
                "has_value": bool(val),
                "status": pill,
                "tone": tone,
            })
            counts["all"] += 1
            counts[pill] = counts.get(pill, 0) + 1
        return {
            "rows": rows,
            "counts": counts,
            "shown": len(rows),
            "total": EJ.search_count([("active", "=", True)]),
        }
