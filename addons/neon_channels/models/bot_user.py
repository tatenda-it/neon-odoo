from odoo import models, fields


class BotUser(models.Model):
    _name = 'neon.bot.user'
    _description = 'WhatsApp Bot User Mapping'

    name = fields.Char(string='Name', required=True)
    phone_number = fields.Char(string='WhatsApp Number', required=True,
        help='Full number with country code e.g. +263771234567')
    user_id = fields.Many2one('res.users', string='Odoo User', required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('phone_unique', 'unique(phone_number)', 'This phone number is already mapped to a user.')
    ]
