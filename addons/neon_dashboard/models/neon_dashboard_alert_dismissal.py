# -*- coding: utf-8 -*-
"""Phase 8A.M7 -- per-user alert dismissals.

The Alerts block surfaces issues from five sources (overdue
invoices, pending approvals, crew gaps, stale quotes, forecast
at-risk). Each surfaced alert carries a stable ``fingerprint``;
when a user clicks "Ack" the OWL component POSTs the fingerprint
here and the alert is filtered out of that user's dashboard going
forward.

⚠️ DECISION (M7, marker 1): re-surfacing is fingerprint-driven.
Fingerprints encode an ISO-week bucket for time-decaying sources
(overdue / pending / stale) so a dismissed alert AUTOMATICALLY
re-appears next week if the underlying condition persists. Crew
gap fingerprints include event_date so a rescheduled event
re-surfaces. Forecast at-risk uses target id only -- new target
period = new fingerprint.

⚠️ DECISION (M7, marker 2): per-user dismissal only -- Robin's
ack does not affect Munashe's view. Implementation via a record
rule scoping to ``user_id = uid`` for every internal-user tier.
Superuser sees all (admin override for audit).

⚠️ DECISION (M7, marker 3): dismissals are append-only. ondelete
on user_id is ``cascade`` (housekeeping when a user is removed);
no API-driven unlink by non-superusers (record rule's
perm_unlink=False).
"""
from odoo import api, fields, models


class NeonDashboardAlertDismissal(models.Model):
    _name = "neon.dashboard.alert.dismissal"
    _description = "Per-User Alert Dismissals"
    _order = "acknowledged_at desc, id desc"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
        default=lambda self: self.env.user.id,
    )
    fingerprint = fields.Char(
        required=True,
        index=True,
        help="Stable identifier for the dismissed alert. Format "
        "<type>:<entity_id>[:<bucket>]. See "
        "neon.dashboard._alert_fingerprint() docstring for the "
        "per-source scheme.",
    )
    acknowledged_at = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
        required=True,
    )

    _sql_constraints = [
        ("user_fingerprint_unique",
         "UNIQUE(user_id, fingerprint)",
         "A user cannot dismiss the same alert twice."),
    ]

    @api.model
    def get_dismissed_fingerprints_for_user(self, user_id=None):
        """Return a set of fingerprint strings the given user (or
        current user) has dismissed. Used by the alerts compute to
        filter out acks."""
        uid = user_id or self.env.user.id
        rows = self.sudo().search_read(
            [("user_id", "=", uid)],
            fields=["fingerprint"],
        )
        return {r["fingerprint"] for r in rows}
