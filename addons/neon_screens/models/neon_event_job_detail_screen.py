# -*- coding: utf-8 -*-
"""Event Job Detail screen (design-deck #10) -- data RPC (virtual model).

The click-into-a-job DETAIL view opened from the Event Jobs LIST (#3). Read-only
OWL client action over the REAL commercial.event.job, read under the requesting
user's OWN ACL (gated to neon_jobs ops groups -- same audience as the list). NO
new field/model/migration; reuses the data layers already built (#1 equipment,
#4 finance costing, #6 crew).

Reads via this RPC and renders an OWL view -- it NEVER loads the native
commercial.event.job FORM, so it structurally avoids the pre-existing
neon_training form access-error (the gate-log field lives on the form, not in
this read set). All fields read here are standard event_job / parent / related
fields -- none are neon_training fields.

Panels: Header (+ setup->start->end->strike timeline, occupation_* fallback),
Equipment Allocation (#1), Event Costing by category + margin (#4), Assigned
Crew (#6), Commercial (quoted/VAT 15.5%/deposit/balance + company ZIMRA BP;
Zoho fiscal OMITTED per decision #11). Action buttons DEFERRED (#13).
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_OPS_GROUPS = (
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
)

# event_job lifecycle -> pill tone
_STATE_TONE = {
    "draft": "muted", "planning": "muted", "prep": "info",
    "ready_for_dispatch": "info", "dispatched": "warn", "in_progress": "warn",
    "strike": "info", "returned": "info", "completed": "ok", "closed": "dark",
    "cancelled": "alert", "released": "muted",
}
_LINE_TONE = {"planned": "muted", "partial": "warn", "fulfilled": "ok", "cancelled": "alert"}
_CREW_TONE = {"pending": "warn", "confirmed": "ok", "declined": "alert"}
_ALERT_TONE = {"ok": "ok", "warn": "warn", "breach": "alert", "severe": "dark"}


class NeonEventJobDetailScreen(models.Model):
    _name = "neon.event.job.detail.screen"
    _description = "Event Job Detail Screen (virtual; @api.model RPC only)"

    @api.model
    def _check_access(self):
        if not any(self.env.user.has_group(g) for g in _OPS_GROUPS):
            raise AccessError(_("You don't have access to event job details."))

    @api.model
    def _money(self, v):
        return "{:,.2f}".format(v or 0.0)

    @api.model
    def _dt(self, val):
        # Render in the user's timezone (Harare) so the timeline matches the
        # crew brief's local "call" time -- not raw UTC.
        if not val:
            return None
        return fields.Datetime.context_timestamp(self, val).strftime("%a %d %b, %H:%M")

    @api.model
    def _timeline(self, ej):
        """setup -> event start -> event end -> strike. Fall back to the
        computed occupation_* span where explicit datetimes are NULL so the
        timeline is never blank (GATE-0 finding)."""
        occ_s, occ_e = ej.occupation_start, ej.occupation_end
        rows = [
            ("Setup", ej.prep_start_datetime or occ_s, not ej.prep_start_datetime),
            ("Event start", occ_s, not (ej.prep_start_datetime or ej.event_date)),
            ("Event end", occ_e, False),
            ("Strike", ej.strike_start_datetime or ej.return_eta_datetime or occ_e,
             not (ej.strike_start_datetime or ej.return_eta_datetime)),
        ]
        return [{"label": lbl, "dt": self._dt(dt) or "—", "estimated": bool(est and dt)}
                for lbl, dt, est in rows]

    @api.model
    def get_data(self, event_job_id):
        self._check_access()
        ej = self.env["commercial.event.job"].browse(int(event_job_id or 0))
        if not ej.exists():
            return {"error": _("Event job not found.")}
        cj = ej.commercial_job_id
        state_sel = dict(ej._fields["state"].selection)
        ccy = (ej.currency_id.symbol or "$")

        # --- Header ---
        header = {
            "id": ej.id,
            "job_id": ej.name,
            "status": state_sel.get(ej.state, ej.state),
            "status_tone": _STATE_TONE.get(ej.state, "muted"),
            "client": ej.partner_id.display_name or cj.name or "—",
            "venue": ej.venue_id.display_name or "—",
            "guests": ej.expected_attendee_count or 0,
            "timeline": self._timeline(ej),
        }

        # --- Equipment Allocation (#1) ---
        eq_sel = dict(self.env["commercial.event.job.equipment.line"]._fields["state"].selection)
        equipment = [{
            "id": l.id,
            "item": l.product_template_id.display_name or "—",
            "planned": l.quantity_planned,
            "allocated": l.quantity_checked_out,
            "remaining": l.quantity_remaining,
            "state": eq_sel.get(l.state, l.state),
            "state_tone": _LINE_TONE.get(l.state, "muted"),
        } for l in ej.equipment_line_ids]

        # --- Event Costing by category + margin (#4) ---
        cat_sel = dict(self.env["neon.finance.cost.line"]._fields["cost_type"].selection)
        cats = {}
        for cl in ej.cost_line_ids:
            key = cl.cost_type or "other"
            cats.setdefault(key, 0.0)
            cats[key] += cl.amount or 0.0
        cost_rows = [{"category": cat_sel.get(k, k), "amount": self._money(v), "raw": v}
                     for k, v in sorted(cats.items(), key=lambda kv: kv[1], reverse=True)]
        cost_max = max([r["raw"] for r in cost_rows], default=0.0) or 1.0
        for r in cost_rows:
            r["pct"] = round(100.0 * r["raw"] / cost_max, 1)
        bccy = (ej.quoted_budget_currency_id.symbol or ccy)
        actual = (ej.quoted_budget or 0.0) - (ej.margin_gross or 0.0)
        costing = {
            "has_data": bool(ej.quoted_budget or cost_rows),
            "quoted": self._money(ej.quoted_budget), "has_quote": bool(ej.quoted_budget),
            "actual": self._money(actual),
            "variance": self._money(ej.budget_variance_quoted),
            "variance_tone": "alert" if (ej.budget_variance_quoted or 0) > 0 else "ok",
            "margin_pct": "{:.1f}%".format(ej.margin_pct or 0.0),
            "alert": (dict(ej._fields["budget_alert_level"].selection).get(ej.budget_alert_level)
                      if ej.budget_alert_level else "—"),
            "alert_tone": _ALERT_TONE.get(ej.budget_alert_level, "muted"),
            "currency": bccy,
            "categories": cost_rows,
        }

        # --- Assigned Crew (#6) via parent commercial_job ---
        role_sel = dict(self.env["commercial.job.crew"]._fields["role"].selection)
        crew_sel = dict(self.env["commercial.job.crew"]._fields["state"].selection)
        crew = [{
            "id": c.id,
            "name": c.partner_id.display_name or "—",
            "role": role_sel.get(c.role, c.role or "—"),
            "state": crew_sel.get(c.state, c.state),
            "state_tone": _CREW_TONE.get(c.state, "muted"),
            "is_chief": c.is_crew_chief,
        } for c in cj.crew_assignment_ids]

        # --- Commercial (quote/VAT/deposit/balance; ZIMRA BP company-level) ---
        commercial = {
            "quoted_value": self._money(ej.quoted_value), "currency": ccy,
            "deposit": self._money(ej.deposit_received),
            "balance": self._money((ej.quoted_value or 0.0) - (ej.deposit_received or 0.0)),
            "finance_status": (ej.finance_status or "—").replace("_", " ").title(),
            "vat": "15.5%",
            "zimra_bp": self.env.company.x_zimra_bpn or "—",
        }

        return {
            "header": header,
            "equipment": equipment,
            "costing": costing,
            "crew": crew,
            "commercial": commercial,
            "counts": {
                "equipment": len(equipment), "crew": len(crew),
                "cost_categories": len(cost_rows),
            },
            # "AI plan" deferred (placeholder intelligence); "Brief crew" is
            # draft-only (compose_crew_brief below) -- a human sends.
            "ai_plan_deferred": True,
        }

    @api.model
    def compose_crew_brief(self, event_job_id):
        """DRAFT-ONLY crew briefing. Assembles a WhatsApp-ready briefing TEXT
        from this job's REAL data and returns it as a string for the human to
        copy + send manually from WhatsApp / neon_channels. This RPC ONLY READS
        and RETURNS TEXT -- it creates NO neon.whatsapp.message row and NEVER
        calls send_message/send_*; nothing leaves the ERP. (Decision: ERP
        composes, the person sends -- keeps real-phone sends behind the human.)
        """
        self._check_access()
        ej = self.env["commercial.event.job"].browse(int(event_job_id or 0))
        if not ej.exists():
            return {"error": _("Event job not found.")}
        cj = ej.commercial_job_id
        role_sel = dict(self.env["commercial.job.crew"]._fields["role"].selection)

        call_dt = ej.prep_start_datetime or ej.occupation_start
        if call_dt:
            when = fields.Datetime.context_timestamp(self, call_dt).strftime(
                "%a %d %b %Y, call %H:%M")
        elif ej.event_date:
            when = fields.Date.to_string(ej.event_date)
        else:
            when = ""

        lines = ["*Event Brief — %s*" % (ej.name or "")]
        client = ej.partner_id.display_name or cj.name
        if client:
            lines.append(client)
        if when:
            lines.append("🗓 %s" % when)
        if ej.venue_id:
            lines.append("📍 %s" % ej.venue_id.display_name)

        crew = cj.crew_assignment_ids
        lines += ["", "*Crew (%d):*" % len(crew)]
        if crew:
            for c in crew:
                chief = " (Chief)" if c.is_crew_chief else ""
                lines.append("• %s — %s%s" % (
                    c.partner_id.display_name or "?",
                    role_sel.get(c.role, c.role or "—"), chief))
        else:
            lines.append("• None assigned yet")

        eq = ej.equipment_line_ids
        lines += ["", "*Equipment (%d):*" % len(eq)]
        if eq:
            for l in eq:
                lines.append("• %d× %s" % (
                    l.quantity_planned, l.product_template_id.display_name or "?"))
        else:
            lines.append("• None assigned yet")

        return {"text": "\n".join(lines),
                "crew_count": len(crew), "equipment_count": len(eq)}
