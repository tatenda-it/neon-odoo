# -*- coding: utf-8 -*-
"""
Manager override for a Capacity Gate reject.

Opens automatically from action_activate when the evaluated aggregate is
'reject' AND the acting user is in group_neon_jobs_manager. Confirmation
persists gate_override_by + gate_override_reason, marks gate_result as
'overridden', and proceeds with the state move to active.
"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommercialJobGateOverrideWizard(models.TransientModel):
    _name = "commercial.job.gate.override.wizard"
    _description = "Manager override for a rejected Capacity Gate"

    job_id = fields.Many2one(
        "commercial.job",
        string="Commercial Job",
        required=True,
    )
    failing_checks_summary = fields.Text(
        string="Failing Checks",
        compute="_compute_failing_checks_summary",
    )
    gate_override_reason = fields.Text(
        string="Override Justification",
        required=True,
        help="Persisted to the job's audit trail (gate_override_reason).",
    )

    @api.depends("job_id", "job_id.gate_check_log")
    def _compute_failing_checks_summary(self):
        for w in self:
            if not w.job_id or not w.job_id.gate_check_log:
                w.failing_checks_summary = False
                continue
            try:
                data = json.loads(w.job_id.gate_check_log)
            except (ValueError, TypeError):
                w.failing_checks_summary = w.job_id.gate_check_log
                continue
            lines = []
            for c in data.get("checks", []):
                if c.get("result") in ("warning", "reject"):
                    lines.append(" - [%s] %s: %s" % (
                        c.get("result", "").upper(),
                        c.get("name", ""),
                        c.get("message", ""),
                    ))
            w.failing_checks_summary = "\n".join(lines) or _("No failing checks recorded.")

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("neon_jobs.group_neon_jobs_manager"):
            raise UserError(_(
                "Only managers (MD/OD) can override the Capacity Gate."
            ))
        if self.job_id.state != "pending":
            raise UserError(_(
                "The job is no longer pending; cannot override activation."
            ))
        self.job_id.write({
            "gate_override_by": self.env.user.id,
            "gate_override_reason": self.gate_override_reason,
            "gate_result": "overridden",
        })
        self.job_id._do_activate_state()
        self.job_id.message_post(body=_(
            "Capacity Gate reject overridden by %s. Reason: %s"
        ) % (self.env.user.name, self.gate_override_reason))
        return {"type": "ir.actions.act_window_close"}
