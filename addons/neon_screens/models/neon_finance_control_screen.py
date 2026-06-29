# -*- coding: utf-8 -*-
"""Finance Control screen (design-deck #4) -- data RPC (virtual model).

Read-only presentation over the REAL live finance data. NO new model/field,
NO writes, NO sudo: every read runs under the requesting user's own finance
ACL (gated to bookkeeper / approver; superusers inherit approver via the
neon_core cascade). A role that can't read a model simply gets an empty panel
-- correct gating, not a bug.

Panels (deck #4):
  1. KPI row -- cash-planning headline for the current week (neon.weekly.budget).
  2. Weekly Cash Planning Board -- this week's lines (neon.weekly.budget.line).
  3. Event Costing Variance -- estimated vs actual per event (commercial.event.job
     stored costing fields: quoted_budget, margin_gross, budget_variance_quoted,
     budget_alert_level).
  4a. Approvals -- neon.finance.approval (append-only).
  4b. Governance card -- STATIC honest statement of the real controls
      (append-only on posted items, multi-director equal authority). No model.

⚠️ DECISION (deck-vs-data): neon.weekly.budget is a flat single-`amount`
planning sheet -- it has NO opening balance and NO In/Out direction field. The
deck's literal "Opening Balance / Expected In / Projected Close" KPIs and
"In/Out" board columns are therefore not backed by the data. Rather than
fabricate a direction/balance or sudo-read the GL (own-ACL rule), the KPI row
shows the real planning metrics (Planned / Paid / Outstanding / Open items) and
the board shows the real Amount/Paid columns with a running balance. Wiring a
true bank position + receivables is a separate scoped follow-up.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_BOOKKEEPER = "neon_finance.group_neon_finance_bookkeeper"
_APPROVER = "neon_finance.group_neon_finance_approver"

_STATUS_TONE = {"planned": "info", "pending": "warn", "paid": "ok"}
_APPROVAL_TONE = {
    "pending": "warn", "approved": "ok", "rejected": "alert", "cancelled": "muted"}
_ALERT_TONE = {"ok": "ok", "warn": "warn", "breach": "alert", "severe": "dark"}
_ALERT_RANK = {"severe": 3, "breach": 2, "warn": 1, "ok": 0}


class NeonFinanceControlScreen(models.Model):
    _name = "neon.finance.control.screen"
    _description = "Finance Control Screen (virtual; @api.model RPC only)"

    # ------------------------------------------------------------------
    @api.model
    def _check_access(self):
        u = self.env.user
        if not (u.has_group(_BOOKKEEPER) or u.has_group(_APPROVER)):
            raise AccessError(_(
                "You don't have permission to view Finance Control."))

    @api.model
    def action_open_finance_control_screen(self):
        self._check_access()
        return {
            "type": "ir.actions.client",
            "tag": "neon_finance_control_screen",
            "name": _("Finance Control"),
            "target": "current",
        }

    # ------------------------------------------------------------------
    @api.model
    def _money(self, val):
        return "{:,.2f}".format(val or 0.0)

    @api.model
    def _constants(self):
        """Subheader constants -- the REAL documented business rules."""
        rate = self.env["ir.config_parameter"].sudo().get_param(
            "neon_dashboard.zig_usd_rate_manual")
        try:
            rate = float(rate or 0.0)
        except (TypeError, ValueError):
            rate = 0.0
        return {
            "currencies": "USD / ZiG",
            "vat": "15.5%",
            "zimra": True,
            "terms": "7-day default terms",
            "append_only": "Append-only on posted items",
            "zig_usd_rate": rate if rate > 0 else None,
        }

    # ------------------------------------------------------------------
    @api.model
    def _current_week(self):
        """The neon.weekly.budget covering today, else the latest week."""
        W = self.env["neon.weekly.budget"]
        today = fields.Date.context_today(self)
        wk = W.search(
            [("week_start", "<=", today),
             ("week_start", ">", today - timedelta(days=7))],
            order="week_start desc", limit=1)
        if not wk:
            wk = W.search([], order="week_start desc", limit=1)
        return wk

    @api.model
    def _kpis_and_board(self):
        wk = self._current_week()
        if not wk:
            return None, None, {"board_rows": 0}
        sym = wk.currency_id.symbol or "$"
        lines = wk.line_ids.sorted(lambda l: (l.date or fields.Date.today(), l.id))
        planned = sum(lines.mapped("amount"))
        paid = sum(lines.mapped("paid"))
        open_items = len(lines.filtered(lambda l: l.status != "paid"))
        kpis = {
            "week_name": wk.name,
            "currency": sym,
            "planned": self._money(planned),
            "paid": self._money(paid),
            "outstanding": self._money(planned - paid),
            "open_items": open_items,
        }
        board, running = [], 0.0
        for l in lines:
            running += l.amount or 0.0
            board.append({
                "id": l.id,
                "date": fields.Date.to_string(l.date) if l.date else "—",
                "details": l.details or "—",
                "amount": self._money(l.amount),
                "paid": self._money(l.paid),
                "status": dict(l._fields["status"].selection).get(l.status, l.status),
                "status_tone": _STATUS_TONE.get(l.status, "muted"),
                "balance": self._money(running),
                "currency": l.currency_id.symbol or sym,
            })
        return kpis, board, {"board_rows": len(board)}

    @api.model
    def _variance(self):
        EJ = self.env["commercial.event.job"]
        jobs = EJ.search(
            ["|", "|", ("quoted_budget", ">", 0),
             ("cost_total_usd", ">", 0), ("cost_total_zig", ">", 0)],
            limit=80)
        rows = []
        for ej in jobs:
            sym = (ej.quoted_budget_currency_id.symbol
                   or ej.initial_budget_currency_id.symbol or "$")
            # same-currency actual cost = quoted_budget - margin_gross
            actual = (ej.quoted_budget or 0.0) - (ej.margin_gross or 0.0)
            rows.append({
                "id": ej.id,
                "_rank": _ALERT_RANK.get(ej.budget_alert_level, 0),
                "event": ej.partner_id.display_name or ej.name or "—",
                "job_ref": ej.name,
                "quoted": self._money(ej.quoted_budget),
                "has_quote": bool(ej.quoted_budget),
                "actual": self._money(actual),
                "variance": self._money(ej.budget_variance_quoted),
                "variance_tone": "alert" if (ej.budget_variance_quoted or 0) > 0 else "ok",
                "margin_pct": "{:.1f}%".format(ej.margin_pct or 0.0),
                "alert": dict(ej._fields["budget_alert_level"].selection).get(
                    ej.budget_alert_level, "—") if ej.budget_alert_level else "—",
                "alert_tone": _ALERT_TONE.get(ej.budget_alert_level, "muted"),
                "currency": sym,
            })
        rows.sort(key=lambda r: r["_rank"], reverse=True)
        return rows

    @api.model
    def _approvals(self):
        AP = self.env["neon.finance.approval"]
        recs = AP.search([], limit=60)
        rows = []
        for a in recs:
            rows.append({
                "id": a.id,
                "name": a.name,
                "quote": a.quote_id.display_name or "—",
                "amount": self._money(a.quote_amount_total_snapshot),
                "currency": a.quote_currency_id_snapshot.symbol or "$",
                "requested_by": a.requested_by_id.name or "—",
                "state": dict(a._fields["state"].selection).get(a.state, a.state),
                "state_tone": _APPROVAL_TONE.get(a.state, "muted"),
                "date": fields.Date.to_string(
                    a.requested_at) if a.requested_at else "—",
            })
        pending = len([r for r in rows if r["state_tone"] == "warn"])
        return rows, pending

    # ------------------------------------------------------------------
    @api.model
    def get_data(self):
        self._check_access()
        kpis, board, board_meta = self._kpis_and_board()
        variance = self._variance()
        approvals, pending = self._approvals()
        return {
            "constants": self._constants(),
            "kpis": kpis,
            "board": board or [],
            "variance": variance,
            "approvals": approvals,
            "counts": {
                "board_rows": board_meta.get("board_rows", 0),
                "variance_rows": len(variance),
                "approvals_total": len(approvals),
                "approvals_pending": pending,
            },
        }
