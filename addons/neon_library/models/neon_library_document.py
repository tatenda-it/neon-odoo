# -*- coding: utf-8 -*-
from odoo import api, fields, models

# file-extension -> FontAwesome icon class for the kanban file-type badge.
_EXT_ICON = {
    "pdf": "fa-file-pdf-o",
    "doc": "fa-file-word-o", "docx": "fa-file-word-o", "odt": "fa-file-word-o",
    "xls": "fa-file-excel-o", "xlsx": "fa-file-excel-o", "csv": "fa-file-excel-o",
    "ods": "fa-file-excel-o",
    "ppt": "fa-file-powerpoint-o", "pptx": "fa-file-powerpoint-o",
    "odp": "fa-file-powerpoint-o",
    "png": "fa-file-image-o", "jpg": "fa-file-image-o", "jpeg": "fa-file-image-o",
    "gif": "fa-file-image-o", "bmp": "fa-file-image-o", "svg": "fa-file-image-o",
    "zip": "fa-file-archive-o", "rar": "fa-file-archive-o", "7z": "fa-file-archive-o",
    "tar": "fa-file-archive-o", "gz": "fa-file-archive-o",
    "txt": "fa-file-text-o", "md": "fa-file-text-o",
    "mp4": "fa-file-video-o", "mov": "fa-file-video-o", "avi": "fa-file-video-o",
    "mkv": "fa-file-video-o",
    "mp3": "fa-file-audio-o", "wav": "fa-file-audio-o", "m4a": "fa-file-audio-o",
}


class NeonLibraryDocument(models.Model):
    _name = "neon.library.document"
    _description = "Neon Library Document"
    _inherit = ["mail.thread"]
    _order = "create_date desc, name asc"

    name = fields.Char(required=True, tracking=True)
    folder_id = fields.Many2one(
        "neon.library.folder", string="Folder", index=True, tracking=True,
        ondelete="set null")
    tag_ids = fields.Many2many("neon.library.tag", string="Tags")
    description = fields.Text()

    # the file -- stored as an ir.attachment (attachment=True) so the stock
    # attachment_indexation module full-text indexes its contents.
    file_data = fields.Binary(
        string="File", attachment=True, required=True)
    file_name = fields.Char(string="File Name")
    file_extension = fields.Char(
        compute="_compute_file_meta", store=True)
    file_icon = fields.Char(
        string="Icon", compute="_compute_file_meta", store=True)

    # honest attribution -- the uploader is the row's create_uid.
    uploaded_by = fields.Many2one(
        "res.users", string="Uploaded By", related="create_uid",
        store=True, readonly=True)

    # full-text content mirrored from the file's ir.attachment.index_content
    # (populated by attachment_indexation). Stored so the library search can
    # match document CONTENT, not just metadata.
    index_content = fields.Text(
        string="Indexed Content", compute="_compute_index_content",
        store=True)
    active = fields.Boolean(default=True, tracking=True)

    @api.depends("file_name")
    def _compute_file_meta(self):
        for rec in self:
            ext = ""
            if rec.file_name and "." in rec.file_name:
                ext = rec.file_name.rsplit(".", 1)[-1].lower().strip()
            rec.file_extension = ext
            rec.file_icon = _EXT_ICON.get(ext, "fa-file-o")

    @api.depends("file_data", "file_name")
    def _compute_index_content(self):
        """Mirror the file's ir.attachment.index_content (set by
        attachment_indexation) onto the document so it's searchable. The
        Binary(attachment=True) write creates the ir.attachment in the same
        transaction; attachment_indexation indexes it synchronously, so by
        the time this stored compute runs the content is available."""
        Att = self.env["ir.attachment"].sudo()
        for rec in self:
            content = False
            if rec.id and rec.file_data:
                att = Att.search([
                    ("res_model", "=", "neon.library.document"),
                    ("res_field", "=", "file_data"),
                    ("res_id", "=", rec.id)], limit=1)
                content = (att.index_content or False) if att else False
            rec.index_content = content
