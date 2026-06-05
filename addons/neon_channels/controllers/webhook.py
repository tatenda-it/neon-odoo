import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# RED #2 (WA-0): the live verify token is read from the active
# neon.whatsapp.config. This module-level value is a fallback ONLY, used
# if no config row exists yet on a fresh DB during setup.
_DEFAULT_VERIFY_TOKEN = "neon_whatsapp_webhook_2026"

# RED #1 (WA-0): Meta app secret for X-Hub-Signature-256 verification.
_APP_SECRET_PARAM = "neon_channels.whatsapp_app_secret"


def _hmac_matches(secret, raw_body, header):
    """Pure, request-free HMAC check (so the smoke can prove a genuinely
    Meta-signed payload PASSES, not just that a wrong one fails). True iff
    ``header`` == 'sha256=' + HMAC_SHA256(secret, raw_body). With no
    secret -> True (fail-open during rollout; caller logs)."""
    if not secret:
        return True
    if not header or not header.startswith('sha256='):
        return False
    key = secret.encode('utf-8') if isinstance(secret, str) else secret
    expected = hmac.new(key, raw_body or b'', hashlib.sha256).hexdigest()
    provided = header.split('=', 1)[1].strip()
    return hmac.compare_digest(expected, provided)


class WhatsAppWebhookController(http.Controller):

    def _verify_token(self):
        cfg = request.env["neon.whatsapp.config"].sudo().search(
            [("active", "=", True)], limit=1)
        return (cfg.verify_token or _DEFAULT_VERIFY_TOKEN) if cfg \
            else _DEFAULT_VERIFY_TOKEN

    @http.route('/whatsapp/webhook', type='http', auth='public',
                methods=['GET'], csrf=False)
    def webhook_verify(self, **kwargs):
        """Meta webhook verification challenge. Token now read from
        config (RED #2), compared constant-time."""
        mode = kwargs.get('hub.mode')
        token = kwargs.get('hub.verify_token') or ''
        challenge = kwargs.get('hub.challenge') or ''
        if mode == 'subscribe' and token and hmac.compare_digest(
                token, self._verify_token()):
            _logger.info('WhatsApp webhook verified successfully.')
            return request.make_response(challenge)
        _logger.warning('WhatsApp webhook verification failed.')
        return request.make_response('Forbidden', status=403)

    def _signature_ok(self, raw_body):
        """RED #1: verify X-Hub-Signature-256 = sha256= HMAC over the
        EXACT raw bytes received (not a re-serialised body). Enforced
        when the app secret is configured; if it is NOT set we log loudly
        and ALLOW so inbound keeps flowing during rollout. Prod MUST set
        neon_channels.whatsapp_app_secret to actually enforce."""
        secret = request.env['ir.config_parameter'].sudo().get_param(
            _APP_SECRET_PARAM)
        if not secret:
            _logger.warning(
                'WhatsApp POST NOT signature-verified: %s is unset. '
                'Set it to enforce.', _APP_SECRET_PARAM)
            return True
        header = request.httprequest.headers.get(
            'X-Hub-Signature-256', '') or ''
        ok = _hmac_matches(secret, raw_body, header)
        if not ok:
            _logger.warning(
                'WhatsApp POST rejected: signature missing/mismatch.')
        return ok

    @http.route('/whatsapp/webhook', type='http', auth='public',
                methods=['POST'], csrf=False)
    def webhook_receive(self, **kwargs):
        """Handle incoming WhatsApp messages. type='http' so we control
        the raw body (for HMAC) + the response status."""
        raw = request.httprequest.get_data()  # exact received bytes
        if not self._signature_ok(raw):
            return request.make_response('Forbidden', status=403)
        try:
            data = json.loads(raw or b'{}')
            for entry in data.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    for message in value.get('messages', []):
                        request.env['neon.whatsapp.message'].sudo()\
                            .handle_inbound(message, value)
        except Exception as e:  # noqa: BLE001
            _logger.error('WhatsApp webhook error: %s', e, exc_info=True)
        return request.make_response('OK')
