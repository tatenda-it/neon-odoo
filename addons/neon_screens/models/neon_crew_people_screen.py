# -*- coding: utf-8 -*-
"""Crew & People screen (design-deck #6) -- data RPC (virtual model, no records).

HONEST DIRECTORY v1 (Tatenda decision 2026-06-29). Read-only over the REAL
canonical crew roster `neon.crew.member` (the inert wages-sheet reference list,
readable by all internal users -- names/roles only, NO pay). Reads under the
user's own ACL; gated to the neon_jobs operations groups.

Shows ONLY what is real: name, role (honest "Unknown" where the source had no
role), Lead-Tech flag, and active/former status.

DELIBERATELY NOT SHOWN (verified absent / would be fabricated -- see
[[project_crew_performance_layer_milestone]]):
  - performance score      -> no real/computed field exists; neon.hr.review is
                              manual, 0 on prod (a score next to a real name
                              would be fabricated).
  - activity completion / scanning accuracy / equipment responsibility metric
    bars -> not modelled; need new crew-level aggregation fields/models.
  - top-performer card + activity timeline -> depend on the above; absent.
  - On Site / Available / On Leave availability -> not derivable for these
    archive rows (not hr.employees, not job-assigned).
These are a SCOPED FUTURE milestone gated on an HR/management policy decision --
NOT built here, NOT faked.
"""
from odoo import _, api, models
from odoo.exceptions import AccessError

_OPS_GROUPS = (
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
)


class NeonCrewPeopleScreen(models.Model):
    _name = "neon.crew.people.screen"
    _description = "Crew & People Screen (virtual; @api.model RPC only)"

    @api.model
    def _check_access(self):
        if not any(self.env.user.has_group(g) for g in _OPS_GROUPS):
            raise AccessError(_("You don't have access to the Crew & People screen."))

    @api.model
    def action_open_crew_people_screen(self):
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_crew_people_screen",
            "name": _("Crew & People"),
            "target": "current",
        }

    @api.model
    def get_data(self):
        self._check_access()
        # active_test=False so FORMER crew (active=False) appear with a status
        # badge -- the directory reflects the whole roster honestly.
        Crew = self.env["neon.crew.member"].with_context(active_test=False)
        recs = Crew.search([])  # model _order = is_lead desc, name
        role_sel = dict(Crew._fields["role"].selection)
        status_sel = dict(Crew._fields["status"].selection)
        rows = []
        for r in recs:
            rows.append({
                "id": r.id,
                "name": r.name,
                "role": role_sel.get(r.role, r.role or "—"),
                "role_known": bool(r.role and r.role != "unknown"),
                "is_lead": r.is_lead,
                "status": status_sel.get(r.status, r.status or "—"),
                "is_former": not r.active,
            })
        return {
            "rows": rows,
            "counts": {
                "total": len(rows),
                "active": len([x for x in rows if not x["is_former"]]),
                "former": len([x for x in rows if x["is_former"]]),
                "leads": len([x for x in rows if x["is_lead"]]),
            },
        }
