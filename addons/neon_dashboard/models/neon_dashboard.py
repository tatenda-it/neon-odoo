# -*- coding: utf-8 -*-
"""Phase 8A.M1-M3 -- neon.dashboard model + default-layout seed helpers
+ get_dashboard_data RPC (M1 framework + M2 KPI + M3 Jobs block).

Architecture (locked at gate 1):

* One dashboard row per (user, dashboard_type), lazy-created on first
  load by ``get_or_create_for_user``.
* ``get_dashboard_data`` is the single RPC the OWL component calls;
  returns layout + KPI dict + jobs block + view-as options in one
  round trip. Mirrors the cash-flow-dashboard get_*_data pattern.
* Three-layer access enforcement (menu groups, server-action groups_id,
  ``_check_dashboard_access`` in this file). No HTTP controller --
  RPC-only.

⚠️ DECISION (M1, marker 1): RPC virtual-model architecture deviates
from the M1-M3 prompt's ``/neon/dashboard/data`` http.Controller. The
existing repo precedent (P5.M10 Workshop, P6.M10 Cash Flow -- both
live in prod) uses ``@api.model`` methods on the model itself called
from OWL via the ORM service. Documented at
reference_owl_dashboard_pattern.md. Three-layer enforcement holds.

⚠️ DECISION (M1, marker 2): no new ``group_neon_dashboard_*`` groups.
``_is_superuser`` reads ``neon_core.group_neon_superuser``;
``_default_dashboard_type_for_user`` walks the five existing tier
meta-groups. Cuts user-grant maintenance to zero -- neon_core's
post_init_hook already cascades robin@/munashe@/tatenda@/admin@/
lisar@/evrill@/ranganai@ into the right tier.

⚠️ DECISION (M1, marker 6): no ``user_id``-based XML grants in
security XML. The M1-M3 prompt's ``neon_partners.user_robin`` etc.
do not exist as stable XML IDs; neon_core's login-based assignment
is the project convention. See reference_odoo17_implied_ids_orm_vs_sql.

⚠️ DECISION (M1, marker 7): top-level menu (no parent) at sequence=5,
sitting above ``neon_jobs.menu_operations_root`` (40). Gate-1 locked.
"""
import base64
from collections import defaultdict
from datetime import date, datetime, time, timedelta
import logging

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


# ⚠️ DECISION (p8a-hygiene timezone): all dashboard datetime
# computations resolve "today" / "now" in Africa/Harare (UTC+2).
# Odoo stores datetimes UTC-naive; rendering and date arithmetic
# both shift through this helper. Per gate-1 lock: stored audit
# timestamps (last_refresh field) stay UTC; only computed
# queries + display strings use Harare.
HARARE_TZ = pytz.timezone("Africa/Harare")


_logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Tier-group XML ids -- single source of truth so every branch reads
# the same constants. All five live in neon_core (gate-1 locked).
# ----------------------------------------------------------------------
_GROUP_SUPERUSER = "neon_core.group_neon_superuser"
_GROUP_BOOKKEEPER = "neon_core.group_neon_bookkeeper"
_GROUP_SALES_REP = "neon_core.group_neon_sales_rep"
_GROUP_LEAD_TECH = "neon_core.group_neon_lead_tech"
_GROUP_CREW = "neon_core.group_neon_crew"
# P-HR-R3b C1 -- HR role-lens: extend the existing 5-role
# View-As mechanism with a sixth role 'hr'. RBAC RED-RAIL:
# 'hr' selectable ONLY by users in HR-tier or superuser.
# Both the View-As resolver AND every HR data branch re-check
# (defence-in-depth). Sales / Lead Tech / Bookkeeper / Crew
# can NOT see HR salaries / disciplinary / leave-detail.
_GROUP_HR_MANAGER = "hr.group_hr_manager"
_GROUP_NEON_HR_ADMIN = "neon_hr.group_neon_hr_admin"

_DASHBOARD_TYPES = [
    ("director", "Director"),
    ("sales", "Sales"),
    ("bookkeeper", "Bookkeeper"),
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
    ("hr", "HR"),
]
_DASHBOARD_TYPE_VALUES = {t[0] for t in _DASHBOARD_TYPES}

# DASH-DUALROLE-1 -- tier-group -> dashboard lens, in LANDING-PRIORITY
# order (first matching entry wins for the default landing lens).
# Bookkeeper ranks ABOVE HR so a dual-role Bookkeeper+HR user (e.g.
# Kudzai, uid 10) lands on Bookkeeper -- her primary role -- with HR one
# View-As switch away. Single-tier users are unaffected (only one entry
# matches them). Superuser is handled separately (all lenses). Both
# group_neon_hr_admin and hr.group_hr_manager grant the 'hr' lens; the
# dedup in _entitled_lenses_for_user keeps 'hr' once. 'tech' (crew) keeps
# its prior position below lead_tech.
#
# ⚠️ DECISION (DASH-DUALROLE-1): the prior resolver ranked HR ABOVE
# Bookkeeper and returned a SINGLE tier per user, so a dual-role
# Bookkeeper+HR user landed on HR and the View-As switcher only ever
# offered HR -- Bookkeeper was unreachable. This table +
# _entitled_lenses_for_user generalise the resolver to the UNION of a
# user's entitled lenses. Only the Bookkeeper/HR order is swapped vs the
# old ladder; every other tier keeps its relative position, so the
# single-tier landing lens is byte-identical to before.
_TIER_LENS_PRIORITY = [
    (_GROUP_BOOKKEEPER, "bookkeeper"),
    (_GROUP_NEON_HR_ADMIN, "hr"),
    (_GROUP_HR_MANAGER, "hr"),
    (_GROUP_LEAD_TECH, "lead_tech"),
    (_GROUP_CREW, "tech"),
    (_GROUP_SALES_REP, "sales"),
]

# ⚠️ DECISION (M3, marker 5): event-state -> mockup badge mapping.
# commercial.event.job has a 12-state machine (draft / planning /
# prep / ready_for_dispatch / dispatched / in_progress / strike /
# returned / completed / closed / cancelled / released). Mockup v2
# shows 5 buckets (PREP / READY / ACTIVE / PENDING / DONE). This
# table is the bridge. cancelled + released are excluded by the
# query, so they're not present here.
_STATE_BADGE = {
    "draft": ("PENDING", "grey"),
    "planning": ("PREP", "amber"),
    "prep": ("PREP", "amber"),
    "ready_for_dispatch": ("READY", "blue"),
    "dispatched": ("READY", "blue"),
    "in_progress": ("ACTIVE", "green"),
    "strike": ("ACTIVE", "green"),
    "returned": ("DONE", "grey"),
    "completed": ("DONE", "grey"),
    "closed": ("DONE", "grey"),
}


# ======================================================================
# Helper models -- default_layouts.xml seeds rows here on -i.
# ======================================================================
class NeonDashboardDefaultLayout(models.Model):
    """One row per dashboard_type. Holds the default ordered widget
    list applied to a freshly-lazy-created neon.dashboard via
    ``_seed_default_layout``. Stored data not user-editable -- changes
    via data/default_layouts.xml only (noupdate=1)."""

    _name = "neon.dashboard.default.layout"
    _description = "Default Widget Layout per Dashboard Type"
    _order = "dashboard_type"

    dashboard_type = fields.Selection(
        _DASHBOARD_TYPES, required=True, index=True,
    )
    layout_line_ids = fields.One2many(
        "neon.dashboard.default.layout.line", "default_layout_id",
        string="Default Lines",
    )

    _sql_constraints = [
        ("dashboard_type_unique",
         "unique(dashboard_type)",
         "Only one default layout per dashboard_type."),
    ]


class NeonDashboardDefaultLayoutLine(models.Model):
    _name = "neon.dashboard.default.layout.line"
    _description = "Default Layout Line (widget seed)"
    _order = "default_layout_id, order_index, id"

    default_layout_id = fields.Many2one(
        "neon.dashboard.default.layout",
        required=True, ondelete="cascade",
    )
    widget_key = fields.Char(required=True)
    visible = fields.Boolean(default=True)
    order_index = fields.Integer(default=0)
    size = fields.Selection(
        [("small", "Small"), ("medium", "Medium"), ("large", "Large")],
        default="medium",
    )


# ======================================================================
# Main model -- neon.dashboard.
# ======================================================================
class NeonDashboard(models.Model):
    _name = "neon.dashboard"
    _description = "Neon Dashboard Instance"
    _rec_name = "name"

    user_id = fields.Many2one(
        "res.users", required=True, ondelete="cascade",
        default=lambda self: self.env.user.id,
        index=True,
    )
    dashboard_type = fields.Selection(
        _DASHBOARD_TYPES, required=True, default="director", index=True,
    )
    name = fields.Char(compute="_compute_name", store=True)
    layout_ids = fields.One2many(
        "neon.dashboard.user.layout", "dashboard_id",
        string="Widget Layout",
    )
    last_refresh = fields.Datetime(default=fields.Datetime.now)
    # P8B.M4: once a user saves an Edit-Layout customization, this
    # flips True and the OWL view renders the unified single-container
    # grid (drag-reorderable) instead of the seeded 4-section layout.
    # Reset-to-defaults flips it back to False. New column on -u;
    # existing rows read False (NULL).
    is_customized = fields.Boolean(default=False)

    _sql_constraints = [
        ("user_type_unique",
         "unique(user_id, dashboard_type)",
         "A user can only have one dashboard of each type."),
    ]

    # ------------------------------------------------------------------
    # Identity + lazy create
    # ------------------------------------------------------------------
    @api.depends("user_id", "dashboard_type")
    def _compute_name(self):
        type_label_map = dict(_DASHBOARD_TYPES)
        for rec in self:
            label = type_label_map.get(rec.dashboard_type, "")
            if rec.user_id:
                rec.name = _("%(user)s's %(type)s Dashboard") % {
                    "user": rec.user_id.name, "type": label,
                }
            else:
                rec.name = label

    @api.model
    def get_or_create_for_user(self, user_id=None, dashboard_type=None):
        """Lazy-create a dashboard row for (user, type).

        Called by ``get_dashboard_data`` on every load; idempotent --
        returns existing row if one matches. Used with sudo() inside
        the RPC so a freshly-created user without write access on
        ``neon.dashboard`` can still receive a row.
        """
        user_id = user_id or self.env.user.id
        if dashboard_type is None:
            dashboard_type = self._default_dashboard_type_for_user(user_id)
        if dashboard_type not in _DASHBOARD_TYPE_VALUES:
            raise ValidationError(
                _("Unknown dashboard_type: %s") % dashboard_type)
        dashboard = self.sudo().search([
            ("user_id", "=", user_id),
            ("dashboard_type", "=", dashboard_type),
        ], limit=1)
        if not dashboard:
            dashboard = self.sudo().create({
                "user_id": user_id,
                "dashboard_type": dashboard_type,
            })
            dashboard._seed_default_layout()
        return dashboard

    @api.model
    def _entitled_lenses_for_user(self, user=None):
        """Ordered list of dashboard lenses a user is entitled to,
        derived from their ACTUAL tier groups -- the single source of
        truth for BOTH the landing default (first entry) and the
        View-As switch set.

        Superuser -> all six lenses (unchanged: _DASHBOARD_TYPES order,
        headed by 'director'). Every other user -> the UNION of lenses
        their tier groups grant, deduped, in _TIER_LENS_PRIORITY landing
        order. A dual-role Bookkeeper+HR user therefore returns
        ['bookkeeper', 'hr']; a single-tier user returns one entry; a
        user in no tier returns [] (callers fall back to 'sales').

        ⚠️ DECISION (DASH-DUALROLE-1): replaces the old one-tier-per-user
        assumption that ranked HR above Bookkeeper and only ever returned
        a single tier. has_group() is evaluated on the passed user record
        (checks THAT user, not env.user) and uses XML ids, never numeric
        group ids, per the project hard rule.
        """
        user = user or self.env.user
        if self._is_superuser(user):
            return [v for v, _label in _DASHBOARD_TYPES]
        lenses = []
        for group_xmlid, lens in _TIER_LENS_PRIORITY:
            if lens not in lenses and user.has_group(group_xmlid):
                lenses.append(lens)
        return lenses

    @api.model
    def _default_dashboard_type_for_user(self, user_id):
        """Map a user to their default landing dashboard.

        ``preferred_dashboard_type`` wins first (unchanged). Otherwise
        the landing lens is the highest-priority entry in the user's
        entitled lens set (``_entitled_lenses_for_user``, ordered by
        ``_TIER_LENS_PRIORITY``).

        ⚠️ DECISION (M1, marker 2 cont'd): superuser takes precedence and
        lands on Director -- handled inside ``_entitled_lenses_for_user``
        (it returns the full set headed by 'director').
        ⚠️ DECISION (DASH-DUALROLE-1): Bookkeeper now ranks ABOVE HR, so a
        dual-role Bookkeeper+HR user lands on Bookkeeper (was: HR) with HR
        one View-As switch away. Single-tier landing is byte-identical to
        the old ladder (only the Bookkeeper/HR order swapped). See
        ``_TIER_LENS_PRIORITY``.
        """
        user = self.env["res.users"].browse(user_id)
        if not user or not user.exists():
            return "director"
        # Honor explicit preference first.
        if user.preferred_dashboard_type:
            return user.preferred_dashboard_type
        lenses = self._entitled_lenses_for_user(user)
        if lenses:
            return lenses[0]
        # Fallback for users with no tier group -- treat as sales so they
        # get a constrained but non-empty dashboard rather than an
        # AccessError. (Unchanged behaviour.)
        return "sales"

    def _seed_default_layout(self):
        """Materialize ``neon.dashboard.user.layout`` rows from the
        matching ``neon.dashboard.default.layout`` seed.

        Called once on lazy-create. If no seed exists for the type
        (e.g., a future dashboard_type loaded without its layout XML),
        leaves layout empty -- the OWL template's ``isWidgetVisible``
        guard short-circuits to False, so the dashboard renders the
        header only. Defensive rather than failing.
        """
        self.ensure_one()
        Default = self.env["neon.dashboard.default.layout"].sudo()
        seed = Default.search(
            [("dashboard_type", "=", self.dashboard_type)], limit=1)
        if not seed:
            _logger.info(
                "neon.dashboard: no default layout seed for type=%s; "
                "user %s receives empty layout.",
                self.dashboard_type, self.user_id.login,
            )
            return
        UserLayout = self.env["neon.dashboard.user.layout"].sudo()
        UserLayout.create([{
            "dashboard_id": self.id,
            "widget_key": line.widget_key,
            "visible": line.visible,
            "order_index": line.order_index,
            "size": line.size,
        } for line in seed.layout_line_ids])

    # ------------------------------------------------------------------
    # Access -- mirrors cash_flow_dashboard pattern.
    # ------------------------------------------------------------------
    @api.model
    def _check_dashboard_access(self):
        """Any internal user with one of the five operational tier
        meta-groups OR an HR-tier group may load the dashboard.
        Tier-specific data filtering happens inside the RPC -- this
        guard only excludes external/portal users.

        ⚠️ DECISION (R3b C1, marker 4): HR-tier users (HR Admin /
        HR Manager) may not be in any of the five neon_core tiers
        but legitimately need dashboard access. Added to the allow-
        list here; the _resolve_dashboard_type call below routes
        them to the 'hr' lens (which itself re-checks _is_hr_user
        per defence-in-depth)."""
        user = self.env.user
        for group in (_GROUP_SUPERUSER, _GROUP_BOOKKEEPER,
                      _GROUP_SALES_REP, _GROUP_LEAD_TECH, _GROUP_CREW,
                      _GROUP_NEON_HR_ADMIN, _GROUP_HR_MANAGER):
            if user.has_group(group):
                return
        raise AccessError(_(
            "You don't have permission to view the Neon Dashboard. "
            "Contact your administrator to be assigned a Neon tier."))

    @api.model
    def _is_superuser(self, user=None):
        user = user or self.env.user
        return user.has_group(_GROUP_SUPERUSER)

    @api.model
    def _is_hr_user(self, user=None):
        """⚠️ DECISION (R3b C1, marker 1): HR role-lens RBAC rail.
        Returns True when the user is in HR-tier or superuser.
        Used in three places (defence-in-depth):
          1. _available_types_for_user (View-As dropdown HR option)
          2. _resolve_dashboard_type (server-side selection check)
          3. _compute_kpi_hr + _compute_hr_*_block (data methods)
        A Sales / Lead Tech / Bookkeeper / Crew user must NOT pass
        this check -- they should never see HR salaries, leave
        details, contract end dates, or disciplinary data."""
        user = user or self.env.user
        return (user.has_group(_GROUP_SUPERUSER)
                 or user.has_group(_GROUP_NEON_HR_ADMIN)
                 or user.has_group(_GROUP_HR_MANAGER))

    @api.model
    def _available_types_for_user(self, user=None):
        """View-As switcher options.

        Superusers see all six tier labels (incl. HR) -- unchanged. A
        user with TWO OR MORE entitled lenses (e.g. a dual-role
        Bookkeeper+HR user) sees the full switchable set so they can move
        between their lenses and back. A single-lens user keeps the exact
        legacy contract: an HR-only user still confirms its one HR option
        (R3b), and every other single tier returns [] so the OWL template
        keeps the switcher hidden -- nothing changes for them.

        ⚠️ DECISION (DASH-DUALROLE-1): the >=2 gate keeps single-tier
        behaviour byte-identical to before (sales / bookkeeper /
        lead_tech / crew -> []; hr-only -> ['hr']); only multi-lens users
        gain the union. No OWL change is needed: the existing
        ``availableTypes.length`` template gate shows the switcher once
        the server ships >=2 options, so the dual-role Bookkeeper<->HR
        round-trip works client-side as-is."""
        user = user or self.env.user
        if self._is_superuser(user):
            return [{"value": v, "label": label}
                     for v, label in _DASHBOARD_TYPES]
        lenses = self._entitled_lenses_for_user(user)
        if len(lenses) >= 2:
            label_map = dict(_DASHBOARD_TYPES)
            return [{"value": v, "label": label_map[v]} for v in lenses]
        # Single-lens users -- preserve the exact legacy contract.
        if lenses == ["hr"]:
            return [{"value": "hr", "label": "HR"}]
        return []

    def _resolve_dashboard_type(self, requested_type):
        """Role-toggle resolver with RBAC. Superusers may flip to
        any dashboard_type. HR-tier users may flip ONLY to 'hr'
        (their default + only allowed lens). Everyone else's
        requested_type is ignored and they get their default.

        ⚠️ DECISION (R3b C1, marker 2): a non-entitled / non-superuser
        request is downgraded to their default lens (NOT raised
        AccessError) -- the OWL component might cache a stale value
        across a role downgrade; silently coercing to the user's real
        tier is safer than 403'ing. The data methods still re-check
        (no data leak).
        ⚠️ DECISION (DASH-DUALROLE-1): generalised from the old HR-only
        special case ("requested == 'hr' and is_hr_user") to "any lens
        the user is ENTITLED to", so a dual-role Bookkeeper+HR user can
        switch to BOTH 'bookkeeper' and 'hr' (and back). A request for a
        lens the user does not hold still coerces to their default."""
        user = self.env.user
        if requested_type and self._is_superuser(user):
            if requested_type not in _DASHBOARD_TYPE_VALUES:
                raise ValidationError(
                    _("Unknown dashboard_type: %s") % requested_type)
            return requested_type
        if (requested_type
                and requested_type in self._entitled_lenses_for_user(user)):
            return requested_type
        return self._default_dashboard_type_for_user(user.id)

    # ------------------------------------------------------------------
    # Africa/Harare timezone helpers (gate-1 hygiene #2).
    #
    # ⚠️ DECISION (p8a-hygiene tz, marker 1): the three helpers below
    # are @api.model so any model in the registry can call them via
    # self.env['neon.dashboard']._today_harare() etc. Single source of
    # truth -- no scattered pytz.timezone('Africa/Harare') literals
    # across files. Per gate-1 §4.4 lock.
    #
    # ⚠️ DECISION (p8a-hygiene tz, marker 2): stored audit timestamps
    # (e.g. neon.dashboard.last_refresh, ir.config_parameter
    # zig_usd_rate_updated_at) stay UTC. ONLY query-window math and
    # display strings shift to Harare. Round-trip integrity preserved
    # for historical audit.
    # ------------------------------------------------------------------
    @api.model
    def _today_harare(self):
        """Calendar date in Africa/Harare. Use for "today", "today-7d",
        etc. windowing in KPI tiles + block queries. At 23:30 UTC on
        a Tuesday it's already Wednesday 01:30 Harare -- this returns
        Wednesday."""
        now_utc = fields.Datetime.now()  # naive UTC per Odoo convention
        return pytz.utc.localize(now_utc).astimezone(HARARE_TZ).date()

    @api.model
    def _now_harare(self):
        """Aware datetime in Africa/Harare. Use for "since yesterday
        00:00" style sub-day windows."""
        now_utc = fields.Datetime.now()
        return pytz.utc.localize(now_utc).astimezone(HARARE_TZ)

    @api.model
    def _format_harare_timestamp(self, dt=None):
        """Format a UTC-naive datetime (or now) as an ISO-ish Harare
        string for display. Used by the dashboard 'last_updated'
        payload key + future audit footnotes."""
        if dt is None:
            dt = fields.Datetime.now()
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(HARARE_TZ).strftime("%Y-%m-%d %H:%M:%S")

    @api.model
    def _harare_date_to_utc_string(self, harare_date):
        """Convert a Harare-tz date (start-of-day) to the naive-UTC
        string suitable for DB comparisons against write_date /
        create_date columns. e.g. Harare midnight = 22:00 UTC the
        previous day."""
        harare_midnight = HARARE_TZ.localize(
            datetime.combine(harare_date, time.min))
        utc_naive = harare_midnight.astimezone(pytz.utc).replace(
            tzinfo=None)
        return fields.Datetime.to_string(utc_naive)

    # ------------------------------------------------------------------
    # Server-action entry point -- mirrors cash_flow_dashboard.
    # ------------------------------------------------------------------
    @api.model
    def action_open_neon_dashboard(self):
        self._check_dashboard_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_dashboard",
            "name": _("Dashboard"),
            "target": "current",
        }

    # ==================================================================
    # ==================================================================
    # RPC -- get_dashboard_data
    # ==================================================================
    # ==================================================================
    @api.model
    def get_dashboard_data(self, dashboard_type=None):
        """Single round-trip the OWL component calls on load.

        Returns a payload with: dashboard_type, layout, kpi dict
        (7 tiles), jobs_block, view-as options, user metadata.
        """
        self._check_dashboard_access()
        resolved_type = self._resolve_dashboard_type(dashboard_type)
        dashboard = self.get_or_create_for_user(
            user_id=self.env.user.id, dashboard_type=resolved_type,
        )
        payload = {
            "dashboard_id": dashboard.id,
            "dashboard_type": resolved_type,
            "is_customized": dashboard.is_customized,
            "user_name": self.env.user.name,
            "user_login": self.env.user.login,
            "user_role_label": self._user_role_label(),
            "is_superuser": self._is_superuser(),
            "layout": self._serialize_layout(dashboard),
            "kpi": self._compute_kpi(resolved_type),
            "jobs_block": self._compute_jobs_block(resolved_type),
            # M4: Crew & Equipment block. dashboard_type currently
            # unused but reserved for Phase 8B variant scoping (lead
            # tech sees own crew assignments only, etc.).
            "crew_equipment_block":
                self._compute_crew_equipment_block(resolved_type),
            # M5: Sales block (pipeline + win rate + lead sources).
            "sales_block": self._compute_sales_block(resolved_type),
            # M6: Finance block (AR aging + cash detail + rate
            # metadata). Shares the cash breakdown payload with the
            # Cash KPI tile so the two views never disagree.
            "finance_block": self._compute_finance_block(resolved_type),
            # M7: Alerts block. Aggregates from 5 sources, filters
            # per-user dismissals, returns severity-sorted list.
            "alerts_block": self._compute_alerts_block(resolved_type),
            # M8: Tasks block. Current-user mail.activity rows,
            # urgency-bucketed in Harare-tz.
            "tasks_block": self._compute_tasks_block(),
            "available_types": self._available_types_for_user(),
            # p8a-hygiene tz: render the refresh timestamp in
            # Africa/Harare so Robin sees the operational TZ.
            "last_updated": self._format_harare_timestamp(),
            # P12.M1: meta the OWL client uses to hydrate the
            # AI Sales Copilot chat-panel expand/collapse state.
            "user_meta": {
                "chat_panel_expanded":
                    bool(self.env.user.chat_panel_expanded),
            },
        }
        # P8B: variant-specific blocks. Computed only for the variant
        # that renders them so director/tech don't pay for queries
        # their layout never shows.
        if resolved_type == "sales":
            payload["hot_deals_block"] = self._compute_hot_deals_block()
            payload["aging_quotes_block"] = self._compute_aging_quotes_block()
        elif resolved_type == "bookkeeper":
            payload["budget_alerts_block"] = self._compute_budget_alerts_block()
            payload["invoice_queue_block"] = self._compute_invoice_queue_block()
            payload["zig_costs_block"] = self._compute_zig_costs_block()
        elif resolved_type == "lead_tech":
            payload["crew_gaps_block"] = self._compute_crew_gaps_block()
            payload["cert_expiry_block"] = self._compute_cert_expiry_block()
            # P-B2 D7 -- conflicts block on the Operations variant.
            payload["conflicts_block"] = self._compute_conflicts_block()
        elif resolved_type == "hr":
            # P-HR-R3b C1.1 -- HR variant panels.
            # All three are re-checked via _check_hr_data_access at
            # the data layer (defence-in-depth: a non-HR caller who
            # constructed type='hr' via a crafted RPC still gets
            # AccessError before any HR data leaves the server).
            payload["hr_contracts_block"] = (
                self._compute_hr_contracts_expiring_block())
            payload["hr_licences_block"] = (
                self._compute_hr_licences_expiring_block())
            payload["hr_pending_leaves_block"] = (
                self._compute_hr_pending_leaves_block())
        # Historical Intelligence (Sales-Intel Layer-1) -- director lens
        # ONLY. Merged into the director payload here (NOT into
        # _compute_kpi_director / the shared block set) so it never bleeds
        # onto a superuser's Sales / Bookkeeper / Lead-Tech / Tech View-As
        # lens. Reads the INERT Zoho archive only; live tiles untouched.
        if resolved_type == "director":
            payload["kpi"].update(self._compute_kpi_hist())
            payload["hist_intel_block"] = self._compute_hist_intel_block()
            # DRAFT (item #1, pending Tatenda review of dashboard scope
            # coupling): director-only live per-rep performance block. Set
            # here in the existing director branch so it never bleeds onto a
            # View-As of another lens -- same containment as hist_intel_block.
            payload["per_rep_block"] = self._compute_per_rep_block()
        return payload

    # ==================================================================
    # P-B2 -- conflicts_block payload
    # ==================================================================
    def _compute_conflicts_block(self):
        """Read the most-recent non-clear conflict run and surface its
        deficit + zero_margin + below_threshold lines for the
        Operations panel. NO recompute here -- panel is read-only.
        Engine runs are triggered by event confirms + line edits +
        the daily cron."""
        Conflict = self.env["neon.equipment.conflict"].sudo()
        latest = Conflict.search(
            [("overall_status", "in",
              ("deficit", "zero_margin"))],
            order="triggered_at desc", limit=1)
        if not latest:
            return {
                "ok": True, "has_conflicts": False,
                "lines": [], "header_id": 0,
                "header_name": "", "triggered_at": "",
                "overall_status": "clear",
            }
        lines = []
        for ln in latest.line_ids.sorted("sub_hire_priority"):
            if ln.status == "surplus":
                continue
            lines.append({
                "id": ln.id,
                "product_id": ln.product_template_id.id,
                "product_name": (
                    ln.product_template_id.workshop_name
                    or ln.product_template_id.name),
                "category_name": (ln.category_id.name
                                   if ln.category_id else ""),
                "required": int(ln.required_qty),
                "available": int(ln.available_qty),
                "margin": int(ln.margin),
                "deficit": int(ln.deficit_qty),
                "status": ln.status,
                "sub_hire_priority": int(ln.sub_hire_priority),
                "competing_events": [{
                    "id": e.id, "name": e.name,
                    "event_date": (
                        e.event_date.isoformat()
                        if e.event_date else ""),
                } for e in ln.competing_event_ids[:5]],
                "competing_count": len(ln.competing_event_ids),
            })
        return {
            "ok": True,
            "has_conflicts": bool(lines),
            "lines": lines,
            "header_id": latest.id,
            "header_name": latest.name,
            "triggered_at": (
                latest.triggered_at.isoformat()
                if latest.triggered_at else ""),
            "overall_status": latest.overall_status,
            "data_quality_note": (
                "Equipment conflicts are detected at calendar-day "
                "granularity until the team starts filling in event-"
                "job load-in/out (or dispatch/return) datetimes. "
                "Setting precise windows gives precise conflict "
                "detection; until then the engine uses a "
                "conservative same-day-overnight window which "
                "favours over-counting (safer) over under-counting."
            ),
        }

    def _user_role_label(self):
        """Human-readable role label for the header user-line."""
        u = self.env.user
        if u.has_group(_GROUP_SUPERUSER):
            return _("Superuser")
        if u.has_group(_GROUP_BOOKKEEPER):
            return _("Bookkeeper")
        if u.has_group(_GROUP_LEAD_TECH):
            return _("Lead Tech")
        if u.has_group(_GROUP_CREW):
            return _("Crew")
        if u.has_group(_GROUP_SALES_REP):
            return _("Sales")
        return _("Internal User")

    def _serialize_layout(self, dashboard):
        return [{
            "widget_key": layout.widget_key,
            "visible": layout.visible,
            "order_index": layout.order_index,
            "size": layout.size,
        } for layout in dashboard.layout_ids.sorted("order_index")]

    # ==================================================================
    # P8B.M4 -- Edit Layout write RPCs.
    #
    # Mirror the M7 dashboard_dismiss_alert contract: @api.model,
    # _check_dashboard_access guard, per-user (own-row record rule +
    # get_or_create_for_user scope), idempotent, return the refreshed
    # get_dashboard_data payload. No new model -- these mutate the
    # existing neon.dashboard.user.layout rows + the is_customized flag.
    # ==================================================================
    @api.model
    def dashboard_update_layout(self, dashboard_type, updates):
        """Batch-write the current user's layout for dashboard_type.

        ``updates`` = [{widget_key, visible, order_index}, ...].
        Idempotent. Flips is_customized=True so the OWL view switches
        to the unified grid. Returns the refreshed payload.

        Mandatory-widget protection still applies via the
        @api.constrains on neon.dashboard.user.layout (D6): attempts to
        hide kpi_cash / kpi_ar_overdue (and block_alerts unless the
        org param permits) are silently re-shown.
        """
        self._check_dashboard_access()
        resolved = self._resolve_dashboard_type(dashboard_type)
        dashboard = self.get_or_create_for_user(
            user_id=self.env.user.id, dashboard_type=resolved)
        self._apply_layout_updates(dashboard, updates)
        dashboard.sudo().write({"is_customized": True})
        return self.get_dashboard_data(resolved)

    @api.model
    def dashboard_reset_layout(self, dashboard_type):
        """Delete the user's user.layout rows for dashboard_type, flip
        is_customized=False, and lazy re-seed from default.layout so
        the next render returns to the rich 4-section layout. Returns
        the refreshed payload."""
        self._check_dashboard_access()
        resolved = self._resolve_dashboard_type(dashboard_type)
        dashboard = self.get_or_create_for_user(
            user_id=self.env.user.id, dashboard_type=resolved)
        dashboard.layout_ids.sudo().unlink()
        dashboard.sudo().write({"is_customized": False})
        dashboard._seed_default_layout()
        return self.get_dashboard_data(resolved)

    @api.model
    def dashboard_apply_layout_to_all_variants(self, source_dashboard_type,
                                               updates):
        """Persist the source layout, then copy its (visible,
        order_index) onto every other dashboard_type the user can
        access -- but only for widget_keys that EXIST in the target
        (variants carry different block sets; a Sales-only block isn't
        forced onto Bookkeeper). Returns {dashboard_type: 'applied' |
        'no_access'}.

        ⚠️ DECISION (M8B.4, marker 2): "accessible" = superuser -> all
        five types; everyone else -> their own default type only. The
        live ACL grants multi-variant visibility through
        group_neon_superuser (the View-as selector is superuser-only,
        M8B.1-3), so there is no per-tier peek beyond superuser. The
        button only renders for >=2 accessible types, so non-superusers
        never reach this path. Reuses _is_superuser rather than
        hardcoding a tier->variant table (D7)."""
        self._check_dashboard_access()
        source = self._resolve_dashboard_type(source_dashboard_type)
        src_dash = self.get_or_create_for_user(
            user_id=self.env.user.id, dashboard_type=source)
        self._apply_layout_updates(src_dash, updates)
        src_dash.sudo().write({"is_customized": True})

        result = {source: "applied"}
        accessible = self._accessible_dashboard_types()
        for dtype in (v for v, _l in _DASHBOARD_TYPES):
            if dtype == source:
                continue
            if dtype not in accessible:
                result[dtype] = "no_access"
                continue
            target = self.get_or_create_for_user(
                user_id=self.env.user.id, dashboard_type=dtype)
            tgt_by_key = {l.widget_key: l for l in target.layout_ids}
            for upd in (updates or []):
                row = tgt_by_key.get(upd.get("widget_key"))
                if not row:
                    continue  # widget not present on this variant
                vals = {}
                if "order_index" in upd:
                    vals["order_index"] = int(upd["order_index"])
                if "visible" in upd:
                    vals["visible"] = bool(upd["visible"])
                if vals:
                    row.write(vals)
            target.sudo().write({"is_customized": True})
            result[dtype] = "applied"
        return result

    @api.model
    def _apply_layout_updates(self, dashboard, updates):
        """Write visible / order_index onto the dashboard's existing
        user.layout rows, matched by widget_key. Unknown keys ignored;
        rows not mentioned are left untouched. ``size`` is display-only
        (D3) and not edited here. sudo() so a tier user without direct
        write on the model can still personalise their own row (the
        own-row record rule already permits write; sudo keeps the
        mandatory @api.constrains the single enforcement point)."""
        by_key = {l.widget_key: l for l in dashboard.layout_ids}
        for upd in (updates or []):
            row = by_key.get(upd.get("widget_key"))
            if not row:
                continue
            vals = {}
            if "order_index" in upd:
                vals["order_index"] = int(upd["order_index"])
            if "visible" in upd:
                vals["visible"] = bool(upd["visible"])
            if vals:
                row.sudo().write(vals)
        return True

    @api.model
    def _accessible_dashboard_types(self):
        """Dashboard types the current user may personalise. Superuser
        -> all five; everyone else -> their own default only. See the
        DECISION marker on dashboard_apply_layout_to_all_variants."""
        if self._is_superuser():
            return [v for v, _l in _DASHBOARD_TYPES]
        return [self._default_dashboard_type_for_user(self.env.user.id)]

    # ==================================================================
    # KPI tiles (M2) -- 7 tiles, every returned dict shape-compatible.
    # ==================================================================
    @api.model
    def _compute_kpi(self, dashboard_type):
        """Dispatch KPI tile set by dashboard_type (Phase 8B).

        Each variant returns ONLY its own tile keys; the OWL
        ``isWidgetVisible`` gate (driven by the seeded layout) decides
        which of those render. director + tech fall through to the
        full 7-tile director set.

        ⚠️ DECISION (P8B.M1, dispatch): flat getattr-free if/elif
        dispatch per the revised Gate-1 D2 lock -- no dispatcher table,
        no subclassing. Keeps every variant's tile assembly in one
        readable place.
        """
        if dashboard_type == "sales":
            return self._compute_kpi_sales()
        if dashboard_type == "bookkeeper":
            return self._compute_kpi_bookkeeper()
        if dashboard_type == "lead_tech":
            return self._compute_kpi_lead_tech()
        if dashboard_type == "hr":
            return self._compute_kpi_hr()
        return self._compute_kpi_director()

    @api.model
    def _compute_kpi_director(self):
        """Director (+ tech fallback) -- the original 7-tile strip."""
        return {
            "kpi_cash": self._kpi_cash_on_hand(),
            "kpi_ar_overdue": self._kpi_ar_overdue(),
            "kpi_jobs_today": self._kpi_jobs_today(),
            "kpi_jobs_week": self._kpi_jobs_week(),
            "kpi_pipeline": self._kpi_pipeline(),
            "kpi_leads": self._kpi_new_leads(),
            "kpi_forecast": self._kpi_forecast(),
        }

    # ==================================================================
    # P8B.M1 -- Sales variant KPI set (6 tiles).
    # Pipeline + New Leads reuse the director helpers; Hot Deals,
    # Aging Quotes, Won-MTD, Win-Rate are new.
    # ==================================================================
    @api.model
    def _compute_kpi_sales(self):
        return {
            "kpi_pipeline": self._kpi_pipeline(),
            "kpi_leads": self._kpi_new_leads(),
            "kpi_hot_deals": self._kpi_hot_deals(),
            "kpi_aging_quotes": self._kpi_aging_quotes(),
            "kpi_won_mtd": self._kpi_won_mtd(),
            "kpi_win_rate": self._kpi_win_rate_tile(),
        }

    # ==================================================================
    # P8B.M2 -- Bookkeeper variant KPI set (6 tiles).
    # Cash + AR Overdue reuse director helpers; Overdue-60+, Pending
    # Invoices are new; Recent Payments + Recent Costs reuse the
    # Phase 6 Cash Flow Dashboard tile methods via sudo (single source
    # of truth -- Director / Bookkeeper / Cash Flow never disagree).
    # ==================================================================
    @api.model
    def _compute_kpi_bookkeeper(self):
        return {
            "kpi_cash": self._kpi_cash_on_hand(),
            "kpi_ar_overdue": self._kpi_ar_overdue(),
            "kpi_overdue_60": self._kpi_overdue_60(),
            "kpi_pending_invoices": self._kpi_pending_invoices(),
            "kpi_recent_payments": self._kpi_recent_payments(),
            "kpi_recent_costs": self._kpi_recent_costs(),
        }

    # ==================================================================
    # P8B.M3 -- Lead Tech variant KPI set (4 tiles).
    # Jobs Today + Jobs Week reuse director helpers; Crew Gaps + Certs
    # Expiring (30d) are new. Equipment Booked/Available deferred to
    # Phase 9+ (needs a unit-level booking surface -- carryover).
    # ==================================================================
    @api.model
    def _compute_kpi_lead_tech(self):
        return {
            "kpi_jobs_today": self._kpi_jobs_today(),
            "kpi_jobs_week": self._kpi_jobs_week(),
            "kpi_crew_gaps": self._kpi_crew_gaps(),
            "kpi_certs_30": self._kpi_certs_30(),
        }

    # ==================================================================
    # P-HR-R3b C1 -- HR variant KPI set (5 tiles).
    # ⚠️ DECISION (R3b C1, marker 5): tile set =
    #   headcount / on_leave_today / contracts_expiring_30 /
    #   licences_expiring_30 / pending_leave_approvals.
    # Defence-in-depth: _check_hr_data_access() refuses non-HR users
    # at the data layer (so a non-HR user who bypasses
    # _resolve_dashboard_type still gets nothing). Each helper uses
    # sudo() to read the HR models -- HR data is intentionally
    # scoped to HR-tier readers via the call-site check, not via
    # plain ACL widening on the underlying records.
    # ==================================================================
    @api.model
    def _check_hr_data_access(self):
        """RBAC red-rail recheck at the HR data layer. A non-HR /
        non-superuser user must NEVER read HR salaries, leave
        details, contract end dates, or disciplinary data even if
        they manage to call the HR compute methods directly."""
        if not self._is_hr_user():
            raise AccessError(_(
                "HR lens requires HR Admin / HR Manager / OD/MD "
                "membership. Sales / Lead Tech / Bookkeeper / "
                "Crew users cannot view this content."))

    @api.model
    def _compute_kpi_hr(self):
        self._check_hr_data_access()
        return {
            "kpi_hr_headcount": self._kpi_hr_headcount(),
            "kpi_hr_on_leave_today": self._kpi_hr_on_leave_today(),
            "kpi_hr_contracts_30":
                self._kpi_hr_contracts_expiring_30(),
            "kpi_hr_licences_30":
                self._kpi_hr_licences_expiring_30(),
            "kpi_hr_pending_leave":
                self._kpi_hr_pending_leave_approvals(),
        }

    def _kpi_hr_headcount(self):
        Employee = self.env["hr.employee"].sudo()
        total = Employee.search_count([("active", "=", True)])
        # ⚠️ DECISION (HR client render, 2026-06-11): the 5 _kpi_hr_*
        # dicts gain `value_display` (str) + `empty` (bool) so the OWL
        # KPI tile markup -- which reads `.value_display` + `.empty`
        # like every director/sales/bookkeeper tile -- can render them
        # verbatim. R3b shipped the server `value`/`label`/`subtitle`
        # shape but never the client tiles, so the tile contract was
        # never exercised. value/label/subtitle/currency are PRESERVED
        # (the phr_r3b C1 smoke asserts `value` is an int).
        #
        # Headcount is never "empty": it renders from the count alone
        # (the count IS data), unlike the four 30-day watch KPIs which
        # grey out at zero. Its deeplink is an inline act_window dict
        # (NOT an xmlid) so the click never depends on a version-
        # specific core Employees action xmlid resolving.
        return {
            "value": int(total or 0),
            "value_display": str(int(total or 0)),
            "label": "Headcount",
            "subtitle": "Active employees",
            "currency": "",
            "empty": False,
            "deeplink_action": {
                "type": "ir.actions.act_window",
                "name": "Employees",
                "res_model": "hr.employee",
                "view_mode": "tree,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("active", "=", True)],
            },
        }

    def _kpi_hr_on_leave_today(self):
        today = self._today_harare()
        Leave = self.env["hr.leave"].sudo()
        count = Leave.search_count([
            ("state", "=", "validate"),
            ("date_from", "<=", today),
            ("date_to", ">=", today),
        ])
        return {
            "value": int(count or 0),
            "value_display": str(int(count or 0)),
            "label": "On Leave Today",
            "subtitle": "Validated, overlapping today",
            "currency": "",
            "empty": (count or 0) == 0,
        }

    def _kpi_hr_contracts_expiring_30(self):
        today = self._today_harare()
        Contract = self.env["hr.contract"].sudo()
        count = Contract.search_count([
            ("state", "in", ("open", "pending")),
            ("date_end", ">=", today),
            ("date_end", "<=", today + timedelta(days=30)),
        ])
        return {
            "value": int(count or 0),
            "value_display": str(int(count or 0)),
            "label": "Contracts Expiring (30d)",
            "subtitle": "Renewal action window",
            "currency": "",
            "empty": (count or 0) == 0,
        }

    def _kpi_hr_licences_expiring_30(self):
        today = self._today_harare()
        Licence = self.env.get("neon.hr.licence")
        if Licence is None:
            return {"value": 0,
                     "value_display": "0",
                     "label": "Licences Expiring (30d)",
                     "subtitle": "neon_hr R3a not installed",
                     "currency": "",
                     "empty": True}
        count = Licence.sudo().search_count([
            ("state", "=", "valid"),
            ("expiry_date", ">=", today),
            ("expiry_date", "<=", today + timedelta(days=30)),
        ])
        return {
            "value": int(count or 0),
            "value_display": str(int(count or 0)),
            "label": "Licences Expiring (30d)",
            "subtitle": "Driver fleet renewal window",
            "currency": "",
            "empty": (count or 0) == 0,
        }

    def _kpi_hr_pending_leave_approvals(self):
        Leave = self.env["hr.leave"].sudo()
        count = Leave.search_count([("state", "=", "confirm")])
        return {
            "value": int(count or 0),
            "value_display": str(int(count or 0)),
            "label": "Pending Leave Approvals",
            "subtitle": "Awaiting approver action",
            "currency": "",
            "empty": (count or 0) == 0,
        }

    # ==================================================================
    # P-HR-R3b C1.1 -- HR variant panels (3).
    # Each returns up to 10 rows, sorted by relevance (most urgent
    # first), with stable dict shapes for the OWL renderer.
    # Defence-in-depth: every panel re-checks _check_hr_data_access.
    # ==================================================================
    @api.model
    def _compute_hr_contracts_expiring_block(self):
        self._check_hr_data_access()
        today = self._today_harare()
        end_window = today + timedelta(days=30)
        Contract = self.env["hr.contract"].sudo()
        contracts = Contract.search([
            ("state", "in", ("open", "pending")),
            ("date_end", ">=", today),
            ("date_end", "<=", end_window),
        ], order="date_end asc, id desc", limit=10)
        rows = [{
            "id": c.id,
            "employee_name": (c.employee_id.name
                                or "(no employee)"),
            "contract_name": c.name or "",
            "date_end": (str(c.date_end)
                          if c.date_end else ""),
            "days_to_end": (
                (c.date_end - today).days if c.date_end else 0),
        } for c in contracts]
        return {"rows": rows, "title": "Contracts Expiring (30d)",
                "row_count": len(rows)}

    @api.model
    def _compute_hr_licences_expiring_block(self):
        self._check_hr_data_access()
        today = self._today_harare()
        end_window = today + timedelta(days=30)
        Licence = self.env.get("neon.hr.licence")
        if Licence is None:
            return {"rows": [], "title": "Licences Expiring (30d)",
                    "row_count": 0,
                    "note": "neon_hr R3a not installed"}
        recs = Licence.sudo().search([
            ("state", "=", "valid"),
            ("expiry_date", ">=", today),
            ("expiry_date", "<=", end_window),
        ], order="expiry_date asc, id desc", limit=10)
        rows = [{
            "id": r.id,
            "employee_name": (r.employee_id.name
                                or "(no employee)"),
            "licence_class": (r.licence_class or ""),
            "expiry_date": (str(r.expiry_date)
                              if r.expiry_date else ""),
            "days_to_expiry": (
                (r.expiry_date - today).days
                if r.expiry_date else 0),
        } for r in recs]
        return {"rows": rows, "title": "Licences Expiring (30d)",
                "row_count": len(rows)}

    @api.model
    def _compute_hr_pending_leaves_block(self):
        self._check_hr_data_access()
        Leave = self.env["hr.leave"].sudo()
        recs = Leave.search([
            ("state", "=", "confirm"),
        ], order="date_from asc, id desc", limit=10)
        rows = [{
            "id": r.id,
            "employee_name": (r.employee_id.name
                                or "(no employee)"),
            "holiday_status":
                (r.holiday_status_id.name or ""),
            "date_from": str(r.date_from) if r.date_from else "",
            "date_to": str(r.date_to) if r.date_to else "",
            "number_of_days": float(r.number_of_days or 0),
        } for r in recs]
        return {"rows": rows, "title": "Pending Leave Approvals",
                "row_count": len(rows)}

    # ⚠️ DECISION (M2, marker 3): Cash-on-Hand source is the standard
    # Odoo ``account.journal`` (type ∈ bank, cash) aggregated through
    # ``account.move.line``. The M1-M3 prompt assumed a
    # ``neon.bank.account`` model with a ``current_balance`` field;
    # no such model exists. ZWG conversion to USD-equivalent is
    # deferred to M6 alongside the RBZ ZiG-USD rate cron (per schema
    # sketch §7.5). For M1-M3 the tile shows USD-only total with a
    # subtitle disclosing the ZWG gap.
    # ⚠️ DECISION (M6, marker 1): supersedes M2's USD-only stub.
    # Cash KPI now sums bank/cash journal balances split by currency
    # (USD direct + ZiG-via-manual-rate). Per
    # project_zig_usd_rate_manual_only memory: the rate is the
    # finance team's manual override at ir.config_parameter
    # neon_dashboard.zig_usd_rate_manual; rate=0 means "no rate
    # set" and ZiG is excluded from the headline total (subtitle
    # surfaces the exclusion -- never silent).
    def _kpi_cash_on_hand(self):
        breakdown = self._cash_journals_breakdown()
        if breakdown.get("empty"):
            return self._empty_kpi(
                _("No bank/cash journals configured yet"),
                value_display="$0",
                deeplink_action="account.action_account_journal_form",
            )
        usd_total = breakdown["usd_total"]
        zig_total = breakdown["zig_total"]
        rate = breakdown["rate"]
        zig_in_usd = breakdown["zig_in_usd"]
        total_usd_equiv = usd_total + zig_in_usd
        return {
            "value": total_usd_equiv,
            "value_display": self._format_money(total_usd_equiv, "USD"),
            "currency": "USD",
            "subtitle": self._cash_subtitle(
                usd_total, zig_total, rate),
            "trend_pct": None,
            "trend_dir": "flat",
            "empty": False,
            "deeplink_action": "account.action_account_journal_form",
            # Extra payload consumed by the Finance block's cash
            # detail card -- single source of truth, computed once.
            "breakdown": {
                "usd_amount": usd_total,
                "zig_amount": zig_total,
                "zig_in_usd": zig_in_usd,
                "rate_used": rate,
                "rate_source": breakdown["rate_source"],
                "rate_as_of": breakdown["rate_as_of"],
                "usd_display": self._format_money(usd_total, "USD"),
                "zig_display": self._format_money(zig_total, "ZWG"),
                "zig_in_usd_display":
                    self._format_money(zig_in_usd, "USD"),
            },
        }

    # ------------------------------------------------------------------
    # M6 -- cash + AR + rate helpers used by both the KPI tile and the
    # Finance block.
    # ------------------------------------------------------------------
    @api.model
    def _cash_journals_breakdown(self):
        """Walk bank+cash journals once. Returns:
           {empty, usd_total, zig_total, rate, zig_in_usd,
            rate_source, rate_as_of}

        ⚠️ DECISION (M6, marker 2): journal balance prefers the
        Odoo 17 computed ``current_account_balance`` (sum of posted
        move lines on the journal's default account, in journal
        currency); falls back to manual SQL aggregation if absent.

        ⚠️ DECISION (M6, marker 3): currency bucketing uses the
        journal's effective currency (explicit currency_id OR
        company-default). ZWG matches the canonical
        neon_finance.currency_zwg ref. ZWL is dead and not handled.
        """
        Journal = self.env["account.journal"].sudo()
        journals = Journal.search([
            ("type", "in", ("bank", "cash")),
            ("company_id", "=", self.env.company.id),
        ])
        if not journals:
            return {"empty": True}
        company_currency = self.env.company.currency_id
        usd_total = 0.0
        zig_total = 0.0
        for j in journals:
            balance = self._journal_balance(j)
            effective = j.currency_id or company_currency
            if effective.name == "ZWG":
                zig_total += balance
            elif effective.name == "USD":
                usd_total += balance
            # Other currencies (unlikely on this build) silently
            # ignored from the headline -- they don't fit USD/ZiG
            # buckets. M6+ polish could surface a third bucket if
            # the company ever opens, say, a ZAR account.
        rate = self._get_zig_usd_rate()
        zig_in_usd = (zig_total / rate) if (rate and rate > 0) else 0.0
        return {
            "empty": False,
            "usd_total": usd_total,
            "zig_total": zig_total,
            "rate": rate,
            "zig_in_usd": zig_in_usd,
            "rate_source": self._zig_rate_source(),
            "rate_as_of": self._zig_rate_timestamp_harare(),
        }

    @api.model
    def _journal_balance(self, journal):
        """Posted balance on a journal's default account."""
        if not journal.default_account_id:
            return 0.0
        Line = self.env["account.move.line"].sudo()
        lines = Line.search([
            ("account_id", "=", journal.default_account_id.id),
            ("parent_state", "=", "posted"),
        ])
        return sum(lines.mapped("balance"))

    @api.model
    def _get_zig_usd_rate(self):
        """Manual override at neon_dashboard.zig_usd_rate_manual.
        Returns float; 0 means "no rate set". Per
        project_zig_usd_rate_manual_only: there is no fallback to an
        auto-fetched value (no RBZ cron). The manual value is the
        single source of truth."""
        Config = self.env["ir.config_parameter"].sudo()
        try:
            raw = Config.get_param(
                "neon_dashboard.zig_usd_rate_manual", "0") or "0"
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        return value if value > 0 else 0.0

    @api.model
    def _zig_rate_source(self):
        """'manual' when the override is non-zero, else 'unset'.
        Reserved values 'rbz' / 'auto' exist in the schema for
        forward-compat but are never set by current code."""
        return "manual" if self._get_zig_usd_rate() > 0 else "unset"

    @api.model
    def _zig_rate_timestamp_harare(self):
        """Returns the rate-last-updated timestamp formatted in
        Africa/Harare for display. Empty string if unset."""
        Config = self.env["ir.config_parameter"].sudo()
        raw = Config.get_param(
            "neon_dashboard.zig_usd_rate_updated_at", "") or ""
        if not raw:
            return ""
        try:
            dt = fields.Datetime.from_string(raw)
        except Exception:  # noqa: BLE001
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(raw.split(".")[0])
            except Exception:  # noqa: BLE001
                return raw
        return self._format_harare_timestamp(dt)

    @api.model
    def _cash_subtitle(self, usd, zig, rate):
        """Build the cash-tile subtitle disclosing the breakdown.
        Never silent -- the user always sees what's included and
        why ZiG might be excluded."""
        if zig == 0 and usd > 0:
            return _("USD only")
        if zig == 0 and usd == 0:
            return _("No cash on hand")
        if usd == 0 and zig > 0 and rate:
            return _("ZiG %(z)s @ %(r).2f") % {
                "z": self._format_money(zig, "ZWG"), "r": rate}
        if usd > 0 and zig > 0 and rate:
            return _(
                "USD %(u)s + ZiG %(z)s @ %(r).2f"
            ) % {
                "u": self._format_money(usd, "USD"),
                "z": self._format_money(zig, "ZWG"),
                "r": rate,
            }
        # zig > 0 and no rate -- exclusion path; subtitle says so.
        return _(
            "USD %(u)s (ZiG %(z)s excluded -- no rate)"
        ) % {
            "u": self._format_money(usd, "USD"),
            "z": self._format_money(zig, "ZWG"),
        }

    def _kpi_ar_overdue(self):
        today = self._today_harare()
        Move = self.env["account.move"].sudo()
        # ⚠️ DECISION (M2, marker inline): account.move uses
        # ``invoice_date_due`` (not ``date_due``) and payment_state
        # values include 'in_payment' which Cash-Flow Dashboard treats
        # as unpaid for receivables purposes. Mirror that convention.
        overdue = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial", "in_payment")),
            ("invoice_date_due", "<", today),
        ])
        if not overdue:
            return self._empty_kpi(
                _("No overdue invoices"), value_display="$0")
        total = sum(overdue.mapped("amount_residual"))
        return {
            "value": total,
            "value_display": self._format_money(total, "USD"),
            "count": len(overdue),
            "subtitle": _("%d overdue") % len(overdue),
            "trend_pct": None,
            "trend_dir": "flat",
            "empty": False,
            "deeplink_action":
                "neon_finance.action_dashboard_top_overdue",
        }

    def _kpi_jobs_today(self):
        today = self._today_harare()
        EventJob = self.env["commercial.event.job"].sudo()
        # ⚠️ DECISION (M2, marker inline): commercial.event.job has
        # NO 'confirmed'/'active'/'prep' literal states. Map to the
        # real 12-state machine. Today's-jobs domain excludes terminal
        # (cancelled / released) only -- everything else is "today's
        # active work" for tile-counting purposes.
        jobs = EventJob.search([
            ("event_date", "=", today),
            ("state", "not in", ("cancelled", "released")),
        ])
        if not jobs:
            return self._empty_kpi(
                _("No jobs scheduled today"), value_display="0")
        # Sub-counters by mockup-v2 bucket.
        buckets = defaultdict(int)
        for j in jobs:
            badge, _color = _STATE_BADGE.get(
                j.state, ("PENDING", "grey"))
            buckets[badge] += 1
        subtitle_bits = []
        for label in ("PREP", "READY", "ACTIVE", "PENDING", "DONE"):
            if buckets.get(label):
                subtitle_bits.append(f"{buckets[label]} {label.lower()}")
        return {
            "value": len(jobs),
            "value_display": str(len(jobs)),
            "subtitle": " / ".join(subtitle_bits) or _("today"),
            "empty": False,
            "deeplink_action": "neon_jobs.commercial_event_job_action",
        }

    def _kpi_jobs_week(self):
        today = self._today_harare()
        end = today + timedelta(days=7)
        EventJob = self.env["commercial.event.job"].sudo()
        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ])
        if not jobs:
            return self._empty_kpi(
                _("No jobs in next 7 days"), value_display="0")
        return {
            "value": len(jobs),
            "value_display": str(len(jobs)),
            "subtitle": _("Next 7 days"),
            "empty": False,
            "deeplink_action": "neon_jobs.commercial_event_job_action",
        }

    # ⚠️ DECISION (M2, marker 4): Pipeline tile reads
    # ``neon.finance.quote.state in (pending_approval, approved,
    # sent)``. The M1-M3 prompt assumed Zoho-style ``stage_id.name
    # in ['Qualified','Proposal Sent','Negotiation']``; quotes in
    # this repo are state-machine-driven, not stage-driven. The
    # state filter mirrors ``neon_finance.dashboard._tile_pipeline``
    # exactly so the two dashboards never disagree.
    def _kpi_pipeline(self):
        Quote = self.env["neon.finance.quote"].sudo()
        active = Quote.search([
            ("state", "in", ("pending_approval", "approved", "sent")),
        ])
        if not active:
            return self._empty_kpi(
                _("No active deals"), value_display="$0")
        # Pipeline crosses currencies; sum USD-quoted only at this
        # tile (consistent with the cash-on-hand decision). Robin's
        # mockup shows a single dollar figure.
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        usd_active = active.filtered(
            lambda q: usd and q.currency_id.id == usd.id)
        if not usd_active:
            return self._empty_kpi(
                _("No USD pipeline -- ZWG total in M6"),
                value_display="$0")
        total = sum(usd_active.mapped("amount_total"))
        return {
            "value": total,
            "value_display": self._format_money(total, "USD"),
            "count": len(usd_active),
            "subtitle": _("%d active") % len(usd_active),
            "empty": False,
            "deeplink_action":
                "neon_finance.action_dashboard_pipeline",
        }

    def _kpi_new_leads(self):
        # ⚠️ DECISION (M2, marker inline): leads are stock ``crm.lead``
        # (Phase 1; extended in neon_crm_extensions but not renamed).
        # "Since yesterday" means create_date >= yesterday-midnight,
        # which gives the Robin-friendly "today + yesterday" rolling
        # window the mockup implies.
        # p8a-hygiene tz: compute the cutoff in Harare so "yesterday"
        # tracks the operational day, not UTC.
        yesterday_start_harare = self._now_harare() - timedelta(days=1)
        yesterday_start = yesterday_start_harare.astimezone(
            pytz.utc).replace(tzinfo=None)
        Lead = self.env["crm.lead"].sudo()
        leads = Lead.search([
            ("create_date", ">=", yesterday_start),
        ])
        if not leads:
            return self._empty_kpi(
                _("No new leads"), value_display="0")
        return {
            "value": len(leads),
            "value_display": str(len(leads)),
            "subtitle": _("Since yesterday"),
            "empty": False,
            "deeplink_action": "crm.crm_lead_all_leads",
        }

    def _kpi_forecast(self):
        """Forecast vs Target tile.

        M5: wires to ``neon.dashboard.target``. The CTA empty-state
        (M2's original behaviour) is preserved as a fall-through when
        no target row covers today.

        ⚠️ DECISION (M5, marker 6): supersedes M2's CTA-only empty
        state. CTA still surfaces when no target exists for the
        current period -- the dashboard never crashes for users
        without a configured target.
        """
        Target = self.env["neon.dashboard.target"].sudo()
        today = self._today_harare()
        target = Target.search([
            ("target_type", "=", "revenue"),
            ("active", "=", True),
            ("date_from", "<=", today),
            ("date_to", ">=", today),
        ], limit=1, order="date_from desc")

        if not target:
            return {
                "value": None,
                "value_display": _("Set a target -->"),
                "subtitle": _("No target set for current period"),
                "empty": True,
                "empty_message": _("Set a target -->"),
                "deeplink_action":
                    "neon_dashboard.action_neon_dashboard_target",
                "cta_label": _("Configure target"),
            }

        days_remaining = max((target.date_to - today).days, 0)
        return {
            "value": target.progress_pct,
            "value_display": f"{int(target.progress_pct)}%",
            "subtitle": _(
                "%(name)s -- %(days)d days left"
            ) % {"name": target.name, "days": days_remaining},
            "progress_pct": target.progress_pct,
            "target_amount_display": self._format_money(
                target.target_amount, target.currency_id.name),
            "actual_amount_display": self._format_money(
                target.actual_amount, target.currency_id.name),
            "empty": False,
            "deeplink_action":
                "neon_dashboard.action_neon_dashboard_target",
        }

    def _empty_kpi(self, message, value_display="$0",
                   deeplink_action=False):
        return {
            "value": 0,
            "value_display": value_display,
            "subtitle": message,
            "empty": True,
            "empty_message": message,
            "trend_pct": None,
            "trend_dir": "flat",
            "deeplink_action": deeplink_action,
        }

    def _format_money(self, amount, currency="USD"):
        prefix = "$" if currency == "USD" else "Z$"
        try:
            amount = float(amount or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if abs(amount) >= 1000:
            return f"{prefix}{amount/1000:.1f}k"
        return f"{prefix}{amount:,.0f}"

    # ==================================================================
    # P8B.M1 -- Sales variant KPI helpers.
    #
    # ⚠️ DECISION (P8B.M1, won/win convention): won/lost measured via
    # neon.finance.quote.state (won='accepted', lost='rejected'/
    # 'expired'), NOT crm.lead stage_id.is_won. Locked at Gate 1 per
    # M5 DECISION marker 7 -- single source of truth so the Sales tile,
    # the Sales-block win-rate sub-widget and the Director dashboard
    # never disagree. write_date is the accept/aging proxy (no
    # dedicated state_changed_date field on the quote model).
    # ==================================================================
    def _kpi_hot_deals(self):
        """Count of quotes in the hot pipeline stages -- Qualified
        (pending_approval) + Proposal Sent (approved). Mirrors the
        Sales-block pipeline-by-stage mapping."""
        Quote = self.env["neon.finance.quote"].sudo()
        hot = Quote.search_count([
            ("state", "in", ("pending_approval", "approved")),
        ])
        if not hot:
            return self._empty_kpi(
                _("No hot deals"), value_display="0",
                deeplink_action="neon_finance.action_dashboard_pipeline")
        return {
            "value": hot,
            "value_display": str(hot),
            "subtitle": _("Qualified + Proposal Sent"),
            "empty": False,
            "deeplink_action": "neon_finance.action_dashboard_pipeline",
        }

    def _kpi_aging_quotes(self):
        """Count of open quotes (draft/sent) with no movement in >7
        days. Ages on write_date per the won/win convention above."""
        Quote = self.env["neon.finance.quote"].sudo()
        cutoff = self._harare_date_to_utc_string(
            self._today_harare() - timedelta(days=7))
        aging = Quote.search_count([
            ("state", "in", ("draft", "sent")),
            ("write_date", "<", cutoff),
        ])
        if not aging:
            return self._empty_kpi(
                _("No aging quotes"), value_display="0",
                deeplink_action="neon_finance.action_dashboard_pipeline")
        return {
            "value": aging,
            "value_display": str(aging),
            "subtitle": _(">7 days, no movement"),
            "empty": False,
            "deeplink_action": "neon_finance.action_dashboard_pipeline",
        }

    def _kpi_won_mtd(self):
        """Count of quotes accepted in the current Harare calendar
        month. write_date is the accept-transition proxy."""
        Quote = self.env["neon.finance.quote"].sudo()
        month_start = self._today_harare().replace(day=1)
        cutoff = self._harare_date_to_utc_string(month_start)
        won = Quote.search_count([
            ("state", "=", "accepted"),
            ("write_date", ">=", cutoff),
        ])
        if not won:
            return self._empty_kpi(
                _("None won yet this month"), value_display="0",
                deeplink_action="neon_finance.action_dashboard_pipeline")
        return {
            "value": won,
            "value_display": str(won),
            "subtitle": month_start.strftime("%B"),
            "empty": False,
            "deeplink_action": "neon_finance.action_dashboard_pipeline",
        }

    def _kpi_win_rate_tile(self):
        """KPI-tile wrapper over the Sales-block win-rate compute
        (won / (won+lost) over the last 90 days)."""
        wr = self._compute_win_rate()
        if wr.get("empty") or wr.get("rate_pct") is None:
            return self._empty_kpi(
                _("No closed deals (90d)"), value_display="--")
        return {
            "value": wr["rate_pct"],
            "value_display": f"{wr['rate_pct']:g}%",
            "subtitle": _("%(w)dW / %(l)dL -- 90d") % {
                "w": wr["won_count"], "l": wr["lost_count"]},
            "empty": False,
            "deeplink_action": "neon_finance.action_dashboard_pipeline",
        }

    # ==================================================================
    # P8B.M2 -- Bookkeeper variant KPI helpers.
    # ==================================================================
    def _kpi_overdue_60(self):
        """AR overdue by more than 60 days -- the critical bucket.
        USD-equivalent (ZiG via manual rate; excluded if rate unset).
        """
        today = self._today_harare()
        cutoff = today - timedelta(days=60)
        Move = self.env["account.move"].sudo()
        overdue = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial", "in_payment")),
            ("invoice_date_due", "<", cutoff),
        ])
        if not overdue:
            return self._empty_kpi(
                _("Nothing 60+ days overdue"), value_display="$0",
                deeplink_action="neon_finance.action_dashboard_top_overdue")
        rate = self._get_zig_usd_rate()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        total = 0.0
        for inv in overdue:
            residual = inv.amount_residual or 0.0
            if usd and inv.currency_id.id == usd.id:
                total += residual
            elif zwg and inv.currency_id.id == zwg.id and rate and rate > 0:
                total += residual / rate
            elif not (zwg and inv.currency_id.id == zwg.id):
                total += residual
        return {
            "value": total,
            "value_display": self._format_money(total, "USD"),
            "count": len(overdue),
            "subtitle": _("%d invoice(s) 60+ days") % len(overdue),
            "empty": False,
            "deeplink_action": "neon_finance.action_dashboard_top_overdue",
        }

    def _kpi_pending_invoices(self):
        """Count of unposted (draft) customer invoices awaiting
        posting/review."""
        Move = self.env["account.move"].sudo()
        pending = Move.search_count([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "draft"),
        ])
        if not pending:
            return self._empty_kpi(
                _("No invoices pending"), value_display="0",
                deeplink_action="account.action_move_out_invoice_type")
        return {
            "value": pending,
            "value_display": str(pending),
            "subtitle": _("Draft, awaiting posting"),
            "empty": False,
            "deeplink_action": "account.action_move_out_invoice_type",
        }

    def _kpi_recent_payments(self):
        """Inbound payments in the last 30 days (USD). Reuses the
        Phase 6 Cash Flow Dashboard tile via sudo -- single source of
        truth. role='finance_all' so the variant shows the full
        finance picture regardless of who is peeking."""
        tile = self._finance_dashboard_tile("_tile_recent_payments")
        usd = (tile or {}).get("usd") or {}
        value = usd.get("value") or 0.0
        if not value:
            return self._empty_kpi(
                _("No payments in 30 days"), value_display="$0",
                deeplink_action="neon_finance.action_dashboard_recent_payments")
        return {
            "value": value,
            "value_display": self._format_money(value, "USD"),
            "count": usd.get("count") or 0,
            "subtitle": _("%d received -- 30d") % (usd.get("count") or 0),
            "empty": False,
            "deeplink_action":
                "neon_finance.action_dashboard_recent_payments",
        }

    def _kpi_recent_costs(self):
        """Vendor costs in the last 30 days (USD). Reuses the Phase 6
        Cash Flow Dashboard tile via sudo."""
        tile = self._finance_dashboard_tile("_tile_recent_costs")
        usd = (tile or {}).get("usd") or {}
        value = usd.get("value") or 0.0
        if not value:
            return self._empty_kpi(
                _("No costs in 30 days"), value_display="$0",
                deeplink_action="neon_finance.action_dashboard_recent_costs")
        return {
            "value": value,
            "value_display": self._format_money(value, "USD"),
            "count": usd.get("count") or 0,
            "subtitle": _("%d posted -- 30d") % (usd.get("count") or 0),
            "empty": False,
            "deeplink_action":
                "neon_finance.action_dashboard_recent_costs",
        }

    @api.model
    def _finance_dashboard_tile(self, method_name, role="finance_all"):
        """Call a neon.finance.dashboard tile method via sudo, scoped
        to the full finance view. neon_finance is a hard dependency so
        the model is always present; the try/except guards only against
        a cross-module action-ref drift inside the reused tile (which
        we don't own) -- on failure the bookkeeper tile degrades to an
        empty payload rather than 500-ing the whole dashboard."""
        FinanceDash = self.env["neon.finance.dashboard"].sudo()
        try:
            return getattr(FinanceDash, method_name)(role) or {}
        except Exception:  # noqa: BLE001
            _logger.warning(
                "Bookkeeper tile reuse failed for %s; degrading to "
                "empty.", method_name, exc_info=True)
            return {}

    # ==================================================================
    # P8B.M3 -- Lead Tech variant KPI helpers.
    # ==================================================================
    def _kpi_crew_gaps(self):
        """Count of confirmed events within 7 days where assigned crew
        is short of the required total."""
        today = self._today_harare()
        end = today + timedelta(days=7)
        EventJob = self.env["commercial.event.job"].sudo()
        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ])
        gap_jobs = jobs.filtered(
            lambda j: (j.crew_total_count or 0) > (j.crew_confirmed_count or 0))
        if not gap_jobs:
            return self._empty_kpi(
                _("All crew slots filled"), value_display="0",
                deeplink_action="neon_jobs.commercial_event_job_action")
        total_gap = sum(
            (j.crew_total_count or 0) - (j.crew_confirmed_count or 0)
            for j in gap_jobs)
        return {
            "value": len(gap_jobs),
            "value_display": str(len(gap_jobs)),
            "subtitle": _("%d crew slot(s) open -- 7d") % total_gap,
            "empty": False,
            "deeplink_action": "neon_jobs.commercial_event_job_action",
        }

    def _kpi_certs_30(self):
        """Count of active certifications expiring within the next 30
        days. Reads neon.training.certification via sudo (lead-tech-
        tier users may lack direct ACL -- cross-module compute read)."""
        today = self._today_harare()
        end = today + timedelta(days=30)
        Cert = self.env["neon.training.certification"].sudo()
        certs = Cert.search_count([
            ("state", "=", "active"),
            ("date_expires", ">=", today),
            ("date_expires", "<=", end),
        ])
        if not certs:
            return self._empty_kpi(
                _("No certs expiring (30d)"), value_display="0")
        return {
            "value": certs,
            "value_display": str(certs),
            "subtitle": _("Expiring within 30 days"),
            "empty": False,
        }

    # ==================================================================
    # Jobs block (M3) -- today + next 7 days, ordered date asc / value
    # desc, limit 10 rows. Click-through opens the event_job form.
    # ==================================================================
    def _compute_jobs_block(self, dashboard_type):
        today = self._today_harare()
        end = today + timedelta(days=7)
        EventJob = self.env["commercial.event.job"].sudo()
        # ⚠️ DECISION (M3, marker 5 cont'd): orders by event_date asc,
        # NOT by value desc as the prompt §4.3 implies. event_job has
        # no value field of its own; the linked neon.finance.quote
        # carries amount_total. Secondary ordering by quote.amount_total
        # would require a per-row sub-query, doubling query count. We
        # order by event_date alone and surface value in the row data
        # via _quote_value_for(job).
        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ], order="event_date asc, id asc", limit=10)
        if not jobs:
            return {
                "empty": True,
                "empty_message": _("No upcoming jobs"),
                "empty_cta_label": _("Create your first event -->"),
                "empty_cta_action":
                    "neon_jobs.commercial_event_job_action",
                "rows": [],
            }
        rows = []
        for j in jobs:
            days_out = (j.event_date - today).days
            crew_total = j.crew_total_count or 0
            crew_confirmed = j.crew_confirmed_count or 0
            crew_gap = max(crew_total - crew_confirmed, 0)
            badge, color = _STATE_BADGE.get(j.state, ("PENDING", "grey"))
            value, value_display = self._quote_value_for(j)
            # ⚠️ DECISION (P9.M9.2, marker 1): four venue-coord keys
            # added to power the dashboard pin modal (D6). venue_id /
            # venue_latitude / venue_longitude are related fields off
            # commercial.event.job (added P9.M9.1); venue_full_address
            # is a non-stored compute. Reading them inside the existing
            # loop costs ONE extra res_partner prefetch for the
            # recordset -- no per-row query. Zero coords mean "unset"
            # per the M9.1 hasCoords getter convention.
            rows.append({
                "id": j.id,
                "client_name":
                    (j.partner_id and j.partner_id.name) or "",
                "event_name": j.name or "",
                "event_label": self._event_date_label(j, days_out),
                "days_label": self._days_label(days_out),
                "state": j.state,
                "state_label": badge,
                "state_color": color,
                "crew_confirmed": crew_confirmed,
                "crew_required": crew_total,
                "crew_gap": crew_gap,
                "venue":
                    (j.venue_id and j.venue_id.name) or "",
                "venue_id": (j.venue_id and j.venue_id.id) or False,
                "venue_latitude": j.venue_latitude or 0.0,
                "venue_longitude": j.venue_longitude or 0.0,
                "venue_full_address": j.venue_full_address or "",
                "value": value,
                "value_display": value_display,
                "deeplink_action":
                    "neon_jobs.commercial_event_job_action",
                "deeplink_id": j.id,
            })
        return {"empty": False, "rows": rows}

    def _quote_value_for(self, event_job):
        """Sum amount_total of every USD quote pointing at this
        event_job, in any non-terminal state. Returns (raw, display).

        ⚠️ DECISION (M3, marker inline): we walk neon.finance.quote
        from event_job_id (the canonical link) rather than mixing in
        sale.order. Multiple quotes per event_job are possible
        (revisions); we sum because the schema sketch §4.3 column
        header is just "value" without disambiguation.
        """
        Quote = self.env["neon.finance.quote"].sudo()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        if not usd:
            return 0.0, "$0"
        quotes = Quote.search([
            ("event_job_id", "=", event_job.id),
            ("currency_id", "=", usd.id),
            ("state", "not in", ("cancelled", "rejected", "expired")),
        ])
        total = sum(quotes.mapped("amount_total"))
        return total, self._format_money(total, "USD")

    def _event_date_label(self, event_job, days_out):
        if days_out == 0:
            return _("Today")
        if days_out == 1:
            return _("Tomorrow")
        if event_job.event_date:
            return event_job.event_date.strftime("%a %d %b")
        return ""

    def _days_label(self, days_out):
        if days_out == 0:
            return _("0 days")
        if days_out == 1:
            return _("1 day")
        return _("%d days") % days_out

    # ==================================================================
    # Crew & Equipment block (M4).
    #
    # ⚠️ DECISION (M4, marker 1): crew availability reads through
    # commercial_job_id.crew_assignment_ids on event_job. The crew
    # assignment model is commercial.job.crew (on the parent
    # commercial.job, NOT event_job-direct). Reaches by traversing the
    # related field. Discovery confirmed M1-M3 Jobs block already does
    # this pattern via crew_total_count / crew_confirmed_count
    # computes.
    #
    # ⚠️ DECISION (M4, marker 2): two-bucket equipment count -- "out"
    # vs "in workshop". Damaged / maintenance / decommissioned /
    # returned / draft units are EXCLUDED from the totals (they're
    # anomaly states, not "available stock" or "currently out").
    # Mockup-exact format: "Audio: 3/4" reads as out/(out+workshop).
    # If a lead tech wants the full state breakdown they have the
    # workshop dashboard from P5.M10. Trade-off is honest signal vs.
    # mockup parity; mockup wins per the schema-sketch lock.
    #
    # ⚠️ DECISION (M4, marker 3): "out" definition follows the
    # gate-1 lock: unit.state in (reserved, checked_out, transferred).
    # "transferred" is included even when both endpoints are internal
    # (workshop A -> workshop B) because the headline question is "is
    # it physically at THE workshop right now" -- a unit in transit
    # isn't on the shelf for next event's allocation regardless of
    # destination.
    # ==================================================================
    @api.model
    def _compute_crew_equipment_block(self, dashboard_type):
        """Two sub-widgets stacked vertically: crew availability table
        (next 7 days, one row per user_id who carries a crew
        assignment in the window or who is a lead-tech-tier user) +
        equipment one-liner (out vs workshop per category)."""
        return {
            "crew": self._compute_crew_availability(dashboard_type),
            "equipment": self._compute_equipment_summary(dashboard_type),
        }

    @api.model
    def _compute_crew_availability(self, dashboard_type):
        """Walk event_jobs in the next 7 days, aggregate crew
        assignments by user_id. Each user gets: name + role + booking
        range OR 'Available'. Sales/lead-tech variants (Phase 8B) can
        scope by lead_tech_id; M4 returns all assignments for any
        tier."""
        today = self._today_harare()
        end = today + timedelta(days=7)
        EventJob = self.env["commercial.event.job"].sudo()
        Crew = self.env["commercial.job.crew"].sudo()

        # ⚠️ DECISION (M4, marker 4): empty-state semantics. "No crew
        # configured" means zero commercial.job.crew rows ANYWHERE,
        # not zero in this 7-day window. A fresh install with no
        # event_jobs but crew users present should render the crew
        # list as "Available" (informational), not as an empty-state
        # CTA pointing at Settings -> Users.
        any_crew = Crew.search_count([])
        if not any_crew:
            return {
                "empty": True,
                "empty_message": _("No crew configured yet"),
                "empty_cta_label": _("Add team members →"),
                # base.action_res_users is the stock Users action.
                # Settings -> Users is the canonical create path.
                "empty_cta_action": "base.action_res_users",
                "rows": [],
            }

        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ])

        # Aggregate assignments by user_id. Skip rows where user_id is
        # NULL (freelancer-only contacts have partner_id but not
        # user_id; M4 widget shows internal-team availability only --
        # freelancer scheduling is a separate Phase 9 widget).
        per_user = {}  # user_id -> {"name", "role", "events": [...]}
        for job in jobs:
            for assignment in job.commercial_job_id.crew_assignment_ids:
                if not assignment.user_id:
                    continue
                # state == 'declined' means the crew member won't be
                # there. Exclude from the booking display but keep
                # the user as a row so they show "Available".
                if assignment.state == "declined":
                    continue
                uid = assignment.user_id.id
                entry = per_user.setdefault(uid, {
                    "user_id": uid,
                    "name": assignment.user_id.name,
                    "role": assignment.role,
                    "role_label":
                        dict(assignment._fields["role"].selection).get(
                            assignment.role, assignment.role),
                    "events": [],
                })
                # Track first/last booked date for the range label.
                entry["events"].append({
                    "event_job_id": job.id,
                    "event_name": job.name,
                    "event_date": job.event_date,
                    "state": assignment.state,
                })

        # Also include lead-tech-tier users who AREN'T booked in the
        # window, so Robin sees the full availability picture.
        lead_tech_group = self.env.ref(
            "neon_jobs.group_neon_jobs_crew_leader",
            raise_if_not_found=False,
        )
        if lead_tech_group:
            for user in lead_tech_group.users:
                if user.id in per_user:
                    continue
                per_user[user.id] = {
                    "user_id": user.id,
                    "name": user.name,
                    "role": "lead_tech",
                    "role_label": _("Lead Tech"),
                    "events": [],
                }

        rows = []
        for entry in per_user.values():
            if entry["events"]:
                # Build a compact "Mon-Thu" range label across the
                # event_dates this user is booked for in the window.
                sorted_dates = sorted(set(e["event_date"]
                                          for e in entry["events"]
                                          if e["event_date"]))
                if sorted_dates:
                    start_label = sorted_dates[0].strftime("%a")
                    end_label = sorted_dates[-1].strftime("%a")
                    if start_label == end_label:
                        range_label = start_label
                    else:
                        range_label = f"{start_label}-{end_label}"
                    booking_label = _(
                        "%(range)s · Booked"
                    ) % {"range": range_label}
                else:
                    booking_label = _("Booked")
                status = "booked"
            else:
                booking_label = _("Available")
                status = "available"

            rows.append({
                "user_id": entry["user_id"],
                "name": entry["name"],
                "role": entry["role"],
                "role_label": entry["role_label"],
                "booking_label": booking_label,
                "status": status,
                # First event_job for the deeplink target. If a user
                # has multiple bookings, we pick the earliest.
                "deeplink_event_job_id":
                    entry["events"][0]["event_job_id"]
                    if entry["events"] else False,
            })

        # Add gap rows: any event_job in the window with confirmed <
        # required gets surfaced as a separate "Gap" row.
        gap_rows = []
        for job in jobs:
            total = job.crew_total_count or 0
            confirmed = job.crew_confirmed_count or 0
            gap = total - confirmed
            if gap > 0:
                gap_rows.append({
                    "event_job_id": job.id,
                    "event_name": job.name,
                    "client_name":
                        (job.partner_id and job.partner_id.name) or "",
                    "event_date": (job.event_date.strftime("%a %d %b")
                                   if job.event_date else ""),
                    "gap_count": gap,
                    "crew_required": total,
                    "crew_confirmed": confirmed,
                    "deeplink_event_job_id": job.id,
                })

        # Sort: booked rows first (by name), then available rows by
        # name. Lead tech surfaced first within each band.
        def _row_sort_key(r):
            return (
                0 if r["status"] == "booked" else 1,
                0 if r["role"] == "lead_tech" else 1,
                r["name"],
            )
        rows.sort(key=_row_sort_key)

        return {
            "empty": False,
            "rows": rows,
            "gaps": gap_rows,
        }

    @api.model
    def _compute_equipment_summary(self, dashboard_type):
        """One row per equipment category: name + out_count +
        workshop_count. Empty-state when zero units configured."""
        Unit = self.env["neon.equipment.unit"].sudo()
        any_unit = Unit.search_count([])
        if not any_unit:
            return {
                "empty": True,
                "empty_message": _("No equipment configured yet"),
                # Equipment menu lives at neon_jobs.menu_workshop_*
                # but the safe deeplink is the unit list action.
                "empty_cta_label": _("Add inventory →"),
                "empty_cta_action":
                    "neon_jobs.neon_equipment_unit_action",
                "categories": [],
            }

        Category = self.env["neon.equipment.category"].sudo()
        cats = Category.search([])
        out_states = ("reserved", "checked_out", "transferred")
        workshop_state = "active"

        # Read all units at once via read_group for performance.
        Unit_sql = Unit.with_context(active_test=False)
        rg = Unit_sql.read_group(
            domain=[("state", "in", out_states + (workshop_state,))],
            fields=["equipment_category_id", "state"],
            groupby=["equipment_category_id", "state"],
            lazy=False,
        )
        # Build a {cat_id: {"out": N, "workshop": N}} map.
        by_cat = {}
        for row in rg:
            cat = row.get("equipment_category_id")
            cat_id = cat[0] if cat else False
            state = row.get("state")
            count = row.get("__count", 0)
            entry = by_cat.setdefault(
                cat_id, {"out": 0, "workshop": 0})
            if state in out_states:
                entry["out"] += count
            elif state == workshop_state:
                entry["workshop"] += count

        categories = []
        for cat in cats:
            counts = by_cat.get(cat.id, {"out": 0, "workshop": 0})
            total = counts["out"] + counts["workshop"]
            if total == 0:
                # Skip categories with zero qualifying units. They
                # exist but have all units in anomaly states; not
                # useful signal for the headline row.
                continue
            categories.append({
                "category_id": cat.id,
                "category_name": cat.name,
                "out_count": counts["out"],
                "workshop_count": counts["workshop"],
                "total": total,
                "display": f"{counts['out']}/{total}",
                "deeplink_action":
                    "neon_jobs.neon_equipment_unit_action",
            })

        # Capture "uncategorised" units only if present.
        uncategorised = by_cat.get(False, {"out": 0, "workshop": 0})
        if uncategorised["out"] + uncategorised["workshop"] > 0:
            categories.append({
                "category_id": False,
                "category_name": _("Uncategorised"),
                "out_count": uncategorised["out"],
                "workshop_count": uncategorised["workshop"],
                "total": uncategorised["out"] + uncategorised["workshop"],
                "display":
                    f"{uncategorised['out']}/"
                    f"{uncategorised['out'] + uncategorised['workshop']}",
                "deeplink_action":
                    "neon_jobs.neon_equipment_unit_action",
            })

        return {
            "empty": False,
            "categories": categories,
        }

    # ==================================================================
    # Sales block (M5).
    #
    # Three sub-widgets: pipeline-by-stage, win rate (last 90 days),
    # lead sources (last 30 days). All sums USD-only with a ZWG
    # disclosure -- ZWG sums land in M6 alongside the RBZ rate cron.
    #
    # ⚠️ DECISION (M5, marker 7): win/loss mapping locked at gate 1:
    #   * won  -> state == "accepted"   (customer signed)
    #   * lost -> state in ("rejected", "expired")  (declined OR aged out)
    # ``cancelled`` is excluded (internal abandonment, not a business
    # loss). Last 90 days uses write_date as the accept-transition
    # proxy (same caveat as the target actuals -- M6 polish item to
    # introduce a dedicated accepted_on / rejected_on audit field on
    # neon.finance.quote).
    # ==================================================================
    @api.model
    def _compute_sales_block(self, dashboard_type):
        return {
            "pipeline_by_stage": self._compute_pipeline_by_stage(),
            "win_rate": self._compute_win_rate(),
            "lead_sources": self._compute_lead_sources(),
        }

    # ==================================================================
    # DRAFT (item #1, pending Tatenda review of dashboard scope coupling):
    # live per-rep performance. ADDITIVE -- new methods + a per_rep_block
    # key in the EXISTING director payload branch + a new block widget.
    # No existing compute / dispatch branch / scope rule / record rule is
    # modified. _per_rep_aggregate is the REUSABLE helper item #5
    # (follow-up rollup) will call with its own (model, domain, measures).
    # ==================================================================
    @api.model
    def _per_rep_aggregate(self, model, rep_field, domain, measures):
        """Generic per-rep read_group.

        Returns {rep_id: {<measure_key>: value, '__count': n}}. Reusable
        across per-rep features (item #1 here; item #5 reuses it with its
        own domains). Runs sudo() so a director aggregates the whole team
        -- consistent with the existing team-wide tile pattern. Unassigned
        groups (no rep) are skipped from the per-rep table.
        """
        out = {}
        for g in self.env[model].sudo().read_group(
                domain, measures, [rep_field], lazy=False):
            rep = g.get(rep_field)
            if not rep:
                continue
            rep_id = rep[0] if isinstance(rep, (list, tuple)) else rep
            row = {"__count": g.get("__count", 0)}
            for m in measures:
                k = m.split(":")[0]
                row[k] = g.get(k) or 0
            out[rep_id] = row
        return out

    def _compute_per_rep_block(self):
        """Director-only per-rep table: pipeline value, win rate,
        conversion, open-activity count -- side by side.

        v1 metric definitions (a REVIEW POINT for Tatenda/Robin):
        pipeline = open quote total (USD); win rate = accepted /
        (accepted + rejected/expired) over 90d (mirrors _compute_win_rate);
        conversion = accepted / all quotes; activity = open mail.activity
        for the rep. Read-only sudo aggregate; per-rep attribution is why
        this is director-scoped (set only in the director payload branch).
        """
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        if not usd:
            return {"empty": True, "rows": [],
                    "empty_message": _("USD currency missing")}
        cutoff = self._harare_date_to_utc_string(
            self._today_harare() - timedelta(days=90))
        Q = "neon.finance.quote"
        pipe = self._per_rep_aggregate(
            Q, "salesperson_id",
            [("state", "in", ("pending_approval", "approved", "sent")),
             ("currency_id", "=", usd.id)],
            ["amount_total:sum"])
        won90 = self._per_rep_aggregate(
            Q, "salesperson_id",
            [("state", "=", "accepted"), ("write_date", ">=", cutoff)], [])
        lost90 = self._per_rep_aggregate(
            Q, "salesperson_id",
            [("state", "in", ("rejected", "expired")),
             ("write_date", ">=", cutoff)], [])
        won_all = self._per_rep_aggregate(
            Q, "salesperson_id", [("state", "=", "accepted")], [])
        total_q = self._per_rep_aggregate(Q, "salesperson_id", [], [])
        acts = self._per_rep_aggregate("mail.activity", "user_id", [], [])
        rep_ids = (set(pipe) | set(won90) | set(lost90)
                   | set(won_all) | set(total_q) | set(acts))
        Users = self.env["res.users"].sudo()
        rows = []
        for rid in rep_ids:
            w = won90.get(rid, {}).get("__count", 0)
            decided = w + lost90.get(rid, {}).get("__count", 0)
            tot = total_q.get(rid, {}).get("__count", 0)
            wa = won_all.get(rid, {}).get("__count", 0)
            rows.append({
                "rep_id": rid,
                "rep_name": Users.browse(rid).name or _("(unknown)"),
                "pipeline_value": pipe.get(rid, {}).get("amount_total", 0.0),
                "win_rate": round(100.0 * w / decided, 1) if decided else 0.0,
                "conversion": round(100.0 * wa / tot, 1) if tot else 0.0,
                "open_activities": acts.get(rid, {}).get("__count", 0),
            })
        rows.sort(key=lambda r: r["pipeline_value"], reverse=True)
        return {
            "empty": not rows,
            "empty_message": _("No per-rep activity yet"),
            "rows": rows,
            "currency_note": _("Pipeline + win/loss are USD-only (v1 DRAFT)"),
        }

    @api.model
    def _compute_pipeline_by_stage(self):
        """USD-only sums per pipeline state. Mirrors
        neon.finance.dashboard._tile_pipeline state filter.

        Mockup-friendly stage labels are mapped from the real
        neon.finance.quote states.
        """
        Quote = self.env["neon.finance.quote"].sudo()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        if not usd:
            return {
                "empty": True,
                "empty_message": _("USD currency missing"),
                "stages": [],
                "currency_note": _(
                    "ZWG totals ship in M6 with RBZ rate cron"),
            }
        active = Quote.search([
            ("state", "in",
             ("pending_approval", "approved", "sent")),
            ("currency_id", "=", usd.id),
        ])
        if not active:
            return {
                "empty": True,
                "empty_message": _("No active deals in pipeline"),
                "stages": [],
                "currency_note": _(
                    "ZWG totals ship in M6 with RBZ rate cron"),
            }

        # Build per-state buckets. Order = pipeline progression.
        order = [
            ("pending_approval", _("Qualified")),
            ("approved", _("Proposal Sent")),
            ("sent", _("Negotiation")),
        ]
        per_state = {s: {"count": 0, "value": 0.0} for s, _l in order}
        for q in active:
            if q.state in per_state:
                per_state[q.state]["count"] += 1
                per_state[q.state]["value"] += q.amount_total

        stages = []
        for state, label in order:
            entry = per_state[state]
            stages.append({
                "state": state,
                "label": label,
                "count": entry["count"],
                "value": entry["value"],
                "value_display": self._format_money(
                    entry["value"], "USD"),
                "deeplink_action":
                    "neon_finance.action_dashboard_pipeline",
            })
        return {
            "empty": False,
            "stages": stages,
            "currency_note": _(
                "USD only -- ZWG totals ship in M6"),
        }

    @api.model
    def _compute_win_rate(self):
        """Won / (Won + Lost) over the last 90 days, write_date-bounded.

        won  := state == 'accepted'
        lost := state in ('rejected', 'expired')

        Returns rate_pct=None when total == 0 (empty-state path
        for the OWL template).
        """
        Quote = self.env["neon.finance.quote"].sudo()
        today = self._today_harare()
        # p8a-hygiene tz: cutoff is Harare midnight of (today - 90d)
        # converted back to UTC for the DB comparison against
        # write_date (Odoo stores naive UTC).
        cutoff = self._harare_date_to_utc_string(
            today - timedelta(days=90))
        won = Quote.search_count([
            ("state", "=", "accepted"),
            ("write_date", ">=", cutoff),
        ])
        lost = Quote.search_count([
            ("state", "in", ("rejected", "expired")),
            ("write_date", ">=", cutoff),
        ])
        total = won + lost
        return {
            "won_count": won,
            "lost_count": lost,
            "total": total,
            "rate_pct": round(won / total * 100, 1) if total else None,
            "empty": total == 0,
            "empty_message": _("No closed deals in last 90 days"),
            "window_label": _("Last 90 days"),
        }

    @api.model
    def _compute_lead_sources(self):
        """Top 4 lead sources by count over the last 30 days.

        Uses crm.lead.source_id (utm.source). Leads without a source
        bucket into "Unspecified".
        """
        Lead = self.env["crm.lead"].sudo()
        today = self._today_harare()
        # p8a-hygiene tz: see _compute_win_rate for cutoff rationale.
        cutoff = self._harare_date_to_utc_string(
            today - timedelta(days=30))
        leads = Lead.search([("create_date", ">=", cutoff)])
        if not leads:
            return {
                "empty": True,
                "empty_message": _(
                    "No new leads in last 30 days"),
                "sources": [],
                "total": 0,
                "window_label": _("Last 30 days"),
            }
        by_source = {}
        for lead in leads:
            src_name = (lead.source_id.name
                        if lead.source_id
                        else _("Unspecified"))
            by_source[src_name] = by_source.get(src_name, 0) + 1
        total = len(leads)
        ranked = sorted(by_source.items(), key=lambda kv: -kv[1])[:4]
        return {
            "empty": False,
            "total": total,
            "window_label": _("Last 30 days"),
            "sources": [
                {
                    "source": name,
                    "count": count,
                    "pct": (round(count / total * 100)
                            if total else 0),
                }
                for name, count in ranked
            ],
        }

    # ==================================================================
    # HISTORICAL INTELLIGENCE (Sales-Intel Layer-1) -- director ONLY.
    #
    # Reads the INERT Zoho archive (neon.finance.quote.archive(.line) +
    # neon.finance.invoice.archive(.line)) and the two SQL-view report
    # models in neon_migration. NEVER reads / blends the live
    # neon.finance.quote / account.move (those are the live tiles above).
    #
    # ⚠️ DECISION (hist-intel, marker 1): SEPARATE helpers with their OWN
    # math -- the archive uses a free Char currency_code (USD/ZWG/ZAR), a
    # status_bucket selection, and quotation_date, none of which match the
    # live state-machine / res.currency model. So none of _kpi_pipeline /
    # _compute_win_rate / _compute_sales_block / the live _format_money
    # USD-filter is reused. A dedicated _fmt_hist formats money.
    #
    # ⚠️ DECISION (hist-intel, marker 2): neon_dashboard does NOT depend on
    # neon_migration (keeps the dashboard decoupled from a migration
    # module). Every archive read is via self.env.get(...) and degrades to
    # an honest empty-state if neon_migration is absent / not yet upgraded
    # -- the same optional-model pattern as _kpi_hr_licences_30's
    # self.env.get("neon.hr.licence").
    #
    # ⚠️ DECISION (hist-intel, marker 3): the never-blend rule is "money
    # sums are USD-only (non-USD disclosed); COUNTS span the whole book"
    # (a count is not a currency sum, so it cannot blend money). Labels +
    # subtitles always say "Historical" + the period span.
    # ==================================================================
    @api.model
    def _hist_period_span(self):
        """'Mon YYYY-Mon YYYY' span of the archived quotes, or '' if the
        archive is absent/empty. Computed from real min/max quotation_date
        (accuracy over a hardcoded label)."""
        QA = self.env.get("neon.finance.quote.archive")
        if QA is None:
            return ""
        QA = QA.sudo()
        first = QA.search([("quotation_date", "!=", False)],
                          order="quotation_date asc", limit=1)
        last = QA.search([("quotation_date", "!=", False)],
                         order="quotation_date desc", limit=1)
        if not first or not last:
            return ""
        return "%s–%s" % (first.quotation_date.strftime("%b %Y"),
                               last.quotation_date.strftime("%b %Y"))

    @api.model
    def _fmt_hist(self, amount, code="USD"):
        """Money formatter for the HISTORICAL tiles. Deliberately separate
        from the live _format_money path. Caller passes a SINGLE-currency
        total -- this never blends. USD -> '$', ZWG -> 'Z$', else code."""
        try:
            amount = float(amount or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        prefix = ("$" if code == "USD"
                  else ("Z$" if code == "ZWG" else (code + " ")))
        if abs(amount) >= 1_000_000:
            return "%s%.1fM" % (prefix, amount / 1_000_000.0)
        if abs(amount) >= 1000:
            return "%s%.1fk" % (prefix, amount / 1000.0)
        return "%s%s" % (prefix, "{:,.0f}".format(amount))

    @api.model
    def _rg_count(self, group, groupby_field):
        """read_group row count, robust across lazy/non-lazy result keys
        ('<field>_count' on lazy single-groupby, '__count' otherwise)."""
        return int(group.get(groupby_field + "_count")
                   or group.get("__count") or 0)

    @api.model
    def _compute_kpi_hist(self):
        """Director-only historical KPI tiles (returns 3 tile dicts)."""
        span = self._hist_period_span()
        return {
            "kpi_hist_winrate": self._kpi_hist_winrate(span),
            "kpi_hist_demand": self._kpi_hist_demand(span),
            "kpi_hist_quotes": self._kpi_hist_quotes(span),
        }

    def _kpi_hist_winrate(self, span):
        """All-time won / (won+lost) over the archive (count ratio across
        all currencies -- a count never blends money)."""
        QA = self.env.get("neon.finance.quote.archive")
        if QA is None:
            return self._empty_kpi(
                _("Zoho archive not installed"), value_display="--")
        QA = QA.sudo()
        won = QA.search_count([("status_bucket", "=", "won")])
        lost = QA.search_count([("status_bucket", "=", "lost")])
        total = won + lost
        if not total:
            return self._empty_kpi(
                _("No closed historical quotes"), value_display="--")
        rate = round(won / total * 100.0, 1)
        return {
            "value": rate,
            "value_display": "%g%%" % rate,
            "subtitle": _(
                "Historical · won %(w)d / lost %(l)d · %(s)s"
            ) % {"w": won, "l": lost, "s": span or _("all-time")},
            "empty": False,
            "deeplink_action": "neon_migration.action_hist_winloss",
        }

    def _kpi_hist_demand(self, span):
        """Most-quoted category by archived line count (all currencies)."""
        QLR = self.env.get("neon.finance.quote.line.report")
        if QLR is None:
            return self._empty_kpi(
                _("Zoho archive not installed"), value_display="--")
        QLR = QLR.sudo()
        groups = QLR.read_group([], ["quantity:sum"], ["category_prefix"])
        if not groups:
            return self._empty_kpi(
                _("No historical quote lines"), value_display="--")
        groups.sort(key=lambda g: self._rg_count(g, "category_prefix"),
                    reverse=True)
        top = groups[0]
        cat = top.get("category_prefix") or _("Uncategorised")
        cnt = self._rg_count(top, "category_prefix")
        return {
            "value": cnt,
            "value_display": "%s" % cat,
            "subtitle": _(
                "Most-quoted category · %(n)s lines · historical"
            ) % {"n": "{:,}".format(cnt)},
            "empty": False,
            "deeplink_action": "neon_migration.action_hist_demand",
        }

    def _kpi_hist_quotes(self, span):
        """Total imported quotes (all currencies) + USD value; non-USD
        disclosed (never blended into the headline figure)."""
        QA = self.env.get("neon.finance.quote.archive")
        if QA is None:
            return self._empty_kpi(
                _("Zoho archive not installed"), value_display="--")
        QA = QA.sudo()
        total_count = QA.search_count([])
        if not total_count:
            return self._empty_kpi(
                _("No imported quotes"), value_display="0")
        usd = QA.search([("currency_code", "=", "USD")])
        usd_value = sum(usd.mapped("amount_total"))
        non_usd = total_count - len(usd)
        if non_usd:
            sub = _(
                "USD value · %(n)d non-USD excluded · %(s)s"
            ) % {"n": non_usd, "s": span or _("all-time")}
        else:
            sub = _("Imported Zoho history · %(s)s") % {
                "s": span or _("all-time")}
        return {
            "value": usd_value,
            "value_display": "%s · %s" % (
                "{:,}".format(total_count),
                self._fmt_hist(usd_value, "USD")),
            "subtitle": sub,
            "empty": False,
            "deeplink_action": "neon_migration.action_quote_rollup",
        }

    @api.model
    def _compute_hist_intel_block(self):
        """Director-only 3-part historical card over the INERT archive.

        Part 1 top-5 categories by demand (line count, all currencies);
        Part 2 win-rate by category (line-volume basis, all currencies);
        Part 3 realisation -- quoted vs won vs invoiced VALUE per category
        (USD only -- money never blends). Each part deep-links its pivot.
        """
        span = self._hist_period_span()
        QLR = self.env.get("neon.finance.quote.line.report")
        RR = self.env.get("neon.finance.realisation.report")
        empty_block = {
            "empty": True,
            "empty_message": _("Zoho archive not installed"),
            "period_span": span,
            "currency_note": "",
            "top_categories": [], "win_by_category": [], "realisation": [],
            "deeplink_demand": "neon_migration.action_hist_demand",
            "deeplink_winloss": "neon_migration.action_hist_winloss",
            "deeplink_realisation": "neon_migration.action_hist_realisation",
        }
        if QLR is None or RR is None:
            return empty_block
        QLR = QLR.sudo()
        RR = RR.sudo()
        usd = [("currency_code", "=", "USD")]

        # Part 1 -- top 5 categories by demand (line count, all currencies).
        demand_groups = QLR.read_group(
            [], ["quantity:sum"], ["category_prefix"])
        demand_groups.sort(
            key=lambda g: self._rg_count(g, "category_prefix"), reverse=True)
        top_categories = [{
            "category": g.get("category_prefix") or _("Uncategorised"),
            "line_count": self._rg_count(g, "category_prefix"),
            "qty": int(g.get("quantity") or 0),
        } for g in demand_groups[:5]]

        # Part 2 -- win-rate by category (won/(won+lost) line volume, all
        # currencies). Line-volume basis (a line belongs to exactly one
        # quote+bucket); labelled as such -- NOT the quote-count headline.
        wl_groups = QLR.read_group(
            [], [], ["category_prefix", "status_bucket"], lazy=False)
        by_cat = {}
        for g in wl_groups:
            cat = g.get("category_prefix") or _("Uncategorised")
            bucket = g.get("status_bucket")
            cnt = int(g.get("__count") or 0)
            d = by_cat.setdefault(cat, {"won": 0, "lost": 0})
            if bucket == "won":
                d["won"] += cnt
            elif bucket == "lost":
                d["lost"] += cnt
        rated = []
        for cat, d in by_cat.items():
            closed = d["won"] + d["lost"]
            if not closed:
                continue
            rated.append({
                "category": cat, "won": d["won"], "lost": d["lost"],
                "rate_pct": round(d["won"] / closed * 100.0, 1),
            })
        rated.sort(key=lambda r: r["rate_pct"], reverse=True)
        win_by_category = rated[:3]
        if len(rated) > 3:
            seen = {r["category"] for r in win_by_category}
            win_by_category = win_by_category + [
                r for r in rated[-3:] if r["category"] not in seen]

        # Part 3 -- realisation: quoted vs won vs invoiced VALUE by category
        # (USD only; "Realised revenue", NOT margin). Top 5 by quoted value.
        real_groups = RR.read_group(
            usd, ["value:sum"], ["category_prefix", "kind"], lazy=False)
        real_map = {}
        for g in real_groups:
            cat = g.get("category_prefix") or _("Uncategorised")
            kind = g.get("kind")
            m = real_map.setdefault(
                cat, {"quoted": 0.0, "won": 0.0, "invoiced": 0.0})
            if kind in m:
                m[kind] += (g.get("value") or 0.0)
        real_sorted = sorted(
            real_map.items(), key=lambda kv: kv[1]["quoted"],
            reverse=True)[:5]
        realisation = [{
            "category": cat,
            "quoted_display": self._fmt_hist(v["quoted"], "USD"),
            "won_display": self._fmt_hist(v["won"], "USD"),
            "invoiced_display": self._fmt_hist(v["invoiced"], "USD"),
        } for cat, v in real_sorted]

        block = dict(empty_block)
        block.update({
            "empty": not (top_categories or win_by_category or realisation),
            "empty_message": _("No historical quote / invoice data yet"),
            "period_span": span,
            "currency_note": _(
                "Counts span all currencies; money values USD only "
                "· Historical (Zoho import)"),
            "top_categories": top_categories,
            "win_by_category": win_by_category,
            "realisation": realisation,
        })
        return block

    # ==================================================================
    # P8B variant blocks -- assembly + filter over existing models.
    # No new SQL patterns; reuses the quote / invoice / cost / cert /
    # event_job sources already walked elsewhere in this file.
    # ==================================================================
    @api.model
    def _compute_hot_deals_block(self):
        """Sales: quotes in Qualified (pending_approval) / Proposal
        Sent (approved), sorted by value desc. Top 10."""
        Quote = self.env["neon.finance.quote"].sudo()
        quotes = Quote.search([
            ("state", "in", ("pending_approval", "approved")),
        ], order="amount_total desc", limit=10)
        if not quotes:
            return {"empty": True,
                    "empty_message": _("No hot deals in the pipeline"),
                    "rows": []}
        stage_label = {
            "pending_approval": _("Qualified"),
            "approved": _("Proposal Sent"),
        }
        rows = [{
            "id": q.id,
            "client_name": (q.partner_id and q.partner_id.name) or "",
            "quote_name": q.name or f"#{q.id}",
            "stage_label": stage_label.get(q.state, q.state),
            "value_display": self._format_money(
                q.amount_total, q.currency_id.name or "USD"),
            "deeplink_action": "neon_finance.action_dashboard_pipeline",
            "deeplink_id": q.id,
        } for q in quotes]
        return {"empty": False, "rows": rows}

    @api.model
    def _compute_aging_quotes_block(self):
        """Sales: open quotes (draft/sent) with no movement in >7
        days, oldest first. Top 10."""
        Quote = self.env["neon.finance.quote"].sudo()
        today = self._today_harare()
        cutoff = self._harare_date_to_utc_string(today - timedelta(days=7))
        quotes = Quote.search([
            ("state", "in", ("draft", "sent")),
            ("write_date", "<", cutoff),
        ], order="write_date asc", limit=10)
        if not quotes:
            return {"empty": True,
                    "empty_message": _("No aging quotes"),
                    "rows": []}
        now_h = self._now_harare()
        rows = []
        for q in quotes:
            aware = pytz.utc.localize(q.write_date)
            age_days = (now_h - aware).days
            rows.append({
                "id": q.id,
                "client_name": (q.partner_id and q.partner_id.name) or "",
                "quote_name": q.name or f"#{q.id}",
                "state": q.state,
                "age_days": age_days,
                "age_label": _("%d days") % age_days,
                "value_display": self._format_money(
                    q.amount_total, q.currency_id.name or "USD"),
                "deeplink_action": "neon_finance.action_dashboard_pipeline",
                "deeplink_id": q.id,
            })
        return {"empty": False, "rows": rows}

    @api.model
    def _compute_budget_alerts_block(self):
        """Bookkeeper: ok/warn/breach/severe event-budget counts.
        Reuses the Phase 6 Cash Flow Dashboard tile via sudo."""
        tile = self._finance_dashboard_tile("_tile_budget_alert_summary")
        levels = (tile or {}).get("levels") or {}
        ok = int(levels.get("ok", 0))
        warn = int(levels.get("warn", 0))
        breach = int(levels.get("breach", 0))
        severe = int(levels.get("severe", 0))
        return {
            "empty": (ok + warn + breach + severe) == 0,
            "empty_message": _("No event budgets tracked yet"),
            "ok": ok, "warn": warn, "breach": breach, "severe": severe,
            "has_issues": (warn + breach + severe) > 0,
        }

    @api.model
    def _compute_invoice_queue_block(self):
        """Bookkeeper: draft customer invoices awaiting posting,
        oldest first. Top 10."""
        Move = self.env["account.move"].sudo()
        drafts = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "draft"),
        ], order="invoice_date asc, create_date asc", limit=10)
        if not drafts:
            return {"empty": True,
                    "empty_message": _("No invoices awaiting posting"),
                    "rows": []}
        rows = [{
            "id": mv.id,
            "name": mv.name or mv.ref or f"#{mv.id}",
            "client_name": (mv.partner_id and mv.partner_id.name) or "",
            "date_display": (mv.invoice_date.strftime("%d %b")
                             if mv.invoice_date else _("No date")),
            "amount_display": self._format_money(
                mv.amount_total, mv.currency_id.name or "USD"),
        } for mv in drafts]
        return {"empty": False, "rows": rows}

    @api.model
    def _compute_zig_costs_block(self):
        """Bookkeeper: current ZiG-USD rate + last 5 costs over $500."""
        rate = self._get_zig_usd_rate()
        block = {
            "rate": rate,
            "rate_display": (f"{rate:.2f}" if rate and rate > 0
                             else _("Not set")),
            "rate_source": self._zig_rate_source(),
            "rate_as_of": self._zig_rate_timestamp_harare(),
            "costs": [],
        }
        Cost = self.env["neon.finance.cost.line"].sudo()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        domain = [("amount", ">", 500)]
        if usd:
            domain.append(("currency_id", "=", usd.id))
        costs = Cost.search(domain, order="date_incurred desc", limit=5)
        block["costs_empty"] = not costs
        block["costs"] = [{
            "id": c.id,
            "label": (c.name or (c.event_job_id and c.event_job_id.name)
                      or f"#{c.id}"),
            "date_display": (c.date_incurred.strftime("%d %b")
                             if c.date_incurred else ""),
            "amount_display": self._format_money(
                c.amount, c.currency_id.name or "USD"),
        } for c in costs]
        return block

    @api.model
    def _compute_crew_gaps_block(self):
        """Lead Tech: upcoming events (next 7d) with unfilled crew
        slots, soonest first."""
        today = self._today_harare()
        end = today + timedelta(days=7)
        EventJob = self.env["commercial.event.job"].sudo()
        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ], order="event_date asc, id asc")
        rows = []
        for job in jobs:
            total = job.crew_total_count or 0
            confirmed = job.crew_confirmed_count or 0
            gap = total - confirmed
            if gap <= 0:
                continue
            days_out = (job.event_date - today).days
            rows.append({
                "id": job.id,
                "event_name": job.name or "",
                "client_name": (job.partner_id and job.partner_id.name) or "",
                "event_date_label": (job.event_date.strftime("%a %d %b")
                                     if job.event_date else ""),
                "days_out": days_out,
                "crew_confirmed": confirmed,
                "crew_required": total,
                "gap_count": gap,
                "deeplink_id": job.id,
            })
        if not rows:
            return {"empty": True,
                    "empty_message": _("All upcoming crew slots filled"),
                    "rows": []}
        return {"empty": False, "rows": rows}

    @api.model
    def _compute_cert_expiry_block(self):
        """Lead Tech: active certifications expiring in the next 30
        days, soonest first. Reads via sudo (cross-module)."""
        Cert = self.env["neon.training.certification"].sudo()
        today = self._today_harare()
        end = today + timedelta(days=30)
        certs = Cert.search([
            ("state", "=", "active"),
            ("date_expires", ">=", today),
            ("date_expires", "<=", end),
        ], order="date_expires asc", limit=10)
        if not certs:
            return {"empty": True,
                    "empty_message": _("No certifications expiring soon"),
                    "rows": []}
        rows = []
        for c in certs:
            days = (c.date_expires - today).days
            rows.append({
                "id": c.id,
                "tech_name": (c.user_id and c.user_id.name) or "",
                "cert_type": (c.type_id.name if c.type_id else ""),
                "days_remaining": days,
                "days_label": _("%d days") % days,
                "expires_display": c.date_expires.strftime("%d %b %Y"),
                "critical": days <= 14,
            })
        return {"empty": False, "rows": rows}

    # ==================================================================
    # M6 -- Finance block (AR aging + cash detail).
    #
    # The block consumes the same cash breakdown as the Cash KPI tile
    # (single round-trip; one journal walk per RPC). AR aging is
    # 3-bucket (0-30 / 31-60 / 61-90+) with the 61-90+ bucket marked
    # critical for the mockup F3 red highlight.
    #
    # ⚠️ DECISION (M6, marker 4): AR sums in USD-equivalent. USD
    # invoices contribute their amount_residual directly; ZiG
    # invoices convert via the manual rate. If the rate is unset,
    # ZiG invoices are excluded from the bucket totals AND the
    # exclusion is surfaced via a 'zig_excluded' flag the OWL
    # template renders as a subtitle.
    #
    # ⚠️ DECISION (M6, marker 5): "today" cutoff for overdue uses
    # Harare today (per p8a-hygiene gate-1 lock). Invoice
    # invoice_date_due is a Date field stored TZ-naively; comparing
    # to Harare-today gives the Robin-friendly answer at any UTC
    # clock-hour.
    # ==================================================================
    @api.model
    def _compute_finance_block(self, dashboard_type):
        cash = self._cash_journals_breakdown()
        ar = self._compute_ar_aging()
        return {
            "cash": cash,
            "ar_aging": ar,
        }

    @api.model
    def _compute_ar_aging(self):
        today = self._today_harare()
        Move = self.env["account.move"].sudo()
        overdue = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in",
             ("not_paid", "partial", "in_payment")),
            ("invoice_date_due", "<", today),
        ])

        rate = self._get_zig_usd_rate()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)

        buckets = {
            "0-30": {"count": 0, "amount_usd_equiv": 0.0},
            "31-60": {"count": 0, "amount_usd_equiv": 0.0},
            "61-90+": {"count": 0, "amount_usd_equiv": 0.0},
        }
        zig_excluded_count = 0

        for inv in overdue:
            days = (today - inv.invoice_date_due).days
            if days <= 30:
                bucket = "0-30"
            elif days <= 60:
                bucket = "31-60"
            else:
                bucket = "61-90+"
            buckets[bucket]["count"] += 1
            residual = inv.amount_residual or 0.0
            inv_currency = inv.currency_id
            if usd and inv_currency.id == usd.id:
                buckets[bucket]["amount_usd_equiv"] += residual
            elif zwg and inv_currency.id == zwg.id:
                if rate and rate > 0:
                    buckets[bucket]["amount_usd_equiv"] += residual / rate
                else:
                    zig_excluded_count += 1
                    # Don't add to total; surfaced via flag.
            else:
                # Other currencies (unusual on this build): treat
                # as USD-equivalent at face value rather than skip.
                buckets[bucket]["amount_usd_equiv"] += residual

        if not overdue:
            return {
                "empty": True,
                "empty_message": _("No overdue invoices"),
                "buckets": [],
                "total_count": 0,
                "total_amount_display": "$0",
                "zig_excluded_count": 0,
                "deeplink_action":
                    "neon_finance.action_dashboard_top_overdue",
            }

        bucket_rows = []
        for key, label, critical in (
            ("0-30", _("0-30 days"), False),
            ("31-60", _("31-60 days"), False),
            ("61-90+", _("61-90+ days"), True),
        ):
            data = buckets[key]
            bucket_rows.append({
                "key": key,
                "label": label,
                "count": data["count"],
                "amount": data["amount_usd_equiv"],
                "amount_display": self._format_money(
                    data["amount_usd_equiv"], "USD"),
                "critical": critical,
            })
        total_amount = sum(b["amount"] for b in bucket_rows)
        return {
            "empty": False,
            "buckets": bucket_rows,
            "total_count": len(overdue),
            "total_amount_display": self._format_money(
                total_amount, "USD"),
            "zig_excluded_count": zig_excluded_count,
            "zig_excluded_message": (
                _(
                    "%(n)s ZiG invoice(s) excluded -- no rate set"
                ) % {"n": zig_excluded_count}
                if zig_excluded_count else ""
            ),
            "deeplink_action":
                "neon_finance.action_dashboard_top_overdue",
        }

    # ==================================================================
    # M7 -- Alerts panel.
    #
    # ⚠️ DECISION (M7, marker 4): five sources, per-user dismissal,
    # severity sort. Each source returns a list of alert dicts with
    # a stable ``fingerprint``. _compute_alerts_block aggregates,
    # filters by per-tier scoping (gate-1 lock §Per-source tier
    # scoping), filters out dismissed fingerprints, sorts by
    # (severity, detected_at), caps at 10 with has_more flag.
    #
    # ⚠️ DECISION (M7, marker 5): fingerprint scheme (gate-1 locked):
    #   overdue_invoice:<id>:week-<iso-year>-<iso-week>
    #   pending_approval:<id>:week-<iso-year>-<iso-week>
    #   crew_gap:<job_id>:<event_date_iso>
    #   stale_quote:<id>:week-<iso-year>-<iso-week>
    #   forecast_at_risk:<target_id>
    # ISO-week bucket on time-decaying sources gives automatic
    # re-surface next week if the underlying condition persists.
    # Crew_gap uses event_date so a rescheduled event re-surfaces.
    # Forecast uses target id only -- new target period = new
    # fingerprint.
    #
    # ⚠️ DECISION (M7, marker 6): documented v1 limitation -- the
    # fingerprint does NOT re-surface on severity escalation alone.
    # An overdue invoice dismissed at 'warning' age stays dismissed
    # when it crosses into 'critical' age within the same ISO week.
    # Re-surfacing on severity change is a Phase 8.5 polish item:
    # would require encoding severity in the fingerprint, which
    # makes every-day-the-clock-ticks generate a new dismissal row.
    # Acceptable for v1 given the weekly re-surface cadence.
    # ==================================================================
    _ALERT_MAX_VISIBLE = 10

    _SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}

    @api.model
    def _iso_week_bucket(self, dt_or_date):
        """Return 'week-<iso-year>-<iso-week>' for the given datetime
        or date. Bucket is computed in Harare-tz so a dismiss at
        23:30 UTC Sunday (Harare Monday 01:30) lands in the new
        week as expected."""
        if hasattr(dt_or_date, "astimezone"):
            local = dt_or_date.astimezone(HARARE_TZ).date()
        elif hasattr(dt_or_date, "isocalendar"):
            local = dt_or_date
        else:
            local = self._today_harare()
        y, w, _d = local.isocalendar()
        return f"week-{y:04d}-{w:02d}"

    @api.model
    def _compute_alerts_block(self, dashboard_type):
        user = self.env.user
        flat = []
        flat.extend(self._alerts_overdue_invoices(user))
        flat.extend(self._alerts_pending_approvals(user))
        flat.extend(self._alerts_crew_gaps(user))
        flat.extend(self._alerts_stale_quotes(user))
        flat.extend(self._alerts_forecast_at_risk(user))

        # Filter dismissed.
        Dismissal = self.env["neon.dashboard.alert.dismissal"]
        dismissed = Dismissal.get_dismissed_fingerprints_for_user(
            user.id)
        flat = [a for a in flat if a["fingerprint"] not in dismissed]

        # Severity sort (critical first), detected_at desc within.
        flat.sort(key=lambda a: (
            self._SEVERITY_RANK.get(a["severity"], 99),
            -1 * self._isoformat_to_sortable_int(
                a.get("detected_at", "")),
        ))

        severity_counts = {"critical": 0, "warning": 0, "info": 0}
        for a in flat:
            sev = a.get("severity", "info")
            if sev in severity_counts:
                severity_counts[sev] += 1

        total = len(flat)
        visible = flat[: self._ALERT_MAX_VISIBLE]
        has_more = total > self._ALERT_MAX_VISIBLE

        if total == 0:
            return {
                "empty": True,
                "empty_message": _("Everything looks healthy"),
                "total_count": 0,
                "severity_counts": severity_counts,
                "alerts": [],
                "has_more": False,
            }
        return {
            "empty": False,
            "total_count": total,
            "severity_counts": severity_counts,
            "alerts": visible,
            "has_more": has_more,
        }

    @staticmethod
    def _isoformat_to_sortable_int(iso_string):
        """Sort-key for ISO timestamps: strip non-digits, parse to
        int. Lexical/numeric ordering matches chronological."""
        if not iso_string:
            return 0
        digits = "".join(c for c in iso_string if c.isdigit())
        return int(digits[:14]) if digits else 0

    # ------------------------------------------------------------------
    # Tier-scoping helpers (gate-1 lock).
    # ------------------------------------------------------------------
    @api.model
    def _user_is_approver(self, user=None):
        user = user or self.env.user
        return user.has_group(
            "neon_finance.group_neon_finance_approver")

    @api.model
    def _user_is_bookkeeper(self, user=None):
        user = user or self.env.user
        return user.has_group(
            "neon_finance.group_neon_finance_bookkeeper")

    @api.model
    def _user_is_sales(self, user=None):
        user = user or self.env.user
        return (user.has_group("neon_finance.group_neon_finance_sales")
                or user.has_group("neon_core.group_neon_sales_rep"))

    @api.model
    def _user_is_lead_tech(self, user=None):
        user = user or self.env.user
        return (user.has_group("neon_jobs.group_neon_jobs_crew_leader")
                or user.has_group("neon_core.group_neon_lead_tech"))

    # ------------------------------------------------------------------
    # Source (a): Overdue invoices.
    # ------------------------------------------------------------------
    @api.model
    def _alerts_overdue_invoices(self, user):
        is_super = self._is_superuser(user)
        is_approver = self._user_is_approver(user)
        is_bookkeeper = self._user_is_bookkeeper(user)
        is_sales = self._user_is_sales(user)
        if not (is_super or is_approver or is_bookkeeper or is_sales):
            return []

        today = self._today_harare()
        Move = self.env["account.move"].sudo()
        base = [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in",
             ("not_paid", "partial", "in_payment")),
            ("invoice_date_due", "<", today),
        ]
        if is_sales and not (is_super or is_approver or is_bookkeeper):
            user_quotes = self.env["neon.finance.quote"].sudo().search([
                ("salesperson_id", "=", user.id),
            ])
            user_sched_names = self.env[
                "neon.finance.invoice.schedule"
            ].sudo().search([
                ("quote_id", "in", user_quotes.ids),
            ]).mapped("name")
            if not user_sched_names:
                return []
            base = base + [("ref", "in", user_sched_names)]

        overdue = Move.search(base)
        week_bucket = self._iso_week_bucket(today)
        now_iso = self._now_harare().isoformat()
        alerts = []
        for inv in overdue:
            days = (today - inv.invoice_date_due).days
            if days > 90:
                severity = "critical"
            elif days > 30:
                severity = "warning"
            else:
                severity = "info"
            alerts.append({
                "fingerprint":
                    f"overdue_invoice:{inv.id}:{week_bucket}",
                "source": "finance",
                "severity": severity,
                "title": _(
                    "Invoice %(name)s - %(days)d days overdue"
                ) % {"name": inv.name or inv.ref or f"#{inv.id}",
                     "days": days},
                "subtitle": _(
                    "%(partner)s - %(amt)s"
                ) % {
                    "partner": (inv.partner_id.name or ""),
                    "amt": self._format_money(
                        inv.amount_residual,
                        inv.currency_id.name or "USD"),
                },
                "detected_at": now_iso,
                "deeplink_action":
                    "neon_finance.action_dashboard_top_overdue",
                "deeplink_res_id": inv.id,
                "can_acknowledge": True,
            })
        return alerts

    # ------------------------------------------------------------------
    # Source (b): Pending OD/MD approvals.
    # ------------------------------------------------------------------
    @api.model
    def _alerts_pending_approvals(self, user):
        if not (self._is_superuser(user)
                or self._user_is_approver(user)):
            return []
        Quote = self.env["neon.finance.quote"].sudo()
        pending = Quote.search([("state", "=", "pending_approval")])
        now_harare = self._now_harare()
        today = self._today_harare()
        week_bucket = self._iso_week_bucket(today)
        now_iso = now_harare.isoformat()
        alerts = []
        for q in pending:
            write_dt = q.write_date
            if write_dt is None:
                hours_pending = 0
            else:
                aware = pytz.utc.localize(write_dt)
                hours_pending = (
                    now_harare - aware
                ).total_seconds() / 3600.0
            if hours_pending > 72:
                severity = "critical"
            elif hours_pending > 24:
                severity = "warning"
            else:
                severity = "info"
            alerts.append({
                "fingerprint":
                    f"pending_approval:{q.id}:{week_bucket}",
                "source": "sales",
                "severity": severity,
                "title": _(
                    "Quote %(name)s pending approval"
                ) % {"name": q.name or f"#{q.id}"},
                "subtitle": _(
                    "%(partner)s - %(amt)s - %(hrs)d hours waiting"
                ) % {
                    "partner": (q.partner_id.name or ""),
                    "amt": self._format_money(
                        q.amount_total,
                        q.currency_id.name or "USD"),
                    "hrs": int(hours_pending),
                },
                "detected_at": now_iso,
                "deeplink_action":
                    "neon_finance.action_dashboard_pipeline",
                "deeplink_res_id": q.id,
                "can_acknowledge": True,
            })
        return alerts

    # ------------------------------------------------------------------
    # Source (c): Crew gaps.
    # ------------------------------------------------------------------
    @api.model
    def _alerts_crew_gaps(self, user):
        if not (self._is_superuser(user)
                or self._user_is_approver(user)
                or self._user_is_lead_tech(user)):
            return []
        EventJob = self.env["commercial.event.job"].sudo()
        today = self._today_harare()
        end = today + timedelta(days=7)
        jobs = EventJob.search([
            ("event_date", ">=", today),
            ("event_date", "<=", end),
            ("state", "not in", ("cancelled", "released")),
        ])
        now_iso = self._now_harare().isoformat()
        alerts = []
        for job in jobs:
            total = job.crew_total_count or 0
            confirmed = job.crew_confirmed_count or 0
            gap = total - confirmed
            if gap <= 0:
                continue
            days_until = (job.event_date - today).days
            severity = "critical" if days_until <= 2 else "warning"
            event_iso = job.event_date.isoformat()
            alerts.append({
                "fingerprint":
                    f"crew_gap:{job.id}:{event_iso}",
                "source": "operations",
                "severity": severity,
                "title": _(
                    "Crew gap: %(name)s - %(gap)d needed"
                ) % {"name": job.name, "gap": gap},
                "subtitle": _(
                    "%(date)s (%(days)d days) - "
                    "%(conf)d/%(total)d confirmed"
                ) % {
                    "date": (job.event_date.strftime("%a %d %b")
                             if job.event_date else ""),
                    "days": days_until,
                    "conf": confirmed,
                    "total": total,
                },
                "detected_at": now_iso,
                "deeplink_action":
                    "neon_jobs.commercial_event_job_action",
                "deeplink_res_id": job.id,
                "can_acknowledge": True,
            })
        return alerts

    # ------------------------------------------------------------------
    # Source (d): Stale quotes.
    # ------------------------------------------------------------------
    @api.model
    def _alerts_stale_quotes(self, user):
        is_super = self._is_superuser(user)
        is_approver = self._user_is_approver(user)
        is_sales = self._user_is_sales(user)
        if not (is_super or is_approver or is_sales):
            return []
        Quote = self.env["neon.finance.quote"].sudo()
        now_harare = self._now_harare()
        cutoff_14 = (now_harare - timedelta(days=14)).astimezone(
            pytz.utc).replace(tzinfo=None)
        domain = [
            ("state", "in",
             ("pending_approval", "approved", "sent")),
            ("write_date", "<", cutoff_14),
        ]
        if is_sales and not (is_super or is_approver):
            domain.append(("salesperson_id", "=", user.id))
        stale = Quote.search(domain)
        today = self._today_harare()
        week_bucket = self._iso_week_bucket(today)
        now_iso = now_harare.isoformat()
        alerts = []
        for q in stale:
            aware = pytz.utc.localize(q.write_date)
            age_days = (now_harare - aware).days
            severity = "warning" if age_days > 30 else "info"
            alerts.append({
                "fingerprint":
                    f"stale_quote:{q.id}:{week_bucket}",
                "source": "sales",
                "severity": severity,
                "title": _(
                    "Quote %(name)s stale (%(days)d days)"
                ) % {"name": q.name or f"#{q.id}", "days": age_days},
                "subtitle": _(
                    "%(partner)s - %(state)s - %(amt)s"
                ) % {
                    "partner": (q.partner_id.name or ""),
                    "state": q.state,
                    "amt": self._format_money(
                        q.amount_total,
                        q.currency_id.name or "USD"),
                },
                "detected_at": now_iso,
                "deeplink_action":
                    "neon_finance.action_dashboard_pipeline",
                "deeplink_res_id": q.id,
                "can_acknowledge": True,
            })
        return alerts

    # ------------------------------------------------------------------
    # Source (e): Forecast at risk.
    # ------------------------------------------------------------------
    @api.model
    def _alerts_forecast_at_risk(self, user):
        if not (self._is_superuser(user)
                or self._user_is_approver(user)):
            return []
        Target = self.env["neon.dashboard.target"].sudo()
        today = self._today_harare()
        target = Target.search([
            ("target_type", "=", "revenue"),
            ("active", "=", True),
            ("date_from", "<=", today),
            ("date_to", ">=", today),
        ], limit=1, order="date_from desc")
        if not target:
            return []
        period_total = (target.date_to - target.date_from).days + 1
        period_elapsed = (today - target.date_from).days + 1
        if period_total <= 0:
            return []
        expected_pct = (period_elapsed / period_total) * 100.0
        actual_pct = target.progress_pct or 0.0
        gap = expected_pct - actual_pct
        if gap < 20:
            return []
        return [{
            "fingerprint": f"forecast_at_risk:{target.id}",
            "source": "sales",
            "severity": "warning",
            "title": _(
                "Forecast at risk: %(actual)d%% vs %(expected)d%% "
                "expected"
            ) % {"actual": int(actual_pct),
                 "expected": int(expected_pct)},
            "subtitle": _(
                "%(name)s - %(elapsed)d of %(total)d days elapsed"
            ) % {
                "name": target.name,
                "elapsed": period_elapsed,
                "total": period_total,
            },
            "detected_at": self._now_harare().isoformat(),
            "deeplink_action":
                "neon_dashboard.action_neon_dashboard_target",
            "deeplink_res_id": target.id,
            "can_acknowledge": True,
        }]

    # ------------------------------------------------------------------
    # Dismissal RPC -- idempotent ack.
    # ------------------------------------------------------------------
    @api.model
    def dashboard_dismiss_alert(self, fingerprint):
        """Creates a dismissal row for the current user if absent,
        then returns the refreshed alerts_block payload."""
        self._check_dashboard_access()
        if fingerprint:
            Dismissal = self.env["neon.dashboard.alert.dismissal"]
            existing = Dismissal.search([
                ("user_id", "=", self.env.user.id),
                ("fingerprint", "=", fingerprint),
            ], limit=1)
            if not existing:
                Dismissal.create({
                    "user_id": self.env.user.id,
                    "fingerprint": fingerprint,
                })
        resolved = self._resolve_dashboard_type(None)
        return self._compute_alerts_block(resolved)

    # ==================================================================
    # M8 -- Tasks block.
    #
    # Surfaces the current user's open mail.activity rows -- Odoo's
    # native to-do mechanism. No new model, no new ACL, no new group:
    # mail.activity rows scope to current user by user_id and respect
    # parent-record permissions natively.
    #
    # ⚠️ DECISION (M8, marker 1): accept the duplication with M7
    # pending-approval alerts for v1. P6.M4 schedules an activity on
    # the approval record when a quote enters pending_approval; the
    # same approval surfaces as an M7 alert. Two surfaces for the
    # same thing, but DIFFERENT action affordances:
    #   M7 Alert "Ack" = system-detected condition; disappears when
    #                    state changes (e.g., quote -> approved)
    #   M8 Task "Done" = user-assigned action; disappears when the
    #                    activity is completed
    # Robin has two ways to resolve, both valid. Future polish
    # candidate: dedup filter to hide M8 tasks whose res_id already
    # appears in M7 alerts. Premature for v1 -- the surfaces have
    # different semantics. Same reasoning applies to budget breach
    # activities scheduled by neon_finance.commercial_event_job
    # extension and to invoice-schedule activities.
    #
    # ⚠️ DECISION (M8, marker 2): urgency bucketing uses
    # _today_harare(), NOT mail.activity.state. The stock state
    # field computes overdue/today/planned against UTC midnight,
    # which misclassifies "Today" for users in +2 timezones. See
    # p8a-hygiene gate-1 lock + the inline comment in
    # _compute_tasks_block for the precise reason.
    # ==================================================================
    _TASK_MAX_VISIBLE = 10

    @api.model
    def _compute_tasks_block(self):
        """Aggregate the current user's open mail.activity rows.

        Activities are deleted when marked done in Odoo, so any
        existing row IS open by definition -- no state filter
        needed.
        """
        Activity = self.env["mail.activity"]
        # Harare-tz urgency: mail.activity.state uses UTC midnight,
        # which misclassifies "Today" for users in +2 timezones.
        # See M6 hygiene + M8 DECISION marker 2.
        today = self._today_harare()
        activities = Activity.search([
            ("user_id", "=", self.env.user.id),
        ], order="date_deadline asc, id asc")

        if not activities:
            return {
                "empty": True,
                "empty_message": _(
                    "Nothing on your list -- caught up"),
                "total_count": 0,
                "overdue_count": 0,
                "today_count": 0,
                "upcoming_count": 0,
                "tasks": [],
                "has_more": False,
            }

        rows = []
        overdue = 0
        due_today = 0
        upcoming = 0
        for act in activities:
            deadline = act.date_deadline
            if deadline is False or deadline is None:
                # No deadline -> treat as upcoming (won't have an
                # 'overdue' identity without a date).
                urgency = "upcoming"
                upcoming += 1
            elif deadline < today:
                urgency = "overdue"
                overdue += 1
            elif deadline == today:
                urgency = "today"
                due_today += 1
            else:
                urgency = "upcoming"
                upcoming += 1

            rows.append({
                "id": act.id,
                "summary": (act.summary
                            or (act.activity_type_id.name if
                                act.activity_type_id else "")
                            or _("Activity")),
                "activity_type":
                    (act.activity_type_id.name
                     if act.activity_type_id else ""),
                "activity_icon":
                    (act.activity_type_id.icon
                     if act.activity_type_id
                     and act.activity_type_id.icon else "fa-tasks"),
                "deadline_display":
                    self._format_deadline(deadline, today),
                "urgency": urgency,
                "source_label": self._task_source_label(act),
                "res_model": act.res_model or "",
                "res_id": act.res_id or 0,
                # Internal sort key only; not exposed to OWL.
                "_sort_deadline": deadline or date.max,
            })

        # Sort: overdue first (oldest deadline asc -> most overdue
        # first), then today, then upcoming (earliest deadline
        # first). Within same urgency, sort by deadline asc.
        _URGENCY_RANK = {"overdue": 0, "today": 1, "upcoming": 2}
        rows.sort(key=lambda r: (
            _URGENCY_RANK.get(r["urgency"], 99),
            r["_sort_deadline"],
            r["id"],
        ))
        # Strip internal sort key before returning.
        for r in rows:
            r.pop("_sort_deadline", None)

        # We want overdue oldest-first (most overdue at top). The
        # ORM search already orders by date_deadline asc, so within
        # overdue the oldest deadlines come first naturally.
        total = len(rows)
        visible = rows[: self._TASK_MAX_VISIBLE]
        return {
            "empty": False,
            "total_count": total,
            "overdue_count": overdue,
            "today_count": due_today,
            "upcoming_count": upcoming,
            "tasks": visible,
            "has_more": total > self._TASK_MAX_VISIBLE,
        }

    @api.model
    def _format_deadline(self, deadline, today):
        """Human-readable deadline string. Used by the OWL template's
        right-aligned column. Returns 'Overdue N day(s)', 'Today',
        'In N day(s)' for within-week, else a 'Mon DD' format."""
        if deadline is False or deadline is None:
            return _("No deadline")
        delta = (deadline - today).days
        if delta < 0:
            days = abs(delta)
            return _("Overdue %(n)d day%(s)s") % {
                "n": days, "s": "" if days == 1 else "s",
            }
        if delta == 0:
            return _("Today")
        if delta <= 7:
            return _("In %(n)d day%(s)s") % {
                "n": delta, "s": "" if delta == 1 else "s",
            }
        try:
            return deadline.strftime("%b %d")
        except Exception:  # noqa: BLE001
            return str(deadline)

    @api.model
    def _task_source_label(self, activity):
        """Human-readable label for the activity's source record.

        Returns display_name (truncated at 50 chars) or empty
        string when the source is missing / orphaned. sudo() the
        lookup because mail.activity's user might not have read
        on every linked model -- for SOURCE-LABELING purposes only
        we want to render the reference; the deeplink action will
        respect ACLs at click time.
        """
        if not activity.res_model or not activity.res_id:
            return ""
        try:
            Model = self.env[activity.res_model].sudo()
        except KeyError:
            return ""
        record = Model.browse(activity.res_id).exists()
        if not record:
            return ""
        name = record.display_name or ""
        if len(name) > 50:
            return name[:50] + "..."
        return name

    @api.model
    def dashboard_complete_task(self, activity_id):
        """Mark a mail.activity done. Returns the refreshed
        tasks_block payload.

        Safety: scopes to current user's own activities. Cross-user
        completion raises AccessError -- shouldn't happen via UI but
        a strict defense at the RPC boundary.
        """
        self._check_dashboard_access()
        Activity = self.env["mail.activity"]
        activity = Activity.browse(activity_id).exists()
        if not activity:
            # Race condition: activity already deleted by another
            # action. Just refresh.
            return self._compute_tasks_block()
        if activity.user_id.id != self.env.user.id:
            raise AccessError(_(
                "You can only complete your own tasks."))
        activity.action_done()
        return self._compute_tasks_block()

    # ==================================================================
    # M10 -- On-demand exports (PDF + Excel snapshots).
    #
    # Two RPC entry points the dashboard's OWL header buttons call:
    #   * export_snapshot_pdf(dashboard_type, active_filter)
    #   * export_snapshot_xlsx(dashboard_type, active_filter)
    # Both return an ir.actions.act_url descriptor pointing at
    # /web/content/<attachment_id>?download=true. Standard Odoo 17
    # download path; user isolation is enforced by attachment ACL.
    #
    # ⚠️ DECISION (M10, marker 1): authoritative widget-list source
    # is the seeded neon.dashboard.default.layout records. Reading
    # XML at runtime instead of hardcoding a Python dict avoids a
    # second source of truth that can drift from the M1 seed. Per-
    # request, the result is cached in env.context via a private key
    # so repeated calls in the same RPC don't re-query.
    #
    # ⚠️ DECISION (M10, marker 2): filter hide rules duplicate
    # between SCSS (M5/M6 client-side hide via
    # .o_neon_dashboard__filter_<x> .widget--<key> { display: none })
    # and Python (_widgets_for_filter for server-side scope). Accepted
    # for v1; test_filter_rules_match_scss parses the SCSS at test
    # time and asserts agreement. Deduping to a single source of
    # truth deferred to Phase 9.
    #
    # ⚠️ DECISION (M10, marker 3): no persistent export-log model.
    # _logger.info per call only. Exports are user-initiated and
    # self-evident; users keep the downloaded file. Different from
    # the M9 digest, where the audit log proves the Monday cron
    # actually fired and reached recipients.
    #
    # ⚠️ DECISION (M10, marker 4): one-shot ir.attachment with
    # res_model=False, res_id=False. User isolation via session-
    # level /web/content ACL (non-public attachment + create_uid
    # check). Odoo's standard attachment GC handles cleanup.
    # ==================================================================
    @api.model
    def export_snapshot_pdf(self, dashboard_type=None, active_filter="all"):
        """Generate dashboard snapshot PDF; return download action."""
        self._check_dashboard_access()
        dashboard_type = self._resolve_dashboard_type(dashboard_type)
        payload = self._build_snapshot_payload(
            dashboard_type, active_filter)
        Report = self.env["ir.actions.report"].sudo()
        pdf_bytes, _content_type = Report._render_qweb_pdf(
            "neon_dashboard.report_snapshot",
            res_ids=None,
            data={"payload": payload},
        )
        if not pdf_bytes:
            raise ValueError(_(
                "Snapshot PDF render returned empty bytes."))
        filename = self._snapshot_filename("pdf", dashboard_type)
        attachment = self._store_snapshot_attachment(
            pdf_bytes, filename, "application/pdf")
        _logger.info(
            "M10 snapshot PDF export: user=%s type=%s filter=%s "
            "attachment=%d size=%d",
            self.env.user.login, dashboard_type, active_filter,
            attachment.id, len(pdf_bytes),
        )
        return self._download_action(attachment, filename)

    @api.model
    def export_snapshot_xlsx(self, dashboard_type=None, active_filter="all"):
        """Generate dashboard snapshot xlsx workbook; return
        download action."""
        self._check_dashboard_access()
        dashboard_type = self._resolve_dashboard_type(dashboard_type)
        payload = self._build_snapshot_payload(
            dashboard_type, active_filter)
        xlsx_bytes = self._render_snapshot_xlsx(payload)
        filename = self._snapshot_filename("xlsx", dashboard_type)
        attachment = self._store_snapshot_attachment(
            xlsx_bytes, filename,
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
        )
        _logger.info(
            "M10 snapshot xlsx export: user=%s type=%s filter=%s "
            "attachment=%d size=%d",
            self.env.user.login, dashboard_type, active_filter,
            attachment.id, len(xlsx_bytes),
        )
        return self._download_action(attachment, filename)

    @api.model
    def _snapshot_filename(self, extension, dashboard_type):
        today = self._today_harare()
        return "neon-{type}-snapshot-{date}.{ext}".format(
            type=dashboard_type or "director",
            date=today.isoformat(),
            ext=extension,
        )

    @api.model
    def _store_snapshot_attachment(self, bytes_content, filename, mimetype):
        """One-shot ir.attachment with no parent record. The
        creating user's session is the only path to /web/content
        download (non-public attachment scoping)."""
        return self.env["ir.attachment"].create({
            "name": filename,
            "datas": base64.b64encode(bytes_content),
            "type": "binary",
            "mimetype": mimetype,
            "res_model": False,
            "res_id": False,
        })

    @api.model
    def _download_action(self, attachment, filename):
        """OWL-consumable download descriptor."""
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/{aid}?download=true&filename={fname}".format(
                aid=attachment.id, fname=filename,
            ),
            "target": "self",
        }

    @api.model
    def _build_snapshot_payload(self, dashboard_type, active_filter):
        """Snapshot payload mirroring M9 digest shape but framed
        as current state. Tier + filter govern which sections land."""
        visible = self._widgets_for_filter(
            dashboard_type, active_filter)
        payload = {
            "snapshot_title": "Neon dashboard snapshot - {}".format(
                dashboard_type.title() if dashboard_type else "Director"),
            "generated_at_harare": self._format_harare_timestamp(),
            "dashboard_type": dashboard_type,
            "active_filter": active_filter,
            "user_name": self.env.user.name,
            "dashboard_url": self._snapshot_dashboard_url(),
        }

        # KPIs -- each key only included if its widget is visible
        # under the current filter+tier.
        kpi_methods = {
            "kpi_cash": "_kpi_cash_on_hand",
            "kpi_ar_overdue": "_kpi_ar_overdue",
            "kpi_jobs_today": "_kpi_jobs_today",
            "kpi_jobs_week": "_kpi_jobs_week",
            "kpi_pipeline": "_kpi_pipeline",
            "kpi_leads": "_kpi_new_leads",
            "kpi_forecast": "_kpi_forecast",
        }
        for widget_key, method_name in kpi_methods.items():
            if widget_key in visible:
                payload[widget_key] = getattr(self, method_name)()

        # Blocks -- each gated on visibility.
        if "block_jobs" in visible:
            payload["jobs_block"] = self._compute_jobs_block(
                dashboard_type)
        if "block_sales" in visible:
            payload["sales_block"] = self._compute_sales_block(
                dashboard_type)
        if "block_finance" in visible:
            payload["finance_block"] = self._compute_finance_block(
                dashboard_type)
            # Extract ar_aging up to top level so the shared partial
            # finds it without spelunking through finance_block.
            payload["ar_aging"] = self._compute_ar_aging()
        if "block_crew_equipment" in visible:
            payload["crew_equipment_block"] = (
                self._compute_crew_equipment_block(dashboard_type))
        if "block_alerts" in visible:
            payload["alerts_block"] = self._compute_alerts_block(
                dashboard_type)
        if "block_tasks" in visible:
            payload["tasks_block"] = self._compute_tasks_block()

        return payload

    @api.model
    def _snapshot_dashboard_url(self):
        """Deep-link URL to the live dashboard. Reuses the M9
        digest helper's contract but is named separately to keep
        the module-level constant scoping for the M9 helper."""
        Config = self.env["ir.config_parameter"].sudo()
        base_url = (Config.get_param("web.base.url")
                    or "https://crm.neonhiring.com")
        try:
            action = self.env.ref(
                "neon_dashboard.action_neon_dashboard_server",
                raise_if_not_found=True)
            menu = self.env.ref(
                "neon_dashboard.menu_neon_dashboard_root",
                raise_if_not_found=True)
            return (
                f"{base_url}/web#action={action.id}"
                f"&cids=1&menu_id={menu.id}"
            )
        except Exception:  # noqa: BLE001
            return f"{base_url}/web"

    # SCSS hide rules sourced from
    # static/src/js/neon_dashboard/neon_dashboard.scss lines 482-526.
    # test_filter_rules_match_scss parses the SCSS at test time and
    # asserts this dict agrees. If you change this dict, change the
    # SCSS too (or fix the SCSS to match -- it's the prior source of
    # truth, present since M5/M6 walkthroughs).
    # ⚠️ DECISION (P8B, variant chip semantics): the per-variant chips
    # (Sales: Hot/Aging/Won; Bookkeeper: Overdue/Due Soon/Recently
    # Paid; Lead Tech: Today/Next 7d/Next 30d) are widget-visibility
    # filters, consistent with the M5/M6 director chips -- they do NOT
    # re-scope the underlying query windows. Re-scoping the data per
    # chip is a Phase 9 enhancement (would require threading the
    # window through every variant compute). Each chip's hide set is
    # mirrored 1:1 in the SCSS .o_neon_dashboard__filter_<key> blocks;
    # test T8974 enforces parity. 'next30' hides nothing (== the
    # lead-tech default view) so it has no SCSS block.
    _FILTER_HIDE_RULES = {
        "all": frozenset(),
        "operations": frozenset({
            "block_sales", "block_finance",
            "kpi_pipeline", "kpi_leads",
            "kpi_forecast", "kpi_ar_overdue",
        }),
        "sales": frozenset({
            "block_jobs", "block_finance",
            "block_crew_equipment",
            "kpi_cash", "kpi_ar_overdue",
            "kpi_jobs_today",
        }),
        "finance": frozenset({
            "block_jobs", "block_sales",
            "block_crew_equipment",
            "kpi_jobs_today", "kpi_jobs_week",
            "kpi_pipeline", "kpi_leads",
        }),
        # --- Sales variant chips ---
        "hot": frozenset({
            "kpi_aging_quotes", "kpi_won_mtd", "kpi_win_rate",
            "block_aging_quotes",
        }),
        "aging": frozenset({
            "kpi_hot_deals", "kpi_won_mtd", "kpi_win_rate",
            "block_hot_deals",
        }),
        "won": frozenset({
            "kpi_hot_deals", "kpi_aging_quotes",
            "block_hot_deals", "block_aging_quotes",
        }),
        # --- Bookkeeper variant chips ---
        "overdue": frozenset({
            "kpi_recent_payments", "kpi_recent_costs",
            "kpi_pending_invoices",
            "block_invoice_queue", "block_zig_costs",
        }),
        "due_soon": frozenset({
            "kpi_recent_payments", "kpi_recent_costs", "kpi_overdue_60",
            "block_budget_alerts", "block_zig_costs",
        }),
        "recently_paid": frozenset({
            "kpi_overdue_60", "kpi_pending_invoices", "kpi_ar_overdue",
            "block_invoice_queue",
        }),
        # --- Lead Tech variant chips ---
        "today": frozenset({
            "kpi_jobs_week", "kpi_certs_30", "block_cert_expiry",
        }),
        "next7": frozenset({
            "kpi_certs_30", "block_cert_expiry",
        }),
        "next30": frozenset(),
    }

    @api.model
    def _widgets_for_filter(self, dashboard_type, active_filter):
        """Returns the set of widget keys that should be in the
        export payload for (dashboard_type, active_filter).

        Logic:
        1. Start with the tier's default widget list from the
           seeded neon.dashboard.default.layout records.
        2. Subtract the active filter's hide set.
        Unknown filter -> treat as 'all' (no hiding).
        """
        base = self._default_widgets_for_dashboard_type(
            dashboard_type)
        hide = self._FILTER_HIDE_RULES.get(
            active_filter, frozenset())
        return [w for w in base if w not in hide]

    @api.model
    def _default_widgets_for_dashboard_type(self, dashboard_type):
        """Read the authoritative widget list from the seeded
        default-layout records. Returns a list (preserving
        order_index ASC) of widget_key strings."""
        DefaultLayout = self.env[
            "neon.dashboard.default.layout"].sudo()
        layout = DefaultLayout.search(
            [("dashboard_type", "=", dashboard_type)], limit=1)
        if not layout:
            # Defensive: shouldn't happen on a properly-installed
            # module (M1 seed loads all 5 records). Log + fall
            # back to director's all-widgets list.
            _logger.warning(
                "No default layout for dashboard_type=%s; "
                "falling back to director.", dashboard_type,
            )
            layout = DefaultLayout.search(
                [("dashboard_type", "=", "director")], limit=1)
            if not layout:
                return []
        return [
            line.widget_key
            for line in layout.layout_line_ids.sorted(
                key=lambda l: (l.order_index, l.id))
        ]

    @api.model
    def _render_snapshot_xlsx(self, payload):
        """Build a multi-sheet xlsx workbook in memory.
        Sheets are conditional on payload keys -- a sales-tier
        export with no finance section gets no Finance sheet.

        ⚠️ DECISION (M10, marker 5): xlsxwriter import at top of
        method scope, not module-level. Library is installed in
        prod (verified at gate-1: xlsxwriter 3.0.2 in container)
        but deferring keeps the module importable on any dev box
        where the wheel is missing. Same pattern as
        [[reference_odoo17_deferred_external_dep]] from P7e.M13.
        """
        import io  # noqa: PLC0415
        import xlsxwriter  # noqa: PLC0415

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})

        fmt_title = workbook.add_format(
            {"bold": True, "font_size": 14, "font_color": "#7165AC"})
        fmt_header = workbook.add_format({
            "bold": True, "bg_color": "#534AB7",
            "font_color": "white", "border": 1,
        })
        fmt_label = workbook.add_format({"bold": True})
        fmt_overdue = workbook.add_format({
            "bg_color": "#FEE2E2", "font_color": "#991B1B",
        })

        self._xlsx_summary_sheet(
            workbook, payload, fmt_title, fmt_header, fmt_label)
        if any(payload.get(k) is not None for k in (
                "kpi_cash", "kpi_ar_overdue", "kpi_jobs_today",
                "kpi_jobs_week", "kpi_pipeline", "kpi_leads",
                "kpi_forecast")):
            self._xlsx_kpis_sheet(
                workbook, payload, fmt_title, fmt_header)
        if payload.get("jobs_block") is not None:
            self._xlsx_jobs_sheet(
                workbook, payload, fmt_title, fmt_header)
        if payload.get("sales_block") is not None:
            self._xlsx_sales_sheet(
                workbook, payload, fmt_title, fmt_header)
        if payload.get("finance_block") is not None:
            self._xlsx_finance_sheet(
                workbook, payload, fmt_title, fmt_header,
                fmt_overdue)
        if payload.get("crew_equipment_block") is not None:
            self._xlsx_crew_sheet(
                workbook, payload, fmt_title, fmt_header)
        if payload.get("alerts_block") is not None:
            self._xlsx_alerts_sheet(
                workbook, payload, fmt_title, fmt_header)
        if payload.get("tasks_block") is not None:
            self._xlsx_tasks_sheet(
                workbook, payload, fmt_title, fmt_header)

        workbook.close()
        return buffer.getvalue()

    @api.model
    def _xlsx_summary_sheet(self, wb, payload, fmt_title, fmt_header,
                            fmt_label):
        s = wb.add_worksheet("Summary")
        s.set_column(0, 0, 28)
        s.set_column(1, 1, 40)
        s.write(0, 0, payload.get("snapshot_title") or "Snapshot",
                fmt_title)
        s.write(2, 0, "Generated", fmt_label)
        s.write(2, 1, payload.get("generated_at_harare") or "")
        s.write(3, 0, "User", fmt_label)
        s.write(3, 1, payload.get("user_name") or "")
        s.write(4, 0, "Dashboard type", fmt_label)
        s.write(4, 1, payload.get("dashboard_type") or "")
        s.write(5, 0, "Filter", fmt_label)
        s.write(5, 1, payload.get("active_filter") or "all")
        s.write(7, 0, "Dashboard URL", fmt_label)
        s.write(7, 1, payload.get("dashboard_url") or "")

    @api.model
    def _xlsx_kpis_sheet(self, wb, payload, fmt_title, fmt_header):
        s = wb.add_worksheet("KPIs")
        s.set_column(0, 0, 24)
        s.set_column(1, 1, 36)
        s.write(0, 0, "KPI snapshot", fmt_title)
        s.write(2, 0, "KPI", fmt_header)
        s.write(2, 1, "Value", fmt_header)
        row = 3
        kpi_labels = [
            ("kpi_cash", "Cash on hand"),
            ("kpi_ar_overdue", "AR overdue"),
            ("kpi_jobs_today", "Jobs today"),
            ("kpi_jobs_week", "Jobs this week"),
            ("kpi_pipeline", "Pipeline value"),
            ("kpi_leads", "New leads"),
            ("kpi_forecast", "Forecast vs target"),
        ]
        for key, label in kpi_labels:
            data = payload.get(key)
            if data is None:
                continue
            display = (data.get("display") if isinstance(data, dict)
                       else None) or (
                data.get("value") if isinstance(data, dict) else None
            ) or "-"
            s.write(row, 0, label)
            s.write(row, 1, str(display))
            row += 1

    @api.model
    def _xlsx_jobs_sheet(self, wb, payload, fmt_title, fmt_header):
        s = wb.add_worksheet("Jobs")
        s.set_column(0, 0, 30)
        s.set_column(1, 1, 14)
        s.set_column(2, 2, 18)
        s.set_column(3, 3, 14)
        s.write(0, 0, "Upcoming jobs", fmt_title)
        jb = payload.get("jobs_block") or {}
        rows = jb.get("rows") or jb.get("jobs") or []
        if not rows:
            s.write(2, 0, "(none)")
            return
        s.write(2, 0, "Title", fmt_header)
        s.write(2, 1, "Date", fmt_header)
        s.write(2, 2, "Status", fmt_header)
        s.write(2, 3, "Value", fmt_header)
        for i, j in enumerate(rows, start=3):
            s.write(i, 0, (j.get("title") or j.get("name")
                           or j.get("display_name") or "-"))
            s.write(i, 1, str(j.get("date_display")
                              or j.get("event_date") or ""))
            s.write(i, 2, str(j.get("badge") or j.get("status")
                              or ""))
            s.write(i, 3, str(j.get("value_display")
                              or j.get("value") or ""))

    @api.model
    def _xlsx_sales_sheet(self, wb, payload, fmt_title, fmt_header):
        s = wb.add_worksheet("Sales")
        s.set_column(0, 0, 28)
        s.set_column(1, 1, 20)
        s.write(0, 0, "Sales pipeline", fmt_title)
        sb = payload.get("sales_block") or {}
        # Real shape: sales_block.pipeline_by_stage is a dict with
        # keys (empty / empty_message / stages / currency_note);
        # stages is the list of dicts to iterate.
        pbs = sb.get("pipeline_by_stage") or {}
        stages = (pbs.get("stages") if isinstance(pbs, dict)
                  else pbs) or []
        if not stages:
            msg = (pbs.get("empty_message") if isinstance(pbs, dict)
                   else "") or "(no active pipeline)"
            s.write(2, 0, msg)
            return
        s.write(2, 0, "Stage", fmt_header)
        s.write(2, 1, "Value", fmt_header)
        for i, st in enumerate(stages, start=3):
            if not isinstance(st, dict):
                s.write(i, 0, str(st))
                continue
            s.write(i, 0, st.get("label") or st.get("stage") or "-")
            s.write(i, 1, str(st.get("value_display")
                              or st.get("value") or 0))

    @api.model
    def _xlsx_finance_sheet(self, wb, payload, fmt_title, fmt_header,
                            fmt_overdue):
        s = wb.add_worksheet("Finance")
        s.set_column(0, 0, 20)
        s.set_column(1, 1, 12)
        s.set_column(2, 2, 18)
        s.write(0, 0, "AR aging + cash mix", fmt_title)
        ar = payload.get("ar_aging") or {}
        buckets = ar.get("buckets") or []
        if buckets:
            s.write(2, 0, "Bucket", fmt_header)
            s.write(2, 1, "Count", fmt_header)
            s.write(2, 2, "Amount", fmt_header)
            for i, b in enumerate(buckets, start=3):
                fmt = (fmt_overdue
                       if "overdue" in (b.get("label") or "").lower()
                       else None)
                s.write(i, 0, b.get("label") or "-", fmt)
                s.write(i, 1, b.get("count") or 0, fmt)
                s.write(i, 2, str(b.get("amount_display")
                                  or b.get("amount") or "-"), fmt)
        else:
            s.write(2, 0, "(no AR aging data)")

    @api.model
    def _xlsx_crew_sheet(self, wb, payload, fmt_title, fmt_header):
        # Sheet name uses '+' not '&' because xlsxwriter / OOXML
        # entity-encodes '&' as '&amp;' in workbook.xml, which is
        # invisible in Excel but trips naive regex matchers in
        # tests + downstream tooling.
        s = wb.add_worksheet("Crew + Equipment")
        s.set_column(0, 0, 28)
        s.set_column(1, 1, 36)
        s.write(0, 0, "Crew + equipment", fmt_title)
        ceb = payload.get("crew_equipment_block") or {}
        # Real shape: {'crew': {...}, 'equipment': {...}}. Both
        # subdicts have a 'label' / 'count' / 'detail' shape. Dump
        # whatever scalars exist; nested lists print as their length.
        s.write(2, 0, "Section", fmt_header)
        s.write(2, 1, "Detail", fmt_header)
        row = 3
        for section_name in ("crew", "equipment"):
            section = ceb.get(section_name) or {}
            if not isinstance(section, dict):
                continue
            for k, v in section.items():
                if isinstance(v, (list, tuple)):
                    display = f"{len(v)} item(s)"
                elif isinstance(v, dict):
                    display = ", ".join(f"{ik}={iv}" for ik, iv
                                        in list(v.items())[:5])
                else:
                    display = str(v) if v is not None else ""
                s.write(row, 0, f"{section_name}.{k}")
                s.write(row, 1, display)
                row += 1
            row += 1  # blank between sections

    @api.model
    def _xlsx_alerts_sheet(self, wb, payload, fmt_title, fmt_header):
        s = wb.add_worksheet("Alerts")
        s.set_column(0, 0, 12)
        s.set_column(1, 1, 50)
        s.write(0, 0, "Open alerts", fmt_title)
        ab = payload.get("alerts_block") or {}
        alerts = ab.get("alerts") or []
        if not alerts:
            s.write(2, 0, "(no alerts)")
            return
        s.write(2, 0, "Severity", fmt_header)
        s.write(2, 1, "Title", fmt_header)
        for i, a in enumerate(alerts, start=3):
            s.write(i, 0, (a.get("severity") or "").upper())
            s.write(i, 1, a.get("title") or a.get("message") or "-")

    @api.model
    def _xlsx_tasks_sheet(self, wb, payload, fmt_title, fmt_header):
        s = wb.add_worksheet("Tasks")
        s.set_column(0, 0, 40)
        s.set_column(1, 1, 30)
        s.set_column(2, 2, 16)
        s.write(0, 0, "Your open tasks", fmt_title)
        tb = payload.get("tasks_block") or {}
        tasks = tb.get("tasks") or []
        if not tasks:
            s.write(2, 0, "(none)")
            return
        s.write(2, 0, "Summary", fmt_header)
        s.write(2, 1, "Source", fmt_header)
        s.write(2, 2, "Deadline", fmt_header)
        for i, t in enumerate(tasks, start=3):
            s.write(i, 0, t.get("summary") or "-")
            s.write(i, 1, t.get("source_label") or "")
            s.write(i, 2, t.get("deadline_display") or "")
