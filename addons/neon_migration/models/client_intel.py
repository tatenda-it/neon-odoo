# -*- coding: utf-8 -*-
"""Client / account intelligence — L2.1 STORED, rule-based, retrospective.

Per-client rollups computed over the loaded archives + the collections
worklist. STORED aggregates (recomputed on refresh, NOT live each open). The
model is SYSTEM-COMPUTED: no group has manual create/write/unlink — rows only
ever appear via cron_recompute() (full idempotent rebuild, run as sudo). Pure
READ feature: it computes and displays, never mutating any source record.

Money is USD-only (the hist-intel currency guard); sensitive fields
(outstanding_*, payment_behaviour) are field-level gated to finance/directors.
The aggregation logic lives in scripts/compute_client_intel.py (a pure,
dry-runnable read) so the gate can prove the numbers before any persist.
"""
import importlib.util
import os

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

# who may open the read-only dashboard / be served its data
_VIEW_GROUPS = ("neon_core.group_neon_sales_rep",
                "neon_core.group_neon_bookkeeper",
                "neon_core.group_neon_superuser")
# the chat panel's own access tiers (mirror neon_dashboard's controller) — so we
# only mount the embedded chat for users who can actually use it.
_CHAT_GROUPS = ("neon_jobs.group_neon_jobs_user",
                "neon_jobs.group_neon_jobs_manager",
                "neon_jobs.group_neon_jobs_crew_leader",
                "neon_core.group_neon_bookkeeper")

# Sensitive fields -> directors + bookkeeper only. neon_migration depends on
# base+neon_core only, so these are neon_core groups (director == superuser per
# the collections precedent); the chat-side sensitive tool re-gates separately.
_SENSITIVE = "neon_core.group_neon_bookkeeper,neon_core.group_neon_superuser"

SEGMENTS = [
    ("high_value_repeat", "High-value repeat"),
    ("steady", "Steady repeat"),
    ("quote_heavy_low_convert", "Quote-heavy / low convert"),
    ("new", "New"),
    ("dormant", "Dormant"),
    ("one_off", "One-off"),
]


def _load_compute():
    """Load the pure aggregation function from scripts/ by path (the same file
    the gate dry-run probe execs) — avoids a scripts-package import."""
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "scripts", "compute_client_intel.py")
    spec = importlib.util.spec_from_file_location(
        "neon_compute_client_intel", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compute_client_intel_rows


class NeonClientIntel(models.Model):
    _name = "neon.client.intel"
    _description = "Client / Account Intelligence (L2.1, computed)"
    _order = "won_value desc, quotes_value desc, id desc"
    _rec_name = "client_name"

    partner_id = fields.Many2one(
        "res.partner", string="Client", index=True, ondelete="cascade",
        help="The aggregated client. Empty on the single 'unmatched' row "
        "(quotes/invoices/jobs with no partner link — bucketed, never dropped).")
    client_name = fields.Char(string="Client", index=True)

    # --- commercial (sales + directors + bookkeeper) ---
    quotes_count = fields.Integer(string="Quotes")
    quotes_value = fields.Float(string="Quoted (USD)",
                                help="Sum of quote totals, USD rows only.")
    won_count = fields.Integer(string="Won")
    won_value = fields.Float(string="Won (USD)",
                             help="Sum of WON quote totals, USD rows only.")
    win_rate = fields.Float(string="Win rate", group_operator="avg",
                            help="won_count / quotes_count (0..1, guarded).")
    invoices_count = fields.Integer(string="Invoices")
    invoiced_value = fields.Float(string="Invoiced (USD)",
                                  help="Sum of invoice totals, USD rows only.")
    jobs_count = fields.Integer(string="Jobs")
    first_job_date = fields.Date(string="First job")
    last_job_date = fields.Date(string="Last job")
    active_years = fields.Integer(
        string="Active years",
        help="Distinct calendar years with a job OR a quote.")
    recency_days = fields.Integer(
        string="Recency (days)",
        help="Days since the last job/quote. NEGATIVE = days until the next "
        "(future-dated) event; 0 may mean undated-only (unknown).")
    event_types = fields.Char(string="Event types",
                              help="Distinct job categories for this client.")
    segment = fields.Selection(
        SEGMENTS, string="Segment", index=True,
        help="RULE-BASED (transparent): dormant if last activity >12mo ago "
        "(undated-only clients are not dormant); high_value_repeat if >=2 "
        "active years (jobs+quotes) and won >= $10k; quote_heavy_low_convert "
        "if >=4 quotes and win rate <25%; new if first activity within a year "
        "and <=1 active year; steady if >=2 active years; else one_off.")

    # --- SENSITIVE (directors + bookkeeper only) ---
    outstanding_usd = fields.Float(
        string="Outstanding (USD)", groups=_SENSITIVE,
        help="Open collections balance (from the worklist).")
    outstanding_status = fields.Char(
        string="Collections status", groups=_SENSITIVE)
    payment_behaviour = fields.Char(
        string="Payment behaviour", groups=_SENSITIVE,
        help="HEURISTIC label (NOT a credit fact): at_risk/slow_paying/owing "
        "from collections status; settled if invoiced & no balance; else "
        "unknown.")

    last_computed = fields.Datetime(string="Last computed", index=True)

    @api.model
    def cron_recompute(self):
        """Full idempotent rebuild. Runs as sudo (the model has no write ACL);
        rows are replaced wholesale so re-runs converge to the same state."""
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
        """Manual 'Recompute now' — wraps the cron entry point (gated by the
        server action's groups_id)."""
        self.cron_recompute()
        return True

    @api.model
    def _pack(self, recs):
        return [{
            "id": r.id, "client": r.client_name,
            "partner_id": r.partner_id.id or False,
            "segment": r.segment or "",
            "quotes_count": r.quotes_count,
            "quotes_value": round(r.quotes_value or 0.0),
            "won_count": r.won_count,
            "won_value": round(r.won_value or 0.0),
            "win_rate_pct": round((r.win_rate or 0.0) * 100, 1),
            "invoiced_value": round(r.invoiced_value or 0.0),
            "jobs_count": r.jobs_count,
            "active_years": r.active_years,
            "recency_days": r.recency_days,
        } for r in recs]

    @api.model
    def get_dashboard_data(self):
        """Read-only RPC for the Owl ranking dashboard. Three-layer enforced
        (menu groups + server-action groups_id + this guard). Sensitive
        collections block is gated to finance/directors; never returned to
        plain sales."""
        user = self.env.user
        is_sales = user.has_group("neon_core.group_neon_sales_rep")
        is_book = user.has_group("neon_core.group_neon_bookkeeper")
        is_super = user.has_group("neon_core.group_neon_superuser")
        if not (is_sales or is_book or is_super):
            raise AccessError(
                _("Client Intelligence is not available for your role."))
        CI = self.sudo()
        base = [("partner_id", "!=", False)]
        is_finance = bool(is_book or is_super)
        last = CI.search([], order="last_computed desc", limit=1)
        data = {
            "top_won": self._pack(
                CI.search(base, order="won_value desc", limit=10)),
            "top_winrate": self._pack(
                CI.search(base + [("quotes_count", ">=", 3)],
                          order="win_rate desc", limit=10)),
            "repeat": self._pack(
                CI.search(base + [("active_years", ">=", 2)],
                          order="won_value desc", limit=10)),
            "dormant": self._pack(
                CI.search(base + [("segment", "=", "dormant")],
                          order="won_value desc", limit=10)),
            "total_clients": CI.search_count(base),
            "is_finance": is_finance,
            "variant": ("director" if is_super
                        else "bookkeeper" if is_book else "sales"),
            "can_chat": any(user.has_group(g) for g in _CHAT_GROUPS),
            "last_computed": (last.last_computed.isoformat()
                              if last and last.last_computed else ""),
        }
        # SENSITIVE — outstanding/collections block: finance + directors only.
        if is_finance:
            outs = CI.search(base + [("outstanding_usd", ">", 0)],
                             order="outstanding_usd desc", limit=10)
            data["outstanding"] = [{
                "client": r.client_name,
                "outstanding_usd": round(r.outstanding_usd or 0.0),
                "status": r.outstanding_status or "",
                "behaviour": r.payment_behaviour or "",
                "segment": r.segment or "",
            } for r in outs]
        else:
            data["outstanding"] = []
        return data
