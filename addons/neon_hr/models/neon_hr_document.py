# -*- coding: utf-8 -*-
"""Neon HR — document catalog + per-employee compliance checklist.

Two models:

* ``neon.hr.document.type`` — the catalog of mandatory document
  kinds (Appendix B7 list). Director/HR-editable, seeded with the
  confirmed mandatory set.

* ``neon.hr.document`` — one checklist row per (employee, type).
  State is attachment-driven: missing until a file is attached, then
  provided, then expired once past ``expiry_date`` (for types that
  carry an expiry). ``perm_unlink = 0`` on every group — corrections
  are made by attaching a fresh file or superseding the row, never by
  deletion (project audit-trail discipline).

⚠️ DECISION: state is a STORED compute keyed on attachment_ids +
expiry_date. The expiry transition depends on "today", which does not
itself fire a recompute — so the daily contract-expiry cron also
nudges document states (model._cron_refresh_document_states) so
expiry is picked up within a day. A 24h lag on a feature whose horizon
is 30 days is acceptable; the alternative (non-stored is_compliant)
would not be SQL-verifiable, which acceptance #6 requires.
"""
from odoo import _, api, fields, models


class NeonHrDocumentType(models.Model):
    _name = "neon.hr.document.type"
    _description = "Neon HR Document Type"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True,
        help="Stable technical key, e.g. 'signed_contract'.",
    )
    sequence = fields.Integer(default=10)
    requires_expiry = fields.Boolean(
        string="Has Expiry",
        help="Tick for documents that lapse (work permit, NSSA, "
        "ID/passport). Such documents flip to 'expired' past their "
        "expiry date and break compliance until renewed.",
    )
    active = fields.Boolean(default=True)
    description = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code)",
         "A document type with this code already exists."),
    ]


class NeonHrDocument(models.Model):
    _name = "neon.hr.document"
    _description = "Neon HR Employee Document"
    _inherit = ["mail.thread"]
    _order = "employee_id, document_type_id"
    _rec_name = "display_name"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade",
        index=True, tracking=True,
    )
    document_type_id = fields.Many2one(
        "neon.hr.document.type", required=True, ondelete="restrict",
        tracking=True,
    )
    # Owner shortcut for the confidentiality record rule (own-docs).
    employee_user_id = fields.Many2one(
        "res.users", related="employee_id.user_id", store=True,
        index=True, string="Employee User",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "neon_hr_document_attachment_rel",
        "document_id", "attachment_id",
        string="Files",
    )
    attachment_count = fields.Integer(
        compute="_compute_attachment_count",
    )
    expiry_date = fields.Date(tracking=True)
    requires_expiry = fields.Boolean(
        related="document_type_id.requires_expiry", store=True,
    )
    state = fields.Selection(
        [("missing", "Missing"),
         ("provided", "Provided"),
         ("expired", "Expired")],
        compute="_compute_state", store=True, tracking=True,
        index=True,
    )
    is_expired = fields.Boolean(compute="_compute_state", store=True)
    notes = fields.Text()

    _sql_constraints = [
        ("employee_type_uniq",
         "unique(employee_id, document_type_id)",
         "This document type is already on the employee's checklist."),
    ]

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    @api.depends("attachment_ids", "expiry_date")
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.attachment_ids:
                rec.state = "missing"
                rec.is_expired = False
            elif rec.expiry_date and rec.expiry_date < today:
                rec.state = "expired"
                rec.is_expired = True
            else:
                rec.state = "provided"
                rec.is_expired = False

    @api.depends("employee_id", "document_type_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (
                rec.employee_id.name or _("New"),
                rec.document_type_id.name or _("Document"),
            )

    @api.model
    def _cron_refresh_document_states(self):
        """Daily nudge so expiry-driven 'expired' transitions land in
        the stored ``state`` column without a user write. Recomputes
        every document carrying an expiry date in the past that is not
        already flagged expired (and vice-versa)."""
        stale = self.sudo().search([("requires_expiry", "=", True)])
        if stale:
            stale.modified(["expiry_date"])
            stale._compute_state()
        return True
