# -*- coding: utf-8 -*-
"""neon.kb.category -- top-level KB taxonomy.

Phase 7d M1. 5 categories by capability cluster (Audio /
Lighting / Video / Safety / Admin). M2's article model
points here; article_count compute lights up automatically
once the article model is in the registry (defensive
env.get pattern).
"""
from odoo import api, fields, models, _


class NeonKBCategory(models.Model):
    _name = "neon.kb.category"
    _description = "Neon Knowledge Base Category"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence asc, name asc"

    name = fields.Char(
        required=True,
        tracking=True,
        translate=True,
    )
    code = fields.Char(
        required=True,
        help="Slug-friendly identifier (e.g. 'audio'). "
             "Stable across renames; used by URL routes "
             "and cross-module references.",
    )
    description = fields.Text(
        translate=True,
    )
    sequence = fields.Integer(default=10)
    icon = fields.Char(
        help="Optional FontAwesome class for the category "
             "card (e.g. 'fa-volume-up').",
    )
    article_count = fields.Integer(
        string="Articles",
        compute="_compute_article_count",
        help="Published, active articles in this category. "
             "Returns 0 if neon.kb.article isn't yet in "
             "the registry (M1 placeholder until M2 ships).",
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ("category_code_unique",
         "UNIQUE(code)",
         "Category code must be unique."),
        ("category_name_unique",
         "UNIQUE(name)",
         "Category name must be unique."),
    ]

    def _compute_article_count(self):
        """Defensive: M1 ships without the article model.
        M2 lands neon.kb.article + this compute lights up.
        """
        Article = self.env.get("neon.kb.article")
        if Article is None:
            for rec in self:
                rec.article_count = 0
            return
        for rec in self:
            rec.article_count = Article.sudo().search_count([
                ("category_id", "=", rec.id),
                ("state", "=", "published"),
                ("active", "=", True),
            ])
