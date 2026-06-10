# -*- coding: utf-8 -*-
from odoo import fields, models


class NeonLibraryTag(models.Model):
    _name = "neon.library.tag"
    _description = "Neon Library Tag"
    _order = "name asc"

    name = fields.Char(required=True)
    color = fields.Integer(string="Colour")

    _sql_constraints = [
        ("library_tag_name_unique", "UNIQUE(name)",
         "A library tag with this name already exists."),
    ]
