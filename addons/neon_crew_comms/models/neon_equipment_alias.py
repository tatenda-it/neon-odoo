# -*- coding: utf-8 -*-
"""Resolver v2 — team-slang alias store (WA-12 matcher normalise step).

A maintainable, UI-reviewable map of team slang -> a product, a category, or a
canonical search TERM, so the resolver funnel can expand "blinder" / "cans" /
"screen" before matching. Every row is PROPOSED on seed and only an explicitly
CONFIRMED row is applied by the matcher -- Robin confirms each (never
auto-assumed); an entry he can't confirm stays 'open'.

Three target kinds (use exactly one):
  * product_template_id -> resolve the slang straight to that product
    ("totem" -> TRUSS TOTEM WITH BASE).
  * category_id          -> scope the slang to a family ("screen" -> Visual).
  * term                 -> substitute a canonical phrase, then match normally
    ("cans" -> "led can").
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NeonEquipmentAlias(models.Model):
    _name = "neon.equipment.alias"
    _description = "Equipment Slang Alias (WA-12 matcher)"
    _order = "state, phrase"
    _rec_name = "phrase"

    phrase = fields.Char(
        required=True, index=True,
        help="The team slang, lowercased ('blinder', 'cans', 'screen'). "
        "Matched whole-word on the inbound item text.")
    product_template_id = fields.Many2one(
        "product.template", ondelete="cascade",
        help="Resolve the slang directly to THIS product.")
    category_id = fields.Many2one(
        "neon.equipment.category", ondelete="cascade",
        help="Scope the slang to this family.")
    term = fields.Char(
        help="Canonical search phrase to substitute for the slang before "
        "matching (e.g. 'cans' -> 'led can').")
    state = fields.Selection(
        [("proposed", "Proposed"), ("confirmed", "Confirmed"),
         ("open", "Open (needs Robin)")],
        required=True, default="proposed", index=True,
        help="Only CONFIRMED aliases are applied by the matcher.")
    note = fields.Char(help="Why proposed / the open question for Robin.")

    _sql_constraints = [
        ("phrase_uniq", "unique(phrase)", "One alias row per slang phrase."),
    ]

    # `phrase` (required, always present on create) is included so the
    # constraint fires even when a row is created with NO target supplied --
    # @api.constrains only triggers on fields actually present in the vals, so
    # a bare {'phrase': ...} would otherwise skip the check entirely.
    @api.constrains("phrase", "product_template_id", "category_id", "term")
    def _check_one_target(self):
        for r in self:
            n = bool(r.product_template_id) + bool(r.category_id) + bool(r.term)
            if n != 1:
                raise ValidationError(_(
                    "Alias %r must have EXACTLY ONE target (a product, a "
                    "category, or a term).") % r.phrase)

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_mark_open(self):
        self.write({"state": "open"})

    # The WA-12 matcher reads the CONFIRMED alias set (_r2_alias_map). Bust the
    # registry cache cross-worker on any change so a freshly-confirmed alias is
    # live without a restart (the per-method clear_cache would only clear this
    # worker, leaving a confirm dead on the others).
    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self.env.registry.clear_cache()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self.env.registry.clear_cache()
        return res

    def unlink(self):
        res = super().unlink()
        self.env.registry.clear_cache()
        return res
