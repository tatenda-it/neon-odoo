# -*- coding: utf-8 -*-
"""P6.M9 -- account.payment.register wizard override.

Enforces Q6 (B1): no cross-currency payment against a Neon invoice.

⚠️ DECISION (P6.M9, locked at design pause): enforcement hook is
the wizard's _create_payments() entry point, NOT @api.constrains on
account.payment. Reason: by the time the constraint fires
post-create, partial reconciliation may already be in flight,
producing a half-committed state. The wizard pre-create is the
earliest cleanly-interceptable point; raising UserError there
returns a precise, action-stage error to the bookkeeper.

Marker 4 (P6.M8): Neon invoices are detected via invoice.ref
starting with 'SCH-'. Non-Neon invoices (vendor bills, manual
moves, refunds) skip the check entirely -- this wizard handles
stock Odoo flows for everyone else.
"""
import re

from odoo import _, models
from odoo.exceptions import UserError


_SCH_REF_RE = re.compile(r"^SCH-\d+$")


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _create_payments(self):
        """Cross-currency guard for Neon invoices, run before the
        standard create-payment + reconcile flow.
        """
        self._neon_check_currency_match()
        return super()._create_payments()

    def _neon_check_currency_match(self):
        """Raise UserError if this wizard's currency_id does not
        match the currency of any selected Neon invoice."""
        if not self.line_ids:
            return
        moves = self.line_ids.move_id
        neon_invoices = moves.filtered(
            lambda m: m.ref and _SCH_REF_RE.match(m.ref or ""))
        for inv in neon_invoices:
            if inv.currency_id != self.currency_id:
                raise UserError(_(
                    "Cross-currency payment blocked: invoice %(inv)s "
                    "is in %(inv_curr)s but the payment is in "
                    "%(pay_curr)s. Neon Finance policy (Q6) requires "
                    "currency-matched payments against scheduled "
                    "invoices. Re-open the wizard with a matching "
                    "journal or change the invoice currency at the "
                    "quote level."
                ) % {
                    "inv": inv.name or inv.display_name,
                    "inv_curr": inv.currency_id.name,
                    "pay_curr": self.currency_id.name,
                })
