# -*- coding: utf-8 -*-
"""neon.kb.tag -- free-form labels for KB articles.

Phase 7d M1. Tags are user-extensible (training_admin can
add via the Configuration menu); seeded empty in M1.
"""
from odoo import api, fields, models, _


class NeonKBTag(models.Model):
    _name = "neon.kb.tag"
    _description = "Neon Knowledge Base Tag"
    _order = "name asc"

    name = fields.Char(
        required=True,
        translate=True,
    )
    color = fields.Integer(default=0)
    article_count = fields.Integer(
        string="Articles",
        compute="_compute_article_count",
        help="Published, active articles tagged here. "
             "Returns 0 if neon.kb.article isn't yet in "
             "the registry.",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("tag_name_unique",
         "UNIQUE(name)",
         "Tag name must be unique."),
    ]

    def _compute_article_count(self):
        Article = self.env.get("neon.kb.article")
        if Article is None:
            for rec in self:
                rec.article_count = 0
            return
        for rec in self:
            rec.article_count = Article.sudo().search_count([
                ("tag_ids", "in", rec.id),
                ("state", "=", "published"),
                ("active", "=", True),
            ])
