# -*- coding: utf-8 -*-
"""B11 / WA-2 -- proactive-WhatsApp opt-out on the contact.

A contact (crew member, client, anyone we might proactively message)
can opt OUT of proactive WhatsApp sends by replying STOP. The flag lives
on res.partner because it is the CANONICAL identity for both permanent
crew (who also have a user/bot.user) AND freelancers (partner-only) --
a bot.user-only flag would miss freelancers (Gate-1 decision, WA-2).

Honoured by ``neon.whatsapp.message.send_template`` (the proactive
path). It does NOT gate reactive Copilot replies -- those are inside
Meta's 24h, user-initiated window, where opt-out doesn't apply.
"""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    wa_opt_out = fields.Boolean(
        string="WhatsApp opted out",
        default=False,
        help="Set when this contact replies STOP over WhatsApp. While "
        "True, proactive WhatsApp sends (send_template) are suppressed. "
        "Reply START to clear. Does not affect replies within an active "
        "conversation.")
    wa_opt_out_date = fields.Datetime(
        string="WhatsApp opt-out date", readonly=True)
