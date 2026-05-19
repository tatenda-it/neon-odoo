# -*- coding: utf-8 -*-
"""P6.M10 -- Cash Flow Dashboard (virtual model, no records).

Mirrors the P5.M10 Workshop Dashboard pattern: no records, every
method @api.model, single get_cash_flow_dashboard_data RPC returns
the full tile payload to the OWL client action.

Six tiles (Schema Sketch §9.2):
1. outstanding_receivables -- unpaid posted invoices, per currency
2. pipeline -- pending_approval/approved/sent quotes, per currency
3. recent_payments -- account.payment in last 30 days, per currency
4. recent_costs -- cost.line in last 30 days, per currency
5. top_overdue -- top 5 partners by overdue receivable
6. budget_alert_summary -- counts per alert level (ok/warn/breach/severe)

⚠️ DECISION (P6.M10, marker 1): virtual model -- no fields, no
records. RPC entry point only. Matches workshop precedent.

⚠️ DECISION (P6.M10, marker 4): tile shape extends Workshop's flat
{value, action_id} to {usd: {value, count, ...}, zwg: {value,
count, ...}, action_id}. Currency separation is structural -- no
mixed totals anywhere (Q6 B1).

⚠️ DECISION (P6.M10, marker 5): per-tile role branching inside
each _count_* helper, NOT a centralised _get_domain_for_user. Six
tiles x four role variations is maintainable inline; centralised
helper would need a special case for crew_leader's degraded view.

⚠️ DECISION (P6.M10, marker 6): crew_leader sees costs + budget
tiles only. Other 4 tiles return None values; template renders "--"
with no click handler. UX: degrades, doesn't hide (layout stable).
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError


# Role identification helpers (reused by every tile).
_BOOKKEEPER_GROUP = "neon_finance.group_neon_finance_bookkeeper"
_APPROVER_GROUP = "neon_finance.group_neon_finance_approver"
_SALES_GROUP = "neon_finance.group_neon_finance_sales"
_CREW_LEADER_GROUP = "neon_jobs.group_neon_jobs_crew_leader"


class NeonFinanceDashboard(models.Model):
    _name = "neon.finance.dashboard"
    _description = "Cash Flow Dashboard (virtual; @api.model RPC only)"

    # ============================================================
    # === Group-check helper. Centralised so the server-action
    # === wrapper and the RPC entry point share one definition.
    # ============================================================
    @api.model
    def _check_dashboard_access(self):
        user = self.env.user
        if not (
            user.has_group(_BOOKKEEPER_GROUP)
            or user.has_group(_APPROVER_GROUP)
            or user.has_group(_SALES_GROUP)
            or user.has_group(_CREW_LEADER_GROUP)
        ):
            raise AccessError(_(
                "You don't have permission to view the cash flow "
                "dashboard."))

    @api.model
    def _user_role_band(self):
        """Returns one of: 'finance_all', 'sales', 'crew_leader',
        or False. Finance-tier (book/approver) sees everything;
        sales sees own; crew_leader sees costs + budget only."""
        user = self.env.user
        if user.has_group(_BOOKKEEPER_GROUP) \
                or user.has_group(_APPROVER_GROUP):
            return "finance_all"
        if user.has_group(_SALES_GROUP):
            return "sales"
        if user.has_group(_CREW_LEADER_GROUP):
            return "crew_leader"
        return False

    # ============================================================
    # === Server-action entry point.
    # ============================================================
    @api.model
    def action_open_cash_flow_dashboard(self):
        self._check_dashboard_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_cash_flow_dashboard",
            "name": _("Cash Flow Dashboard"),
            "target": "current",
        }

    # ============================================================
    # === Currency resolution helpers.
    # ============================================================
    @api.model
    def _currencies(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        return usd, zwg

    @api.model
    def _empty_currency_payload(self):
        """Standard payload shape for a tile a role isn't allowed to
        see. Template renders this as '--' with no click handler."""
        return {
            "usd": None,
            "zwg": None,
            "action_id": False,
        }

    # ============================================================
    # === Tile 1: outstanding_receivables
    # ============================================================
    @api.model
    def _tile_outstanding_receivables(self, role):
        if role == "crew_leader":
            return self._empty_currency_payload()
        usd, zwg = self._currencies()
        Move = self.env["account.move"].sudo()
        # Base domain: posted out_invoice with residual > 0
        base = [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial", "in_payment")),
        ]
        if role == "sales":
            # Neon invoices belong to quotes where salesperson = user.
            # Marker 4 pattern: parse invoice.ref (SCH-*) to find the
            # owning schedule->quote->salesperson.
            user_quotes = self.env["neon.finance.quote"].sudo().search(
                [("salesperson_id", "=", self.env.user.id)])
            user_sched_names = self.env[
                "neon.finance.invoice.schedule"].sudo().search([
                    ("quote_id", "in", user_quotes.ids),
                ]).mapped("name")
            base = base + [("ref", "in", user_sched_names)]
        out = {"action_id": self.env.ref(
            "neon_finance.action_dashboard_outstanding_receivables").id}
        for code, curr in (("usd", usd), ("zwg", zwg)):
            if not curr:
                out[code] = {"value": 0.0, "count": 0,
                             "overdue_value": 0.0, "overdue_count": 0}
                continue
            moves = Move.search(base + [("currency_id", "=", curr.id)])
            value = sum(moves.mapped("amount_residual"))
            today = fields.Date.context_today(self)
            overdue = moves.filtered(
                lambda m: m.invoice_date_due and m.invoice_date_due < today)
            out[code] = {
                "value": value,
                "count": len(moves),
                "overdue_value": sum(overdue.mapped("amount_residual")),
                "overdue_count": len(overdue),
            }
        return out

    # ============================================================
    # === Tile 2: pipeline (pending_approval + approved + sent quotes)
    # ============================================================
    @api.model
    def _tile_pipeline(self, role):
        if role == "crew_leader":
            return self._empty_currency_payload()
        usd, zwg = self._currencies()
        Quote = self.env["neon.finance.quote"].sudo()
        base = [("state", "in", ("pending_approval", "approved", "sent"))]
        if role == "sales":
            base = base + [("salesperson_id", "=", self.env.user.id)]
        out = {"action_id": self.env.ref(
            "neon_finance.action_dashboard_pipeline").id}
        for code, curr in (("usd", usd), ("zwg", zwg)):
            if not curr:
                out[code] = {"value": 0.0, "count": 0}
                continue
            quotes = Quote.search(
                base + [("currency_id", "=", curr.id)])
            out[code] = {
                "value": sum(quotes.mapped("amount_total")),
                "count": len(quotes),
            }
        return out

    # ============================================================
    # === Tile 3: recent_payments (last 30 days, posted out-payments)
    # ============================================================
    @api.model
    def _tile_recent_payments(self, role):
        if role == "crew_leader":
            return self._empty_currency_payload()
        usd, zwg = self._currencies()
        Pay = self.env["account.payment"].sudo()
        cutoff = fields.Date.context_today(self) - timedelta(days=30)
        base = [
            ("state", "=", "posted"),
            ("payment_type", "=", "inbound"),
            ("date", ">=", cutoff),
        ]
        if role == "sales":
            # Inbound payments matched against Neon invoices owned by user
            user_quotes = self.env["neon.finance.quote"].sudo().search(
                [("salesperson_id", "=", self.env.user.id)])
            user_sched_invs = self.env[
                "neon.finance.invoice.schedule"].sudo().search([
                    ("quote_id", "in", user_quotes.ids),
                ]).mapped("invoice_id").ids
            base = base + [("reconciled_invoice_ids", "in", user_sched_invs)]
        out = {"action_id": self.env.ref(
            "neon_finance.action_dashboard_recent_payments").id}
        for code, curr in (("usd", usd), ("zwg", zwg)):
            if not curr:
                out[code] = {"value": 0.0, "count": 0}
                continue
            pays = Pay.search(base + [("currency_id", "=", curr.id)])
            out[code] = {
                "value": sum(pays.mapped("amount")),
                "count": len(pays),
            }
        return out

    # ============================================================
    # === Tile 4: recent_costs (last 30 days)
    # ============================================================
    @api.model
    def _tile_recent_costs(self, role):
        usd, zwg = self._currencies()
        Cost = self.env["neon.finance.cost.line"].sudo()
        cutoff = fields.Date.context_today(self) - timedelta(days=30)
        base = [("date_incurred", ">=", cutoff)]
        if role == "sales":
            user_jobs = self.env["commercial.event.job"].sudo().search([])
            # Sales tier doesn't carry salesperson on event_job (per
            # M5 polish: event_job.salesperson chain is absent).
            # Filter via quote -> event_job chain.
            user_quotes = self.env["neon.finance.quote"].sudo().search([
                ("salesperson_id", "=", self.env.user.id),
                ("event_job_id", "!=", False),
            ])
            user_ej_ids = user_quotes.mapped("event_job_id").ids
            base = base + [("event_job_id", "in", user_ej_ids)]
        elif role == "crew_leader":
            # Crew leader sees costs they recorded.
            base = base + [("recorded_by_id", "=", self.env.user.id)]
        out = {"action_id": self.env.ref(
            "neon_finance.action_dashboard_recent_costs").id}
        for code, curr in (("usd", usd), ("zwg", zwg)):
            if not curr:
                out[code] = {"value": 0.0, "count": 0}
                continue
            costs = Cost.search(
                base + [("currency_id", "=", curr.id)])
            out[code] = {
                "value": sum(costs.mapped("amount")),
                "count": len(costs),
            }
        return out

    # ============================================================
    # === Tile 5: top_overdue (top 5 partners by overdue receivable,
    # === company currency for ranking; per-currency breakdown shown)
    # ============================================================
    @api.model
    def _tile_top_overdue(self, role):
        if role == "crew_leader":
            return {"rows": [], "action_id": False}
        Move = self.env["account.move"].sudo()
        today = fields.Date.context_today(self)
        base = [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "in", ("not_paid", "partial")),
            ("invoice_date_due", "<", today),
        ]
        if role == "sales":
            user_quotes = self.env["neon.finance.quote"].sudo().search(
                [("salesperson_id", "=", self.env.user.id)])
            user_sched_names = self.env[
                "neon.finance.invoice.schedule"].sudo().search([
                    ("quote_id", "in", user_quotes.ids),
                ]).mapped("name")
            base = base + [("ref", "in", user_sched_names)]
        moves = Move.search(base)
        # Aggregate by partner in company currency for the top-5
        # ranking. amount_residual_signed is company-currency
        # signed; abs() handles refunds.
        partner_totals = {}
        for m in moves:
            partner_totals.setdefault(m.partner_id, {
                "amount": 0.0, "max_days": 0, "count": 0,
            })
            partner_totals[m.partner_id]["amount"] += abs(
                m.amount_residual_signed)
            days_overdue = (today - m.invoice_date_due).days
            if days_overdue > partner_totals[
                    m.partner_id]["max_days"]:
                partner_totals[m.partner_id]["max_days"] = days_overdue
            partner_totals[m.partner_id]["count"] += 1
        ranked = sorted(
            partner_totals.items(),
            key=lambda kv: kv[1]["amount"],
            reverse=True)[:5]
        rows = [{
            "partner_id": p.id,
            "partner_name": p.name,
            "amount": vals["amount"],
            "max_days": vals["max_days"],
            "invoice_count": vals["count"],
        } for p, vals in ranked]
        return {
            "rows": rows,
            "action_id": self.env.ref(
                "neon_finance.action_dashboard_top_overdue").id,
        }

    # ============================================================
    # === Tile 6: budget_alert_summary (counts per alert level)
    # ============================================================
    @api.model
    def _tile_budget_alert_summary(self, role):
        # Crew leader sees this tile too -- they're closest to cost
        # creation and want signal on which events are running hot.
        EJ = self.env["commercial.event.job"].sudo()
        base = []
        if role == "sales":
            # Filter to event_jobs whose quote belongs to user
            user_quotes = self.env["neon.finance.quote"].sudo().search([
                ("salesperson_id", "=", self.env.user.id),
                ("event_job_id", "!=", False),
            ])
            user_ej_ids = user_quotes.mapped("event_job_id").ids
            base = [("id", "in", user_ej_ids)]
        elif role == "crew_leader":
            base = [("lead_tech_id", "=", self.env.user.id)]
        levels = {}
        for level in ("ok", "warn", "breach", "severe"):
            levels[level] = EJ.search_count(
                base + [("budget_alert_level", "=", level)])
        return {
            "levels": levels,
            "action_id": self.env.ref(
                "neon_finance.action_dashboard_budget_alerts").id,
        }

    # ============================================================
    # === RPC: get_cash_flow_dashboard_data
    # === Single round-trip the OWL component calls.
    # ============================================================
    @api.model
    def get_cash_flow_dashboard_data(self):
        self._check_dashboard_access()
        role = self._user_role_band()
        return {
            "outstanding_receivables": self._tile_outstanding_receivables(role),
            "pipeline": self._tile_pipeline(role),
            "recent_payments": self._tile_recent_payments(role),
            "recent_costs": self._tile_recent_costs(role),
            "top_overdue": self._tile_top_overdue(role),
            "budget_alert_summary": self._tile_budget_alert_summary(role),
            "role": role,
            "last_updated": fields.Datetime.to_string(
                fields.Datetime.now()),
        }
