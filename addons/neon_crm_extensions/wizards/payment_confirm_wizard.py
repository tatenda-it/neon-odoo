# -*- coding: utf-8 -*-
"""
Day 11 — Confirm Payment wizard.

A TransientModel that captures payment-claim details from a sales user
and, on submit:

  1. Sets payment_claim_status = 'claimed' on the originating lead
  2. Moves the lead to the "Payment Pending Verification" stage
  3. Posts an activity log on the lead summarising the claim
  4. Sends a WhatsApp notification to Munashe via the OpenClaw API,
     using ir.config_parameter values for URL, token, and recipient

The WhatsApp call is best-effort: if OpenClaw is misconfigured or the
HTTP request fails, the payment claim still records correctly and the
failure is logged. Sales users should not be blocked from claiming a
payment because of a notification outage.
"""

import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Hard timeout for the OpenClaw HTTP call, in seconds. Kept short so a
# slow/unreachable provider does not freeze the wizard for the user.
OPENCLAW_TIMEOUT = 8


class NeonPaymentConfirmWizard(models.TransientModel):
    _name = "neon.payment.confirm.wizard"
    _description = "Neon: Confirm Payment Received Wizard"

    lead_id = fields.Many2one(
        comodel_name="crm.lead",
        string="Deal",
        required=True,
        ondelete="cascade",
    )
    amount = fields.Float(
        string="Amount",
        required=True,
        digits=(12, 2),
    )
    payment_method = fields.Selection(
        selection=[
            ("cash", "Cash"),
            ("ecocash", "EcoCash"),
            ("bank_usd", "Bank Transfer USD"),
            ("bank_zig", "Bank Transfer ZiG"),
        ],
        string="Payment Method",
        required=True,
    )
    reference = fields.Char(
        string="Reference Number",
        required=True,
    )
    payment_date = fields.Date(
        string="Payment Date",
        required=True,
        default=fields.Date.context_today,
    )
    notes = fields.Text(
        string="Notes",
    )

    # ────────────────────────────────────────────────────────────────
    # Defaults — populate lead_id from active_id when launched from
    # the lead form's header button.
    # ────────────────────────────────────────────────────────────────

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "crm.lead" and active_id and "lead_id" in fields_list:
            defaults["lead_id"] = active_id
        return defaults

    # ────────────────────────────────────────────────────────────────
    # Confirm action
    # ────────────────────────────────────────────────────────────────

    def action_confirm_payment(self):
        """Persist the claim, move stage, log activity, notify WhatsApp."""
        self.ensure_one()
        lead = self.lead_id
        if not lead:
            raise UserError(_("No deal is associated with this wizard."))
        if self.amount <= 0:
            raise UserError(_("Amount must be greater than zero."))

        stage = self.env.ref(
            "neon_crm_extensions.stage_payment_pending_verification",
            raise_if_not_found=False,
        )

        write_vals = {"payment_claim_status": "claimed"}
        if stage:
            write_vals["stage_id"] = stage.id
        lead.write(write_vals)

        method_label = dict(self._fields["payment_method"].selection).get(
            self.payment_method, self.payment_method
        )
        body = _(
            "Payment claim: $%(amount).2f via %(method)s, ref %(reference)s. "
            "Awaiting Munashe's verification."
        ) % {
            "amount": self.amount,
            "method": method_label,
            "reference": self.reference,
        }
        if self.notes:
            body = "%s<br/><em>%s</em>" % (body, self.notes)
        lead.message_post(body=body)

        self._neon_send_whatsapp_to_munashe(method_label)

        return {"type": "ir.actions.act_window_close"}

    # ────────────────────────────────────────────────────────────────
    # OpenClaw WhatsApp integration
    # ────────────────────────────────────────────────────────────────

    def _neon_send_whatsapp_to_munashe(self, method_label):
        """POST a notification to OpenClaw. Best-effort — failures are
        logged but never raised, so a payment claim is never blocked
        by a notification outage."""
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param("neon_crm_extensions.openclaw_api_url")
        token = params.get_param("neon_crm_extensions.openclaw_api_token")
        to_number = params.get_param("neon_crm_extensions.munashe_whatsapp_number")

        if not (url and token and to_number):
            _logger.warning(
                "[Day 11] OpenClaw notification skipped — one or more of "
                "openclaw_api_url, openclaw_api_token, "
                "munashe_whatsapp_number is not configured."
            )
            return False

        client_name = (
            self.lead_id.partner_id.name
            or self.lead_id.contact_name
            or self.lead_id.name
            or "an unnamed client"
        )
        sales_user = self.env.user.name
        message = _(
            "%(user)s confirmed $%(amount).2f from %(client)s via "
            "%(method)s, ref %(reference)s. Please verify in Zoho Books."
        ) % {
            "user": sales_user,
            "amount": self.amount,
            "client": client_name,
            "method": method_label,
            "reference": self.reference,
        }

        payload = {
            "to": to_number,
            "message": message,
        }
        headers = {
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=OPENCLAW_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            _logger.warning(
                "[Day 11] OpenClaw notification failed for lead %s: %s",
                self.lead_id.id,
                exc,
            )
            return False

        _logger.info(
            "[Day 11] OpenClaw notification sent for lead %s (ref %s)",
            self.lead_id.id,
            self.reference,
        )
        return True
