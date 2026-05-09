from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class TwilioConfig(models.Model):
    _name = 'twilio.config'
    _description = 'Twilio Configuration'

    name = fields.Char(string='Configuration Name', required=True, default='Neon Twilio Config')
    account_sid = fields.Char(string='Account SID', required=True)
    auth_token = fields.Char(string='Auth Token', required=True)
    phone_number = fields.Char(string='Twilio Phone Number', help='E.g. +14758897488')
    whatsapp_number = fields.Char(string='WhatsApp Sandbox Number', help='E.g. +14155238886')
    authorised_numbers = fields.Text(
        string='Authorised Bot Numbers',
        help='Comma-separated list of phone numbers allowed to use the WhatsApp bot. E.g. +263771234567, +263772345678'
    )
    active = fields.Boolean(default=True)

    def test_connection(self):
        """Test Twilio API connection."""
        try:
            import urllib.request
            import base64
            url = f'https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}.json'
            credentials = base64.b64encode(f'{self.account_sid}:{self.auth_token}'.encode()).decode()
            req = urllib.request.Request(url, headers={'Authorization': f'Basic {credentials}'})
            urllib.request.urlopen(req)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': 'Twilio connection is working correctly.',
                    'type': 'success',
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Connection Failed',
                    'message': str(e),
                    'type': 'danger',
                }
            }
