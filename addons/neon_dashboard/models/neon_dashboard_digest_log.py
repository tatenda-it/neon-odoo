# -*- coding: utf-8 -*-
"""Phase 8A.M9 -- weekly digest send history.

One row per send attempt. Holds the report subject so the QWeb
report can bind to a concrete model (res_ids=[log.id]) and the
mail.template likewise. AbstractModel orchestrator
(neon.dashboard.weekly.digest) writes here.

⚠️ DECISION (M9, marker 1): two-model split. Spec called for a
single AbstractModel; reality is that ir.actions.report.model and
mail.template.model_id are fragile against AbstractModel binding.
Persistent log Model = report subject + email anchor; abstract
orchestrator = cron + helpers. Resolves spec §5.4 risk.

⚠️ DECISION (M9, marker 2): append-only audit. perm_unlink=0 for
all tiers (superuser too, in spirit -- the CSV says 1 for
superuser purely for housekeeping). Log rows are observability,
not user data.
"""
import logging

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class NeonDashboardDigestLog(models.Model):
    _name = "neon.dashboard.digest.log"
    _description = "Weekly Digest Send History"
    _order = "sent_at desc, id desc"
    _rec_name = "display_label"

    sent_at = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
        required=True,
        index=True,
    )
    window_start = fields.Date(readonly=True)
    window_end = fields.Date(readonly=True)
    window_label = fields.Char(
        readonly=True,
        help="Human-readable window string used in PDF + email "
        "subject (e.g. '19 May - 25 May 2026').",
    )
    recipient_count = fields.Integer(readonly=True)
    recipient_ids = fields.Many2many(
        "res.users",
        "neon_dashboard_digest_log_recipient_rel",
        "log_id",
        "user_id",
        readonly=True,
    )
    pdf_attachment_id = fields.Many2one(
        "ir.attachment",
        readonly=True,
        ondelete="set null",
        help="The PDF rendered for this digest send. Email "
        "attachment references the same ir.attachment row.",
    )
    status = fields.Selection(
        [
            ("sent", "Sent"),
            ("no_recipients", "No recipients"),
            ("error", "Error"),
        ],
        default="sent",
        readonly=True,
        required=True,
        index=True,
    )
    error_message = fields.Text(
        readonly=True,
        help="Populated when status='error'. Truncated to first "
        "2000 chars to avoid filling the table on repeated failures.",
    )
    triggered_by_id = fields.Many2one(
        "res.users",
        readonly=True,
        ondelete="set null",
        help="User who fired the manual trigger; null for cron-"
        "driven sends (those run as base.user_root).",
    )
    display_label = fields.Char(
        compute="_compute_display_label",
        store=False,
    )

    @api.depends("sent_at", "window_label", "status")
    def _compute_display_label(self):
        for log in self:
            ts = fields.Datetime.to_string(log.sent_at) if log.sent_at else ""
            log.display_label = (
                f"{ts} - {log.window_label or '?'} ({log.status})"
            )

    # ------------------------------------------------------------
    # Render helpers -- the QWeb report binds to this model with
    # res_ids=[log.id], so the template iterates `docs` (recordset
    # of NeonDashboardDigestLog). The orchestrator stashes the
    # payload dict on the recordset via context for the duration of
    # a single render.
    # ------------------------------------------------------------
    def _get_render_payload(self):
        """Return the payload dict the template needs. The
        orchestrator passes the payload via ``data={'payload': {...}}``
        on _render_qweb_pdf; this helper bridges that into the
        QWeb template scope without forcing every template
        expression to dig through ``data``."""
        self.ensure_one()
        return self.env.context.get("digest_payload") or {}
