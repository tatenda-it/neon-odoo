# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    is_venue = fields.Boolean(
        string="Is a Venue",
        default=False,
        help="Mark this partner as a venue. Enables room sub-records and "
        "filters this partner into venue selection on Commercial Jobs.",
    )
    # P9.M9.1 (D6): provenance of partner_latitude/partner_longitude.
    # 'geocoded' = set by base_geolocalize's Nominatim lookup;
    # 'manual' = user pasted/edited coords directly. Drives the
    # "Manually pinned" badge + the snapshot-restore in write() that
    # protects a manual pin from base_geolocalize's auto-zero on
    # address change. partner_latitude/longitude themselves are plain
    # editable Floats from `base` (NOT readonly at field or view level
    # -- discovery confirmed), so no readonly override is needed.
    coords_source = fields.Selection(
        [("geocoded", "Geocoded"), ("manual", "Manually pinned")],
        string="Coordinates Source",
        default="geocoded",
    )
    room_ids = fields.One2many(
        "venue.room",
        "venue_id",
        string="Rooms",
    )
    room_count = fields.Integer(
        string="Room Count",
        compute="_compute_room_count",
    )

    # === Rapid Ops eligibility (P2.M8) ===
    # Trusted-client fast-path: partners flagged here can have their
    # Commercial Jobs activated via action_rapid_activate, which bypasses
    # the SOFT capacity-gate checks while still enforcing the HARD ones
    # (date/venue/room + crew double-booking).
    commercial_job_master_ids = fields.One2many(
        "commercial.job.master",
        "partner_id",
        string="Master Contracts",
    )
    is_rapid_ops_eligible_manual = fields.Boolean(
        string="Rapid Ops Eligible (manual)",
        default=False,
        tracking=True,
        help="Manager-only override. When set, this partner is treated as a "
        "trusted client and Sales can activate their jobs via the Rapid "
        "Activate fast path.",
    )
    has_active_master_contract = fields.Boolean(
        string="Has Active Master Contract",
        compute="_compute_has_active_master_contract",
        store=True,
    )
    is_rapid_ops_eligible = fields.Boolean(
        string="Rapid Ops Eligible",
        compute="_compute_is_rapid_ops_eligible",
        store=True,
        help="True when this partner can be rapid-activated by Sales. "
        "Either the manual flag is set OR there is an active master "
        "contract on file.",
    )

    @api.depends("room_ids")
    def _compute_room_count(self):
        for rec in self:
            rec.room_count = len(rec.room_ids)

    @api.depends("commercial_job_master_ids", "commercial_job_master_ids.state")
    def _compute_has_active_master_contract(self):
        for rec in self:
            rec.has_active_master_contract = any(
                m.state == "active" for m in rec.commercial_job_master_ids
            )

    @api.depends("is_rapid_ops_eligible_manual", "has_active_master_contract")
    def _compute_is_rapid_ops_eligible(self):
        for rec in self:
            rec.is_rapid_ops_eligible = (
                rec.is_rapid_ops_eligible_manual or rec.has_active_master_contract
            )

    # ============================================================
    # === Write guard — only managers can toggle the manual flag
    # The view also hides the field for non-managers via groups=, but
    # the API-side guard catches scripted writes / RPC calls that
    # bypass the form.
    # ============================================================
    # Address fields whose change makes base_geolocalize auto-zero coords.
    _GEO_ADDR_FIELDS = frozenset({
        "street", "street2", "city", "zip", "state_id", "country_id",
    })

    def write(self, vals):
        if "is_rapid_ops_eligible_manual" in vals:
            user = self.env.user
            if not (
                self.env.su
                or user.has_group("neon_jobs.group_neon_jobs_manager")
            ):
                raise UserError(_(
                    "Only Managers can change the Rapid Ops eligibility flag."
                ))
        # P9.M9.1 (D6): a direct lat/long edit marks the pin 'manual'
        # (unless the write already states the source -- e.g. the
        # geo_localize override below sets 'geocoded' afterwards).
        if (("partner_latitude" in vals or "partner_longitude" in vals)
                and "coords_source" not in vals):
            vals = dict(vals, coords_source="manual")
        # P9.M9.1 (D6 snapshot-restore): base_geolocalize.write() zeroes
        # coords on any address change. Protect a MANUAL pin: snapshot
        # before super, restore after. (Geocoded pins are intentionally
        # left to base's zero-on-address-change behaviour.)
        addr_change = bool(self._GEO_ADDR_FIELDS & set(vals))
        coords_in_vals = (
            "partner_latitude" in vals or "partner_longitude" in vals)
        snapshot = {}
        if addr_change and not coords_in_vals:
            for rec in self:
                if rec.coords_source == "manual" and (
                        rec.partner_latitude or rec.partner_longitude):
                    snapshot[rec.id] = (
                        rec.partner_latitude, rec.partner_longitude)
        res = super().write(vals)
        for rec in self:
            snap = snapshot.get(rec.id)
            if snap:
                # super(ResPartner, rec): re-apply coords WITHOUT
                # re-entering this override (no recursion); base sees
                # coords-only vals so it won't re-zero.
                super(ResPartner, rec).write({
                    "partner_latitude": snap[0],
                    "partner_longitude": snap[1],
                    "coords_source": "manual",
                })
        return res

    def geo_localize(self):
        """Override base_geolocalize: after a successful geocode, stamp
        coords_source='geocoded' (the clean reset path -- clicking
        Geolocate undoes a manual pin). super() raises + rolls back if
        any partner fails to resolve, so this only stamps on full
        success. (super's internal coord write transiently trips the
        'manual' flip above; the stamp here corrects it.)"""
        res = super().geo_localize()
        located = self.filtered(
            lambda p: p.partner_latitude or p.partner_longitude)
        if located:
            located.write({"coords_source": "geocoded"})
        return res

    def action_geolocate_venue(self):
        """Force-geocode the selected venue(s) via base_geolocalize's
        Nominatim/OSM provider (D1). force_geo_localize re-geocodes even
        if coords already exist. geo_localize() raises a UserError
        listing any partner it couldn't resolve -- surfaced as-is."""
        venues = self.filtered("is_venue")
        if not venues:
            return False
        venues.with_context(force_geo_localize=True).geo_localize()
        return True
