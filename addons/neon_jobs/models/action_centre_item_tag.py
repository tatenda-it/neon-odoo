# -*- coding: utf-8 -*-
"""P4.M1 — Action Centre tag model.

Lightweight free-tagging surface for action.centre.item records.
Names are unique so colour-coded tags can be reused across items
without duplication. Managers maintain the tag list; everyone reads.
"""
from odoo import fields, models


class ActionCentreItemTag(models.Model):
    _name = "action.centre.item.tag"
    _description = "Action Centre Tag"
    _order = "name"

    name = fields.Char(required=True)
    color = fields.Integer(default=0)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Tag name must be unique."),
    ]
