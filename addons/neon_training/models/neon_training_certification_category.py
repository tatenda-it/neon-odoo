# -*- coding: utf-8 -*-
"""
P7a.M1 — Certification Category (Schema Sketch §2.1).

Top-level taxonomy for the four certification groups Neon tracks:
Equipment, Role Tier, Safety, Soft Skill. Each category encodes
default policy fields (skill-level mode, expiry, external-trainer
requirement) that child certification.type rows inherit and may
override per-type.

Audit-trail discipline (Phase 6 H3=A standard, carried forward
into Phase 7): perm_unlink=0 for every group in ir.model.access.
csv. Categories are never deleted; archive via active=False and
append a successor row if the taxonomy itself needs to change.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_SKILL_LEVEL_MODES = [
    ("binary",   "Binary (Pass / Fail)"),
    ("tiered_3", "Tiered (3 levels)"),
    ("custom",   "Custom per type"),
]

_CODE_REGEX = re.compile(r"^[a-z0-9_]+$")


class NeonTrainingCertificationCategory(models.Model):
    _name = "neon.training.certification.category"
    _description = "Training Certification Category"
    _inherit = ["mail.thread"]
    _order = "sequence, name"

    name = fields.Char(
        string="Category",
        required=True,
        translate=True,
        tracking=True,
    )
    code = fields.Char(
        string="Code",
        required=True,
        tracking=True,
        help="Stable lowercase identifier used in XML IDs and code "
        "references. Lowercase alphanumeric + underscore only "
        "(e.g. 'equipment', 'role', 'safety', 'soft').",
    )
    sequence = fields.Integer(default=10)
    audit_track = fields.Boolean(
        string="Audit-Track",
        default=False,
        tracking=True,
        help="When set, child type changes and individual certification "
        "grants/revocations under this category emit chatter entries "
        "and feed downstream audit reports. Safety and Equipment "
        "default on; Soft Skill default off.",
    )
    requires_external_trainer = fields.Boolean(
        string="Requires External Trainer",
        default=False,
        tracking=True,
        help="When True, certifications in this category default to "
        "sign-off by an external accredited trainer (Safety / NSSA / "
        "ZERA pattern). Per-type override available.",
    )
    skill_level_mode = fields.Selection(
        _SKILL_LEVEL_MODES,
        string="Skill Level Mode",
        required=True,
        default="binary",
        tracking=True,
        help="How proficiency is graded for certifications in this "
        "category. binary = pass / fail (most safety, languages); "
        "tiered_3 = three-level skill ladder (consoles); custom = "
        "per-type selection (role tier).",
    )
    expiry_required = fields.Boolean(
        string="Expiry Required",
        default=False,
        tracking=True,
        help="When True, grants under this category MUST carry an "
        "expiry_date. Drives renewal reminders downstream (M5+).",
    )
    default_validity_months = fields.Integer(
        string="Default Validity (months)",
        default=0,
        tracking=True,
        help="Default number of months a granted certification stays "
        "valid before requiring re-certification. 0 = no default "
        "(per-type override required). Used as the seed value when "
        "creating a new certification.type under this category.",
    )
    icon = fields.Char(
        string="Icon (FontAwesome)",
        help="FontAwesome class for kanban tile rendering — e.g. "
        "'fa-cog'. Used by the certification.type kanban view + "
        "future M6 dashboard tiles.",
    )
    active = fields.Boolean(default=True, tracking=True)

    type_ids = fields.One2many(
        "neon.training.certification.type",
        "category_id",
        string="Certification Types",
    )
    type_count = fields.Integer(
        compute="_compute_type_count",
        string="# Types",
    )

    _sql_constraints = [
        ("unique_code", "UNIQUE (code)",
         "Certification category codes must be unique."),
    ]

    @api.depends("type_ids")
    def _compute_type_count(self):
        for rec in self:
            rec.type_count = len(rec.type_ids)

    @api.constrains("code")
    def _check_code_format(self):
        for rec in self:
            if not rec.code or not _CODE_REGEX.match(rec.code):
                raise ValidationError(_(
                    "Category code '%s' is invalid. Use lowercase "
                    "letters, digits, and underscores only "
                    "(e.g. 'equipment', 'soft_skill').") % (rec.code,))

    @api.constrains("default_validity_months")
    def _check_validity_non_negative(self):
        for rec in self:
            if rec.default_validity_months < 0:
                raise ValidationError(_(
                    "Default validity (months) must be zero or "
                    "positive (got %s) on category %s.") % (
                        rec.default_validity_months, rec.display_name))
