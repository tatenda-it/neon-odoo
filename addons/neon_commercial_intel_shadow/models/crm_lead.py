# -*- coding: utf-8 -*-
from odoo import _, api, fields, models

# Key fields used for the missing-info check + confidence bucketing.
# Rule-based, needs no live data. Tune the list as the pipeline firms up.
_KEY_FIELDS = [
    "neon_event_type",
    "neon_sector",
    "partner_id",
    "expected_revenue",
    "neon_strategic_value",
    "neon_next_action_type",
]


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # --- 2B shadow fields (separate from the live x_lead_score) -------------
    neon_shadow_score = fields.Integer(
        string="Shadow Score",
        help="Rule-based shadow score (2B). NON-AUTHORITATIVE - placeholder "
             "rules, not validated against live data. Does not affect the live "
             "lead score.",
    )
    neon_ai_reason = fields.Text(string="AI Reason (shadow)")
    neon_deal_risk = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")],
        string="Deal Risk (shadow)",
    )
    neon_missing_info = fields.Text(
        string="Missing Info",
        compute="_compute_neon_missing_info",
        help="Key fields not yet populated. Computed, no data needed.",
    )

    @api.depends(*_KEY_FIELDS)
    def _compute_neon_missing_info(self):
        labels = self.env["crm.lead"].fields_get(_KEY_FIELDS)
        for lead in self:
            missing = []
            for f in _KEY_FIELDS:
                if f in lead._fields and not lead[f]:
                    missing.append(labels.get(f, {}).get("string", f))
            lead.neon_missing_info = ", ".join(missing) if missing else _("Complete")

    def _neon_confidence_from_completeness(self):
        """Placeholder confidence: more populated key fields => higher
        confidence. Thresholds are PLACEHOLDER - tune post-cutover."""
        self.ensure_one()
        present = sum(1 for f in _KEY_FIELDS if f in self._fields and self[f])
        ratio = present / len(_KEY_FIELDS) if _KEY_FIELDS else 0
        if ratio >= 0.75:
            return "high"
        if ratio >= 0.4:
            return "medium"
        return "low"

    def action_neon_shadow_rescore(self):
        """Manual shadow rescoring. Writes shadow fields ONLY and drops a
        recommendation into the review queue. No auto-action, no touch to the
        live score. Safe to run, but results are non-authoritative pre-data-gate.
        """
        Rule = self.env["neon.shadow.scoring.rule"]
        Rec = self.env["neon.shadow.recommendation"]
        for lead in self:
            score, reasons = Rule._score_lead(lead)
            confidence = lead._neon_confidence_from_completeness()
            lead.write({
                "neon_shadow_score": score,
                "neon_ai_reason": "\n".join(reasons) if reasons else _("No rules matched."),
                "neon_score_confidence": confidence,
            })
            Rec.create({
                "name": _("Shadow score: %s") % lead.display_name,
                "rec_type": "score",
                "lead_id": lead.id,
                "recommendation": _("Suggested shadow score: %s") % score,
                "rationale": "\n".join(reasons) if reasons else _("No rules matched."),
                "confidence": confidence,
            })
        return True

    # --- Inert cron stubs (ship INACTIVE; see data/neon_shadow_cron.xml) -----
    # These are scaffolding. They create review-queue items only; they never act.
    @api.model
    def _cron_neon_shadow_daily_brief(self):
        """Stub: surface a few 'brief items' for review. Placeholder logic -
        leads missing key info. Real brief composition is post-data-gate work."""
        Rec = self.env["neon.shadow.recommendation"]
        leads = self.search([("active", "=", True), ("type", "=", "opportunity")], limit=20)
        for lead in leads:
            lead._compute_neon_missing_info()
            if lead.neon_missing_info and lead.neon_missing_info != _("Complete"):
                Rec.create({
                    "name": _("Brief: incomplete data on %s") % lead.display_name,
                    "rec_type": "brief_item",
                    "lead_id": lead.id,
                    "recommendation": _("Complete: %s") % lead.neon_missing_info,
                    "rationale": _("Daily brief stub - data completeness check."),
                    "confidence": "low",
                })
        return True

    @api.model
    def _cron_neon_shadow_leak_watch(self):
        """Stub leak watcher. NOTE: reconcile with the existing #3/#5 dashboard
        drafts before activating - do not duplicate their logic. Placeholder:
        flags opportunities whose next-action date has passed."""
        Rec = self.env["neon.shadow.recommendation"]
        today = fields.Date.context_today(self)
        leaks = self.search([
            ("type", "=", "opportunity"),
            ("neon_next_action_date", "!=", False),
            ("neon_next_action_date", "<", today),
        ], limit=50)
        for lead in leaks:
            Rec.create({
                "name": _("Leak: overdue next action on %s") % lead.display_name,
                "rec_type": "leak_alert",
                "lead_id": lead.id,
                "recommendation": _("Next action was due %s") % lead.neon_next_action_date,
                "rationale": _("Leak-watch stub - overdue next-action date."),
                "confidence": "medium",
            })
        return True
