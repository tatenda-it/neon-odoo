# -*- coding: utf-8 -*-
"""B11 / WA-2 -- commercial.job: human-triggered crew notification +
reminders (bridge). Role-gated to ops (Manager OR Crew Leader), the same
set as the existing can_edit_crew gate (Gate-1 decision 1)."""
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Ops gate -- "who manages this job's crew" (mirrors can_edit_crew).
_OPS_GROUPS = (
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
)


class CommercialJob(models.Model):
    _inherit = "commercial.job"

    def _wa_check_notify_access(self):
        """Server-side ops gate (defence in depth behind the button's
        invisible='not can_edit_crew')."""
        if not any(self.env.user.has_group(g) for g in _OPS_GROUPS):
            raise UserError(_(
                "Only ops (Manager or Crew Leader) can notify crew over "
                "WhatsApp."))

    # ---- Piece B: human-triggered "Notify crew" --------------------
    def action_notify_crew(self):
        """Header button -> open the recipient-confirmation wizard listing
        un-notified pending crew on this job. NO auto-send."""
        self.ensure_one()
        self._wa_check_notify_access()
        return {
            "type": "ir.actions.act_window",
            "name": _("Notify Crew"),
            "res_model": "commercial.job.crew.notify.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_job_id": self.id},
        }

    # ---- job_reminder: manual trigger now, cron deferred -----------
    def _wa_send_job_reminders(self):
        """Send the job_reminder template to every CONFIRMED crew member
        on these jobs (rate-limited per assignment). Returns (sent,
        skipped)."""
        sent = skipped = 0
        for job in self:
            for crew in job.crew_assignment_ids.filtered(
                    lambda c: c.state == "confirmed"):
                res = crew._wa_send_reminder()
                if res.get("ok"):
                    sent += 1
                else:
                    skipped += 1
        return sent, skipped

    def action_send_job_reminders(self):
        """Header button -> send reminders to confirmed crew now."""
        self.ensure_one()
        self._wa_check_notify_access()
        sent, skipped = self._wa_send_job_reminders()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reminders sent"),
                "message": _("Sent %(s)s, skipped %(k)s (not confirmed / "
                             "no phone / opted out / recently sent).")
                % {"s": sent, "k": skipped},
                "type": "success" if sent else "warning",
                "sticky": False,
            },
        }

    @api.model
    def _cron_send_job_reminders(self):
        """Day-before reminder sweep. CRON-READY but NOT enabled this
        version (the ir.cron ships active=False -- human-first). Sends
        job_reminder to confirmed crew on jobs happening tomorrow."""
        tomorrow = date.today() + timedelta(days=1)
        jobs = self.sudo().search([("event_date", "=", tomorrow)])
        sent, skipped = jobs._wa_send_job_reminders()
        return {"sent": sent, "skipped": skipped, "jobs": len(jobs)}
