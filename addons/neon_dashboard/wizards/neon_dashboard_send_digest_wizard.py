# -*- coding: utf-8 -*-
"""Phase 8A.M9 -- "Send weekly digest now" admin wizard.

TransientModel under Settings -> Neon -> Send weekly digest.
Single button (action_send_now) that calls the orchestrator's
send_digest_now() and pops a notification with the result.

⚠️ DECISION (M9, marker 8): no cron-mocking, no window override,
no recipient override. The wizard is a "press the button to fire
the same code the Monday cron fires" -- not a what-if simulator.
Anything else lives behind a future polish milestone.
"""
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


class NeonDashboardSendDigestWizard(models.TransientModel):
    _name = "neon.dashboard.send.digest.wizard"
    _description = "Send Weekly Digest Now (admin)"

    last_log_summary = fields.Char(
        readonly=True,
        help="Summary of the most recent log row for context.",
    )

    @staticmethod
    def _default_last_log_summary(env):
        Log = env["neon.dashboard.digest.log"].sudo()
        latest = Log.search([], limit=1, order="sent_at desc")
        if not latest:
            return _("(no prior sends recorded)")
        return _(
            "Last: %(when)s - %(window)s - %(status)s "
            "(%(count)d recipient(s))"
        ) % {
            "when": fields.Datetime.to_string(latest.sent_at),
            "window": latest.window_label or "?",
            "status": latest.status,
            "count": latest.recipient_count or 0,
        }

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if "last_log_summary" in fields_list:
            defaults["last_log_summary"] = (
                self._default_last_log_summary(self.env))
        return defaults

    def action_send_now(self):
        self.ensure_one()
        Digest = self.env["neon.dashboard.weekly.digest"]
        result = Digest.send_digest_now(
            triggered_by_id=self.env.user.id)

        if result.get("status") == "sent":
            title = _("Weekly digest sent")
            msg = _(
                "Sent to %(count)d recipient(s). Window: "
                "%(start)s to %(end)s."
            ) % {
                "count": result.get("count", 0),
                "start": result.get("window_start"),
                "end": result.get("window_end"),
            }
            ntype = "success"
        elif result.get("status") == "no_recipients":
            title = _("No recipients")
            msg = _(
                "The approver group has no active members; nothing "
                "was sent. Add a user to the Approver group and try "
                "again.")
            ntype = "warning"
        else:
            title = _("Weekly digest FAILED")
            msg = _(
                "Send failed: %(err)s. See the digest history for "
                "the error log row.") % {
                "err": result.get("error", "(unknown)")[:200],
            }
            ntype = "danger"

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": msg,
                "type": ntype,
                "sticky": False,
            },
        }
