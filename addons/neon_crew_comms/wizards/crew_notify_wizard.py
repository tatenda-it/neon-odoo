# -*- coding: utf-8 -*-
"""B11 / WA-2 -- "Notify crew" recipient-confirmation wizard (Piece B).

Human-in-the-loop: ops opens it, sees the un-notified pending crew on
the job (with a resolvable phone, not opted out, not notified in the last
12h), reviews, then confirms the send. NO auto-send, NO cron this version.
"""
from odoo import _, api, fields, models


class CrewNotifyWizard(models.TransientModel):
    _name = "commercial.job.crew.notify.wizard"
    _description = "Notify Crew (WhatsApp)"

    job_id = fields.Many2one("commercial.job", string="Job", required=True,
                             readonly=True)
    candidate_crew_ids = fields.Many2many(
        "commercial.job.crew", string="Crew to notify",
        help="Pending crew on this job with a WhatsApp number who haven't "
        "been notified in the last 12h and haven't opted out.")
    summary = fields.Char(readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        job_id = self.env.context.get("default_job_id")
        if job_id:
            job = self.env["commercial.job"].browse(job_id)
            cands = job.crew_assignment_ids.filtered(
                lambda c: c._wa_is_notifiable())
            res["job_id"] = job.id
            res["candidate_crew_ids"] = [(6, 0, cands.ids)]
            pending = len(job.crew_assignment_ids.filtered(
                lambda c: c.state == "pending"))
            res["summary"] = _(
                "%(n)s of %(p)s pending crew are ready to notify "
                "(rest: no WhatsApp number, opted out, or notified in the "
                "last 12h).") % {"n": len(cands), "p": pending}
        return res

    def action_send(self):
        self.ensure_one()
        self.job_id._wa_check_notify_access()
        sent = skipped = 0
        for crew in self.candidate_crew_ids:
            # re-check at send (state/opt-out/rate-limit may have moved).
            if not crew._wa_is_notifiable():
                skipped += 1
                continue
            res = crew._wa_send_assignment_notification()
            if res.get("ok"):
                sent += 1
            else:
                skipped += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Crew notified"),
                "message": _("Sent %(s)s, skipped %(k)s.")
                % {"s": sent, "k": skipped},
                "type": "success" if sent else "warning",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
