# -*- coding: utf-8 -*-
"""P6.M11 -- cost recovery invoice wizard.

Approver opens from event_job form button "Create Cost Recovery
Invoice" (visible when pending_cost_recovery=True). Wizard prompts
for amount, currency, handling fee, notes; on confirm creates an
account.move out_invoice linked to event_job.partner_id and clears
the pending_cost_recovery flag.

⚠️ DECISION (P6.M11, marker 6): wizard CONVERTS the write-off cost
(stored in incident.currency_id, usually USD) into the event_job's
quote currency. Conversion via the most recent
neon.finance.conversion.rate effective at wizard-open time. This
separates the write-off cost.line (in USD, intrinsic asset value)
from the recovery invoice (in client's quote currency, what they
expect to pay).

⚠️ DECISION (P6.M11, marker 7): invoice.ref = "RECOV-<incident.name>"
extends M8's parse-via-ref pattern. No related field added to
account.move. Recovery invoices are identifiable by the RECOV-
prefix.

⚠️ DECISION (P6.M11, marker 8): clearing of
event_job.pending_cost_recovery happens here, in the wizard's
confirm action, AFTER the invoice is successfully created. If the
approver cancels (closes the wizard) the flag stays set.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class NeonFinanceCostRecoveryWizard(models.TransientModel):
    _name = "neon.finance.cost.recovery.wizard"
    _description = "Cost Recovery Invoice Wizard"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(
        "res.partner",
        related="event_job_id.partner_id",
        readonly=True,
    )
    cost_line_id = fields.Many2one(
        "neon.finance.cost.line",
        compute="_compute_cost_line",
        store=False,
        help="The most recent write-off cost.line on this event "
        "job, used to default the recovery amount.",
    )
    handling_fee_pct = fields.Float(
        string="Handling Fee %",
        default=10.0,
        help="Percentage uplift on the write-off cost. Default 10% "
        "covers Neon's administrative overhead in recovering the "
        "loss. Approver can adjust.",
    )
    amount = fields.Monetary(
        compute="_compute_amount",
        readonly=False,
        store=True,
        currency_field="currency_id",
        help="Total recovery amount (write-off cost x (1 + handling "
        "fee %)) converted to event_job's quote currency.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency",
        readonly=False,
        store=True,
        help="Defaults to event_job's quote currency. Approver can "
        "override to bill in a different currency if negotiated.",
    )
    invoice_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
    )
    description = fields.Char(
        compute="_compute_description",
        readonly=False,
        store=True,
    )
    notes = fields.Text()

    @api.depends("event_job_id")
    def _compute_cost_line(self):
        for wiz in self:
            if not wiz.event_job_id:
                wiz.cost_line_id = False
                continue
            wiz.cost_line_id = self.env[
                "neon.finance.cost.line"].sudo().search([
                    ("event_job_id", "=", wiz.event_job_id.id),
                    ("cost_type", "=", "write_off"),
                ], order="date_incurred desc, id desc", limit=1)

    @api.depends("event_job_id", "cost_line_id", "handling_fee_pct")
    def _compute_amount(self):
        for wiz in self:
            if not wiz.cost_line_id:
                wiz.amount = 0.0
                continue
            base = wiz.cost_line_id.amount or 0.0
            multiplier = 1.0 + (wiz.handling_fee_pct or 0.0) / 100.0
            # Currency conversion: write-off cost is in
            # cost_line.currency_id; target is event_job quote
            # currency. Apply conversion only if currencies differ.
            target_currency = wiz._compute_target_currency()
            if (wiz.cost_line_id.currency_id
                    and target_currency
                    and wiz.cost_line_id.currency_id != target_currency):
                converted = wiz._convert_via_neon_rate(
                    base, wiz.cost_line_id.currency_id, target_currency)
            else:
                converted = base
            wiz.amount = converted * multiplier

    @api.depends("event_job_id")
    def _compute_currency(self):
        for wiz in self:
            wiz.currency_id = wiz._compute_target_currency()

    def _compute_target_currency(self):
        """Event_job's quote currency. Falls back to company currency
        (USD) when no accepted quote exists yet."""
        self.ensure_one()
        if not self.event_job_id:
            return self.env.company.currency_id
        # Most recent accepted quote on this event_job
        quote = self.env["neon.finance.quote"].sudo().search([
            ("event_job_id", "=", self.event_job_id.id),
            ("state", "=", "accepted"),
        ], order="accepted_at desc, id desc", limit=1)
        if quote and quote.currency_id:
            return quote.currency_id
        return self.env.company.currency_id

    def _convert_via_neon_rate(self, amount, src_currency,
                                tgt_currency):
        """Look up rate via the model's get_active_rate helper.

        Marker 6: conversion at wizard-open time (forward-looking).
        Returns the unconverted amount when no rate is available --
        the form remains usable; final guard at confirm time raises
        if the wizard tries to bill in a target currency without a
        rate. See action_create_recovery_invoice.
        """
        self.ensure_one()
        Rate = self.env["neon.finance.conversion.rate"].sudo()
        rate = Rate.get_active_rate(src_currency, tgt_currency)
        if rate is None:
            return amount  # graceful: caller will catch at confirm
        return amount * rate

    @api.depends("event_job_id")
    def _compute_description(self):
        for wiz in self:
            wiz.description = _(
                "Cost recovery: damage / loss at %(event)s"
            ) % {"event": wiz.event_job_id.display_name or "(event)"}

    def action_create_recovery_invoice(self):
        """Approver-only. Creates the account.move + posts chatter
        + clears the pending_cost_recovery flag."""
        self.ensure_one()
        if not (self.env.user.has_group(
                    "neon_finance.group_neon_finance_approver")):
            from odoo.exceptions import AccessError
            raise AccessError(_(
                "Only the Finance Approver group can finalise a "
                "cost-recovery invoice."))
        if self.amount <= 0:
            raise UserError(_(
                "Recovery amount must be positive."))
        if not self.event_job_id.partner_id:
            raise UserError(_(
                "Event %(event)s has no partner; cannot create a "
                "recovery invoice."
            ) % {"event": self.event_job_id.name})
        if not (self.description or "").strip():
            raise UserError(_(
                "Description is required on the recovery invoice."))
        # Marker 6 final guard: if conversion was required (currencies
        # differ) and no rate covered it, the amount equals the
        # unconverted base. Reject so the approver knows to set a rate.
        if (self.cost_line_id
                and self.cost_line_id.currency_id
                and self.currency_id
                and self.cost_line_id.currency_id != self.currency_id):
            Rate = self.env["neon.finance.conversion.rate"].sudo()
            rate = Rate.get_active_rate(
                self.cost_line_id.currency_id, self.currency_id)
            if rate is None:
                raise UserError(_(
                    "No conversion rate available from %(src)s to "
                    "%(tgt)s. Bookkeeper must set one in "
                    "Configuration > Finance > Conversion Rates "
                    "before this recovery invoice can be created."
                ) % {
                    "src": self.cost_line_id.currency_id.name,
                    "tgt": self.currency_id.name,
                })
        # Compute the ref: RECOV-<incident.name> when a write-off
        # cost.line links back to an incident. Fall back to
        # RECOV-<event_job.name> when the chain is broken.
        ref_anchor = "RECOV"
        incident_name = ""
        if (self.cost_line_id
                and self.cost_line_id.source_movement_id):
            mvmt = self.cost_line_id.source_movement_id
            incident = self.env[
                "neon.equipment.incident"].sudo().search([
                    ("source_checkin_movement_id", "=", mvmt.id),
                ], limit=1)
            if incident:
                incident_name = incident.name
        ref = "%s-%s" % (
            ref_anchor,
            incident_name or self.event_job_id.name,
        )
        move = self.env["account.move"].sudo().create({
            "move_type": "out_invoice",
            "partner_id": self.event_job_id.partner_id.id,
            "currency_id": self.currency_id.id,
            "invoice_date": self.invoice_date,
            "ref": ref,
            "invoice_origin": self.event_job_id.name,
            "narration": self.notes or "",
            "invoice_line_ids": [(0, 0, {
                "name": self.description,
                "quantity": 1.0,
                "price_unit": self.amount,
            })],
        })
        # Clear the recovery flag and post chatter.
        self.event_job_id.sudo().write(
            {"pending_cost_recovery": False})
        self.event_job_id.sudo().message_post(body=_(
            "Cost recovery invoice %(inv)s created for %(curr)s "
            "%(amt).2f by %(user)s."
        ) % {
            "inv": move.name or move.display_name,
            "curr": self.currency_id.name,
            "amt": self.amount,
            "user": self.env.user.name,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Recovery Invoice"),
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": move.id,
            "target": "current",
        }
