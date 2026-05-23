# -*- coding: utf-8 -*-
"""neon.external.training.vendor -- external training
provider (manufacturer, regulator, accreditation body).

Phase 7c M1. Pure reference data + chatter for vendor-level
notes. The booking model lands in M2 and points here via
M2O.
"""
from odoo import api, fields, models, _


class NeonExternalTrainingVendor(models.Model):
    _name = "neon.external.training.vendor"
    _description = "Neon External Training Vendor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name asc"

    name = fields.Char(
        required=True,
        tracking=True,
        help="Display name of the vendor / provider.",
    )
    contact_name = fields.Char(
        string="Contact Person",
        tracking=True,
    )
    contact_phone = fields.Char(
        string="Phone",
        tracking=True,
    )
    contact_email = fields.Char(
        string="Email",
        tracking=True,
    )
    website = fields.Char(tracking=True)
    address = fields.Text()
    country_id = fields.Many2one(
        "res.country",
        string="Country",
        default=lambda self: self._default_country(),
        tracking=True,
    )
    notes = fields.Text(
        help="Vendor-level free-form notes. Per-booking "
             "notes live on the booking record.",
    )
    active = fields.Boolean(default=True, tracking=True)
    booking_count = fields.Integer(
        string="Bookings",
        compute="_compute_booking_count",
        help="Count of external-training bookings pointing "
             "at this vendor (placeholder until the booking "
             "model ships in M2).",
    )

    _sql_constraints = [
        ("vendor_name_unique",
         "UNIQUE(name)",
         "Vendor name must be unique."),
    ]

    @api.model
    def _default_country(self):
        """Default to Zimbabwe when the base.zw ref resolves.
        Falls back to no default if base data is absent
        (e.g., very stripped install)."""
        zw = self.env.ref(
            "base.zw", raise_if_not_found=False)
        return zw.id if zw else False

    def _compute_booking_count(self):
        """M1 placeholder: booking model not shipped yet.
        M2 will replace this with a real search_count
        against neon.external.training.booking.vendor_id.
        """
        Booking = self.env.get(
            "neon.external.training.booking")
        if Booking is None:
            for rec in self:
                rec.booking_count = 0
            return
        for rec in self:
            rec.booking_count = Booking.sudo().search_count(
                [("vendor_id", "=", rec.id)])

    # ------------------------------------------------------------------
    # M5 -- smart-button handler for the Booking History card.
    # Opens the booking action filtered to this vendor.
    # ------------------------------------------------------------------
    def action_view_bookings(self):
        self.ensure_one()
        return {
            "name": _("Bookings -- %s") % self.name,
            "type": "ir.actions.act_window",
            "res_model": "neon.external.training.booking",
            "view_mode": "kanban,tree,form",
            "domain": [("vendor_id", "=", self.id)],
            "context": {"default_vendor_id": self.id},
        }
