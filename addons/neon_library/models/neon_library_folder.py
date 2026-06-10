# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class NeonLibraryFolder(models.Model):
    _name = "neon.library.folder"
    _description = "Neon Library Folder"
    _inherit = ["mail.thread"]
    _order = "complete_name asc"
    _parent_name = "parent_id"
    _parent_store = True

    name = fields.Char(required=True, tracking=True)
    parent_id = fields.Many2one(
        "neon.library.folder", string="Parent Folder",
        ondelete="restrict", index=True, tracking=True,
        help="Folders nest. Deleting is restricted to managers and "
        "blocked while the folder still holds child folders.")
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many(
        "neon.library.folder", "parent_id", string="Subfolders")
    document_ids = fields.One2many(
        "neon.library.document", "folder_id", string="Documents")
    complete_name = fields.Char(
        string="Full Path", compute="_compute_complete_name",
        store=True, recursive=True)
    document_count = fields.Integer(
        string="Documents", compute="_compute_document_count")
    active = fields.Boolean(default=True, tracking=True)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = "%s / %s" % (
                    rec.parent_id.complete_name, rec.name or "")
            else:
                rec.complete_name = rec.name or ""

    @api.depends("document_ids")
    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    @api.constrains("parent_id")
    def _check_no_recursion(self):
        if not self._check_recursion():
            raise ValidationError(
                _("A folder cannot be its own ancestor."))

    def action_open_documents(self):
        """Open this folder's documents (the smart-button / row action)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.complete_name,
            "res_model": "neon.library.document",
            "view_mode": "kanban,list,form",
            "domain": [("folder_id", "=", self.id)],
            "context": {"default_folder_id": self.id},
        }
