# -*- coding: utf-8 -*-
"""P6.M9 -- account.move._compute_payment_state extension.

Drives the schedule.state propagation for customer payment matching.

⚠️ DECISION (P6.M9, locked at design pause): mechanism is a
compute-extend, NOT a write() override. Per the M6 lesson
(CLAUDE.md "compute chains bypass write()"), Odoo's
account.move.payment_state is a stored computed field
(compute='_compute_payment_state', store=True) -- updates to it via
the compute trigger do NOT fire model.write(). The only reliable
hook is to extend the compute itself, super(), then propagate.

Marker 4 (P6.M8): we do NOT add a quote_id / schedule_id related
field on account.move. Neon invoices are detected via
invoice.ref starting with 'SCH-' (the schedule sequence M7 stamps).
This degrades gracefully for vendor bills, refunds, and manual
moves -- the propagation helper finds no matching schedule and
returns. Non-Neon invoices render Odoo's stock behaviour untouched.
"""
import logging
import re

from odoo import _, api, models


_logger = logging.getLogger(__name__)


# Schedule.invoice_id is set when M7's action_create_invoice fires;
# invoice.ref is stamped with the schedule sequence (SCH-NNNNNN). The
# reverse lookup is the canonical path Neon invoices use; non-Neon
# invoices (vendor bills, manual entries) won't match.
_SCH_REF_RE = re.compile(r"^SCH-\d+$")


# Map of Odoo's account.move.payment_state -> our schedule state.
# 'in_payment' is intentionally absent: it means "payment recorded
# but not yet matched/cleared by reconciliation". Treating it as
# 'paid' would prematurely close the schedule. We leave the schedule
# at 'invoiced' until payment_state reaches 'paid'.
_PAYMENT_STATE_TO_SCHEDULE_STATE = {
    "paid": "paid",
    "partial": "partial",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    @api.depends("amount_residual", "move_type", "state", "company_id")
    def _compute_payment_state(self):
        """Extend Odoo's stored compute. After Odoo writes the new
        payment_state, propagate to any neon.finance.invoice.schedule
        whose invoice_id == this move.

        Side-effect placement rationale (M6 pattern): dispatching
        from the compute body is the only way to react to a
        store=True compute update without losing it (write() override
        misses these mutations because Odoo bypasses write() when
        recomputing stored fields).
        """
        super()._compute_payment_state()
        self._neon_propagate_payment_state_to_schedule()

    def _neon_propagate_payment_state_to_schedule(self):
        """Map invoice.payment_state -> schedule.state for any Neon
        invoice. Reversal (paid -> not_paid) flips the schedule back
        to 'invoiced'; the schedule never returns to 'scheduled'
        because the invoice still exists post-reversal.

        Marker 6 (locked P6.M9): reversal target is 'invoiced', not
        'scheduled'. Pre-trigger state ('scheduled') means no invoice
        was ever created; a reversed-payment invoice still exists.
        """
        # Filter to plausible candidates without searching the
        # schedule table for irrelevant moves.
        candidates = self.filtered(
            lambda m: m.ref and _SCH_REF_RE.match(m.ref or ""))
        if not candidates:
            return
        Schedule = self.env["neon.finance.invoice.schedule"].sudo()
        scheds = Schedule.search([
            ("invoice_id", "in", candidates.ids),
        ])
        if not scheds:
            return
        for sched in scheds:
            invoice = sched.invoice_id
            new_state = _PAYMENT_STATE_TO_SCHEDULE_STATE.get(
                invoice.payment_state)
            if new_state is None:
                # not_paid / in_payment / reversed / legacy. Reversal
                # path: if schedule was previously paid/partial and
                # invoice now reverts to not_paid, set back to
                # 'invoiced' (invoice still exists post-chargeback).
                if (sched.state in ("paid", "partial")
                        and invoice.payment_state in ("not_paid", "reversed")):
                    sched.sudo().write({"state": "invoiced"})
                    sched.quote_id.sudo().message_post(body=_(
                        "Schedule %(sched)s state reverted to "
                        "Invoiced: invoice %(inv)s payment_state = "
                        "%(ps)s."
                    ) % {
                        "sched": sched.name,
                        "inv": invoice.name or invoice.display_name,
                        "ps": invoice.payment_state,
                    })
                continue
            if sched.state == new_state:
                continue
            sched.sudo().write({"state": new_state})
            sched.quote_id.sudo().message_post(body=_(
                "Schedule %(sched)s state -> %(new)s (invoice "
                "%(inv)s payment_state = %(ps)s)."
            ) % {
                "sched": sched.name,
                "new": dict(sched._fields["state"].selection).get(
                    new_state, new_state),
                "inv": invoice.name or invoice.display_name,
                "ps": invoice.payment_state,
            })
