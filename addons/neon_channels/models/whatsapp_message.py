from odoo import models, fields, api
import logging
import requests

_logger = logging.getLogger(__name__)


class WhatsAppMessage(models.Model):
    _name = 'neon.whatsapp.message'
    _description = 'WhatsApp Message'
    _order = 'create_date desc'

    name = fields.Char(string='Message ID', required=True)
    direction = fields.Selection([
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ], string='Direction', required=True)
    phone_number = fields.Char(string='Phone Number', required=True)
    message_body = fields.Text(string='Message Body')
    message_type = fields.Char(string='Message Type', default='text')
    state = fields.Selection([
        ('received', 'Received'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('failed', 'Failed'),
    ], string='Status', default='received')
    lead_id = fields.Many2one('crm.lead', string='CRM Lead')
    raw_payload = fields.Text(string='Raw Payload')

    @api.model
    def process_incoming(self, message, metadata):
        """Process an incoming WhatsApp message and create/update CRM lead."""
        try:
            msg_id = message.get('id')
            from_number = message.get('from')
            msg_type = message.get('type', 'text')

            # Extract message body
            body = ''
            if msg_type == 'text':
                body = message.get('text', {}).get('body', '')
            elif msg_type == 'image':
                body = '[Image received]'
            elif msg_type == 'document':
                body = '[Document received]'
            elif msg_type == 'audio':
                body = '[Audio received]'
            else:
                body = f'[{msg_type} received]'

            _logger.info('Processing WhatsApp message from %s: %s', from_number, body)

            # Find or create CRM lead
            lead = self._find_or_create_lead(from_number, body)

            # Create message record
            self.create({
                'name': msg_id,
                'direction': 'inbound',
                'phone_number': from_number,
                'message_body': body,
                'message_type': msg_type,
                'state': 'received',
                'lead_id': lead.id if lead else False,
                'raw_payload': str(message),
            })

            _logger.info('WhatsApp message processed successfully for lead: %s', lead.name if lead else 'None')

        except Exception as e:
            _logger.error('Error processing WhatsApp message: %s', str(e))

    def _find_or_create_lead(self, phone_number, message_body):
        """Find existing lead by phone or create a new one."""
        # Search for existing lead with this phone number
        lead = self.env['crm.lead'].search([
            ('phone', '=', phone_number),
            ('stage_id.is_won', '=', False),
        ], limit=1)

        if not lead:
            # Also search mobile field
            lead = self.env['crm.lead'].search([
                ('mobile', '=', phone_number),
                ('stage_id.is_won', '=', False),
            ], limit=1)

        if not lead:
            # Create new lead
            lead = self.env['crm.lead'].create({
                'name': f'WhatsApp Enquiry from {phone_number}',
                'phone': phone_number,
                'description': f'Initial message: {message_body}',
                'source_id': self.env.ref('utm.utm_source_website', raise_if_not_found=False) and
                             self.env.ref('utm.utm_source_website').id or False,
            })
            _logger.info('Created new CRM lead for WhatsApp contact: %s', phone_number)
        else:
            # Log message on existing lead
            lead.message_post(
                body=f'<b>WhatsApp message received:</b><br/>{message_body}',
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )

        return lead

    def send_message(self, to_number, message_body):
        """Send a WhatsApp message via Meta API."""
        config = self.env['neon.whatsapp.config'].search([('active', '=', True)], limit=1)
        if not config:
            _logger.error('No active WhatsApp configuration found.')
            return False

        url = f"https://graph.facebook.com/v25.0/{config.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": message_body},
        }

        try:
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code == 200:
                _logger.info('WhatsApp message sent to %s', to_number)
                return True
            else:
                _logger.error('Failed to send WhatsApp message: %s', response.text)
                return False
        except Exception as e:
            _logger.error('Error sending WhatsApp message: %s', str(e))
            return False
