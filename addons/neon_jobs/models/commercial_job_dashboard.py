# -*- coding: utf-8 -*-
"""
P2.M7 — Operations Dashboard and My Schedule (TransientModels).

Each dashboard is a transient record created on form-view open. Counts
are computed fields (depends_context); top-3 previews are regular M2Ms
populated at create() time. This avoids a quirk where stored computed
M2Ms on a TransientModel don't reliably fire on initial create with
only `depends_context` declared — the rel table stays empty and the
form sees no records.

Refresh = re-open the act_window, which creates a fresh transient.
"""
from odoo import _, api, fields, models


class CommercialJobDashboard(models.TransientModel):
    _name = "commercial.job.dashboard"
    _description = "Operations Dashboard (P2.M7)"

    # === Counters (computed; cheap search_count queries) ===
    gate_issues_count = fields.Integer(compute="_compute_gate_issues_count")
    soft_hold_count = fields.Integer(compute="_compute_soft_hold_count")
    crew_gap_count = fields.Integer(compute="_compute_crew_gap_count")
    needs_attention_count = fields.Integer(compute="_compute_needs_attention_count")
    cash_flow_count = fields.Integer(compute="_compute_cash_flow_count")

    # === Top-3 previews (populated at create() time) ===
    # Distinct relation= names avoid autogen collisions between five
    # M2Ms all pointing from this model to commercial.job.
    gate_issues_top3 = fields.Many2many(
        "commercial.job",
        relation="cjd_gate_issues_top3_rel",
        column1="dashboard_id", column2="job_id",
        string="Top Gate Issues",
    )
    soft_hold_top3 = fields.Many2many(
        "commercial.job",
        relation="cjd_soft_hold_top3_rel",
        column1="dashboard_id", column2="job_id",
        string="Top Soft Hold Risks",
    )
    crew_gap_top3 = fields.Many2many(
        "commercial.job",
        relation="cjd_crew_gap_top3_rel",
        column1="dashboard_id", column2="job_id",
        string="Top Crew Gaps",
    )
    needs_attention_top3 = fields.Many2many(
        "commercial.job",
        relation="cjd_needs_attention_top3_rel",
        column1="dashboard_id", column2="job_id",
        string="Top Needs Attention",
    )
    cash_flow_top3 = fields.Many2many(
        "commercial.job",
        relation="cjd_cash_flow_top3_rel",
        column1="dashboard_id", column2="job_id",
        string="Top Cash-flow Risks",
    )

    # ============================================================
    # === Domain helpers
    # ============================================================
    def _gate_issues_domain(self):
        return [
            ("state", "=", "active"),
            ("gate_result", "in", ("reject", "warning")),
        ]

    def _soft_hold_domain(self):
        return [
            ("state", "=", "pending"),
            ("soft_hold_state", "in", ("expiring_soon", "expired")),
        ]

    def _crew_gap_domain(self):
        # crew_total_count is non-stored; the "has any crew" filter
        # happens in Python after the SQL prefilter.
        return [
            ("state", "=", "active"),
            ("event_date", ">=", fields.Date.today()),
        ]

    def _needs_attention_domain(self):
        return [
            ("state", "in", ("pending", "active")),
            ("needs_attention", "=", True),
        ]

    def _cash_flow_domain(self):
        today = fields.Date.today()
        return [
            ("state", "in", ("pending", "active")),
            ("finance_status", "in", ("quoted", "deposit_pending")),
            ("event_date", ">=", today),
            ("event_date", "<=", fields.Date.add(today, days=14)),
        ]

    def _crew_gap_jobs(self):
        candidates = self.env["commercial.job"].search(
            self._crew_gap_domain(), order="event_date asc"
        )
        return candidates.filtered(
            lambda j: j.crew_total_count > 0
            and j.crew_confirmed_count < j.crew_total_count
        )

    # ============================================================
    # === Count computes
    # ============================================================
    @api.depends_context("uid")
    def _compute_gate_issues_count(self):
        count = self.env["commercial.job"].search_count(self._gate_issues_domain())
        for rec in self:
            rec.gate_issues_count = count

    @api.depends_context("uid")
    def _compute_soft_hold_count(self):
        count = self.env["commercial.job"].search_count(self._soft_hold_domain())
        for rec in self:
            rec.soft_hold_count = count

    @api.depends_context("uid")
    def _compute_crew_gap_count(self):
        gap_jobs = self._crew_gap_jobs()
        for rec in self:
            rec.crew_gap_count = len(gap_jobs)

    @api.depends_context("uid")
    def _compute_needs_attention_count(self):
        count = self.env["commercial.job"].search_count(self._needs_attention_domain())
        for rec in self:
            rec.needs_attention_count = count

    @api.depends_context("uid")
    def _compute_cash_flow_count(self):
        count = self.env["commercial.job"].search_count(self._cash_flow_domain())
        for rec in self:
            rec.cash_flow_count = count

    # ============================================================
    # === Create override — populate top-3 previews on every open
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        Job = self.env["commercial.job"]
        gate = Job.search(self._gate_issues_domain(), order="event_date asc", limit=3)
        soft_hold = Job.search(self._soft_hold_domain(), order="soft_hold_until asc", limit=3)
        crew_gap = self._crew_gap_jobs()[:3]
        attn = Job.search(self._needs_attention_domain(), order="create_date desc", limit=3)
        cash = Job.search(self._cash_flow_domain(), order="event_date asc", limit=3)
        for rec in records:
            rec.write({
                "gate_issues_top3": [(6, 0, gate.ids)],
                "soft_hold_top3": [(6, 0, soft_hold.ids)],
                "crew_gap_top3": [(6, 0, crew_gap.ids)],
                "needs_attention_top3": [(6, 0, attn.ids)],
                "cash_flow_top3": [(6, 0, cash.ids)],
            })
        return records

    # ============================================================
    # === Action methods
    # ============================================================
    @api.model
    def action_open(self):
        """Open the dashboard. Server-action entry point used by the menu
        and the Refresh button.

        Pattern: create a persisted record server-side and return an
        act_window targeting that record by id. The browser opens a
        materialised record so all computed counts and top-3 previews
        (populated by create()) are immediately visible. A plain new-
        form act_window would show zeroed defaults instead, because the
        form is unsaved and default_get returns nothing for computed
        counters or M2Ms.

        Per-user singleton: prior dashboard records for the calling
        user are unlinked first so Refresh doesn't accumulate stale
        transients.
        """
        self.search([("create_uid", "=", self.env.uid)]).unlink()
        rec = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("Operations Dashboard"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": rec.id,
            "target": "current",
        }

    def action_refresh(self):
        return self.action_open()

    def _drilldown(self, name, domain):
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "commercial.job",
            "view_mode": "tree,form",
            "domain": domain,
            "context": {},
        }

    def action_open_gate_issues(self):
        return self._drilldown(_("Gate Issues"), self._gate_issues_domain())

    def action_open_soft_hold(self):
        return self._drilldown(_("Soft Hold Risks"), self._soft_hold_domain())

    def action_open_crew_gap(self):
        return self._drilldown(_("Crew Gaps"), self._crew_gap_domain())

    def action_open_needs_attention(self):
        return self._drilldown(_("Needs Attention"), self._needs_attention_domain())

    def action_open_cash_flow(self):
        return self._drilldown(_("Cash-flow Watch"), self._cash_flow_domain())


class CommercialJobCrewSchedule(models.TransientModel):
    _name = "commercial.job.crew.schedule"
    _description = "My Schedule (P2.M7) — crew-tier dashboard"

    my_upcoming_count = fields.Integer(compute="_compute_my_upcoming_count")
    my_upcoming_top3 = fields.Many2many(
        "commercial.job",
        relation="cjcs_upcoming_top3_rel",
        column1="schedule_id", column2="job_id",
        string="My Upcoming Events",
    )
    my_pending_confirms_count = fields.Integer(compute="_compute_my_pending_confirms_count")
    my_pending_confirms_top3 = fields.Many2many(
        "commercial.job.crew",
        relation="cjcs_pending_confirms_top3_rel",
        column1="schedule_id", column2="crew_id",
        string="Pending My Confirmation",
    )

    # ============================================================
    # === Helpers — role-aware scoping (P2.M7 update)
    #
    # Crew-only users (have neon_jobs_crew, NOT user/manager) see their
    # own assignments. User/manager users see all crew assignments
    # across all users — the management oversight view. A user in both
    # crew AND user/manager groups still sees the "all" view (the
    # broader group dominates).
    # ============================================================
    def _is_crew_only(self):
        return (
            self.env.user.has_group("neon_jobs.group_neon_jobs_crew")
            and not self.env.user.has_group("neon_jobs.group_neon_jobs_user")
            and not self.env.user.has_group("neon_jobs.group_neon_jobs_manager")
        )

    def _scoped_user_filter(self):
        return ([("user_id", "=", self.env.uid)] if self._is_crew_only() else [])

    def _scoped_confirmed_job_ids(self):
        domain = [("state", "=", "confirmed")] + self._scoped_user_filter()
        return self.env["commercial.job.crew"].search(domain).mapped("job_id.id")

    def _scoped_pending_assignments(self):
        domain = [("state", "=", "pending")] + self._scoped_user_filter()
        return self.env["commercial.job.crew"].search(domain)

    def _upcoming_job_domain(self, job_ids):
        today = fields.Date.today()
        return [
            ("id", "in", job_ids),
            ("event_date", ">=", today),
            "|",
            ("state", "=", "active"),
            "&",
            ("state", "=", "pending"),
            ("deposit_received", ">", 0),
        ]

    def _scoped_relevant_pending_assignments(self):
        today = fields.Date.today()
        candidates = self._scoped_pending_assignments()
        return candidates.filtered(
            lambda c: c.job_id.event_date and c.job_id.event_date >= today
            and (
                c.job_id.state == "active"
                or (c.job_id.state == "pending" and c.job_id.deposit_received > 0)
            )
        ).sorted(key=lambda c: c.job_id.event_date)

    # ============================================================
    # === Count computes
    # ============================================================
    @api.depends_context("uid")
    def _compute_my_upcoming_count(self):
        confirmed_jobs = self._scoped_confirmed_job_ids()
        count = self.env["commercial.job"].search_count(
            self._upcoming_job_domain(confirmed_jobs)
        )
        for rec in self:
            rec.my_upcoming_count = count

    @api.depends_context("uid")
    def _compute_my_pending_confirms_count(self):
        relevant = self._scoped_relevant_pending_assignments()
        for rec in self:
            rec.my_pending_confirms_count = len(relevant)

    # ============================================================
    # === Create override — populate top-3 previews
    # ============================================================
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        confirmed_jobs = self._scoped_confirmed_job_ids()
        upcoming = self.env["commercial.job"].search(
            self._upcoming_job_domain(confirmed_jobs),
            order="event_date asc", limit=3,
        )
        pending = self._scoped_relevant_pending_assignments()[:3]
        for rec in records:
            rec.write({
                "my_upcoming_top3": [(6, 0, upcoming.ids)],
                "my_pending_confirms_top3": [(6, 0, pending.ids)],
            })
        return records

    # ============================================================
    # === Action methods
    # ============================================================
    @api.model
    def action_open(self):
        """Same singleton + persisted-record pattern as Operations
        Dashboard. See CommercialJobDashboard.action_open."""
        self.search([("create_uid", "=", self.env.uid)]).unlink()
        rec = self.create({})
        return {
            "type": "ir.actions.act_window",
            "name": _("My Schedule"),
            "res_model": self._name,
            "view_mode": "form",
            "res_id": rec.id,
            "target": "current",
        }

    def action_refresh(self):
        return self.action_open()

    def action_open_my_upcoming(self):
        confirmed_jobs = self._scoped_confirmed_job_ids()
        return {
            "type": "ir.actions.act_window",
            "name": _("My Upcoming Events"),
            "res_model": "commercial.job",
            "view_mode": "tree,form",
            "domain": self._upcoming_job_domain(confirmed_jobs),
        }

    def action_open_my_pending_confirms(self):
        domain = [("state", "=", "pending")] + self._scoped_user_filter()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pending My Confirmation"),
            "res_model": "commercial.job.crew",
            "view_mode": "tree,form",
            "domain": domain,
        }
