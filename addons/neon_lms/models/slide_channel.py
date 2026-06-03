# -*- coding: utf-8 -*-
"""slide.channel inherit -- Neon program extension.

Single channel record carries the Neon training program
identity + program state. Tracks (the 7 sub-courses) are
children via neon_track_ids o2m.
"""
import re

from odoo import api, fields, models, _


_NEON_PROGRAM_STATES = [
    ("draft", "Draft"),
    ("active", "Active"),
    ("archived", "Archived"),
]

# P7g: the 17 orphan "M01 content" .. "M17 content" placeholder slides the
# P7e import left at sequence 0 (one per module, before the first section).
# Import artifacts, not real content -- removed by _neon_apply_branding_config.
_NEON_ORPHAN_RE = re.compile(r"^M\d{2} content$")

# P7g: per-track accent colour for the 7 track cards (brand palette +
# violet/grape variants; lime #c8f36b is the hero/CTA accent). Keyed by the
# neon.lms.track code so the cards stay data-driven off the existing model.
_NEON_TRACK_ACCENTS = {
    "TRK_FOUND_SAFETY": "#6B21A8",   # grape -- the gate / primary
    "TRK_AUDIO":        "#8b5cf6",   # violet
    "TRK_LIGHTING":     "#a78bfa",   # lilac
    "TRK_VIDEO_LED":    "#7c3aed",   # violet-700
    "TRK_WORKFLOW_OPS": "#9333ea",   # purple
    "TRK_SOFT_SKILLS":  "#6d28d9",   # violet-800
    "TRK_RIGGING":      "#3f0f6b",   # grape-deep
}


class SlideChannelNeonLMS(models.Model):
    _inherit = "slide.channel"

    neon_program_state = fields.Selection(
        _NEON_PROGRAM_STATES,
        string="Neon Program State",
        default="draft",
        tracking=True,
        help="Lifecycle state of the Neon training program. "
             "Draft (in setup), Active (open for enrollment), "
             "Archived (closed). M1 ships state=draft on the "
             "seeded channel; admin promotes to active when "
             "M7 enrollment is wired.",
    )
    neon_track_ids = fields.One2many(
        "neon.lms.track",
        "channel_id",
        string="Neon Tracks",
        help="The 7 sub-courses under this Neon channel.",
    )
    neon_total_tracks = fields.Integer(
        compute="_compute_neon_total_tracks",
        store=True,
        help="Cached count of associated tracks (target: 7).",
    )
    neon_capstone_cert_type_id = fields.Many2one(
        "neon.training.certification.type",
        string="Capstone Cert Type",
        help="The capstone cert issued on full program "
             "completion. Populated by M9 seed (cert_type_"
             "neon_technical). Nullable in M1.",
    )

    # P7g: flags the channel that gets the Neon course-page branding
    # (hero + track cards + capstone). Scopes the QWeb override so no other
    # eLearning course is touched. Set by _neon_apply_branding_config.
    neon_branded = fields.Boolean(
        string="Neon Branded Course Page",
        default=False,
        help="When set, the course landing renders the Neon Workshop "
             "Training hero, track cards, and capstone band instead of the "
             "stock eLearning cover.",
    )

    @api.depends("neon_track_ids")
    def _compute_neon_total_tracks(self):
        for rec in self:
            rec.neon_total_tracks = len(rec.neon_track_ids)

    # ================================================================
    # P7g -- course-page branding helpers (consumed by the QWeb override)
    # ================================================================
    def _neon_track_cards(self):
        """The 7 track cards for the branded landing -- reuses the existing
        neon.lms.track model (no parallel mapping). Each card: name, module
        count, gate flag, the sub-cert it earns, accent colour, blurb."""
        self.ensure_one()
        cards = []
        # sudo: a frontend learner rendering the course page has no ACL on
        # neon.lms.track / certification.type (admin-side models). These
        # reads return display-only dicts, so the escalation is scoped to
        # the read -- the [[sudo in computed reads]] pattern. Without it the
        # branded template raises AccessError -> 403 for non-admin members.
        for t in self.sudo().neon_track_ids.sorted(lambda r: (r.sequence, r.id)):
            cards.append({
                "name": t.name,
                "module_count": t.module_count,
                "is_gate": t.is_foundation_gate,
                "cert_label": t.sub_cert_type_id.name or "",
                "color": _NEON_TRACK_ACCENTS.get(t.code, "#6B21A8"),
                "description": t.description or "",
            })
        return cards

    def _neon_branding_stats(self):
        """Hero stats strip: tracks / modules / lessons / certs. Lessons =
        real content slides in the module bands (seq >= 1000), excluding the
        seq-0 orphan placeholders. Certs = 7 sub-certs + capstone = 8."""
        self.ensure_one()
        # sudo for the same reason as _neon_track_cards: frontend learners
        # lack ACL on neon.lms.track / certification.type.
        tracks = self.sudo().neon_track_ids
        lessons = self.env["slide.slide"].sudo().search_count([
            ("channel_id", "=", self.id),
            ("is_category", "=", False),
            ("sequence", ">=", 1000),
        ])
        certs = len(tracks.mapped("sub_cert_type_id")) + (
            1 if self.sudo().neon_capstone_cert_type_id else 0)
        return {
            "tracks": len(tracks),
            "modules": sum(tracks.mapped("module_count")),
            "lessons": lessons,
            "certs": certs,
        }

    def _neon_apply_branding_config(self):
        """Idempotent branding + publish step (called by the migration; also
        the single code path the smoke exercises). Per P7g Gate 1:
        - flag neon_branded + publish the channel to MEMBERS (enrolled
          learners only -- NOT public-internet; enroll model unchanged)
        - Responsible -> Robin Goneso (not OdooBot)
        - clear the stock cover image (the hero is a CSS gradient, no photo)
        - publish the real lessons + section headers (currently unpublished)
        - delete the 17 'MNN content' seq-0 orphan placeholders
        """
        Slide = self.env["slide.slide"].sudo()
        robin = self.env["res.users"].sudo().search(
            [("login", "=", "robin@neonhiring.co.zw")], limit=1)
        for ch in self:
            vals = {
                "neon_branded": True,
                "visibility": "members",
                "is_published": True,
            }
            if robin:
                vals["user_id"] = robin.id
            if ch.image_1920:
                vals["image_1920"] = False
            ch.write(vals)
            content = Slide.search([
                ("channel_id", "=", ch.id),
                ("is_category", "=", False),
                ("sequence", ">=", 1000),
                ("is_published", "=", False),
            ])
            if content:
                content.write({"is_published": True})
            secs = Slide.search([
                ("channel_id", "=", ch.id),
                ("is_category", "=", True),
                ("is_published", "=", False),
            ])
            if secs:
                secs.write({"is_published": True})
            orphans = Slide.search([
                ("channel_id", "=", ch.id),
                ("is_category", "=", False),
                ("sequence", "<", 1000),
            ]).filtered(lambda s: _NEON_ORPHAN_RE.match(s.name or ""))
            if orphans:
                orphans.unlink()
        return True

    # ================================================================
    # P7j (item 1) -- slide / channel cover image
    # ================================================================
    def _get_placeholder_filename(self, field):
        """Cover placeholder for neon_branded channels = the approved Neon
        event image, not the stock channel_type='training' coffee-mug.
        slide.slide._get_placeholder_filename delegates to the channel, so
        this one override covers all 237 lesson slides + the channel card +
        any future slide with no cover image (zero DB writes). Non-branded
        channels keep the stock website_slides default via super()."""
        image_fields = ["image_%s" % size
                        for size in (1920, 1024, 512, 256, 128)]
        if self.neon_branded and field in image_fields:
            return "neon_lms/static/src/img/neon_slide_cover.jpg"
        return super()._get_placeholder_filename(field)
