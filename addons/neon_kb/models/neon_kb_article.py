# -*- coding: utf-8 -*-
"""neon.kb.article -- knowledge base article.

Phase 7d M2. 3-state machine (draft / published /
archived); slug-friendly code auto-generates from name;
state transitions go through the write() override per
Phase 7c M5 pattern (kanban drag-drop respects the graph).

Record rules:
* Internal users see published articles (+ own drafts via
  OR-merged rule).
* Portal users see published only.
* Admins / superuser see everything via permissive rules.
"""
import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_logger = logging.getLogger(__name__)


_STATE_SELECTION = [
    ("draft", "Draft"),
    ("published", "Published"),
    ("archived", "Archived"),
]

_ALLOWED_TRANSITIONS = {
    "draft": {"published"},
    "published": {"draft", "archived"},
    "archived": {"published"},
}


def _slugify(text):
    """ASCII-only slug -- lowercase, alphanumerics, hyphens.
    Runs of non-alphanumerics collapse to a single hyphen;
    leading / trailing hyphens stripped. Empty input or
    all-non-alphanumeric input maps to 'untitled'."""
    if not text:
        return "untitled"
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out or "untitled"


class NeonKBArticle(models.Model):
    _name = "neon.kb.article"
    _description = "Neon Knowledge Base Article"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "last_updated desc, id desc"

    name = fields.Char(
        required=True,
        tracking=True,
        translate=True,
    )
    code = fields.Char(
        string="Slug",
        help="URL-friendly slug auto-generated from name on "
             "create. Admin can override before publish if "
             "needed; stable across renames once set "
             "(create-only auto-gen, no compute re-fire).",
    )
    category_id = fields.Many2one(
        "neon.kb.category",
        string="Category",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    tag_ids = fields.Many2many(
        "neon.kb.tag",
        "neon_kb_article_tag_rel",
        "article_id",
        "tag_id",
        string="Tags",
    )
    body = fields.Html(
        required=True,
        translate=True,
        sanitize=True,
        help="Article content. Rich text (HTML field).",
    )
    summary = fields.Text(
        translate=True,
        help="1-line description for list view + portal "
             "card. Maximum 280 characters.",
    )
    keywords = fields.Char(
        help="Comma-separated search keywords. Used by "
             "name_search override (M3).",
    )
    state = fields.Selection(
        _STATE_SELECTION,
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    author_id = fields.Many2one(
        "res.users",
        string="Author",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
        index=True,
    )
    published_by_id = fields.Many2one(
        "res.users",
        string="Published By",
        readonly=True,
        copy=False,
        tracking=True,
    )
    date_published = fields.Datetime(
        string="Published On",
        readonly=True,
        copy=False,
        tracking=True,
    )
    last_updated = fields.Datetime(
        string="Last Updated",
        compute="_compute_last_updated",
        store=True,
        help="Tracks the most recent write. M2 fires on "
             "any field write; Phase 11 may narrow to "
             "body-only mutations.",
    )
    view_count = fields.Integer(
        string="Views",
        default=0,
        readonly=True,
        copy=False,
        help="Incremented by M4 portal view + admin form "
             "open hook.",
    )
    attachment_ids = fields.One2many(
        "ir.attachment",
        compute="_compute_attachment_ids",
        string="Attachments",
        help="ir.attachment records pointing at this "
             "article (res_model + res_id linkage).",
    )
    # ------------------------------------------------------------------
    # M5 -- cross-link M2M fields. Forward-string references
    # to Phase 7a + Phase 7e models. The join tables are
    # created idempotently by the M5 post-migrate (per
    # reference_odoo17_forward_string_m2o_fk.md applied to
    # M2M).
    # ------------------------------------------------------------------
    related_cert_type_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_kb_article_cert_type_rel",
        "article_id", "cert_type_id",
        string="Related Certifications",
        help="Cert types this article relates to. Cross-"
             "link for users browsing their certs.",
    )
    related_sop_ids = fields.Many2many(
        "neon.lms.sop",
        "neon_kb_article_sop_rel",
        "article_id", "sop_id",
        string="Related SOPs",
        help="LMS SOPs this article extends or references.",
    )
    related_module_ids = fields.Many2many(
        "neon.lms.module",
        "neon_kb_article_module_rel",
        "article_id", "module_id",
        string="Related LMS Modules",
        help="Training modules this article supports.",
    )
    active = fields.Boolean(default=True, tracking=True)

    _sql_constraints = [
        ("article_code_unique",
         "UNIQUE(code)",
         "Article slug must be unique."),
    ]

    # ==================================================================
    # Create-time slug auto-gen (NOT a stored compute --
    # @api.depends on stored compute fires on dependency
    # changes which interacts badly with Odoo's flush queue
    # under savepoint rollback. Keep slug write-once at
    # create time; admin renames don't shift the URL slug,
    # which matches the audit-stable behaviour we want).
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("code"):
                vals["code"] = _slugify(vals.get("name", ""))
        return super().create(vals_list)

    @api.depends("write_date", "create_date")
    def _compute_last_updated(self):
        for rec in self:
            rec.last_updated = (
                rec.write_date or rec.create_date)

    def _compute_attachment_ids(self):
        Attachment = self.env["ir.attachment"]
        for rec in self:
            rec.attachment_ids = Attachment.sudo().search([
                ("res_model", "=", rec._name),
                ("res_id", "=", rec.id),
            ])

    # ==================================================================
    # Validation
    # ==================================================================
    @api.constrains("summary")
    def _check_summary_length(self):
        for rec in self:
            if rec.summary and len(rec.summary) > 280:
                raise ValidationError(_(
                    "Summary cannot exceed 280 characters "
                    "(got %(n)d on '%(name)s')."
                ) % {"n": len(rec.summary),
                     "name": rec.display_name})

    # ==================================================================
    # State machine
    # ==================================================================
    def _transition_to(self, new_state, extra_vals=None):
        """Enforce _ALLOWED_TRANSITIONS; write under
        internal context flag to avoid write() re-entry
        (Phase 7c M5 pattern)."""
        self.ensure_one()
        vals = dict(extra_vals or {})
        if self.state == new_state:
            raise UserError(_(
                "Article '%s' is already in state '%s'."
            ) % (self.display_name, new_state))
        allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise UserError(_(
                "Cannot transition article '%(name)s' "
                "from '%(cur)s' to '%(new)s'. Allowed: "
                "%(allowed)s."
            ) % {
                "name": self.display_name,
                "cur": self.state,
                "new": new_state,
                "allowed": ", ".join(sorted(allowed))
                           or "(none)",
            })
        vals["state"] = new_state
        self.sudo().with_context(
            neon_p7d_internal_transition=True).write(vals)

    def write(self, vals):
        """Route state writes through _transition_to so
        kanban drag-drop (M3) respects the graph. Internal
        transitions set the context flag to skip the
        guard."""
        if (
            "state" in vals
            and not self.env.context.get(
                "neon_p7d_internal_transition")
        ):
            new_state = vals["state"]
            for rec in self:
                if rec.state != new_state:
                    rec._transition_to(new_state)
            vals = {k: v for k, v in vals.items()
                    if k != "state"}
            if not vals:
                return True
        return super().write(vals)

    # ------------------------------------------------------------------
    # Author / admin gate -- enforced server-side. Form
    # buttons gate via groups attribute too, but xmlrpc /
    # shell calls bypass the view layer.
    # ------------------------------------------------------------------
    def _assert_author_or_admin(self):
        self.ensure_one()
        admin_g = self.env.ref(
            "neon_training.group_neon_training_admin",
            raise_if_not_found=False)
        super_g = self.env.ref(
            "neon_core.group_neon_superuser",
            raise_if_not_found=False)
        user = self.env.user
        is_author = self.author_id == user
        is_admin = (
            (admin_g and admin_g in user.groups_id)
            or (super_g and super_g in user.groups_id)
            or user.id == self.env.ref("base.user_root").id)
        if not (is_author or is_admin):
            raise AccessError(_(
                "Only the author or a training/superuser "
                "tier member can change this article's "
                "state."))

    def action_publish(self):
        self.ensure_one()
        self._assert_author_or_admin()
        if not self.body or not self.body.strip():
            raise UserError(_(
                "Article body cannot be empty when "
                "publishing."))
        prior_state = self.state
        self._transition_to("published", {
            "published_by_id": self.env.user.id,
            "date_published": fields.Datetime.now(),
        })
        # M7 -- pick the right notification based on which
        # transition we just made (draft->published is
        # "published"; archived->published goes through
        # action_republish which fires a different event).
        if prior_state == "draft":
            self._notify_article_published()

    def action_archive_article(self):
        """Named action_archive_article (not action_archive)
        to avoid collision with mail.thread's archive
        helpers. Routes through the state graph."""
        self.ensure_one()
        self._assert_author_or_admin()
        self._transition_to("archived")
        # M7 -- notify author the article is archived.
        self._notify_article_archived()

    def action_republish(self):
        self.ensure_one()
        # Restricted to admin / superuser only -- republish
        # of an archived article is an admin action even
        # for the original author.
        admin_g = self.env.ref(
            "neon_training.group_neon_training_admin",
            raise_if_not_found=False)
        super_g = self.env.ref(
            "neon_core.group_neon_superuser",
            raise_if_not_found=False)
        user = self.env.user
        is_admin = (
            (admin_g and admin_g in user.groups_id)
            or (super_g and super_g in user.groups_id)
            or user.id == self.env.ref("base.user_root").id)
        if not is_admin:
            raise AccessError(_(
                "Republish from archived is admin-tier "
                "only."))
        self._transition_to("published", {
            "published_by_id": self.env.user.id,
            "date_published": fields.Datetime.now(),
        })
        # M7 -- notify author the article is republished.
        self._notify_article_republished()

    def action_back_to_draft(self):
        self.ensure_one()
        self._assert_author_or_admin()
        self._transition_to("draft")
        # M7 -- notify author the article is back to draft.
        self._notify_article_back_to_draft()

    # ==================================================================
    # M4 -- view_count helper. Called by the portal article
    # detail route. Form-opens (admin browsing) DON'T
    # increment; only portal reads do. This keeps the
    # popularity metric scoped to the audience the metric
    # is for. Phase 11 can add rate-limiting (once per
    # user per hour) without changing callers.
    # ==================================================================
    def _increment_view_count(self, user):
        """Increment view_count by 1. sudo()s the write
        so portal users (read-only ACL via record rule)
        don't trip write ACL."""
        self.ensure_one()
        self.sudo().write(
            {"view_count": self.view_count + 1})

    # ==================================================================
    # M3 -- name_search override searches across name +
    # summary + keywords (not just name). Mailto-style
    # multi-field OR domain.
    # ==================================================================
    @api.model
    def _name_search(self, name="", domain=None,
                     operator="ilike", limit=100,
                     order=None):
        if name:
            search_domain = ["|", "|",
                ("name", operator, name),
                ("summary", operator, name),
                ("keywords", operator, name),
            ]
            if domain:
                search_domain = (
                    ["&"] + search_domain + list(domain))
            return self._search(
                search_domain, limit=limit, order=order)
        return super()._name_search(
            name=name, domain=domain, operator=operator,
            limit=limit, order=order)

    # ==================================================================
    # M7 -- notification dispatcher + 4 event hooks.
    #
    # Pattern follows reference_neon_notification_stub_
    # pattern.md (Phase 7b M12 / Phase 7e M12 / Phase 7c M7
    # precedent). _notify_send is the single override point
    # Phase 9 swaps for actual dispatch. The 4 event hooks
    # stay stable -- their channels=[...] + body shape are
    # the API contract.
    #
    # Stub marker [Notification stub - Phase 9 will send]
    # uses ASCII hyphen per the reference doc; Phase 9's
    # regression smoke greps for the exact substring.
    # ==================================================================
    def _notify_send(self, event, channels, subject, body):
        """Stub dispatcher. Phase 9 overrides to send actual
        WhatsApp / email via the dispatch engine."""
        self.ensure_one()
        author_partner = (
            self.author_id.partner_id
            if self.author_id else False)
        author_email = (author_partner.email
                        if author_partner else "(no email)")
        author_phone = (author_partner.phone
                        if author_partner else "(no phone)")
        channel_str = ", ".join(channels)
        full_body = (
            "<p><strong>[Notification stub - Phase 9 will "
            "send]</strong></p>"
            "<p><b>Event:</b> %s</p>"
            "<p><b>Channels:</b> %s</p>"
            "<p><b>To:</b> %s / %s</p>"
            "<hr/>%s"
        ) % (event, channel_str,
             author_email or "(no email)",
             author_phone or "(no phone)",
             body)
        self.sudo().message_post(
            subject=subject,
            body=full_body,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def _notify_article_published(self):
        """Fires on state -> published from draft."""
        self.ensure_one()
        self._notify_send(
            event="kb_article_published",
            channels=["email"],
            subject=_(
                "Article published - %s") % self.name,
            body=_(
                "<p>Hi %(author)s,</p>"
                "<p>Your article '%(name)s' has been "
                "published in the %(category)s category. "
                "View it at /my/kb/article/%(code)s.</p>"
            ) % {
                "author": self.author_id.name,
                "name": self.name,
                "category": self.category_id.name,
                "code": self.code,
            },
        )

    def _notify_article_archived(self):
        """Fires on state -> archived."""
        self.ensure_one()
        self._notify_send(
            event="kb_article_archived",
            channels=["email"],
            subject=_(
                "Article archived - %s") % self.name,
            body=_(
                "<p>Hi %(author)s,</p>"
                "<p>Your article '%(name)s' has been "
                "archived. It is no longer visible to "
                "portal users. Contact an admin to "
                "re-publish if needed.</p>"
            ) % {
                "author": self.author_id.name,
                "name": self.name,
            },
        )

    def _notify_article_back_to_draft(self):
        """Fires on state -> draft (from published)."""
        self.ensure_one()
        self._notify_send(
            event="kb_article_back_to_draft",
            channels=["email"],
            subject=_(
                "Article moved to draft - %s") % self.name,
            body=_(
                "<p>Hi %(author)s,</p>"
                "<p>Your article '%(name)s' has been moved "
                "back to draft for editing. Republish when "
                "ready.</p>"
            ) % {
                "author": self.author_id.name,
                "name": self.name,
            },
        )

    def _notify_article_republished(self):
        """Fires on state -> published from archived."""
        self.ensure_one()
        self._notify_send(
            event="kb_article_republished",
            channels=["email"],
            subject=_(
                "Article republished - %s") % self.name,
            body=_(
                "<p>Hi %(author)s,</p>"
                "<p>Your article '%(name)s' has been "
                "republished and is again visible to portal "
                "users.</p>"
            ) % {
                "author": self.author_id.name,
                "name": self.name,
            },
        )
