# -*- coding: utf-8 -*-
"""Operations Calendar screen (composed) — client-action host + holds RPC.

Design-deck screen #2, side-panel layout: the native commercial.job calendar
on the LEFT (embedded via the OWL <View/> component — the REAL native view, so
scales / popups / drag / colour legend are preserved, NOT hand-rolled) + a
"Holds to chase" panel on the RIGHT (a compact list rendered from get_holds()
over the same real soft-hold data).

Fieldless virtual host (the blessed neon_screens pattern, same as
neon.equipment.screen). Reads commercial.job under the user's OWN ACL
(neon_jobs groups) — no sudo, no fabricated data.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_HOLD_LABEL = {"active": "Active", "expiring_soon": "Expiring soon", "expired": "Expired"}
_HOLD_TONE = {"active": "ok", "expiring_soon": "warn", "expired": "alert"}


class NeonOperationsScreen(models.Model):
    _name = "neon.operations.screen"
    _description = "Operations Calendar Screen (virtual; client-action host)"

    @api.model
    def _check_access(self):
        u = self.env.user
        if not (u.has_group("neon_jobs.group_neon_jobs_user")
                or u.has_group("neon_jobs.group_neon_jobs_manager")
                or u.has_group("neon_jobs.group_neon_jobs_crew_leader")):
            raise AccessError(_(
                "You don't have access to the Operations Calendar screen."))

    @api.model
    def action_open_operations_screen(self):
        """Inline client action. Passes the exact calendar view id so the OWL
        layout embeds the REAL existing calendar view (not an auto-picked one)."""
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_operations_calendar_screen",
            "name": _("Operations Calendar"),
            "target": "current",
            "params": {
                "calendar_view_id": self.env.ref(
                    "neon_jobs.commercial_job_view_calendar").id,
            },
        }

    @api.model
    def get_holds(self):
        """Soft holds to chase — same real data as the companion view
        (soft_hold_state / soft_hold_until / extension_count), soonest first.
        Read under the user's own ACL."""
        self._check_access()
        jobs = self.env["commercial.job"].search(
            [("soft_hold_state", "in", ["active", "expiring_soon", "expired"])],
            order="soft_hold_until asc, event_date asc", limit=60)
        rows = []
        for j in jobs:
            rows.append({
                "id": j.id,
                "name": j.name,
                "client": j.partner_id.display_name or "",
                "venue": j.venue_id.display_name or "",
                "event_date": fields.Date.to_string(j.event_date) if j.event_date else "",
                "soft_hold_until": (fields.Date.to_string(j.soft_hold_until)
                                    if j.soft_hold_until else ""),
                "extensions": j.soft_hold_extension_count,
                "state": j.soft_hold_state,
                "state_label": _HOLD_LABEL.get(j.soft_hold_state, j.soft_hold_state),
                "tone": _HOLD_TONE.get(j.soft_hold_state, "muted"),
            })
        return {"holds": rows, "count": len(rows)}
