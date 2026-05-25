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
from collections import defaultdict
from datetime import timedelta
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


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

_DASHBOARD_TYPES = [
    ("director", "Director"),
    ("sales", "Sales"),
    ("bookkeeper", "Bookkeeper"),
    ("lead_tech", "Lead Tech"),
    ("tech", "Tech"),
]
_DASHBOARD_TYPE_VALUES = {t[0] for t in _DASHBOARD_TYPES}

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
    def _default_dashboard_type_for_user(self, user_id):
        """Map a user to their default landing dashboard.

        Walks the five neon_core tier meta-groups in priority order.
        ⚠️ DECISION (M1, marker 2 cont'd): superuser takes precedence
        over bookkeeper -- on dev DB Tatenda is sales + superuser and
        should land on Director per schema sketch §6.2.
        """
        user = self.env["res.users"].browse(user_id)
        if not user or not user.exists():
            return "director"
        # Honor explicit preference first.
        if user.preferred_dashboard_type:
            return user.preferred_dashboard_type
        # Then walk tier groups in priority order.
        if user.has_group(_GROUP_SUPERUSER):
            return "director"
        if user.has_group(_GROUP_BOOKKEEPER):
            return "bookkeeper"
        if user.has_group(_GROUP_LEAD_TECH):
            return "lead_tech"
        if user.has_group(_GROUP_CREW):
            return "tech"
        if user.has_group(_GROUP_SALES_REP):
            return "sales"
        # Fallback for users with no tier group -- treat as sales so
        # they get a constrained but non-empty dashboard rather than
        # an AccessError. M5 will tighten this.
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
        """Any internal user with one of the five tier meta-groups may
        load the dashboard. Tier-specific data filtering happens inside
        the RPC -- this guard only excludes external/portal users."""
        user = self.env.user
        for group in (_GROUP_SUPERUSER, _GROUP_BOOKKEEPER,
                      _GROUP_SALES_REP, _GROUP_LEAD_TECH, _GROUP_CREW):
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
    def _available_types_for_user(self, user=None):
        """View-as dropdown options. Superusers see all five tier
        labels; everyone else gets an empty list (dropdown hidden by
        the OWL template)."""
        user = user or self.env.user
        if not self._is_superuser(user):
            return []
        return [{"value": v, "label": label} for v, label in _DASHBOARD_TYPES]

    def _resolve_dashboard_type(self, requested_type):
        """Superusers may flip dashboard_type via the View-as dropdown;
        everyone else's requested_type is ignored and they get their
        default."""
        user = self.env.user
        if requested_type and self._is_superuser(user):
            if requested_type not in _DASHBOARD_TYPE_VALUES:
                raise ValidationError(
                    _("Unknown dashboard_type: %s") % requested_type)
            return requested_type
        return self._default_dashboard_type_for_user(user.id)

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
        return {
            "dashboard_id": dashboard.id,
            "dashboard_type": resolved_type,
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
            "available_types": self._available_types_for_user(),
            "last_updated": fields.Datetime.to_string(
                fields.Datetime.now()),
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
    # KPI tiles (M2) -- 7 tiles, every returned dict shape-compatible.
    # ==================================================================
    @api.model
    def _compute_kpi(self, dashboard_type):
        """All 7 KPI tile values. dashboard_type is reserved for tier
        scoping (M5 sales variant filters Pipeline by salesperson;
        M6 bookkeeper variant adds AP); for M1-M3 the tiles return
        unfiltered values plus empty-state shape."""
        return {
            "kpi_cash": self._kpi_cash_on_hand(),
            "kpi_ar_overdue": self._kpi_ar_overdue(),
            "kpi_jobs_today": self._kpi_jobs_today(),
            "kpi_jobs_week": self._kpi_jobs_week(),
            "kpi_pipeline": self._kpi_pipeline(),
            "kpi_leads": self._kpi_new_leads(),
            "kpi_forecast": self._kpi_forecast(),
        }

    # ⚠️ DECISION (M2, marker 3): Cash-on-Hand source is the standard
    # Odoo ``account.journal`` (type ∈ bank, cash) aggregated through
    # ``account.move.line``. The M1-M3 prompt assumed a
    # ``neon.bank.account`` model with a ``current_balance`` field;
    # no such model exists. ZWG conversion to USD-equivalent is
    # deferred to M6 alongside the RBZ ZiG-USD rate cron (per schema
    # sketch §7.5). For M1-M3 the tile shows USD-only total with a
    # subtitle disclosing the ZWG gap.
    def _kpi_cash_on_hand(self):
        Journal = self.env["account.journal"].sudo()
        # ⚠️ DECISION (M2, marker inline): dotted-domain filters on
        # NULL FKs (currency_id.name in (USD, False)) do not match
        # journals where currency_id IS NULL -- Odoo's domain
        # resolver follows the FK and there's no row to read .name
        # from. Surfaced by T8204. Filter Python-side instead:
        # search all bank/cash journals, then pick the ones whose
        # effective currency (explicit OR company-default) is USD.
        all_bank_cash = Journal.search([
            ("type", "in", ("bank", "cash")),
        ])
        if not all_bank_cash:
            return self._empty_kpi(
                _("No bank/cash journals configured yet"),
                value_display="$0",
                deeplink_action="account.action_account_journal_form",
            )
        company_currency = self.env.company.currency_id
        usd_journals = all_bank_cash.filtered(
            lambda j: (j.currency_id or company_currency).name == "USD"
        )
        if not usd_journals:
            return self._empty_kpi(
                _("No USD bank/cash journals -- ZWG total in M6"),
                value_display="$0",
                deeplink_action="account.action_account_journal_form",
            )
        total = 0.0
        for j in usd_journals:
            # account.journal exposes a computed ``current_account_
            # balance`` since Odoo 17 (sum of posted move lines on
            # default accounts). Fall back to summing move lines
            # directly when the field isn't available.
            if hasattr(j, "current_account_balance"):
                total += j.current_account_balance or 0.0
            else:
                lines = self.env["account.move.line"].sudo().search([
                    ("journal_id", "=", j.id),
                    ("parent_state", "=", "posted"),
                ])
                total += sum(lines.mapped("balance"))
        return {
            "value": total,
            "value_display": self._format_money(total, "USD"),
            "currency": "USD",
            # ⚠️ DECISION (M2, marker 3 cont'd): subtitle discloses
            # ZWG omission until M6. Robin sees the gap, no fake data.
            "subtitle": _(
                "USD only -- ZWG total lands in M6 with RBZ rate"),
            "trend_pct": None,
            "trend_dir": "flat",
            "empty": False,
            "deeplink_action": "account.action_account_journal_form",
        }

    def _kpi_ar_overdue(self):
        today = fields.Date.context_today(self)
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
        today = fields.Date.context_today(self)
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
        today = fields.Date.context_today(self)
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
        yesterday_start = fields.Datetime.now() - timedelta(days=1)
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
        """Forecast vs Target. ``neon.dashboard.target`` lands in M5;
        until then the tile is an empty-state CTA per prompt M2 spec.
        """
        return {
            "value": None,
            "value_display": _("Set a target -->"),
            "subtitle": _("Forecast vs Target ships in M5"),
            "empty": True,
            "empty_message": _("Set a target -->"),
            "deeplink_action": False,
            "cta_label": _("Configure target"),
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
    # Jobs block (M3) -- today + next 7 days, ordered date asc / value
    # desc, limit 10 rows. Click-through opens the event_job form.
    # ==================================================================
    def _compute_jobs_block(self, dashboard_type):
        today = fields.Date.context_today(self)
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
        today = fields.Date.context_today(self)
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
