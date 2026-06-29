# -*- coding: utf-8 -*-
"""CRM Pipeline screen (design-deck #5) -- data RPC (virtual model, no records).

Read-only presentation over the EXISTING live CRM pipeline. NO new field/model,
NO writes, NO sudo: reads crm.lead / crm.stage under the requesting user's own
CRM ACL (CRM record rules apply -- salesperson sees own/team per the standard
rules). NO crm.stage change of any kind -- the screen reflects the pipeline
exactly as it is, grouping by the LIVE crm.stage set (8 on prod, whatever exists
elsewhere) ordered by (sequence, id). Stage names are NEVER hardcoded.

⚠️ DECISION (deck-vs-data): the deck's lead-source dimension (WhatsApp / Meta /
Website / Referral / eGP Tender) maps to real utm.source records that ARE
configured (WhatsApp, Website -- Events/Hiring, Referral, Zimbabwe eGP, Facebook/
Instagram), but verified 2026-06-29 that ZERO leads carry a source_id on prod or
local. So source is shown as a per-card badge WHERE SET (none today) + an honest
"N of M leads have a source" coverage chip -- never fabricated, never a forced
column.
"""
from odoo import _, api, models
from odoo.exceptions import AccessError

_CRM_USER = "sales_team.group_sale_salesman"


class NeonCrmPipelineScreen(models.Model):
    _name = "neon.crm.pipeline.screen"
    _description = "CRM Pipeline Screen (virtual; @api.model RPC only)"

    @api.model
    def _check_access(self):
        if not self.env.user.has_group(_CRM_USER):
            raise AccessError(_("You don't have access to the CRM Pipeline screen."))

    @api.model
    def action_open_crm_pipeline_screen(self):
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_crm_pipeline_screen",
            "name": _("CRM Pipeline"),
            "target": "current",
        }

    @api.model
    def _money(self, val):
        return "{:,.0f}".format(val or 0.0)

    @api.model
    def get_data(self):
        self._check_access()
        Lead = self.env["crm.lead"]
        Stage = self.env["crm.stage"]
        stages = Stage.search([], order="sequence, id")
        # The whole pipeline as it is: all active leads/opportunities, under the
        # user's own ACL (CRM record rules scope visibility).
        leads = Lead.search([("active", "=", True)], order="expected_revenue desc, id desc", limit=500)

        by_stage = {}
        for l in leads:
            by_stage.setdefault(l.stage_id.id if l.stage_id else 0, []).append(l)

        def card(l):
            return {
                "id": l.id,
                "name": l.name or "—",
                "client": l.partner_id.display_name or l.contact_name or l.partner_name or "—",
                "value": self._money(l.expected_revenue),
                "has_value": bool(l.expected_revenue),
                "currency": (l.company_currency.symbol or "$"),
                "probability": round(l.probability or 0.0),
                "source": l.source_id.name or "",
                "tags": l.tag_ids.mapped("name"),
                "lead_type": l.type,
            }

        columns = []
        for st in stages:
            st_leads = by_stage.get(st.id, [])
            columns.append({
                "id": st.id,
                "name": st.name,
                "count": len(st_leads),
                "value": self._money(sum(x.expected_revenue or 0.0 for x in st_leads)),
                "cards": [card(x) for x in st_leads],
            })
        # leads with no stage at all -> honest extra bucket (only if present)
        orphan = by_stage.get(0, [])
        if orphan:
            columns.append({
                "id": 0, "name": "(no stage)", "count": len(orphan),
                "value": self._money(sum(x.expected_revenue or 0.0 for x in orphan)),
                "cards": [card(x) for x in orphan],
            })

        sourced = len([l for l in leads if l.source_id])
        currency = (leads[:1].company_currency.symbol if leads else
                    self.env.company.currency_id.symbol) or "$"
        return {
            "columns": columns,
            "totals": {
                "leads": len(leads),
                "value": self._money(sum(l.expected_revenue or 0.0 for l in leads)),
                "currency": currency,
                "stages": len(stages),
                "sourced": sourced,
            },
        }
