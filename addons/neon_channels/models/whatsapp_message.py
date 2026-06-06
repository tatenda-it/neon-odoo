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
    # WA-0 audit -- set on a privileged (mapped bot.user) Copilot turn.
    bot_user_id = fields.Many2one(
        'neon.bot.user', string='Bot User',
        help='Set when the sender is a mapped team member (privileged '
             'WhatsApp Copilot turn).')
    variant = fields.Char(
        string='Resolved Variant',
        help='Role variant resolved for a privileged turn '
             '(director/sales/bookkeeper/lead_tech).')
    provider_key = fields.Char(
        string='AI Provider',
        help='Chat provider used for the assistant reply (google/groq).')

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

    # ==================================================================
    # WA-0 -- inbound router + cta_url outbound
    # ==================================================================
    @api.model
    def _extract_body(self, message, msg_type):
        """Pull a text body out of a Meta inbound message of any type."""
        if msg_type == 'text':
            return message.get('text', {}).get('body', '')
        if msg_type == 'interactive':
            inter = message.get('interactive', {})
            for k in ('button_reply', 'list_reply'):
                if inter.get(k):
                    return inter[k].get('title') or inter[k].get('id') or ''
            return '[interactive]'
        return f'[{msg_type} received]'

    @api.model
    def handle_inbound(self, message, metadata):
        """WA-0 inbound router. A mapped sender (neon.bot.user) gets a
        PRIVILEGED WhatsApp Copilot turn under THEIR identity. An unmapped
        sender falls through to the existing raw-lead intake
        (process_incoming), UNCHANGED -- no privileged access."""
        from .wa_copilot import WhatsAppCopilotService  # noqa: PLC0415
        from .phone_utils import to_e164  # noqa: PLC0415
        svc = WhatsAppCopilotService(self.env)
        # WA-1 boundary normalization: canonicalise the sender ONCE here so
        # everything downstream (storage, resolve, history match, lead-
        # intake) sees E.164 and a plain == works. raw_from is kept for the
        # outbound SEND (Meta's exact format, already proven deliverable --
        # don't risk a send-format regression). Mutate a COPY so the
        # caller's dict is untouched.
        raw_from = message.get('from')
        from_e164 = to_e164(raw_from)
        message = dict(message)
        message['from'] = from_e164
        # WA-0 fix: delegate to the SINGLE resolver (RBAC-defensive
        # >1-match -> UNRESOLVED). One source of truth.
        bot_user = svc.resolve(from_e164)
        if not bot_user:
            # Unmapped -> raw-lead intake; it reads message['from'] (now
            # canonical), so the created crm.lead phone is E.164 too.
            return self.process_incoming(message, metadata)

        msg_type = message.get('type', 'text')
        # WA-1: pull the tapped reply id (button_reply / list_reply) so we
        # ROUTE by id, not by the echoed title. The title is kept for the
        # stored row body + as the pick-back label.
        reply_id = reply_title = None
        if msg_type == 'interactive':
            inter = message.get('interactive', {}) or {}
            for k in ('button_reply', 'list_reply'):
                if inter.get(k):
                    reply_id = inter[k].get('id')
                    reply_title = inter[k].get('title')
                    break
        body = self._extract_body(message, msg_type)
        inbound = self.sudo().create({
            'name': message.get('id') or f'wa-in-{from_e164}',
            'direction': 'inbound',
            'phone_number': from_e164,
            'message_body': body,
            'message_type': msg_type,
            'state': 'received',
            'bot_user_id': bot_user.id,
            'raw_payload': str(message),
        })

        variant = False
        provider_key = self.env['ir.config_parameter'].sudo().get_param(
            'neon_channels.whatsapp_provider_key', 'google')
        try:
            variant = svc.variant_for(bot_user.user_id)
            if reply_id:
                # WA-1 Piece B -- a tap-back. Route the payload id.
                result = svc.handle_tap(bot_user, reply_id, reply_title)
            elif svc.wants_menu(body):
                # WA-1 Slice 3 -- deterministic capability-menu intent.
                result = svc.build_menu_result(bot_user)
            else:
                result = svc.run_turn(bot_user, body,
                                      exclude_message_id=inbound.id)
        except Exception as e:  # noqa: BLE001
            _logger.error('WhatsApp Copilot turn failed: %s', e,
                          exc_info=True)
            result = {'text': 'Sorry -- something went wrong handling '
                              'that. Please try again.', 'cta_url': None,
                      'interactive': None}

        reply = result.get('text') or 'Done.'
        cta = result.get('cta_url')
        interactive = result.get('interactive')
        # WA-1 Piece C -- a structured send ALWAYS has a text fallback.
        if interactive:
            sent_via = self.sudo().send_interactive_or_text(
                raw_from, interactive,
                result.get('text_fallback') or reply, cta_url=cta)
        elif cta:
            self.sudo().send_cta_url(raw_from, reply, 'Confirm in Odoo', cta)
            sent_via = 'cta_url'
        else:
            self.sudo().send_message(raw_from, reply)
            sent_via = 'text'

        # Outbound audit row. message_type reflects the path actually used;
        # sent_via is logged AND appended to the stored body so the
        # fallback path is auditable without a new column (method-only).
        body_suffix = (f'\n[cta_url] {cta}' if cta else '') \
            + f'\n[sent_via:{sent_via}]'
        self.sudo().create({
            'name': f'wa-out-{from_e164}',
            'direction': 'outbound',
            'phone_number': from_e164,
            'message_body': reply + body_suffix,
            'message_type': 'interactive' if (interactive or cta) else 'text',
            'state': 'sent',
            'bot_user_id': bot_user.id,
            'variant': variant or False,
            # WA-0: record the provider that ACTUALLY served (may be the
            # Groq fallback when Gemini 503'd), not just the configured one.
            'provider_key': result.get('provider_key') or provider_key,
        })
        return True

    def send_cta_url(self, to_number, body_text, display_text, url):
        """WA-0 outbound interactive cta_url -- a single URL button. ONE
        fixed shape (NOT the deferred buttons/list/cards renderer). Carries
        the confirm-in-Odoo deep-link. Allowed as a reply within Meta's
        24h customer-service window (no template needed)."""
        config = self.env['neon.whatsapp.config'].sudo().search(
            [('active', '=', True)], limit=1)
        if not config:
            _logger.error('No active WhatsApp configuration found.')
            return False
        api_url = (f"https://graph.facebook.com/v25.0/"
                   f"{config.phone_number_id}/messages")
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": (body_text or '')[:1024]},
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": (display_text or 'Open')[:20],
                        "url": url,
                    },
                },
            },
        }
        try:
            response = requests.post(api_url, json=payload, headers=headers)
            if response.status_code == 200:
                _logger.info('WhatsApp cta_url sent to %s', to_number)
                return True
            _logger.error('Failed to send WhatsApp cta_url: %s',
                          response.text)
            return False
        except Exception as e:  # noqa: BLE001
            _logger.error('Error sending WhatsApp cta_url: %s', str(e))
            return False

    # ==================================================================
    # WA-1 -- interactive renderer (reply buttons + list) + fallback
    # ==================================================================
    def _post_interactive(self, to_number, interactive, label='interactive'):
        """Shared Meta Cloud API interactive sender. ``interactive`` is
        the full 'interactive' object (type + body + action). Returns
        True on a Meta 200, False on any error/non-200 so the caller can
        fall back to text. Allowed inside Meta's 24h customer-service
        window (these are replies to an inbound message)."""
        config = self.env['neon.whatsapp.config'].sudo().search(
            [('active', '=', True)], limit=1)
        if not config:
            _logger.error('No active WhatsApp configuration found.')
            return False
        api_url = (f"https://graph.facebook.com/v25.0/"
                   f"{config.phone_number_id}/messages")
        headers = {
            "Authorization": f"Bearer {config.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "interactive",
            "interactive": interactive,
        }
        try:
            response = requests.post(api_url, json=payload, headers=headers)
            if response.status_code == 200:
                _logger.info('WhatsApp %s sent to %s', label, to_number)
                return True
            _logger.error('Failed to send WhatsApp %s: %s',
                          label, response.text)
            return False
        except Exception as e:  # noqa: BLE001
            _logger.error('Error sending WhatsApp %s: %s', label, str(e))
            return False

    def send_buttons(self, to_number, body_text, buttons):
        """WA-1 Slice 1 -- reply buttons (interactive type 'button',
        MAX 3). ``buttons`` = [{'id','title'}]; title clipped to Meta's
        20-char limit, id to 256."""
        btns = [{"type": "reply",
                 "reply": {"id": (b["id"] or "")[:256],
                           "title": (b.get("title") or "")[:20]}}
                for b in (buttons or [])[:3]]
        interactive = {
            "type": "button",
            "body": {"text": (body_text or "")[:1024]},
            "action": {"buttons": btns},
        }
        return self._post_interactive(to_number, interactive, 'buttons')

    def send_list(self, to_number, body_text, button_text, sections):
        """WA-1 Slice 2 -- list message (interactive type 'list', up to
        10 rows across sections). ``sections`` =
        [{'title','rows':[{'id','title','description'}]}]. Row title <=24,
        description <=72, the open-list button <=20 (Meta limits)."""
        out_sections = []
        total = 0
        for sec in (sections or []):
            rows = []
            for r in (sec.get('rows') or []):
                if total >= 10:
                    break
                row = {"id": (r["id"] or "")[:200],
                       "title": (r.get("title") or "")[:24]}
                if r.get("description"):
                    row["description"] = r["description"][:72]
                rows.append(row)
                total += 1
            if rows:
                out_sections.append(
                    {"title": (sec.get("title") or "")[:24], "rows": rows})
            if total >= 10:
                break
        interactive = {
            "type": "list",
            "body": {"text": (body_text or "")[:1024]},
            "action": {"button": (button_text or "Options")[:20],
                       "sections": out_sections},
        }
        return self._post_interactive(to_number, interactive, 'list')

    def send_interactive_or_text(self, to_number, interactive,
                                 text_fallback, cta_url=None):
        """WA-1 Piece C -- MANDATORY text fallback. Try the structured
        send; if Meta rejects it (or it errors / is skipped), send the
        proven WA-0 text (or text+cta_url) instead -- a button/list
        failure NEVER means no reply. Returns the path actually used:
        'buttons' | 'list' | 'cta_url' | 'text'."""
        kind = (interactive or {}).get("kind")
        ok = False
        if kind == "buttons":
            ok = self.send_buttons(
                to_number, interactive.get("body", ""),
                interactive.get("buttons") or [])
        elif kind == "list":
            ok = self.send_list(
                to_number, interactive.get("body", ""),
                interactive.get("button_text", "Options"),
                interactive.get("sections") or [])
        if ok:
            return kind
        _logger.warning(
            'WA interactive(%s) send failed/unsupported -- falling back '
            'to text for %s', kind, to_number)
        if cta_url:
            self.send_cta_url(
                to_number, text_fallback or 'Please confirm in Odoo.',
                'Confirm in Odoo', cta_url)
            return 'cta_url'
        self.send_message(to_number, text_fallback or 'Done.')
        return 'text'
