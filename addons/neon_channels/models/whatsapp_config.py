from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class WhatsAppConfig(models.Model):
    _name = 'neon.whatsapp.config'
    _description = 'WhatsApp Business API Configuration'

    name = fields.Char(string='Configuration Name', required=True, default='Neon WhatsApp Config')
    phone_number_id = fields.Char(string='Phone Number ID', required=True)
    whatsapp_business_account_id = fields.Char(string='WhatsApp Business Account ID', required=True)
    access_token = fields.Char(string='Access Token', required=True)
    verify_token = fields.Char(string='Verify Token', required=True, default='neon_whatsapp_webhook_2026')
    webhook_url = fields.Char(string='Webhook URL', readonly=True, compute='_compute_webhook_url')
    active = fields.Boolean(default=True)

    @api.depends('phone_number_id')
    def _compute_webhook_url(self):
        for rec in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            rec.webhook_url = f"{base_url}/whatsapp/webhook"

    def action_test_connection(self):
        """Test the WhatsApp API connection."""
        import requests
        url = f"https://graph.facebook.com/v25.0/{self.phone_number_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Successful',
                        'message': 'WhatsApp API connection is working correctly.',
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Connection Failed',
                        'message': f'Error: {response.text}',
                        'type': 'danger',
                    }
                }
        except Exception as e:
            _logger.error('WhatsApp connection test error: %s', str(e))
