# -*- coding: utf-8 -*-
"""neon.lms.sop -- Standard Operating Procedures.

Phase 7e M6. Reference material attached to modules; not
gated, not tracked for completion. SOPs are read-only
reference docs that learners (and admin) can pull up for
equipment + procedures.
"""
from odoo import api, fields, models, _


class NeonLMSSOP(models.Model):
    _name = "neon.lms.sop"
    _description = "Neon LMS Standard Operating Procedure"
    _order = "name asc"

    name = fields.Char(
        required=True,
        translate=True,
    )
    equipment_or_procedure = fields.Char(
        string="Equipment / Procedure",
        help="The piece of equipment or workflow this SOP "
             "covers (e.g., 'Allen and Heath SQ6', "
             "'Generator startup', 'Outdoor stage rig').",
    )
    document_attachment_id = fields.Many2one(
        "ir.attachment",
        string="Document",
        ondelete="set null",
        help="The actual PDF / image / doc file. SOPs can "
             "exist without a doc (text-only summary) but "
             "typically carry one.",
    )
    summary = fields.Text(
        translate=True,
        help="Plain-text summary visible inline without "
             "downloading the attachment.",
    )
    last_revised = fields.Date()
    module_ids = fields.Many2many(
        "neon.lms.module",
        "neon_lms_sop_module_rel",
        "sop_id",
        "module_id",
        string="Linked Modules",
        help="SOPs can attach to multiple modules. Reference "
             "material is reusable across the program.",
    )
    # Phase 7d M5: reverse pointer from the KB article M2M.
    # Same join table as the forward field on neon.kb.article;
    # join table created on the KB side. Forward-string
    # reference -- neon_lms does NOT depend on neon_kb (KB
    # depends on LMS for the cross-link).
    kb_article_ids = fields.Many2many(
        "neon.kb.article",
        "neon_kb_article_sop_rel",
        "sop_id",
        "article_id",
        string="KB Articles",
        help="Knowledge base articles that reference this "
             "SOP. Phase 7d M5 reverse pointer.",
    )
    active = fields.Boolean(default=True)

    def _get_attachment_url(self):
        """Return the download URL for the attached doc, or
        False when no attachment is set. Portal layer (later
        milestone) consumes this for the SOP card download
        link.
        """
        self.ensure_one()
        if not self.document_attachment_id:
            return False
        return "/web/content/%d?download=1" % (
            self.document_attachment_id.id,)
