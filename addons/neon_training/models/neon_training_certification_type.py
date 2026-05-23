# -*- coding: utf-8 -*-
"""
P7a.M1 — Certification Type (Schema Sketch §2.2).

Individual certifications within a category. Equipment-bound types
optionally link to a workshop SKU (product.template with
is_workshop_item=True) — gate-1 D.1 decision.

Validity, skill-level-mode, and sign-off authority default from
the parent category and may override per-type. Regulatory metadata
(body + code) is freetext, populated for safety + driver certs.
"""
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_SKILL_LEVEL_MODES = [
    ("binary",   "Binary (Pass / Fail)"),
    ("tiered_3", "Tiered (3 levels)"),
    ("custom",   "Custom per type"),
]

_SIGN_OFF_AUTHORITIES = [
    ("self_with_peer",    "Self + Peer"),
    ("lead_tech",         "Lead Tech"),
    ("od_md",             "OD / MD"),
    ("external_trainer",  "External Trainer"),
    # Phase 7e M9: auto-issued by the LMS workflow without
    # human verification. _resolve_verify_authority_partners
    # returns empty for this authority (no TODO routing).
    ("system",            "System (LMS Auto-Issued)"),
]

_CODE_REGEX = re.compile(r"^[a-z0-9_]+$")


class NeonTrainingCertificationType(models.Model):
    _name = "neon.training.certification.type"
    _description = "Training Certification Type"
    _inherit = ["mail.thread"]
    _order = "category_id, name"

    name = fields.Char(
        string="Name",
        required=True,
        translate=True,
        tracking=True,
    )
    code = fields.Char(
        string="Code",
        required=True,
        tracking=True,
        help="Stable lowercase identifier (lowercase letters, digits, "
        "underscore). Unique within a category — combined with "
        "category_id forms the natural key.",
    )
    category_id = fields.Many2one(
        "neon.training.certification.category",
        string="Category",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    equipment_category_id = fields.Many2one(
        "neon.equipment.category",
        string="Equipment Category",
        ondelete="set null",
        help="Workshop equipment category this certification covers. "
        "Populated for Equipment-category types (e.g. an MA3 Console "
        "cert ties to the Lighting equipment category). Null for "
        "Role / Safety / Soft Skill types.",
    )
    # P7a.M1 — ⚠️ DECISION marker D.1: equipment_model_id Many2one
    # to product.template with workshop domain. No neon.equipment.
    # model exists in the workshop hierarchy; product.template is
    # the established "model / SKU / nickname" layer per Phase 5
    # hybrid granularity (product.template = model, neon.equipment
    # .unit = serialised instance). Seed leaves this null on M1;
    # Ranganai populates post-install via UI.
    equipment_model_id = fields.Many2one(
        "product.template",
        string="Equipment Model",
        ondelete="set null",
        domain="[('is_workshop_item', '=', True), "
               "('equipment_category_id', '=', equipment_category_id)]",
        help="Specific workshop SKU this certification covers (e.g. "
        "the 'MA Lighting grandMA3 Light' product). Filtered to the "
        "selected equipment_category_id. Populate post-install once "
        "Ranganai audits which product.template rows correspond.",
    )
    validity_months = fields.Integer(
        string="Validity (months)",
        default=0,
        tracking=True,
        help="Number of months a granted certification stays valid. "
        "0 = no expiry. Inherits the parent category's "
        "default_validity_months at creation time.",
    )
    # P7a.M1 — ⚠️ DECISION marker D.2: nullable override.
    # When null, ``effective_skill_level_mode`` falls back to the
    # category. Spec was ambiguous on the fall-back mechanic; nullable
    # override + computed effective field is cleaner than two parallel
    # stored fields.
    skill_level_mode = fields.Selection(
        _SKILL_LEVEL_MODES,
        string="Skill Level Mode (override)",
        tracking=True,
        help="Override the parent category's skill-level mode for "
        "this specific type. Leave blank to inherit. Example: most "
        "Equipment types are tiered_3, but LED Wall is binary "
        "(competent or not — no middle).",
    )
    effective_skill_level_mode = fields.Selection(
        _SKILL_LEVEL_MODES,
        string="Effective Skill Level Mode",
        compute="_compute_effective_skill_level_mode",
        store=True,
        help="Resolved skill-level mode: this type's override if "
        "set, else the parent category's default.",
    )
    sign_off_authority = fields.Selection(
        _SIGN_OFF_AUTHORITIES,
        string="Sign-Off Authority",
        required=True,
        default="lead_tech",
        tracking=True,
        help="Who is authorised to sign off a grant of this "
        "certification. external_trainer is the default for Safety "
        "and Driver Licence types.",
    )
    regulatory_body = fields.Char(
        string="Regulatory Body",
        tracking=True,
        help="Issuing or accrediting body, e.g. NSSA, ZERA, "
        "St John Ambulance, Zimbabwe Traffic Safety Council. "
        "Freetext — no Many2one to a partners list yet.",
    )
    regulatory_code = fields.Char(
        string="Regulatory Code / Reference",
        help="Statutory reference or issuing scheme code if any.",
    )
    description = fields.Text()
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ("unique_category_code",
         "UNIQUE (category_id, code)",
         "Certification type codes must be unique within a category."),
    ]

    @api.depends("skill_level_mode", "category_id.skill_level_mode")
    def _compute_effective_skill_level_mode(self):
        for rec in self:
            rec.effective_skill_level_mode = (
                rec.skill_level_mode or rec.category_id.skill_level_mode)

    @api.constrains("code")
    def _check_code_format(self):
        for rec in self:
            if not rec.code or not _CODE_REGEX.match(rec.code):
                raise ValidationError(_(
                    "Certification type code '%s' is invalid. Use "
                    "lowercase letters, digits, and underscores only "
                    "(e.g. 'ma3_console', 'work_at_heights').") % (
                        rec.code,))

    @api.constrains("validity_months")
    def _check_validity_non_negative(self):
        for rec in self:
            if rec.validity_months < 0:
                raise ValidationError(_(
                    "Validity (months) must be zero or positive "
                    "(got %s) on certification type %s.") % (
                        rec.validity_months, rec.display_name))

    @api.onchange("category_id")
    def _onchange_category_id(self):
        """Seed validity from the category default when the
        category is first picked on a new record. Does not stomp
        an explicit override the user has already typed."""
        for rec in self:
            if rec.category_id and not rec.validity_months:
                rec.validity_months = (
                    rec.category_id.default_validity_months)

    @api.onchange("equipment_category_id")
    def _onchange_equipment_category_id(self):
        """Clear stale equipment_model_id when the equipment_category
        is changed, so a model from the previous category doesn't
        survive in the UI before the domain re-applies."""
        for rec in self:
            if (rec.equipment_model_id and
                    rec.equipment_model_id.equipment_category_id !=
                    rec.equipment_category_id):
                rec.equipment_model_id = False
