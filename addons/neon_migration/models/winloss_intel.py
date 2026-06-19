# -*- coding: utf-8 -*-
"""Win/Loss intelligence — L2.3 STORED, rule-based, retrospective.

Win-rate over the quote archive cut by CLIENT / REP / PERIOD / CATEGORY. STORED
long-format aggregates (one row per dimension×key), recomputed on refresh.
SYSTEM-COMPUTED: no group has manual create/write/unlink; rows appear only via
cron_recompute() (sudo). PURE READ feature.

win_rate = won / total quotes (matches L2.1 + the live client board);
decided_win_rate = won/(won+lost) is an honest secondary. No historical
lost-reason (forward-only = WA-12.3). Money USD-only; non-USD disclosed.
All-commercial readable (not sensitive).
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

DIMENSIONS = [("client", "Client"), ("rep", "Sales Rep"),
              ("period", "Period"), ("category", "Category")]


def _load_compute():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "scripts", "compute_winloss_intel.py")
    spec = importlib.util.spec_from_file_location(
        "neon_compute_winloss_intel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_winloss_rows


class NeonWinlossIntel(models.Model):
    _name = "neon.winloss.intel"
    _description = "Win/Loss Intelligence (L2.3, computed)"
    _order = "dimension, win_rate desc, quotes_count desc"
    _rec_name = "key_label"

    dimension = fields.Selection(DIMENSIONS, string="Cut", index=True)
    key_label = fields.Char(string="Key", index=True)
    partner_id = fields.Many2one("res.partner", string="Client", index=True)
    year = fields.Integer(string="Year")
    month = fields.Integer(string="Month #")
    quotes_count = fields.Integer(string="Quotes")
    won_count = fields.Integer(string="Won")
    lost_count = fields.Integer(string="Lost")
    open_count = fields.Integer(string="Open")
    historical_count = fields.Integer(string="Historical")
    win_rate = fields.Float(
        string="Win rate", group_operator="avg",
        help="won / total quotes (incl. open + historical) — matches L2.1.")
    decided_win_rate = fields.Float(
        string="Decided win rate", group_operator="avg",
        help="won / (won + lost) — honest secondary; the archive has real "
        "'lost'. No historical lost-reason (capture is forward-only).")
    # --- realisation half (UNTAXED, reconciles to the L1 Realisation pivot) ---
    quoted_value_usd = fields.Float(
        string="Quoted (USD, untaxed)",
        help="Σ quote amount_untaxed (USD). Reconciles to the L1 Realisation "
        "'quoted'. 0 on category rows (value would double-count).")
    won_value_usd = fields.Float(string="Won (USD, untaxed)",
                                 help="Σ won-quote amount_untaxed (USD).")
    invoiced_count = fields.Integer(
        string="Invoices",
        help="Invoice-archive count in this cut (by invoice date / partner / "
        "rep). NB: every won quote also carries an invoice link, so the "
        "won→invoiced LINK coverage is 100% — not a real funnel.")
    invoiced_value_usd = fields.Float(
        string="Invoiced (USD, untaxed)",
        help="Σ invoice-archive amount_untaxed (USD) — realised revenue; "
        "reconciles to the L1 Realisation 'invoiced'.")
    win_value_rate = fields.Float(
        string="Win value rate", group_operator="avg",
        help="won_value / quoted_value (value-weighted win).")
    realisation_rate = fields.Float(
        string="Realisation rate", group_operator="avg",
        help="invoiced_value / won_value (won→invoiced VALUE realisation).")
    nonusd_quote_value = fields.Float(string="Non-USD quoted (disclosure)")
    last_computed = fields.Datetime(string="Last computed", index=True)

    @api.model
    def cron_recompute(self):
        compute = _load_compute()
        rows, _stats = compute(self.env)
        now = fields.Datetime.now()
        for r in rows:
            r["last_computed"] = now
        M = self.sudo().with_context(active_test=False)
        M.search([]).unlink()
        if rows:
            M.create(rows)
        return True

    def action_recompute(self):
        self.cron_recompute()
        return True

    @api.model
    def _pack(self, recs):
        return [{
            "key": r.key_label, "partner_id": r.partner_id.id or False,
            "quotes": r.quotes_count, "won": r.won_count, "lost": r.lost_count,
            "open": r.open_count, "historical": r.historical_count,
            "win_rate_pct": round(r.win_rate * 100, 1),
            "decided_pct": round(r.decided_win_rate * 100, 1),
            "quoted_value_usd": round(r.quoted_value_usd or 0.0),
            "won_value_usd": round(r.won_value_usd or 0.0),
            "invoiced_count": r.invoiced_count,
            "invoiced_value_usd": round(r.invoiced_value_usd or 0.0),
            "win_value_rate_pct": round(r.win_value_rate * 100, 1),
            "realisation_pct": round(r.realisation_rate * 100, 1),
        } for r in recs]

    @api.model
    def get_dashboard_data(self):
        user = self.env.user
        if not any(user.has_group(g) for g in _VIEW_GROUPS):
            raise AccessError(
                _("Win/Loss Intelligence is not available for your role."))
        M = self.sudo()

        def cut(dim, order, limit=None, dom=None):
            d = [("dimension", "=", dim)] + (dom or [])
            return self._pack(M.search(d, order=order, limit=limit))

        # overall totals from the rep cut (every quote has a rep) — single pass
        reps = M.search([("dimension", "=", "rep")])
        tot = {"quotes": sum(r.quotes_count for r in reps),
               "won": sum(r.won_count for r in reps),
               "lost": sum(r.lost_count for r in reps),
               "open": sum(r.open_count for r in reps),
               "historical": sum(r.historical_count for r in reps),
               "quoted_value_usd": round(
                   sum(r.quoted_value_usd or 0.0 for r in reps)),
               "won_value_usd": round(sum(r.won_value_usd or 0.0 for r in reps)),
               "invoiced_count": sum(r.invoiced_count for r in reps),
               "invoiced_value_usd": round(
                   sum(r.invoiced_value_usd or 0.0 for r in reps)),
               "nonusd_quote_value": round(
                   sum(r.nonusd_quote_value or 0.0 for r in reps))}
        tot["win_rate_pct"] = (round(100.0 * tot["won"] / tot["quotes"], 1)
                               if tot["quotes"] else 0.0)
        _decided_den = tot["won"] + tot["lost"]
        tot["decided_win_rate_pct"] = (
            round(100.0 * tot["won"] / _decided_den, 1) if _decided_den else 0.0)
        tot["win_value_rate_pct"] = (
            round(100.0 * tot["won_value_usd"] / tot["quoted_value_usd"], 1)
            if tot["quoted_value_usd"] else 0.0)
        tot["realisation_pct"] = (
            round(100.0 * tot["invoiced_value_usd"] / tot["won_value_usd"], 1)
            if tot["won_value_usd"] else 0.0)
        last = M.search([], order="last_computed desc", limit=1)
        return {
            "overall": tot,
            "by_rep": cut("rep", "won_value_usd desc"),
            # category_prefix has a long noisy tail (~678 distinct, mostly
            # one-off); rank the real categories by VOLUME with a floor so a
            # 1/1=100% noise category can't top the card.
            "by_category": cut("category", "quotes_count desc", limit=15,
                               dom=[("quotes_count", ">=", 10)]),
            "by_period": self._pack(M.search(
                [("dimension", "=", "period")], order="year, month")),
            # client board: min 3 quotes so 1/1=100% can't top it
            "top_client_winrate": cut(
                "client", "win_rate desc", limit=15,
                dom=[("quotes_count", ">=", 3)]),
            "top_client_volume": cut("client", "quotes_count desc", limit=15),
            "top_client_realisation": cut(
                "client", "won_value_usd desc", limit=15,
                dom=[("won_value_usd", ">", 0)]),
            "variant": ("director" if user.has_group(
                "neon_core.group_neon_superuser")
                else "bookkeeper" if user.has_group(
                    "neon_core.group_neon_bookkeeper") else "sales"),
            "can_chat": any(user.has_group(g) for g in _CHAT_GROUPS),
            "last_computed": (last.last_computed.isoformat()
                              if last and last.last_computed else ""),
        }
