# -*- coding: utf-8 -*-
"""M6 -- ZiG-USD Rate admin wizard.

TransientModel that reads the current rate from ir.config_parameter
on open and writes back on save. Single-action UX: open via
Settings -> Neon -> ZiG-USD Rate -> form -> change rate -> Save
-> ir.config_parameter updated + wizard closes.

⚠️ DECISION (M6, marker inline): TransientModel + ir.config_parameter
backing rather than a persistent singleton model. Pattern matches
Odoo's stock res.config.settings wizards. No new permanent table;
no record-rule plumbing; no migration to maintain. The four
parameter keys live in data/zig_rate_config.xml (noupdate=1).

⚠️ DECISION (M6, marker inline): on save, three keys are stamped:
* zig_usd_rate_manual    = new value (single source of truth)
* zig_usd_rate_source    = 'manual'
* zig_usd_rate_updated_at = UTC ISO datetime (stored audit per
  the timezone gate-1 lock; the cash-tile subtitle renders this
  via _format_harare_timestamp for display).
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


_CONFIG_KEY_RATE = "neon_dashboard.zig_usd_rate_manual"
_CONFIG_KEY_SOURCE = "neon_dashboard.zig_usd_rate_source"
_CONFIG_KEY_UPDATED_AT = "neon_dashboard.zig_usd_rate_updated_at"


class NeonDashboardZigRateWizard(models.TransientModel):
    _name = "neon.dashboard.zig.rate.wizard"
    _description = "ZiG-USD Manual Rate (admin)"

    rate = fields.Float(
        required=True,
        digits=(12, 4),
        help="Rate in ZiG per 1 USD. Example: 25.50 means 1 USD = "
        "25.50 ZiG. The cash KPI tile uses this to convert ZiG "
        "journal balances to USD-equivalent.",
    )
    updated_at_display = fields.Char(
        string="Last Updated",
        readonly=True,
        help="When the rate was last changed (Africa/Harare).",
    )
    source_display = fields.Char(
        string="Source",
        readonly=True,
        help="Always 'manual' once a rate is set. Reserved values "
        "'rbz' / 'unset' exist for forward-compat but are not "
        "currently used.",
    )

    @api.model
    def default_get(self, fields_list):
        """Read current ir.config_parameter values into the wizard
        so the form opens populated with the live rate."""
        defaults = super().default_get(fields_list)
        Config = self.env["ir.config_parameter"].sudo()
        raw_rate = Config.get_param(_CONFIG_KEY_RATE, "0") or "0"
        try:
            defaults["rate"] = float(raw_rate)
        except (TypeError, ValueError):
            defaults["rate"] = 0.0
        updated_iso = Config.get_param(_CONFIG_KEY_UPDATED_AT, "") or ""
        defaults["updated_at_display"] = self._format_updated_at(updated_iso)
        defaults["source_display"] = Config.get_param(
            _CONFIG_KEY_SOURCE, "unset") or "unset"
        return defaults

    def _format_updated_at(self, iso_string):
        """Render the stored UTC ISO timestamp in Africa/Harare for
        display. Falls back to '(never set)' on empty / parse error."""
        if not iso_string:
            return _("(never set)")
        try:
            dt = fields.Datetime.from_string(iso_string)
        except Exception:  # noqa: BLE001
            try:
                # ISO with 'T' separator from .isoformat() at save time
                from datetime import datetime
                dt = datetime.fromisoformat(iso_string.split(".")[0])
            except Exception:  # noqa: BLE001
                return iso_string
        Dashboard = self.env["neon.dashboard"]
        return Dashboard._format_harare_timestamp(dt) + " (Harare)"

    def action_save(self):
        """Stamp ir.config_parameter and close the wizard."""
        self.ensure_one()
        if self.rate < 0:
            raise ValidationError(_(
                "Rate must be non-negative. Use 0 to clear the "
                "override (ZiG will then be excluded from USD-"
                "equivalent totals)."))
        Config = self.env["ir.config_parameter"].sudo()
        # Single source of truth for the rate.
        Config.set_param(_CONFIG_KEY_RATE, str(self.rate))
        # Source: 'manual' if a real rate is set, 'unset' if zeroed.
        new_source = "manual" if self.rate > 0 else "unset"
        Config.set_param(_CONFIG_KEY_SOURCE, new_source)
        # Audit timestamp -- UTC per gate-1 stored-audit lock.
        Config.set_param(
            _CONFIG_KEY_UPDATED_AT,
            fields.Datetime.now().isoformat(),
        )
        _logger.info(
            "ZiG-USD rate updated by %s: rate=%s source=%s",
            self.env.user.login, self.rate, new_source,
        )
        return {"type": "ir.actions.act_window_close"}
