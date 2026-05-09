import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

VERIFY_TOKEN = "neon_whatsapp_webhook_2026"


class WhatsAppWebhookController(http.Controller):

    @http.route('/whatsapp/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def webhook_verify(self, **kwargs):
        """Handle Meta webhook verification challenge."""
        mode = kwargs.get('hub.mode')
        token = kwargs.get('hub.verify_token')
        challenge = kwargs.get('hub.challenge')

        if mode == 'subscribe' and token == VERIFY_TOKEN:
            _logger.info('WhatsApp webhook verified successfully.')
            return request.make_response(challenge)
        
        _logger.warning('WhatsApp webhook verification failed.')
        return request.make_response('Forbidden', status=403)

    @http.route('/whatsapp/webhook', type='json', auth='public', methods=['POST'], csrf=False)
    def webhook_receive(self, **kwargs):
        """Handle incoming WhatsApp messages from Meta."""
        try:
            data = json.loads(request.httprequest.data)
            _logger.info('WhatsApp webhook received: %s', data)

            entries = data.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    messages = value.get('messages', [])
                    for message in messages:
                        request.env['neon.whatsapp.message'].sudo().process_incoming(
                            message, value.get('metadata', {})
                        )
        except Exception as e:
            _logger.error('WhatsApp webhook error: %s', str(e))

        return 'OK'
