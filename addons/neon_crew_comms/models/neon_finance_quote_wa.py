# -*- coding: utf-8 -*-
"""QUOTE-UX-1 routing unification — route the SHARED submit into the WA rail.

neon_crew_comms is downstream of neon_finance, so it may inherit
neon.finance.quote and extend action_submit_for_approval. This is the SINGLE
place the WhatsApp approval ping attaches to the shared submit, so BOTH origins
funnel through it and the approver is pinged on WhatsApp EXACTLY ONCE:

  * the Odoo "Submit for Approval" button  -> action_submit_for_approval
  * the WhatsApp _wa12_submit flow          -> action_submit_for_approval
    (the explicit _wa12_send_approval_ping call in _wa12_submit is removed, so
     the WA-origin quote no longer double-pings).

neon_finance itself stays WhatsApp-agnostic (the dependency arrow is
crew_comms -> finance only). The Odoo mail.activity TODO scheduled by the base
method STAYS — additive: the Odoo inbox AND WhatsApp both notify; email is no
longer the only channel.

The ping mechanism (audience, HMAC buttons, first-tap-wins lock, 24h window,
cold template, wa12_* intents) is byte-unchanged — this only moves WHERE it is
invoked from.
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class NeonFinanceQuote(models.Model):
    _inherit = "neon.finance.quote"

    def action_submit_for_approval(self):
        """After the shared submit transitions a quote to pending_approval,
        fire the WhatsApp approval ping.

        REQUESTER = the quote's salesperson_id (origin-independent): the Odoo
        form submitter is env.user and the WA submitter is resolved via
        with_user(+sudo), so salesperson_id is the stable owner for BOTH and
        the natural ping attribution + PDF recipient.

        A WA send failure must NEVER roll back the committed submit (the
        approval record + pending state stand; the approver can still action it
        in Odoo and via the enriched activity note)."""
        res = super().action_submit_for_approval()
        WA = self.env["neon.whatsapp.message"].sudo()
        for rec in self:
            # Only the standard branch pings. The config-relaxation auto-approve
            # (state == 'approved') has no approver to ping; the WA flow sends
            # that quote's PDF straight to the requester instead.
            if rec.state != "pending_approval":
                continue
            requester = rec.salesperson_id or rec.create_uid
            try:
                pinged = WA._wa12_send_approval_ping(rec, requester)
            except Exception as exc:  # noqa: BLE001 -- never roll back the submit
                _logger.warning(
                    "QUOTE-UX-1: WhatsApp approval ping failed for %s: %s",
                    rec.name, exc)
                continue
            if pinged and rec.approval_id:
                # the forward-compat fields the approval model already declares
                # for "the WhatsApp dispatcher notified OD/MD".
                rec.approval_id.sudo().write({
                    "notification_sent": True,
                    "notification_sent_at": fields.Datetime.now(),
                })
        return res
