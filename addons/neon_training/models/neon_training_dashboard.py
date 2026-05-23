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

    # P7a pre-deploy fix #4 (21 May 2026): override display_name
    # so the breadcrumb reads "Training Compliance Dashboard"
    # instead of the default Odoo fallback "neon.training
    # .dashboard,<id>". The TransientModel materialises a fresh
    # record per dashboard open, so the id varies (29/37/41/etc.)
    # -- making the default fallback look like debug noise.
    # Constant display_name masks the ephemeral id.
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = _("Training Compliance Dashboard")

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
    # Phase 7b M11 -- onboarding counters
    #
    # Two non-stored computed Integers. Read from neon.onboarding.
    # candidate via defensive env.get pattern so this Phase 7a
    # model stays installable when neon_onboarding is not present.
    # ============================================================
    candidates_in_cert_collection = fields.Integer(
        string="In Cert Collection",
        compute="_compute_onboarding_counters",
        store=False,
        help="Candidates currently in cert_collection state. "
             "Returns 0 if neon_onboarding is not installed.",
    )
    candidates_in_probationary = fields.Integer(
        string="Probationary",
        compute="_compute_onboarding_counters",
        store=False,
        help="Candidates currently in probationary state. "
             "Returns 0 if neon_onboarding is not installed.",
    )

    # ============================================================
    # Phase 7e M11 -- LMS progression counters
    #
    # Four non-stored Integer / Char computes. Defensive env.get
    # pattern -- counters return 0 / empty if Phase 7e not
    # installed.
    # ============================================================
    lms_active_enrollments = fields.Integer(
        string="LMS Active Enrollments",
        compute="_compute_lms_counters",
        store=False,
        help="Count of enrollments where neon_state is in "
             "('in_progress', 'completed'). Returns 0 if "
             "neon_lms is not installed.",
    )
    lms_pending_capstone = fields.Integer(
        string="LMS Pending Capstone",
        compute="_compute_lms_counters",
        store=False,
        help="Count of enrollments at neon_state='completed' "
             "but capstone cert not yet issued (cross-"
             "milestone drift detector). Returns 0 if "
             "neon_lms is not installed.",
    )
    lms_authorities_granted_30d = fields.Integer(
        string="LMS Authorities Granted (30 days)",
        compute="_compute_lms_counters",
        store=False,
        help="Count of operating authorities granted via "
             "LMS track certification in the last 30 days. "
             "Counted via track.completion records "
             "transitioning to 'certified' state with "
             "associated authority grants. Returns 0 if "
             "neon_lms is not installed.",
    )
    lms_track_cert_distribution = fields.Char(
        string="LMS Track Cert Distribution",
        compute="_compute_lms_counters",
        store=False,
        help="Per-track sub-cert count summary "
             "(e.g., 'Foundations: 5, Audio: 3, ...'). "
             "Returns empty string if neon_lms not installed.",
    )

    # ============================================================
    # Phase 7c M6 -- External Training counters + drill-through.
    # Same defensive env.get pattern as the Phase 7e M11 LMS
    # counters above -- if neon_external_training is not
    # installed, both counters return 0 and the drill-through
    # actions return False (the form view's invisible-on-False
    # button behaviour hides the click target).
    # ============================================================
    external_bookings_upcoming = fields.Integer(
        string="External Bookings (Upcoming 30d)",
        compute="_compute_external_training_counters",
        store=False,
        help="Count of external-training bookings in "
             "('booked', 'pending_approval') with "
             "scheduled_date in the next 30 days. Returns 0 "
             "if neon_external_training is not installed.",
    )
    external_bookings_pending_completion = fields.Integer(
        string="External Bookings (Pending Completion)",
        compute="_compute_external_training_counters",
        store=False,
        help="Count of external-training bookings stuck at "
             "'attended' for more than 7 days -- pending "
             "completion verification. Returns 0 if "
             "neon_external_training is not installed.",
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

    # ============================================================
    # Phase 7b M11 -- onboarding compute + drill-through.
    # ============================================================
    def _compute_onboarding_counters(self):
        """Defensive lookup: neon.onboarding.candidate may not
        exist on this DB if neon_onboarding isn't installed.
        env.get returns None in that case; counters return 0
        so the dashboard renders cleanly either way.
        """
        Candidate = self.env.get("neon.onboarding.candidate")
        for rec in self:
            if Candidate is None:
                rec.candidates_in_cert_collection = 0
                rec.candidates_in_probationary = 0
                continue
            rec.candidates_in_cert_collection = (
                Candidate.sudo().search_count([
                    ("state", "=", "cert_collection"),
                ]))
            rec.candidates_in_probationary = (
                Candidate.sudo().search_count([
                    ("state", "=", "probationary"),
                ]))

    def action_view_candidates_cert_collection(self):
        """Drill-through to candidates filtered by state=
        cert_collection. Returns False if neon_onboarding is
        not installed (button stays inert).
        """
        self.ensure_one()
        Candidate = self.env.get("neon.onboarding.candidate")
        if Candidate is None:
            return False
        return self._drill(
            "neon_onboarding.action_neon_onboarding_candidate",
            domain=[("state", "=", "cert_collection")],
            name=_("Candidates in Cert Collection"))

    def action_view_candidates_probationary(self):
        self.ensure_one()
        Candidate = self.env.get("neon.onboarding.candidate")
        if Candidate is None:
            return False
        return self._drill(
            "neon_onboarding.action_neon_onboarding_candidate",
            domain=[("state", "=", "probationary")],
            name=_("Candidates in Probationary"))

    # ============================================================
    # Phase 7e M11 -- LMS counters + drill-through.
    # ============================================================
    def _compute_lms_counters(self):
        """Defensive: neon.lms.enrollment + track.completion +
        operating.authority may not exist if Phase 7e isn't
        installed. env.get returns None; counters default to
        0 / empty string.
        """
        Enrollment = self.env.get("slide.channel.partner")
        TrackComp = self.env.get("neon.lms.track.completion")
        Track = self.env.get("neon.lms.track")
        for rec in self:
            if Enrollment is None or TrackComp is None:
                rec.lms_active_enrollments = 0
                rec.lms_pending_capstone = 0
                rec.lms_authorities_granted_30d = 0
                rec.lms_track_cert_distribution = ""
                continue
            # Active enrollments.
            rec.lms_active_enrollments = (
                Enrollment.sudo().search_count([
                    ("neon_state", "in",
                     ("in_progress", "completed")),
                ]))
            # Pending capstone: state=completed AND no
            # capstone cert linked.
            rec.lms_pending_capstone = (
                Enrollment.sudo().search_count([
                    ("neon_state", "=", "completed"),
                    ("neon_capstone_cert_id", "=", False),
                ]))
            # Authorities granted in last 30 days: count
            # track_completion records transitioned to
            # certified state with associated authorities.
            cutoff_30d = (
                fields.Datetime.now() - timedelta(days=30))
            recent_certified = TrackComp.sudo().search([
                ("state", "=", "certified"),
                ("certification_date", ">=", cutoff_30d),
            ])
            # Sum authorities across all recent certifications.
            rec.lms_authorities_granted_30d = sum(
                len(tc.track_id.operating_authority_ids)
                for tc in recent_certified)
            # Per-track cert distribution.
            if Track is None:
                rec.lms_track_cert_distribution = ""
                continue
            tracks = Track.sudo().search([])
            parts = []
            for trk in tracks:
                count = TrackComp.sudo().search_count([
                    ("track_id", "=", trk.id),
                    ("state", "=", "certified"),
                ])
                parts.append("%s: %d" % (trk.name, count))
            rec.lms_track_cert_distribution = ", ".join(parts)

    def action_view_lms_active_enrollments(self):
        self.ensure_one()
        Enrollment = self.env.get("slide.channel.partner")
        if Enrollment is None:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("LMS Active Enrollments"),
            "res_model": "slide.channel.partner",
            "view_mode": "tree,form",
            "domain": [
                ("neon_state", "in",
                 ("in_progress", "completed")),
            ],
            "context": {},
        }

    def action_view_lms_pending_capstone(self):
        self.ensure_one()
        Enrollment = self.env.get("slide.channel.partner")
        if Enrollment is None:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("LMS Pending Capstone"),
            "res_model": "slide.channel.partner",
            "view_mode": "tree,form",
            "domain": [
                ("neon_state", "=", "completed"),
                ("neon_capstone_cert_id", "=", False),
            ],
            "context": {},
        }

    def action_view_lms_recent_authorities(self):
        self.ensure_one()
        TrackComp = self.env.get(
            "neon.lms.track.completion")
        if TrackComp is None:
            return False
        cutoff_30d = (
            fields.Datetime.now() - timedelta(days=30))
        return {
            "type": "ir.actions.act_window",
            "name": _("LMS Track Certifications (30 days)"),
            "res_model": "neon.lms.track.completion",
            "view_mode": "tree,form",
            "domain": [
                ("state", "=", "certified"),
                ("certification_date", ">=", cutoff_30d),
            ],
            "context": {},
        }

    def action_view_lms_track_distribution(self):
        self.ensure_one()
        TrackComp = self.env.get(
            "neon.lms.track.completion")
        if TrackComp is None:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("LMS Track Completions (Certified)"),
            "res_model": "neon.lms.track.completion",
            "view_mode": "tree,form",
            "domain": [("state", "=", "certified")],
            "context": {"group_by": "track_id"},
        }

    # ============================================================
    # Phase 7c M6 -- External Training counters compute +
    # drill-through actions.
    # ============================================================
    def _compute_external_training_counters(self):
        Booking = self.env.get(
            "neon.external.training.booking")
        today = fields.Date.context_today(self)
        thirty_days = today + timedelta(days=30)
        seven_days_ago = today - timedelta(days=7)
        for rec in self:
            if Booking is None:
                rec.external_bookings_upcoming = 0
                rec.external_bookings_pending_completion = 0
                continue
            rec.external_bookings_upcoming = (
                Booking.sudo().search_count([
                    ("state", "in",
                     ("booked", "pending_approval")),
                    ("scheduled_date", ">=", today),
                    ("scheduled_date", "<=", thirty_days),
                ]))
            rec.external_bookings_pending_completion = (
                Booking.sudo().search_count([
                    ("state", "=", "attended"),
                    ("date_attended", "<=", seven_days_ago),
                ]))

    def action_view_upcoming_external(self):
        self.ensure_one()
        Booking = self.env.get(
            "neon.external.training.booking")
        if Booking is None:
            return False
        today = fields.Date.context_today(self)
        thirty_days = today + timedelta(days=30)
        return {
            "type": "ir.actions.act_window",
            "name": _("External Bookings (Upcoming 30d)"),
            "res_model": "neon.external.training.booking",
            "view_mode": "kanban,tree,form",
            "domain": [
                ("state", "in",
                 ("booked", "pending_approval")),
                ("scheduled_date", ">=", today),
                ("scheduled_date", "<=", thirty_days),
            ],
            "context": {},
        }

    def action_view_pending_completion_external(self):
        self.ensure_one()
        Booking = self.env.get(
            "neon.external.training.booking")
        if Booking is None:
            return False
        today = fields.Date.context_today(self)
        seven_days_ago = today - timedelta(days=7)
        return {
            "type": "ir.actions.act_window",
            "name": _(
                "External Bookings (Pending Completion)"),
            "res_model": "neon.external.training.booking",
            "view_mode": "kanban,tree,form",
            "domain": [
                ("state", "=", "attended"),
                ("date_attended", "<=", seven_days_ago),
            ],
            "context": {},
        }

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
