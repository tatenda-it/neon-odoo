# -*- coding: utf-8 -*-
"""Demand & seasonality — L2.2 STORED, rule-based, retrospective.

Demand intelligence over the job + quote spine, aggregated BY TIME (year,
month) — NOT by client and NOT by event-type (STEP-0 found no usable type
taxonomy). STORED aggregates recomputed on refresh. SYSTEM-COMPUTED: no group
has manual create/write/unlink; rows appear only via cron_recompute() (sudo).
PURE READ feature — computes and displays, never mutating any source.

Two models:
  neon.demand.intel      one row per (year, month) — the seasonality grain.
  neon.demand.recurring  one row per recurring normalised title (>=2 years) —
                         DESCRIPTIVE recurrence, never a forecast.

Money is USD-only (non-USD disclosed); demand/seasonality carries no
debtor/payment data, so it is all-commercial readable (not sensitive).
"""
import importlib.util
import os

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_VIEW_GROUPS = ("neon_core.group_neon_sales_rep",
                "neon_core.group_neon_bookkeeper",
                "neon_core.group_neon_superuser")
_CHAT_GROUPS = ("neon_jobs.group_neon_jobs_user",
                "neon_jobs.group_neon_jobs_manager",
                "neon_jobs.group_neon_jobs_crew_leader",
                "neon_core.group_neon_bookkeeper")

_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _load_compute():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "scripts", "compute_demand_intel.py")
    spec = importlib.util.spec_from_file_location(
        "neon_compute_demand_intel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_demand_rows


class NeonDemandIntel(models.Model):
    _name = "neon.demand.intel"
    _description = "Demand & Seasonality (L2.2, computed by month)"
    _order = "year desc, month desc"

    year = fields.Integer(string="Year", index=True)
    month = fields.Integer(string="Month #", index=True)
    period = fields.Char(string="Period", compute="_compute_period", store=True)
    jobs_count = fields.Integer(string="Jobs")
    quotes_count = fields.Integer(string="Quotes")
    quotes_value_usd = fields.Float(string="Quoted (USD)",
                                    help="USD rows only; non-USD disclosed.")
    won_count = fields.Integer(string="Won")
    won_value_usd = fields.Float(string="Won (USD)")
    nonusd_quote_value = fields.Float(
        string="Non-USD quoted (disclosure)",
        help="ZWG/ZAR quote value in that month — disclosed, NEVER blended "
        "into the USD sums.")
    last_computed = fields.Datetime(string="Last computed", index=True)

    @api.depends("year", "month")
    def _compute_period(self):
        for r in self:
            mlabel = _MONTHS[r.month] if 0 < (r.month or 0) < 13 else "?"
            r.period = "%04d-%02d %s" % (r.year or 0, r.month or 0, mlabel)

    @api.model
    def cron_recompute(self):
        """Full idempotent rebuild of BOTH demand models (sudo)."""
        compute = _load_compute()
        drows, rrows, _stats = compute(self.env)
        now = fields.Datetime.now()
        for r in drows:
            r["last_computed"] = now
        for r in rrows:
            r["last_computed"] = now
        D = self.sudo().with_context(active_test=False)
        D.search([]).unlink()
        if drows:
            D.create(drows)
        R = self.env["neon.demand.recurring"].sudo()
        R.search([]).unlink()
        if rrows:
            R.create(rrows)
        return True

    def action_recompute(self):
        self.cron_recompute()
        return True

    @api.model
    def get_dashboard_data(self):
        """Read-only RPC for the seasonality board. 3-layer enforced."""
        user = self.env.user
        if not any(user.has_group(g) for g in _VIEW_GROUPS):
            raise AccessError(
                _("Demand & Seasonality is not available for your role."))
        D = self.sudo()
        rows = D.search([], order="year, month")
        # time series (curve)
        series = [{
            "year": r.year, "month": r.month,
            "label": "%04d-%02d" % (r.year, r.month),
            "jobs": r.jobs_count, "quotes": r.quotes_count,
            "quotes_value_usd": round(r.quotes_value_usd or 0.0),
        } for r in rows]
        # seasonality: aggregate across years by calendar month
        season = {m: {"jobs": 0, "quotes": 0, "months": 0} for m in range(1, 13)}
        years = set()
        for r in rows:
            years.add(r.year)
            s = season[r.month]
            s["jobs"] += r.jobs_count
            s["quotes"] += r.quotes_count
            s["months"] += 1
        n_years = max(len(years), 1)
        seasonality = [{
            "month": m, "label": _MONTHS[m],
            "jobs_total": season[m]["jobs"],
            "jobs_avg": round(season[m]["jobs"] / n_years, 1),
            "quotes_total": season[m]["quotes"],
        } for m in range(1, 13)]
        # year-over-year
        yoy_map = {}
        for r in rows:
            y = yoy_map.setdefault(
                r.year, {"year": r.year, "jobs": 0, "quotes": 0,
                         "quotes_value_usd": 0.0, "won_value_usd": 0.0})
            y["jobs"] += r.jobs_count
            y["quotes"] += r.quotes_count
            y["quotes_value_usd"] += r.quotes_value_usd or 0.0
            y["won_value_usd"] += r.won_value_usd or 0.0
        yoy = [{**v, "quotes_value_usd": round(v["quotes_value_usd"]),
                "won_value_usd": round(v["won_value_usd"])}
               for v in sorted(yoy_map.values(), key=lambda x: x["year"])]
        # recurring named events
        rec = self.env["neon.demand.recurring"].sudo().search(
            [], order="distinct_years desc, total_occurrences desc", limit=25)
        recurring = [{
            "title": r.sample_raw_title, "years": r.year_list,
            "distinct_years": r.distinct_years,
            "occurrences": r.total_occurrences,
        } for r in rec]
        nonusd = round(sum(r.nonusd_quote_value or 0.0 for r in rows))
        last = rows[-1].last_computed if rows else False
        return {
            "series": series,
            "seasonality": seasonality,
            "yoy": yoy,
            "recurring": recurring,
            "years": sorted(years),
            "totals": {
                "jobs": sum(r.jobs_count for r in rows),
                "quotes": sum(r.quotes_count for r in rows),
                "quotes_value_usd": round(
                    sum(r.quotes_value_usd or 0.0 for r in rows)),
                "nonusd_quote_value": nonusd,
                "recurring_count": self.env["neon.demand.recurring"].sudo(
                ).search_count([]),
            },
            "variant": ("director" if user.has_group(
                "neon_core.group_neon_superuser")
                else "bookkeeper" if user.has_group(
                    "neon_core.group_neon_bookkeeper") else "sales"),
            "can_chat": any(user.has_group(g) for g in _CHAT_GROUPS),
            "last_computed": last.isoformat() if last else "",
        }


class NeonDemandRecurring(models.Model):
    _name = "neon.demand.recurring"
    _description = "Recurring Named Events (L2.2, descriptive)"
    _order = "distinct_years desc, total_occurrences desc"
    _rec_name = "sample_raw_title"

    normalised_title = fields.Char(string="Normalised title", index=True)
    sample_raw_title = fields.Char(string="Event (sample)")
    distinct_years = fields.Integer(string="Distinct years")
    year_list = fields.Char(string="Years")
    total_occurrences = fields.Integer(string="Occurrences")
    first_seen = fields.Date(string="First seen")
    last_seen = fields.Date(string="Last seen")
    last_computed = fields.Datetime(string="Last computed", index=True)
