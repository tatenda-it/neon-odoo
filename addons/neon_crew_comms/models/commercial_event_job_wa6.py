# -*- coding: utf-8 -*-
"""B11 / WA-6 -- commercial.event.job: OD-initiated equipment finalize
(bridge). A header button (mirrors commercial.job.action_notify_crew)
that, gated to the OD/superuser, sends the initiator a 3-button finalize
choice on WhatsApp. NO auto-trigger / NO cron -- manual first."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CommercialEventJobWA6(models.Model):
    _inherit = "commercial.event.job"

    wa6_can_initiate = fields.Boolean(
        compute="_compute_wa6_can_initiate",
        help="True for the OD (config login) or a Neon Superuser -- gates "
        "the 'Finalize Equipment (WhatsApp)' header button. Computed per "
        "current user (not stored).")

    @api.depends_context("uid")
    def _compute_wa6_can_initiate(self):
        can = self.env["neon.whatsapp.message"].sudo()._wa6_can_initiate(
            self.env.user)
        for rec in self:
            rec.wa6_can_initiate = can

    def action_wa6_initiate_finalize(self):
        """Header button -> send the initiator (the clicking OD/superuser)
        their 3-button finalize choice on WhatsApp. Server-side gate is
        defence-in-depth behind the button's invisible='not
        wa6_can_initiate'."""
        self.ensure_one()
        WM = self.env["neon.whatsapp.message"].sudo()
        if not WM._wa6_can_initiate(self.env.user):
            raise UserError(_(
                "Only the OD (or a Neon Superuser) can initiate equipment "
                "finalize over WhatsApp."))
        res = WM._wa6_send_initiate(self, self.env.user)
        if not res.get("ok") and res.get("reason") == "no_botuser":
            raise UserError(_(
                "Your Odoo user has no active WhatsApp number mapped "
                "(neon.bot.user). Map your number first, or ask an "
                "administrator."))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Finalize prompt sent"),
                "message": _(
                    "A WhatsApp finalize choice for %s was sent to your "
                    "number. Tap a button there to continue.") % self.name,
                "type": "success", "sticky": False,
            },
        }
