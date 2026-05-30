# -*- coding: utf-8 -*-
"""Neon HR — Action Centre reuse without touching neon_jobs files.

⚠️ DECISION: the spec says "reuse the existing Action Centre / alert
mechanism — do not invent one" AND "shares NO files with neon_jobs"
(so a parallel B2 session stays merge-safe). Those pull in opposite
directions: the real Action Centre lives in neon_jobs and its
``trigger_type`` is a Selection sourced from a Python list there.

Resolution: add the new ``contract_expiry_30days`` trigger via
``selection_add`` from THIS module (no edit to neon_jobs'
TRIGGER_TYPE_SELECTION), on BOTH models that carry the field, and
override trigger.config._compute_name so the new key resolves to a
real label instead of "Unknown" (the base compute reads the neon_jobs
module-level list, which selection_add does not extend).

neon_hr depends on neon_jobs, but shares no FILES with it.
"""
from odoo import _, api, fields, models

# neon_hr-contributed Action Centre triggers (R1a contract expiry + R2
# accident NSSA deadline). Added via selection_add from this module so
# neon_jobs' TRIGGER_TYPE_SELECTION is never edited.
NEON_HR_TRIGGERS = [
    ("contract_expiry_30days", "Contract Expiring / Expired"),
    ("accident_nssa_14day", "Workplace Accident — NSSA 14-Day Deadline"),
]


class ActionCentreItem(models.Model):
    _inherit = "action.centre.item"

    trigger_type = fields.Selection(
        selection_add=NEON_HR_TRIGGERS,
        ondelete={t[0]: "set default" for t in NEON_HR_TRIGGERS},
    )


class ActionCentreTriggerConfig(models.Model):
    _inherit = "action.centre.trigger.config"

    trigger_type = fields.Selection(
        selection_add=NEON_HR_TRIGGERS,
        ondelete={t[0]: "cascade" for t in NEON_HR_TRIGGERS},
    )

    @api.depends("trigger_type")
    def _compute_name(self):
        """Override so contract_expiry_30days (added via selection_add,
        absent from neon_jobs' module-level TRIGGER_TYPE_SELECTION)
        resolves to its real label. Reads the EFFECTIVE field selection
        (base + selection_add), so base trigger labels are unchanged."""
        for rec in self:
            labels = dict(
                rec._fields["trigger_type"]._description_selection(rec.env))
            rec.name = labels.get(rec.trigger_type) or _("Unknown")
