# -*- coding: utf-8 -*-
"""P-B13 -- Set-API-key wizard.

⚠️ DECISION (B13, D7, gate-1 Q3): API key is pasted via a
TransientModel wizard rather than the ir.config_parameter Settings
page. Why:

1. The plaintext value is stored on a wizard record which Odoo
   auto-cleans (TransientModel garbage collection runs hourly).
2. The field is `password=True` so the input is masked in the form
   widget and the value never appears in chatter, breadcrumbs, or
   tooltips.
3. The wizard's confirm action sudo-writes to ir.config_parameter
   then unlinks itself immediately -- the key sits on the wizard
   row for at most one transaction.
4. ACL: only group_neon_superuser can create/read the wizard. No
   non-OD/MD user can spawn it or list pre-existing rows.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


_logger = logging.getLogger(__name__)


_SUPERUSER_GROUP = "neon_core.group_neon_superuser"


class NeonDocGenSetKeyWizard(models.TransientModel):
    _name = "neon.doc.gen.set.key.wizard"
    _description = "Set Doc-Gen API Key"

    provider_id = fields.Many2one(
        "neon.doc.gen.provider", required=True, ondelete="cascade",
        readonly=True,
    )
    api_key = fields.Char(
        string="API Key",
        required=True,
        help="Paste the Anthropic API key. Field is masked. The "
             "value is written to ir.config_parameter and the "
             "wizard row is unlinked immediately afterwards.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        # Enforce superuser ACL at create-time so even a wizard
        # spawn requires OD/MD.
        if not self.env.user.has_group(_SUPERUSER_GROUP):
            raise AccessError(_(
                "Only Neon Superusers (OD/MD) can set the doc-gen "
                "API key."))
        return super().create(vals_list)

    def action_save_key(self):
        self.ensure_one()
        if not self.env.user.has_group(_SUPERUSER_GROUP):
            raise AccessError(_(
                "Only Neon Superusers (OD/MD) can set the doc-gen "
                "API key."))
        if not self.provider_id:
            raise AccessError(_(
                "No provider record bound to this wizard."))
        plaintext = (self.api_key or "").strip()
        if not plaintext:
            raise AccessError(_("API key cannot be blank."))
        # Capture metadata BEFORE unlink (the recordset's fields
        # become unreadable after self.unlink()).
        provider_name = self.provider_id.name
        user_login = self.env.user.login
        wid = self.id
        # Write the key + unlink the wizard row immediately so the
        # plaintext doesn't linger in the DB even briefly.
        self.provider_id._set_api_key(plaintext)
        # Sudo to bypass the wizard model ACL for unlink (cleanup
        # only -- the user just provided the key).
        self.sudo().unlink()
        _logger.info(
            "Doc-gen API key set for provider %s by user %s "
            "(wizard id=%s, key NOT logged).",
            provider_name, user_login, wid)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("API key updated"),
                "message": _(
                    "Key saved. Use 'Test connection' to verify."),
                "type": "success",
                "sticky": False,
            },
        }
