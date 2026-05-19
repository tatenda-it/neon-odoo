# -*- coding: utf-8 -*-
"""P6.M9 -- res.partner credit hold extension.

Set automatically by late-policy='account_hold' when a Neon
invoice schedule transitions to overdue and the partner's payment
term carries that policy.

⚠️ DECISION (P6.M9, locked at design pause): field-on-res.partner,
not a dedicated neon.finance.credit.hold model. Marker 4 applies
to *stock* Odoo coupling -- res.partner is already neon-customized
via neon_crm_extensions (x_outstanding_balance) and neon_jobs
(is_venue / rapid-ops). A dedicated model would add join overhead
for hot-path checks ("can sales create a new quote?") with no
audit advantage -- chatter on res.partner already captures the
flip lifecycle via mail.thread.

⚠️ DECISION (Marker 7): manual clearing only. Auto-clear on
payment would hide the historical event from approver review.
"""
from odoo import _, fields, models
from odoo.exceptions import AccessError


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_neon_credit_hold = fields.Boolean(
        string="Credit Hold (Neon Finance)",
        default=False,
        tracking=True,
        copy=False,
        help="Set when a payment.term with late_policy='account_hold' "
        "fires its overdue trigger. Blocks new quotes from this "
        "partner per finance policy. Bookkeeper or Approver clears "
        "manually via the Clear Credit Hold action.",
    )

    def action_clear_credit_hold(self):
        """Bookkeeper / Approver-only manual clear. Posts a chatter
        message attributing the clearance."""
        if not (self.env.user.has_group(
                    "neon_finance.group_neon_finance_bookkeeper")
                or self.env.user.has_group(
                    "neon_finance.group_neon_finance_approver")):
            raise AccessError(_(
                "Only Bookkeeper or Approver can clear a credit "
                "hold. Sales reps cannot self-clear."))
        for rec in self:
            if not rec.x_neon_credit_hold:
                continue
            rec.sudo().write({"x_neon_credit_hold": False})
            rec.sudo().message_post(
                body=_("Credit hold cleared by %(user)s.") % {
                    "user": self.env.user.name},
                author_id=self.env.user.partner_id.id,
            )
        return True
