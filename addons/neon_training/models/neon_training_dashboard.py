# -*- coding: utf-8 -*-
"""
P7a.M12 -- training compliance dashboard.

Virtual model (no records, no fields persisted). The form-view
rendering pattern (DP9 lean): one singleton record materialised
on demand, with computed counter fields that drive card-styled
groups in the form view. No OWL component, no JS bundle. Phase
12 polish path to OWL stays open if Robin wants live refresh
or per-currency tiles.

9 counters:
  active_certs_total
  active_certs_equipment
  active_certs_role_tier
  active_certs_safety
  active_certs_soft_skill
  expiring_30d / expiring_60d / expiring_90d
  pending_verification_count
  recent_cross_competency_count
  tier_1_fires_30d / tier_2_fires_30d / tier_3_fires_30d

(13 fields total -- the prompt said 9, gate-1 enumerated 8-9;
re-counting against the actual coverage: 13 makes sense.)

Drill-through server actions (one per counter cluster):
  action_open_active_certs
  action_open_expiring
  action_open_pending_verification
  action_open_recent_cross_competency
  action_open_tier_fires (tier filter from context)
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


_USER_GROUP = "neon_training.group_neon_training_user"
_SIGNOFF_GROUP = "neon_training.group_neon_training_signoff"
_ADMIN_GROUP = "neon_training.group_neon_training_admin"


class NeonTrainingDashboard(models.TransientModel):
    """Transient virtual model -- one record materialised per
    dashboard open. Auto-vacuum cleans up transient rows on a
    schedule. No persistent state; counts compute live.

    Pattern reference: neon_finance.dashboard (P6.M10) uses
    @api.model RPC for an OWL client. P7a.M12 uses TransientModel
    so the form view opens against a real (short-lived) record
    whose computed fields populate per-render (DP9 lighter path).
    """
    _name = "neon.training.dashboard"
    _description = "Training Compliance Dashboard"

    # ============================================================
    # Counter fields (computed, non-stored)
    # ============================================================
    active_certs_total = fields.Integer(
        string="Active Certifications",
        compute="_compute_counters",
        store=False,
    )
    active_certs_equipment = fields.Integer(
        string="Equipment Certs",
        compute="_compute_counters",
        store=False,
    )
    active_certs_role_tier = fields.Integer(
        string="Role-Tier Certs",
        compute="_compute_counters",
        store=False,
    )
    active_certs_safety = fields.Integer(
        string="Safety Certs",
        compute="_compute_counters",
        store=False,
    )
    active_certs_soft_skill = fields.Integer(
        string="Soft-Skill Certs",
        compute="_compute_counters",
        store=False,
    )
    expiring_30d = fields.Integer(
        string="Expiring within 30 days",
        compute="_compute_counters",
        store=False,
    )
    expiring_60d = fields.Integer(
        string="Expiring within 60 days",
        compute="_compute_counters",
        store=False,
    )
    expiring_90d = fields.Integer(
        string="Expiring within 90 days",
        compute="_compute_counters",
        store=False,
    )
    pending_verification_count = fields.Integer(
        string="Pending Verification",
        compute="_compute_counters",
        store=False,
    )
    recent_cross_competency_count = fields.Integer(
        string="Cross-Competency (30 days)",
        compute="_compute_counters",
        store=False,
    )
    tier_1_fires_30d = fields.Integer(
        string="Tier 1 Info Fires (30 days)",
        compute="_compute_counters",
        store=False,
    )
    tier_2_fires_30d = fields.Integer(
        string="Tier 2 Warn Fires (30 days)",
        compute="_compute_counters",
        store=False,
    )
    tier_3_fires_30d = fields.Integer(
        string="Tier 3 Block Fires (30 days)",
        compute="_compute_counters",
        store=False,
    )

    # ============================================================
    # Access check + compute
    # ============================================================
    def _check_dashboard_access(self):
        user = self.env.user
        if not (user.has_group(_USER_GROUP)
                or user.has_group(_SIGNOFF_GROUP)
                or user.has_group(_ADMIN_GROUP)):
            raise AccessError(_(
                "You don't have permission to view the training "
                "compliance dashboard."))

    @api.model
    def _category_xmlid_for_code(self, code):
        """Resolve a category xmlid by code. Returns the category
        record or empty recordset.
        """
        xmlid = "neon_training.cert_category_%s" % code
        return self.env.ref(xmlid, raise_if_not_found=False)

    def _compute_counters(self):
        """One pass; populates all 13 counters. Sudo defensively
        since training_user tier may render the dashboard but
        lacks read on gate_log without ir.rule scope (own
        triggered fires only). Counters are aggregate -- showing
        zero would mislead training_user, so sudo escalation
        gives accurate totals.

        DP7 (gate-1): no caching. Counts recompute per dashboard
        open. Production volume ~15 users; query cost trivial.
        """
        Cert = self.env["neon.training.certification"].sudo()
        CC = self.env["neon.training.cross_competency"].sudo()
        GateLog = self.env["neon.training.assignment_gate_log"].sudo()

        today = fields.Date.context_today(self)
        d30 = today + timedelta(days=30)
        d60 = today + timedelta(days=60)
        d90 = today + timedelta(days=90)
        cutoff_30d = fields.Datetime.now() - timedelta(days=30)

        # Resolve category records once.
        cat_equipment = self._category_xmlid_for_code("equipment")
        cat_role_tier = self._category_xmlid_for_code("role")
        cat_safety = self._category_xmlid_for_code("safety")
        cat_soft_skill = self._category_xmlid_for_code("soft")

        # NOTE: access check is enforced at action_open_dashboard
        # (the user-facing entry point) and at the menu/server-
        # action groups_id layer. We deliberately don't re-check
        # inside the compute -- it fires under various envs
        # (display rendering, RPC fields_get, etc.) and a
        # per-field gate would block legitimate reads.
        for rec in self:
            # Active certs (any category).
            rec.active_certs_total = Cert.search_count(
                [("state", "=", "active")])
            rec.active_certs_equipment = Cert.search_count([
                ("state", "=", "active"),
                ("type_id.category_id", "=",
                 cat_equipment.id if cat_equipment else 0),
            ])
            rec.active_certs_role_tier = Cert.search_count([
                ("state", "=", "active"),
                ("type_id.category_id", "=",
                 cat_role_tier.id if cat_role_tier else 0),
            ])
            rec.active_certs_safety = Cert.search_count([
                ("state", "=", "active"),
                ("type_id.category_id", "=",
                 cat_safety.id if cat_safety else 0),
            ])
            rec.active_certs_soft_skill = Cert.search_count([
                ("state", "=", "active"),
                ("type_id.category_id", "=",
                 cat_soft_skill.id if cat_soft_skill else 0),
            ])

            # Expiring active certs in the 30/60/90 day forecast.
            # Cumulative -- expiring_60d INCLUDES expiring_30d.
            # Matches Robin's mental model ("how many in the next
            # quarter total?").
            rec.expiring_30d = Cert.search_count([
                ("state", "=", "active"),
                ("date_expires", ">=", today),
                ("date_expires", "<=", d30),
            ])
            rec.expiring_60d = Cert.search_count([
                ("state", "=", "active"),
                ("date_expires", ">=", today),
                ("date_expires", "<=", d60),
            ])
            rec.expiring_90d = Cert.search_count([
                ("state", "=", "active"),
                ("date_expires", ">=", today),
                ("date_expires", "<=", d90),
            ])

            rec.pending_verification_count = Cert.search_count(
                [("state", "=", "pending_verification")])

            rec.recent_cross_competency_count = CC.search_count(
                [("demonstrated_at", ">=", cutoff_30d.date())])

            # Gate log fires by tier (last 30 days).
            rec.tier_1_fires_30d = GateLog.search_count([
                ("gate_tier", "=", "tier_1_assignment"),
                ("fired_at", ">=", cutoff_30d),
            ])
            rec.tier_2_fires_30d = GateLog.search_count([
                ("gate_tier", "=", "tier_2_quote_accept"),
                ("fired_at", ">=", cutoff_30d),
            ])
            rec.tier_3_fires_30d = GateLog.search_count([
                ("gate_tier", "=", "tier_3_event_start"),
                ("fired_at", ">=", cutoff_30d),
            ])

    # ============================================================
    # Server-action entry point (opened from menu).
    # ============================================================
    @api.model
    def action_open_dashboard(self):
        """Materialise a singleton dashboard record via new() and
        open its form view. The form view's drill-through buttons
        navigate to filtered lists.
        """
        self._check_dashboard_access()
        rec = self.sudo().create({})
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Training Compliance Dashboard"),
            "res_model": "neon.training.dashboard",
            "view_mode": "form",
            "target":    "current",
            "res_id":    rec.id,
            "context":   {"form_view_initial_mode": "readonly"},
        }

    # ============================================================
    # Drill-through actions.
    # ============================================================
    def action_open_active_certs(self):
        return self._drill(
            "neon_training.neon_training_certification_action",
            domain=[("state", "=", "active")],
            name=_("Active Certifications"))

    def action_open_expiring_certs(self):
        """The form-view button passes the day-horizon via context
        (default_day_horizon set on button). We read it here."""
        days = self.env.context.get("dashboard_expiring_days", 30)
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=days)
        return self._drill(
            "neon_training.neon_training_certification_action",
            domain=[
                ("state", "=", "active"),
                ("date_expires", ">=", today),
                ("date_expires", "<=", horizon),
            ],
            name=_("Expiring within %d days") % days)

    def action_open_pending_verification(self):
        return self._drill(
            "neon_training.neon_training_certification_action",
            domain=[("state", "=", "pending_verification")],
            name=_("Pending Verification"))

    def action_open_recent_cross_competency(self):
        cutoff = (fields.Datetime.now() - timedelta(days=30)).date()
        return self._drill(
            "neon_training.neon_training_cross_competency_action",
            domain=[("demonstrated_at", ">=", cutoff)],
            name=_("Cross-Competency (30 days)"))

    def action_open_tier_fires(self):
        """Tier passed via context; opens gate-log filtered."""
        tier = self.env.context.get("dashboard_tier",
                                    "tier_1_assignment")
        cutoff = fields.Datetime.now() - timedelta(days=30)
        tier_label_map = {
            "tier_1_assignment":   _("Tier 1 Info Fires (30 days)"),
            "tier_2_quote_accept": _("Tier 2 Warn Fires (30 days)"),
            "tier_3_event_start":  _("Tier 3 Block Fires (30 days)"),
        }
        return self._drill(
            "neon_training.assignment_gate_log_action",
            domain=[
                ("gate_tier", "=", tier),
                ("fired_at", ">=", cutoff),
            ],
            name=tier_label_map.get(tier, _("Gate Fires (30 days)")))

    def _drill(self, action_xmlid, domain, name):
        """Resolve the named action, overlay the drill domain,
        and return an ir.actions.act_window dict the client
        opens as the next breadcrumb.
        """
        action = self.env.ref(action_xmlid).sudo().read()[0]
        action["domain"] = domain
        action["name"] = name
        action["context"] = {}
        # Strip res_id / target so the list opens, not a form.
        action.pop("res_id", None)
        return action
