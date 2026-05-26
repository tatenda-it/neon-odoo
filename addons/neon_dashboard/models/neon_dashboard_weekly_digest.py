# -*- coding: utf-8 -*-
"""Phase 8A.M9 -- weekly digest orchestrator.

AbstractModel containing the cron entry point, window math,
payload builder, PDF renderer, email sender, and log writer.
Persistent state lives in [[neon_dashboard_digest_log]]; the
report and the mail.template both bind to that concrete Model
to dodge the AbstractModel-binding fragility called out in the
M9 prompt §5.4.

⚠️ DECISION (M9, marker 3): daily cron + Monday-in-Harare guard
rather than ir.cron's interval_type=weeks. Daily cadence with
inside guard sidesteps Odoo's historical weekly-cron DST bugs
and is testable via a single _today_harare() mock.

⚠️ DECISION (M9, marker 4): failures NEVER re-raise from the
cron entry. Any exception in _send_digest_for_window writes a
log row with status='error' + truncated error_message; the cron
returns normally so subsequent runs are not blocked. Email send
itself uses force_send=False so it queues via the mail outbox.

⚠️ DECISION (M9, marker 5): recipients = members of
neon_finance.group_neon_finance_approver, resolved at send
time. Same group the M7 Alerts panel uses for the "Pending
approvals" surface -- tier consistency across the dashboard
ecosystem. Empty group => status='no_recipients', no email
attempt.

⚠️ DECISION (M9, marker 6): payload reuses
neon.dashboard._compute_jobs_block('director') /
_compute_alerts_block('director') / _compute_ar_aging() /
_kpi_* methods unchanged. Digest is a re-packaging of the
director-tier dashboard view, not a new data layer. Two
window-bounded count helpers (_count_quotes_state_in_window,
_count_invoices_paid_in_window, _count_jobs_completed_in_window)
are digest-specific and live here.

⚠️ DECISION (M9, marker 7): dashboard_url uses the deep-link
form {base}/web#action={action_id}&cids=1&menu_id={menu_id}.
Fallback to {base}/web on ref-lookup failure (graceful, never
crashes the render).
"""
from datetime import timedelta
import base64
import logging

from odoo import _, api, fields, models


_logger = logging.getLogger(__name__)


_APPROVER_GROUP_XMLID = "neon_finance.group_neon_finance_approver"
_REPORT_XMLID = "neon_dashboard.report_weekly_digest"
_MAIL_TEMPLATE_XMLID = "neon_dashboard.mail_template_weekly_digest"
_DASHBOARD_ACTION_XMLID = "neon_dashboard.action_neon_dashboard_server"
_DASHBOARD_MENU_XMLID = "neon_dashboard.menu_neon_dashboard_root"


class NeonDashboardWeeklyDigest(models.AbstractModel):
    _name = "neon.dashboard.weekly.digest"
    _description = "Weekly Digest Orchestrator (cron + PDF + email)"

    # ================================================================
    # Cron + manual trigger entry points.
    # ================================================================
    @api.model
    def _cron_send_weekly_digest(self):
        """Daily cron entry. Fires the actual send only on Mondays
        (Africa/Harare). Any failure logs + writes an error log row
        but never re-raises -- the cron must keep running."""
        Dashboard = self.env["neon.dashboard"]
        today = Dashboard._today_harare()
        if today.weekday() != 0:  # Monday is 0
            _logger.info(
                "Weekly digest cron: not Monday in Harare "
                "(today=%s, weekday=%d), skipping.",
                today, today.weekday(),
            )
            return
        try:
            result = self._send_digest_for_window(today)
            _logger.info("Weekly digest cron: %s", result)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Weekly digest cron FAILED (not re-raising): %s",
                exc, exc_info=True,
            )
            self._write_error_log(str(exc))

    @api.model
    def send_digest_now(self, triggered_by_id=None):
        """Manual trigger. Runs the same path as the cron but does
        NOT enforce the Monday guard. Returns the result dict."""
        Dashboard = self.env["neon.dashboard"]
        today = Dashboard._today_harare()
        try:
            return self._send_digest_for_window(
                today, triggered_by_id=triggered_by_id)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Weekly digest manual send FAILED: %s",
                exc, exc_info=True,
            )
            log = self._write_error_log(
                str(exc), triggered_by_id=triggered_by_id)
            return {
                "status": "error",
                "count": 0,
                "error": str(exc),
                "log_id": log.id if log else False,
            }

    # ================================================================
    # Main send pipeline.
    # ================================================================
    @api.model
    def _send_digest_for_window(self, anchor_today, triggered_by_id=None):
        """Compute window, resolve recipients, build payload,
        render PDF, send email, write log. Returns a status dict."""
        # Window: last 7 days, ending YESTERDAY. So a Monday anchor
        # -> Mon previous-week 00:00 to Sun 23:59. Sat anchor (manual
        # trigger on Saturday) -> Sun previous-week to Fri.
        window_end = anchor_today - timedelta(days=1)
        window_start = window_end - timedelta(days=6)

        recipients = self._resolve_recipients()
        if not recipients:
            _logger.warning(
                "Weekly digest: no recipients in group %s; nothing to do.",
                _APPROVER_GROUP_XMLID,
            )
            log = self._write_log(
                status="no_recipients",
                window_start=window_start,
                window_end=window_end,
                recipients=self.env["res.users"],
                pdf_attachment=False,
                triggered_by_id=triggered_by_id,
            )
            return {
                "status": "no_recipients",
                "count": 0,
                "log_id": log.id,
            }

        payload = self._build_digest_payload(
            window_start, window_end, anchor_today)

        # Pre-create the log so the PDF attachment can be linked
        # (res_id=log.id) before send. Email then references the
        # already-attached ir.attachment so we don't render twice.
        log = self._write_log(
            status="sent",
            window_start=window_start,
            window_end=window_end,
            recipients=recipients,
            pdf_attachment=False,
            triggered_by_id=triggered_by_id,
        )

        pdf_attachment = self._render_and_attach_pdf(log, payload)
        log.sudo().write({"pdf_attachment_id": pdf_attachment.id})

        self._send_digest_email(log, recipients, payload, pdf_attachment)

        return {
            "status": "sent",
            "count": len(recipients),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "log_id": log.id,
            "attachment_id": pdf_attachment.id,
        }

    # ================================================================
    # Recipients.
    # ================================================================
    @api.model
    def _resolve_recipients(self):
        """Members of the approver group. sudo() because the cron
        user is base.user_root by default; for manual sends the
        triggering user is already superuser-tier.

        ⚠️ DECISION (M9, marker 9): exclude base.user_root by id,
        NOT by _is_system(). Real directors (Robin, Munashe,
        Tatenda) are in neon_core.group_neon_superuser, which
        implies base.group_system -> _is_system() returns True for
        them. Filtering on _is_system() would silently drop the
        whole audience.
        """
        group = self.env.ref(_APPROVER_GROUP_XMLID,
                             raise_if_not_found=False)
        if not group:
            _logger.warning(
                "Approver group xmlid %s not found.",
                _APPROVER_GROUP_XMLID,
            )
            return self.env["res.users"]
        root_user = self.env.ref("base.user_root",
                                 raise_if_not_found=False)
        root_id = root_user.id if root_user else 0
        users = group.sudo().users.filtered(
            lambda u: u.active and u.id != root_id)
        return users

    # ================================================================
    # Payload builder.
    # ================================================================
    @api.model
    def _build_digest_payload(self, window_start, window_end, anchor_today):
        """Aggregate the data the PDF + email need. Reuses existing
        director-tier compute methods on neon.dashboard.

        Cron context note: self.env.user is base.user_root, so all
        per-user scoping (alerts dismissals, tasks) is for the cron
        user, not for Robin. Digest shows tier-level data only.
        """
        Dashboard = self.env["neon.dashboard"].sudo()

        # KPIs -- current state, not window state. Directors want to
        # know "where are we now", not "what was AR at midnight last
        # Monday".
        kpi_cash = Dashboard._kpi_cash_on_hand()
        kpi_ar = Dashboard._kpi_ar_overdue()
        kpi_today = Dashboard._kpi_jobs_today()
        kpi_week = Dashboard._kpi_jobs_week()
        kpi_pipeline = Dashboard._kpi_pipeline()
        kpi_leads = Dashboard._kpi_new_leads()
        kpi_forecast = Dashboard._kpi_forecast()

        # Window-bounded counts (M9-specific helpers below).
        last_week_won = self._count_quotes_state_in_window(
            "accepted", window_start, window_end)
        last_week_lost = self._count_quotes_state_in_window(
            ["rejected", "expired"], window_start, window_end)
        last_week_paid = self._count_invoices_paid_in_window(
            window_start, window_end)
        last_week_jobs_done = self._count_jobs_completed_in_window(
            window_start, window_end)

        # Forward look -- reuse director-tier block computes. These
        # already return rendered display strings.
        try:
            jobs_block = Dashboard._compute_jobs_block("director")
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Digest: jobs block compute failed (%s); using empty.",
                exc,
            )
            jobs_block = {"rows": [], "empty": True}

        try:
            alerts_block = Dashboard._compute_alerts_block("director")
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Digest: alerts compute failed (%s); using empty.",
                exc,
            )
            alerts_block = {"alerts": [], "empty": True}

        try:
            ar_aging = Dashboard._compute_ar_aging()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Digest: AR aging compute failed (%s); using empty.",
                exc,
            )
            ar_aging = {"buckets": [], "empty": True}

        return {
            "window_label": self._format_window_label(
                window_start, window_end),
            "window_start": window_start,
            "window_end": window_end,
            "anchor_today_label": anchor_today.strftime(
                "%A, %d %B %Y"),
            "anchor_today": anchor_today,

            "kpi_cash": kpi_cash,
            "kpi_ar_overdue": kpi_ar,
            "kpi_jobs_today": kpi_today,
            "kpi_jobs_week": kpi_week,
            "kpi_pipeline": kpi_pipeline,
            "kpi_leads": kpi_leads,
            "kpi_forecast": kpi_forecast,

            "last_week_quotes_won": last_week_won,
            "last_week_quotes_lost": last_week_lost,
            "last_week_invoices_paid": last_week_paid,
            "last_week_jobs_completed": last_week_jobs_done,

            "jobs_block": jobs_block,
            "alerts_block": alerts_block,
            "ar_aging": ar_aging,

            "dashboard_url": self._resolve_dashboard_url(),
        }

    @api.model
    def _format_window_label(self, window_start, window_end):
        """Human-readable label e.g. '19 May - 25 May 2026'."""
        if window_start.year == window_end.year:
            return "{} - {}".format(
                window_start.strftime("%d %b"),
                window_end.strftime("%d %b %Y"),
            )
        return "{} - {}".format(
            window_start.strftime("%d %b %Y"),
            window_end.strftime("%d %b %Y"),
        )

    @api.model
    def _resolve_dashboard_url(self):
        """Compute the deep-link URL into the Director Dashboard.
        Falls back to {base}/web on any ref-lookup failure so the
        render never crashes on this. See gate-1 #4 (revised)."""
        Config = self.env["ir.config_parameter"].sudo()
        base_url = (Config.get_param("web.base.url")
                    or "https://crm.neonhiring.com")
        try:
            action = self.env.ref(_DASHBOARD_ACTION_XMLID,
                                  raise_if_not_found=True)
            menu = self.env.ref(_DASHBOARD_MENU_XMLID,
                                raise_if_not_found=True)
            return (
                f"{base_url}/web#action={action.id}"
                f"&cids=1&menu_id={menu.id}"
            )
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "Digest dashboard_url ref lookup failed (%s); "
                "falling back to /web.", exc,
            )
            return f"{base_url}/web"

    # ================================================================
    # Window-bounded count helpers (M9-specific).
    # ================================================================
    @api.model
    def _count_quotes_state_in_window(
            self, state_or_states, window_start, window_end):
        """Quotes whose state transitioned to one of state_or_states
        in the window. Approximated via write_date as the transition
        timestamp (quote.state-machine writes are infrequent enough
        that write_date is a faithful proxy)."""
        Quote = self.env["neon.finance.quote"].sudo()
        states = (state_or_states if isinstance(state_or_states, list)
                  else [state_or_states])
        return Quote.search_count([
            ("state", "in", states),
            ("write_date", ">=", self._date_to_utc_start(window_start)),
            ("write_date", "<=", self._date_to_utc_end(window_end)),
        ])

    @api.model
    def _count_invoices_paid_in_window(self, window_start, window_end):
        """account.move (out_invoice) with payment_state='paid' and
        invoice_date_due / write_date in the window. Use write_date
        as the 'paid at' proxy since the actual payment isn't always
        on a clean field."""
        Move = self.env["account.move"].sudo()
        return Move.search_count([
            ("move_type", "=", "out_invoice"),
            ("payment_state", "=", "paid"),
            ("write_date", ">=", self._date_to_utc_start(window_start)),
            ("write_date", "<=", self._date_to_utc_end(window_end)),
        ])

    @api.model
    def _count_jobs_completed_in_window(self, window_start, window_end):
        """commercial.event.job that reached state='completed' or
        'closed' with event_date in the window."""
        Job = self.env["commercial.event.job"].sudo()
        return Job.search_count([
            ("state", "in", ["completed", "closed"]),
            ("event_date", ">=", window_start),
            ("event_date", "<=", window_end),
        ])

    @api.model
    def _date_to_utc_start(self, d):
        return fields.Datetime.to_string(
            fields.Datetime.from_string(f"{d} 00:00:00"))

    @api.model
    def _date_to_utc_end(self, d):
        return fields.Datetime.to_string(
            fields.Datetime.from_string(f"{d} 23:59:59"))

    # ================================================================
    # PDF rendering + attachment.
    # ================================================================
    @api.model
    def _render_and_attach_pdf(self, log, payload):
        """Render the QWeb report bound to neon.dashboard.digest.log
        with res_ids=[log.id], create an ir.attachment, return it.
        The template reads context['digest_payload'] via the log
        recordset's _get_render_payload() helper."""
        log_with_ctx = log.with_context(digest_payload=payload)
        Report = self.env["ir.actions.report"].sudo()
        # Note: _render_qweb_pdf returns (bytes, content_type) tuple
        # in Odoo 17. See ir_actions_report.py:916.
        pdf_bytes, _content_type = Report._render_qweb_pdf(
            _REPORT_XMLID,
            res_ids=[log.id],
            data={"digest_payload": payload},
        )
        if not pdf_bytes:
            raise ValueError(
                _("Weekly digest PDF render returned empty bytes."))
        filename = "neon-weekly-digest-{}.pdf".format(
            payload.get("window_end").isoformat()
            if payload.get("window_end") else "unknown"
        )
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "datas": base64.b64encode(pdf_bytes),
            "res_model": log._name,
            "res_id": log.id,
            "type": "binary",
            "mimetype": "application/pdf",
        })
        # Just to make rebound context visible to any downstream
        # callers reading log_with_ctx (no-op for the attachment).
        _ = log_with_ctx
        return attachment

    # ================================================================
    # Email send.
    # ================================================================
    @api.model
    def _send_digest_email(self, log, recipients, payload, pdf_attachment):
        """Send the digest via mail.template bound to
        neon.dashboard.digest.log. recipient_ids and attachment_ids
        injected via email_values so we don't render twice."""
        template = self.env.ref(_MAIL_TEMPLATE_XMLID,
                                raise_if_not_found=False)
        if not template:
            _logger.warning(
                "Digest mail.template %s missing; nothing sent.",
                _MAIL_TEMPLATE_XMLID,
            )
            return
        partner_ids = recipients.mapped("partner_id").ids
        template.sudo().with_context(
            digest_payload=payload,
        ).send_mail(
            log.id,
            force_send=False,
            email_values={
                "recipient_ids": [(6, 0, partner_ids)],
                "attachment_ids": [(6, 0, [pdf_attachment.id])],
            },
        )

    # ================================================================
    # Log writers.
    # ================================================================
    @api.model
    def _write_log(self, status, window_start, window_end,
                   recipients, pdf_attachment, triggered_by_id=None):
        Log = self.env["neon.dashboard.digest.log"].sudo()
        return Log.create({
            "status": status,
            "window_start": window_start,
            "window_end": window_end,
            "window_label": self._format_window_label(
                window_start, window_end),
            "recipient_ids": [(6, 0, recipients.ids)] if recipients else False,
            "recipient_count": len(recipients) if recipients else 0,
            "pdf_attachment_id": (
                pdf_attachment.id if pdf_attachment else False),
            "triggered_by_id": triggered_by_id or False,
        })

    @api.model
    def _write_error_log(self, error_message, triggered_by_id=None):
        """Best-effort write of an error log row. If even this
        fails we just log to the python logger and return None --
        the cron must NOT crash."""
        try:
            Dashboard = self.env["neon.dashboard"]
            today = Dashboard._today_harare()
            Log = self.env["neon.dashboard.digest.log"].sudo()
            return Log.create({
                "status": "error",
                "window_start": today - timedelta(days=7),
                "window_end": today - timedelta(days=1),
                "window_label": "(error)",
                "recipient_count": 0,
                "error_message": (error_message or "")[:2000],
                "triggered_by_id": triggered_by_id or False,
            })
        except Exception as exc:  # noqa: BLE001
            _logger.error(
                "Digest error log write FAILED on top of original "
                "error (%s); original was: %s", exc, error_message,
            )
            return None
