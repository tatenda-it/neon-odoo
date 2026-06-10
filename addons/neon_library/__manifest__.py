# -*- coding: utf-8 -*-
{
    "name": "Neon Library",
    # A small bespoke company file library for Odoo Community (no Documents
    # app; knowledge uninstallable on this stack). One record = one file.
    #   * neon.library.folder  -- nested folders (parent/child) + doc count
    #   * neon.library.document -- the file (Binary attachment=True + name +
    #     mimetype), tag_ids, uploaded_by (create_uid), chatter
    #   * neon.library.tag     -- simple colour tags
    # Access: all internal users read + create + write OWN; UNLINK and moving
    # OTHERS' files are restricted to neon_core.group_neon_superuser (the
    # org admin/leadership tier -- the file-library curators). Depends on the
    # stock attachment_indexation so PDF/doc CONTENTS are full-text indexed
    # (ir.attachment.index_content) and surfaced in the library search.
    "version": "17.0.1.0.0",
    "summary": "Company file library -- nested folders, tagged documents, "
               "upload/download, full-text content search.",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Library",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "neon_core",
        # full-text indexing of PDF/doc/etc. attachment contents -> the
        # document's index_content surfaces them in the library search.
        "attachment_indexation",
    ],
    "data": [
        "security/neon_library_security.xml",
        "security/ir.model.access.csv",
        "views/neon_library_tag_views.xml",
        "views/neon_library_folder_views.xml",
        "views/neon_library_document_views.xml",
        # menu LAST -- targets the actions defined in the view files above.
        "views/neon_library_menu.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
