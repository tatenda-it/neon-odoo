# -*- coding: utf-8 -*-
"""Portal controllers for /my/kb routes.

Phase 7d M4: list (with search + category filter +
pagination) + single-article detail with view_count
increment.

Form-open by admin in the backend does NOT increment
view_count (admin browsing shouldn't pollute popularity
metric). Only the portal route bumps the counter.
"""
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import (
    CustomerPortal, pager as portal_pager)


_KB_PER_PAGE = 10


class NeonKBPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        """Surface KB counter on /my so portal users see a
        card linking to the knowledge base when at least
        one article is published.
        """
        values = super()._prepare_home_portal_values(
            counters)
        if "kb_count" in counters:
            values["kb_count"] = request.env[
                "neon.kb.article"
            ].sudo().search_count([
                ("state", "=", "published"),
                ("active", "=", True),
            ])
        return values

    # ==================================================================
    # /my/kb -- list with search + category + pagination
    # ==================================================================
    @http.route(
        ["/my/kb", "/my/kb/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_kb_list(self, page=1, category=None,
                       search=None, **kw):
        domain = [
            ("state", "=", "published"),
            ("active", "=", True),
        ]
        current_category = None
        if category:
            cat = request.env[
                "neon.kb.category"
            ].sudo().search(
                [("code", "=", category)], limit=1)
            if cat:
                domain.append(
                    ("category_id", "=", cat.id))
                current_category = cat
        if search:
            domain += [
                "|", "|",
                ("name", "ilike", search),
                ("summary", "ilike", search),
                ("keywords", "ilike", search),
            ]

        Article = request.env["neon.kb.article"].sudo()
        total = Article.search_count(domain)

        # Build pager (portal_pager from portal.controllers)
        # handles edge cases (page=0, page out of bounds).
        pager = portal_pager(
            url="/my/kb",
            url_args={"category": category,
                      "search": search},
            total=total,
            page=page,
            step=_KB_PER_PAGE,
        )

        articles = Article.search(
            domain,
            limit=_KB_PER_PAGE,
            offset=pager["offset"],
            order="date_published desc, view_count desc",
        )
        categories = request.env[
            "neon.kb.category"
        ].sudo().search(
            [("active", "=", True)], order="sequence")

        values = {
            "articles": articles,
            "categories": categories,
            "current_category": current_category,
            "search": search or "",
            "pager": pager,
            "total": total,
            "page_name": "kb",
        }
        return request.render(
            "neon_kb.portal_kb_list", values)

    # ==================================================================
    # /my/kb/article/<code> -- single article detail
    # ==================================================================
    @http.route(
        ["/my/kb/article/<string:code>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_kb_article(self, code, **kw):
        Article = request.env["neon.kb.article"].sudo()
        article = Article.search([
            ("code", "=", code),
            ("state", "=", "published"),
            ("active", "=", True),
        ], limit=1)
        if not article:
            return request.redirect("/my/kb")

        # Bump view counter. The helper sudo()s the write so
        # portal users (read-only via ACL+rule) don't trip
        # write ACL.
        article._increment_view_count(request.env.user)

        values = {
            "article": article,
            "page_name": "kb",
        }
        return request.render(
            "neon_kb.portal_kb_article", values)
