# -*- coding: utf-8 -*-
"""Neon HR — employee category (7 confirmed kinds).

⚠️ DECISION (spec offered "Selection or M2O"): modelled as an M2O
``neon.hr.category`` with 7 seeded rows rather than a bare Selection.
Rationale:
  * acceptance #6 SQL-verifies "7 categories seeded" — needs real rows;
  * each category drives a DISTINCT required-document set (M2M to the
    document-type catalog) which is far cleaner as data than a Python
    dict, and HR can adjust a doc-set without a code change;
  * R1b ("build cleanly so R1b bolts on") hangs default pay type,
    leave defaults and freelance-rate links off the category — a model
    gives those a home.

The 7 ``code`` values are still a fixed, code-known set (a SQL unique
constraint + seeded xml ids), so code that needs to branch on category
can match on ``code`` deterministically.
"""
from odoo import api, fields, models


class NeonHrCategory(models.Model):
    _name = "neon.hr.category"
    _description = "Neon HR Employee Category"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical key, e.g. 'employed_technician'.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    # Default pay type drives R1b payroll/wage wiring. Stored on the
    # category so a new contract for the category starts from the
    # right default; the per-contract field remains authoritative.
    default_pay_type = fields.Selection(
        [("salary", "Monthly Salary"),
         ("per_job", "Per Job / Per Event"),
         ("hourly", "Hourly / Day Rate"),
         ("commission", "Commission")],
        default="salary", required=True,
    )

    required_document_type_ids = fields.Many2many(
        "neon.hr.document.type",
        "neon_hr_category_doctype_rel",
        "category_id", "doctype_id",
        string="Required Documents",
        help="The document set an employee in this category must "
        "hold to be compliant.",
    )
    required_document_count = fields.Integer(
        compute="_compute_required_document_count",
    )

    # ⚠️ Notice period: permanent = 30 days (legally settled). All
    # other categories are NOT hard-defaulted to 3 months — the value
    # is configurable here and FLAGGED for legal sign-off so nobody
    # mistakes an invented default for a confirmed one.
    notice_period_days = fields.Integer(
        default=30,
        help="Default notice period (days) for contracts in this "
        "category. Copied to a new contract as a starting value; the "
        "per-contract field is authoritative.",
    )
    notice_flagged_for_legal = fields.Boolean(
        string="Notice Pending Legal Sign-off",
        help="True where the notice period is a placeholder awaiting "
        "legal confirmation (everything except permanent).",
    )

    description = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code)",
         "A category with this code already exists."),
    ]

    @api.depends("required_document_type_ids")
    def _compute_required_document_count(self):
        for rec in self:
            rec.required_document_count = len(
                rec.required_document_type_ids)
