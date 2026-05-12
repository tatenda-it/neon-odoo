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
        return super().write(vals)
