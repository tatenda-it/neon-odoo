# -*- coding: utf-8 -*-
"""P6.M11 -- workshop write-off integration via incident extension.

⚠️ DECISION (P6.M11, locked at design pause): hook point is
`neon.equipment.incident.action_resolve_writeoff`, NOT
`neon.equipment.movement` creation. Discovery confirmed three
spec-vs-reality corrections:

  1. Movement is append-only audit log with no value field.
  2. Value lives on incident.estimated_loss_value.
  3. is_client_caused is a resolution-time judgment; belongs with
     the lifecycle (incident), not the audit log (movement).

So neon_finance extends the incident model: adds an
is_client_caused Boolean, extends action_resolve_writeoff via
super-call to auto-create the cost.line + flag the event_job for
client-caused recoveries.

⚠️ DECISION (P6.M11, marker 3): action_resolve_writeoff signature
extends with is_client_caused=False kwarg. Backwards compatible:
existing callers passing just `reason=` still work.

⚠️ DECISION (P6.M11, marker 9): notification dispatch on the
auto-created cost.line piggybacks on M5's
_notify_finance_oversight. Self-suppression for the resolving
manager applies normally.
"""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class NeonEquipmentIncident(models.Model):
    _inherit = "neon.equipment.incident"

    is_client_caused = fields.Boolean(
        string="Client-Caused",
        default=False,
        tracking=True,
        help="Set by the resolving manager when the loss / damage "
        "is attributable to client conduct (vs wear-and-tear or "
        "internal handling). Triggers Phase 6 cost-recovery flow: "
        "event_job.pending_cost_recovery flag + approver action.",
    )

    def action_resolve_writeoff(self, reason=None, is_client_caused=False):
        """Extend P5.M9 incident write-off resolution with Phase 6
        cost.line auto-creation.

        Backwards-compatible: callers passing only `reason=` get the
        default is_client_caused=False (treated as wear-and-tear --
        cost.line still created for P&L accuracy, but no recovery
        flag fires).

        Marker 1 mechanism: super() first (validates manager
        authority + transitions state). Then write the
        is_client_caused flag explicitly so the value is tracked
        via mail.thread. THEN create the cost.line + flag.

        Marker 4: cost.line.source_movement_id is populated from
        incident.source_checkin_movement_id when available; may be
        False (incident created via missing+incident_link path or
        stock-take line).
        """
        super().action_resolve_writeoff(reason=reason)
        # Now write the causation flag (super() left it default).
        # State is already 'resolved_writeoff'; this is a metadata
        # write, not a transition.
        if is_client_caused:
            for rec in self:
                rec.sudo().write({"is_client_caused": True})
        # Auto-create cost.line per incident. Incidents without a
        # source_event_job_id (e.g. stock-take-originated write-offs)
        # skip the cost.line step with a log entry; they remain a
        # valid P5.M9 resolution path. M11's contract is "when there
        # IS an event_job, the P&L gets a cost.line."
        for rec in self:
            if not rec.source_event_job_id:
                _logger.info(
                    "Incident %s resolved as write-off with no "
                    "source_event_job_id (stock-take-origin path). "
                    "Skipping P6.M11 cost.line auto-create.",
                    rec.name)
                continue
            rec._neon_finance_create_writeoff_cost_line(
                is_client_caused=is_client_caused)
        return True

    def _neon_finance_create_writeoff_cost_line(self, is_client_caused):
        """Create a cost.line tied to this incident + flag the
        event_job if client-caused. Idempotent: skips if a cost.line
        with source_movement_id already exists pointing to our
        check-in movement.

        Marker 5: cost.line.currency_id inherits from
        incident.currency_id (defaults to company currency, usually
        USD). The recovery invoice (separate wizard) handles
        conversion to event_job's quote currency at wizard time
        per Marker 6.
        """
        self.ensure_one()
        CostLine = self.env["neon.finance.cost.line"].sudo()
        # Idempotency: if a cost.line already exists for this
        # incident's check-in movement, don't double-create. The
        # source_movement_id link is the primary key.
        existing = CostLine.search([
            ("source_movement_id", "=",
             self.source_checkin_movement_id.id or 0),
            ("event_job_id", "=", self.source_event_job_id.id),
            ("cost_type", "=", "write_off"),
        ], limit=1) if self.source_checkin_movement_id else CostLine
        if existing:
            _logger.info(
                "Incident %s already has a cost.line "
                "(%s); skipping auto-create.",
                self.name, existing.name)
            return existing
        cost = CostLine.create({
            "event_job_id": self.source_event_job_id.id,
            "cost_type": "write_off",
            "name": _("Write-off: %(inc)s -- %(unit)s") % {
                "inc": self.name, "unit": self.unit_id.name},
            "amount": self.estimated_loss_value or 0.0,
            "currency_id": (
                self.currency_id.id
                if self.currency_id
                else self.env.company.currency_id.id),
            "date_incurred": fields.Date.context_today(self),
            "recorded_by_id": self.env.user.id,
            "source_movement_id": (
                self.source_checkin_movement_id.id
                if self.source_checkin_movement_id else False),
            "notes": _(
                "Auto-created from incident %(inc)s resolved as "
                "write-off by %(user)s. Estimated loss value: "
                "%(curr)s %(amt).2f. Client-caused: %(client)s."
            ) % {
                "inc": self.name,
                "user": self.env.user.name,
                "curr": (
                    self.currency_id.name
                    if self.currency_id
                    else self.env.company.currency_id.name),
                "amt": self.estimated_loss_value or 0.0,
                "client": "yes" if is_client_caused else "no",
            },
        })
        # Chatter post on the incident + on the event_job for audit
        # trail. Marker 9 + chatter pattern from M5.
        self.sudo().message_post(body=_(
            "Cost line %(cost)s created for write-off "
            "(%(curr)s %(amt).2f)."
        ) % {
            "cost": cost.name,
            "curr": cost.currency_id.name,
            "amt": cost.amount,
        })
        self.source_event_job_id.sudo().message_post(body=_(
            "Write-off cost recorded from incident %(inc)s: "
            "%(curr)s %(amt).2f. Client-caused: %(client)s."
        ) % {
            "inc": self.name,
            "curr": cost.currency_id.name,
            "amt": cost.amount,
            "client": "yes" if is_client_caused else "no",
        })
        # Flag event_job for client-caused recoveries.
        if is_client_caused:
            self.source_event_job_id.sudo().write(
                {"pending_cost_recovery": True})
        return cost
