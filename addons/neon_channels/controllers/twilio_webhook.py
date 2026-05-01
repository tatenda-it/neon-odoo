import json
import logging
import werkzeug

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TwilioWebhookController(http.Controller):

    @http.route('/twilio/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def twilio_webhook(self, **kwargs):
        """Handle incoming Twilio WhatsApp messages."""
        try:
            # Extract message data from Twilio POST
            from_number = kwargs.get('From', '').replace('whatsapp:', '')
            to_number = kwargs.get('To', '').replace('whatsapp:', '')
            body = kwargs.get('Body', '').strip()
            profile_name = kwargs.get('ProfileName', '')

            _logger.info(f'Twilio webhook received from {from_number}: {body}')

            if not from_number or not body:
                return self._twilio_response('')

            # Check if this is a bot command from authorised numbers
            twilio_config = request.env['twilio.config'].sudo().search([], limit=1)
            authorised_numbers = []
            if twilio_config:
                authorised_numbers = [n.strip() for n in re.split(r'[,
]', twilio_config.authorised_numbers or '') if n.strip()]

            if authorised_numbers and from_number in authorised_numbers:
                # Process as bot command
                reply = self._process_bot_command(body, from_number, profile_name)
            else:
                # Process as regular client message — create lead
                reply = self._process_client_message(body, from_number, profile_name)

            return self._twilio_response(reply)

        except Exception as e:
            _logger.error(f'Twilio webhook error: {e}')
            return self._twilio_response('Sorry, an error occurred. Please try again.')

    def _process_client_message(self, body, from_number, profile_name):
        """Create or update CRM lead from client WhatsApp message."""
        env = request.env

        # Check if contact exists
        partner = env['res.partner'].sudo().search([('mobile', 'like', from_number[-9:])], limit=1)

        # Check if lead already exists for this number
        existing_lead = env['crm.lead'].sudo().search([
            ('mobile', 'like', from_number[-9:]),
            ('stage_id.name', 'not in', ['Closed Won', 'Lost'])
        ], limit=1)

        if existing_lead:
            # Add message as note on existing lead
            existing_lead.sudo().message_post(
                body=f'<b>WhatsApp (Twilio):</b> {body}',
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            return f'Message received. Reference: {existing_lead.name}'
        else:
            # Create new lead
            lead_name = f'WhatsApp Enquiry from {profile_name or from_number}'
            lead = env['crm.lead'].sudo().create({
                'name': lead_name,
                'mobile': from_number,
                'contact_name': profile_name or from_number,
                'description': body,
                'source_id': env['utm.source'].sudo().search([('name', 'ilike', 'WhatsApp')], limit=1).id or False,
                'stage_id': env['crm.stage'].sudo().search([('name', '=', 'New')], limit=1).id,
            })
            # Log message
            env['neon.whatsapp.message'].sudo().create({
                'phone_number': from_number,
                'message_body': body,
                'direction': 'inbound',
                'message_type': 'text',
                
                'lead_id': lead.id,
            })
            return f'Thank you for contacting Neon Events Elements. We will respond within 2 hours. Reference: {lead_name}'

    def _process_bot_command(self, body, from_number, profile_name):
        """Process bot commands from authorised team members."""
        env = request.env
        body_lower = body.lower().strip()

        try:
            if body_lower.startswith('lead:'):
                return self._cmd_create_lead(body[5:].strip(), env)
            elif body_lower.startswith('update:'):
                return self._cmd_update_lead(body[7:].strip(), env)
            elif body_lower.startswith('note:'):
                return self._cmd_add_note(body[5:].strip(), env)
            elif body_lower.startswith('task:'):
                return self._cmd_add_task(body[5:].strip(), env)
            elif body_lower.startswith('call:'):
                return self._cmd_log_call(body[5:].strip(), env)
            else:
                return ('Available commands:\n'
                        'Lead: [Client] - [Stage] - [Notes]\n'
                        'Update: [Client] - [Stage] - [Notes]\n'
                        'Note: [Client] - [Message]\n'
                        'Task: [Client] - [Task] - [Assignee]\n'
                        'Call: [Number] - [Notes]')
        except Exception as e:
            _logger.error(f'Bot command error: {e}')
            return f'Error processing command: {str(e)}'

    def _cmd_create_lead(self, args, env):
        parts = [p.strip() for p in args.split('-')]
        if len(parts) < 2:
            return 'Format: Lead: [Client] - [Stage] - [Notes]'
        client = parts[0]
        stage_name = parts[1] if len(parts) > 1 else 'New'
        notes = parts[2] if len(parts) > 2 else ''
        stage = env['crm.stage'].sudo().search([('name', 'ilike', stage_name)], limit=1)
        lead = env['crm.lead'].sudo().create({
            'name': f'{client} - Enquiry',
            'partner_name': client,
            'description': notes,
            'stage_id': stage.id if stage else env['crm.stage'].sudo().search([('name', '=', 'New')], limit=1).id,
        })
        return f'Lead created: {client} - {stage.name if stage else "New"}'

    def _cmd_update_lead(self, args, env):
        parts = [p.strip() for p in args.split('-')]
        if len(parts) < 2:
            return 'Format: Update: [Client] - [Stage] - [Notes]'
        client = parts[0]
        stage_name = parts[1]
        notes = parts[2] if len(parts) > 2 else ''
        lead = env['crm.lead'].sudo().search([('name', 'ilike', client)], limit=1)
        if not lead:
            return f'Client not found: {client}. Reply with CONFIRM to create new lead.'
        stage = env['crm.stage'].sudo().search([('name', 'ilike', stage_name)], limit=1)
        if stage:
            lead.sudo().write({'stage_id': stage.id})
        if notes:
            lead.sudo().message_post(body=f'<b>Bot update:</b> {notes}', message_type='comment', subtype_xmlid='mail.mt_note')
        return f'Updated: {lead.name} - {stage.name if stage else stage_name}'

    def _cmd_add_note(self, args, env):
        parts = [p.strip() for p in args.split('-', 1)]
        if len(parts) < 2:
            return 'Format: Note: [Client] - [Message]'
        client, message = parts[0], parts[1]
        lead = env['crm.lead'].sudo().search([('name', 'ilike', client)], limit=1)
        if not lead:
            return f'Client not found: {client}'
        lead.sudo().message_post(body=f'<b>Bot note:</b> {message}', message_type='comment', subtype_xmlid='mail.mt_note')
        return f'Note added to: {lead.name}'

    def _cmd_add_task(self, args, env):
        parts = [p.strip() for p in args.split('-')]
        if len(parts) < 2:
            return 'Format: Task: [Client] - [Task] - [Assignee]'
        client = parts[0]
        task = parts[1]
        lead = env['crm.lead'].sudo().search([('name', 'ilike', client)], limit=1)
        if not lead:
            return f'Client not found: {client}'
        activity_type = env['mail.activity.type'].sudo().search([('name', 'ilike', 'To-Do')], limit=1)
        if activity_type:
            from datetime import date, timedelta
            env['mail.activity'].sudo().create({
                'res_model_id': env['ir.model'].sudo().search([('model', '=', 'crm.lead')]).id,
                'res_id': lead.id,
                'activity_type_id': activity_type.id,
                'summary': task,
                'date_deadline': (date.today() + timedelta(days=1)).strftime('%Y-%m-%d'),
                'user_id': env.uid,
            })
        return f'Task created: {task} on {lead.name}'

    def _cmd_log_call(self, args, env):
        parts = [p.strip() for p in args.split('-', 1)]
        phone = parts[0]
        notes = parts[1] if len(parts) > 1 else ''
        lead = env['crm.lead'].sudo().create({
            'name': f'Call from {phone}',
            'mobile': phone,
            'description': notes,
            'stage_id': env['crm.stage'].sudo().search([('name', '=', 'New')], limit=1).id,
        })
        return f'Call logged: {phone} - Lead created'

    def _twilio_response(self, message):
        """Return TwiML response."""
        if message:
            twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{message}</Message>
</Response>'''
        else:
            twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return werkzeug.wrappers.Response(twiml, content_type='text/xml', status=200)
