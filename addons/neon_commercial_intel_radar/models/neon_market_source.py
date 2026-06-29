# -*- coding: utf-8 -*-
from odoo import api, fields, models


class NeonMarketSource(models.Model):
    """A subscribed market-signal source. Adding one is config, not code.
    Yield counters (brief s11a) turn source selection into evidence."""

    _name = "neon.market.source"
    _description = "Neon Market Radar Source"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    source_type = fields.Selection(
        [
            ("tender_alert", "Tender Alert"),
            ("award", "Award Notice"),
            ("news", "News / Programme Signal"),
            ("mailing_list", "Supplier Mailing List"),
        ],
        string="Source Type",
        required=True,
        default="tender_alert",
    )
    ingest_method = fields.Selection(
        [
            ("email_alias", "Email alert -> inbox alias"),
            ("public_poll", "Public-bulletin poll"),
        ],
        string="Ingest Method",
        required=True,
        default="email_alias",
    )
    email_match = fields.Char(
        string="Sender Match",
        help="Sender address or domain used to attribute inbound mail to this "
             "source (substring match on the From address).",
    )
    tos_status = fields.Selection(
        [
            ("cleared", "Cleared"),
            ("check", "Needs Check"),
            ("restricted", "Restricted"),
        ],
        string="ToS Status",
        default="check",
        required=True,
        help="Governance flag. 'public_poll' sources must be 'cleared' against "
             "the portal's written terms before the poller is activated.",
    )
    notes = fields.Text()

    signal_ids = fields.One2many(
        "neon.market.signal", "source_id", string="Signals")

    # --- s11a yield counters (evidence-driven source pruning) ---
    signal_count = fields.Integer(
        compute="_compute_yield", store=False)
    event_relevant_count = fields.Integer(
        compute="_compute_yield", store=False)
    promoted_count = fields.Integer(
        compute="_compute_yield", store=False)

    @api.depends("signal_ids", "signal_ids.state", "signal_ids.event_relevant")
    def _compute_yield(self):
        for src in self:
            sigs = src.signal_ids
            src.signal_count = len(sigs)
            src.event_relevant_count = len(sigs.filtered("event_relevant"))
            src.promoted_count = len(
                sigs.filtered(lambda s: s.state == "promoted"))

    def action_radar_poll_sample(self):
        """Test button (public_poll sources): run the eGP parser on the built-in
        sample fixture. No live HTTP. Creates RAW signals attributed to self."""
        Signal = self.env["neon.market.signal"]
        for src in self:
            Signal._neon_radar_parse_egp_bulletin(
                Signal._neon_radar_sample_text(), src)
        return True
