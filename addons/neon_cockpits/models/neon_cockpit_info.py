# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonCockpitInfo(models.Model):
    """Single-source money-rules surface for the cockpits. VAT is READ from the
    one shared account.tax record (neon_finance.tax_vat_15_5_sale) via a related
    field - never hard-coded per screen. Deferred surfaces are flagged here and
    contribute NO live figures."""

    _name = "neon.cockpit.info"
    _description = "Neon Cockpit - Money Rules & Deferred Surfaces"

    name = fields.Char(default="Neon Money Rules", required=True)

    # --- VAT: the ONE shared record, referenced everywhere ---
    vat_tax_id = fields.Many2one(
        "account.tax", string="Shared VAT Tax Record",
        help="The single account.tax all surfaces reference. Do NOT hard-code "
             "the rate anywhere - read it from here.")
    vat_rate = fields.Float(
        string="VAT Rate (%)", related="vat_tax_id.amount", readonly=True,
        help="Resolved from the shared tax record (not hard-coded).")
    vat_group_id = fields.Many2one(
        "account.tax.group", related="vat_tax_id.tax_group_id", readonly=True)

    # --- Currency posture ---
    currency_primary_id = fields.Many2one(
        "res.currency", string="Primary Currency (US$)")
    currency_mirror_label = fields.Char(
        string="Mirror Currency", default="ZiG (ZWG)", readonly=True)
    zar_note = fields.Char(
        default="ZAR is confined to the restricted SA account only (deferred).",
        readonly=True)

    # --- Terms / compliance ---
    zimra_registration = fields.Char(
        string="ZIMRA Registration", help="Shown on invoices; from the ZIMRA cert.")
    payment_terms_days = fields.Integer(
        string="Default Payment Terms (days)", default=7)
    append_only_note = fields.Char(
        default="Posted ledger records are append-only (not deletable).",
        readonly=True)

    # --- Deferred surfaces (shown as deferred; NO live balance) ---
    undeposited_funds_deferred = fields.Boolean(
        string="Undeposited Funds - DEFERRED", default=True, readonly=True)
    restricted_sa_tier_deferred = fields.Boolean(
        string="Restricted Directors SA Tier - DEFERRED", default=True,
        readonly=True)
    deferred_note = fields.Char(
        default="DEFERRED - not yet built; contributes NO live balance.",
        readonly=True)
