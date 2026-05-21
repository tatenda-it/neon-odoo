# -*- coding: utf-8 -*-
"""
P7a.M12 -- "Who can do X" query wizard.

Robin's data-analytics framing made operational. Operator picks
one or more required cert types, optionally a level (when the
selected types share a tiered skill_level_mode), and toggles
soft-criteria flags (include cross-competency demonstrators,
include pending verification, include suspended). The wizard
returns matching res.users with badges indicating which path
(formal cert vs cross-competency) makes them eligible.

DP6 (gate-1): performance smoke asserts response under 500ms.
Production user count ~15; ORM cost trivial.

DP8 (gate-1): sales-tier MAY use Find Qualified User (read-only
search). The wizard ACL grants training_user/signoff/admin
plus finance_sales for the dispatch-staffing flow.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_LEVEL_FILTER_NA = "any"


class NeonTrainingFindQualifiedUserWizard(models.TransientModel):
    _name = "neon.training.find_qualified_user_wizard"
    _description = "Find Qualified User Search"

    # ============================================================
    # Input criteria
    # ============================================================
    cert_type_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_training_find_qualified_wizard_cert_type_rel",
        "wizard_id",
        "cert_type_id",
        string="Required Certifications",
        help="Pick one or more cert types. The search returns "
        "users who hold an active cert for EACH selected type "
        "(AND match). Use cross-competency softening to also "
        "include users who have a documented demonstration.",
    )
    required_level = fields.Selection(
        [
            (_LEVEL_FILTER_NA, "Any level"),
            # Binary mode values.
            ("pass",       "Pass (binary)"),
            # Tiered_3 mode values.
            ("basic",      "Basic (tier 1)"),
            ("standard",   "Standard (tier 2)"),
            ("expert",     "Expert (tier 3)"),
            # Custom mode values (role tier).
            ("lead_tech",  "Lead Tech (custom)"),
            ("tech",       "Tech (custom)"),
            ("runner",     "Runner (custom)"),
            ("driver",     "Driver (custom)"),
        ],
        string="Required Level",
        default=_LEVEL_FILTER_NA,
        help="Filter to certs at this exact level. 'Any' "
        "treats all active certs as matches regardless of "
        "level value. Values come from the same enum as the "
        "certification model: binary (pass/fail), tiered_3 "
        "(basic/standard/expert), custom (lead_tech/tech/"
        "runner/driver).",
    )
    include_cross_competency = fields.Boolean(
        string="Include Cross-Competency Demonstrators",
        default=False,
        help="When True, users with a documented cross-"
        "competency observation for any selected cert type "
        "appear in results (badge: 'softened').",
    )
    include_pending = fields.Boolean(
        string="Include Pending Verification",
        default=False,
        help="When True, users whose cert for the selected "
        "type(s) is in 'pending_verification' state appear "
        "(badge: 'unverified').",
    )
    include_suspended = fields.Boolean(
        string="Include Suspended",
        default=False,
        help="When True, users whose cert is suspended also "
        "appear (badge: 'suspended'). Use for audit purposes; "
        "suspended users are NOT operationally qualified.",
    )

    # ============================================================
    # Results
    # ============================================================
    matched_user_ids = fields.Many2many(
        "res.users",
        "neon_training_find_qualified_wizard_user_rel",
        "wizard_id",
        "user_id",
        string="Matched Users",
        readonly=True,
        help="Users matching ALL selected criteria. Empty until "
        "Search is clicked.",
    )
    result_summary = fields.Html(
        string="Result Summary",
        readonly=True,
        sanitize=False,
        compute="_compute_result_summary",
        store=True,
    )

    @api.depends("matched_user_ids", "cert_type_ids")
    def _compute_result_summary(self):
        for rec in self:
            if not rec.cert_type_ids:
                rec.result_summary = (
                    "<p class='text-muted'>"
                    "Pick one or more cert types, set optional "
                    "filters, then click Search."
                    "</p>")
                continue
            n = len(rec.matched_user_ids)
            cert_names = ", ".join(rec.cert_type_ids.mapped("name"))
            if n == 0:
                rec.result_summary = (
                    "<div class='alert alert-warning'>"
                    "<strong>No matches.</strong> No users "
                    "currently hold (active) certs for: "
                    "<em>%s</em>. Consider relaxing the filters "
                    "or adding cross-competency demonstrators."
                    "</div>") % cert_names
                continue
            rec.result_summary = (
                "<div class='alert alert-success'>"
                "<strong>%d user%s</strong> match the criteria: "
                "<em>%s</em>."
                "</div>") % (n, "" if n == 1 else "s", cert_names)

    # ============================================================
    # Actions
    # ============================================================
    def action_search(self):
        """Resolve matched_user_ids based on input criteria.
        Sudo on the cert + cc reads -- the wizard is opened by
        any tier from training_user upward, including finance_
        sales. Cert + cross_competency reads need ACL bypass for
        the cross-tier search to work uniformly.
        """
        self.ensure_one()
        if not self.cert_type_ids:
            raise UserError(_(
                "Pick at least one cert type before searching."))

        Cert = self.env["neon.training.certification"].sudo()
        CC = self.env["neon.training.cross_competency"].sudo()

        # Build the state filter.
        states = ["active"]
        if self.include_pending:
            states.append("pending_verification")
        if self.include_suspended:
            states.append("suspended")

        # Find users holding ALL selected cert types (AND match).
        # Per-type search + intersection. Keeps the SQL simple
        # and handles the level filter consistently.
        matched_via_cert = None
        for cert_type in self.cert_type_ids:
            cert_domain = [
                ("type_id", "=", cert_type.id),
                ("state", "in", states),
            ]
            if self.required_level != _LEVEL_FILTER_NA:
                cert_domain.append(
                    ("level", "=", self.required_level))
            certs = Cert.search(cert_domain)
            users_for_type = certs.mapped("user_id")
            if matched_via_cert is None:
                matched_via_cert = users_for_type
            else:
                matched_via_cert &= users_for_type

        matched_via_cert = (
            matched_via_cert
            or self.env["res.users"].sudo())

        # Optional: cross-competency union.
        matched_via_cc = self.env["res.users"].sudo()
        if self.include_cross_competency:
            cc_records = CC.search([
                ("certification_type_id", "in",
                 self.cert_type_ids.ids),
            ])
            # User must have a CC for EACH selected cert type
            # (AND match, parallel to the cert path). Otherwise
            # a user with one CC for one type would match,
            # which dilutes the criterion.
            for cert_type in self.cert_type_ids:
                cc_for_type = cc_records.filtered(
                    lambda c: c.certification_type_id == cert_type)
                users_for_type = cc_for_type.mapped("user_id")
                if not matched_via_cc:
                    matched_via_cc = users_for_type
                else:
                    matched_via_cc &= users_for_type

        all_matched = matched_via_cert | matched_via_cc
        self.matched_user_ids = [(6, 0, all_matched.ids)]
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Find Qualified User"),
            "res_model": "neon.training.find_qualified_user_wizard",
            "view_mode": "form",
            "target":    "new",
            "res_id":    self.id,
        }

    def action_reset(self):
        """Clear all input + result fields. Returns the wizard
        in its empty state.
        """
        self.ensure_one()
        self.write({
            "cert_type_ids":           [(5, 0, 0)],
            "required_level":          _LEVEL_FILTER_NA,
            "include_cross_competency": False,
            "include_pending":          False,
            "include_suspended":        False,
            "matched_user_ids":        [(5, 0, 0)],
        })
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Find Qualified User"),
            "res_model": "neon.training.find_qualified_user_wizard",
            "view_mode": "form",
            "target":    "new",
            "res_id":    self.id,
        }

    @api.model
    def action_open_wizard(self):
        """Entry point invoked by the menu. Materialises an empty
        wizard and opens the form.
        """
        rec = self.sudo().create({})
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Find Qualified User"),
            "res_model": "neon.training.find_qualified_user_wizard",
            "view_mode": "form",
            "target":    "new",
            "res_id":    rec.id,
        }
