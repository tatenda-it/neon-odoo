# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- RuleBasedAdapter (always-on fallback).

Six SQL/ORM-derived rules per addendum §8. No external dependency,
no API key, no AI. When the orchestrator falls back here, the
widget shows real specific insights derived from operational data.

The adapter is constructed with ``env`` rather than a provider
record because no config exists for rule-based -- it's always
available, always free. The orchestrator wraps the call.

⚠️ DECISION (M11, marker inline): rules fire only when called as
fallback (orchestrator decides). NOT interleaved with successful
AI results. Per prompt D6, addendum §8 confirms "fallback adapter".
"""
import logging
from datetime import timedelta

from .base_adapter import AdapterResult, BaseAdapter, InsightItem


_logger = logging.getLogger(__name__)


_MAX_INSIGHTS = 5


class RuleBasedAdapter(BaseAdapter):
    """Plain Python adapter with an env handle.

    Does not extend the standard BaseAdapter constructor (which
    expects a provider record) -- instead, accepts ``env`` and
    passes None to the parent. The orchestrator's _call_rule_based
    constructs this via ``RuleBasedAdapter(env=self.env)``.
    """

    def __init__(self, provider_record=None, env=None):
        super().__init__(provider_record)
        self.env = env

    def generate_insights(self, dashboard_context):
        import time  # noqa: PLC0415
        start = time.time()
        if self.env is None:
            return AdapterResult(
                success=False,
                error_message="RuleBasedAdapter requires env handle.",
                latency_ms=int((time.time() - start) * 1000),
            )
        items = []
        for rule in (
            self._rule_overdue_invoices,
            self._rule_crew_gaps,
            self._rule_cert_expiry,
            self._rule_pipeline_behind_target,
            self._rule_cash_low,
            self._rule_slow_lead_followup,
        ):
            try:
                rule(items, dashboard_context)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "RuleBasedAdapter: rule %s failed: %s",
                    rule.__name__, exc,
                )
            if len(items) >= _MAX_INSIGHTS:
                break
        items.sort(key=lambda i: (i.priority, i.title))
        return AdapterResult(
            success=True,
            insights=items[:_MAX_INSIGHTS],
            raw_response="rule-based",
            latency_ms=int((time.time() - start) * 1000),
        )

    def health_check(self):
        return self.env is not None

    # ==============================================================
    # Six rules per addendum §8
    # ==============================================================
    def _rule_overdue_invoices(self, items, ctx):
        """account.move with payment_state != paid and
        invoice_date_due < today-60."""
        Move = self.env["account.move"].sudo()
        today = self.env["neon.dashboard"]._today_harare()
        cutoff = today - timedelta(days=60)
        overdue = Move.search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "!=", "paid"),
            ("invoice_date_due", "<", cutoff),
        ], order="invoice_date_due asc", limit=3)
        for move in overdue:
            days_overdue = (today - move.invoice_date_due).days
            partner = move.partner_id.display_name or "Unknown"
            items.append(InsightItem(
                priority=1,
                title=(
                    f"{partner[:40]} "
                    f"{move.currency_id.symbol or ''}"
                    f"{move.amount_total:,.0f} "
                    f"overdue {days_overdue} days"
                ),
                detail=(
                    f"Invoice {move.name} for {partner} is "
                    f"{days_overdue} days past due. Recommend "
                    f"final notice before debt collection."
                ),
                source_ref={
                    "model": "account.move",
                    "res_id": move.id,
                },
            ))

    def _rule_crew_gaps(self, items, ctx):
        """commercial.event.job confirmed with event_date <=
        today+7 and crew shortfall."""
        Job = self.env["commercial.event.job"].sudo()
        today = self.env["neon.dashboard"]._today_harare()
        horizon = today + timedelta(days=7)
        jobs = Job.search([
            ("event_date", ">=", today),
            ("event_date", "<=", horizon),
            ("state", "in", [
                "planning", "prep", "ready_for_dispatch",
                "dispatched", "in_progress",
            ]),
        ], limit=10)
        for job in jobs:
            required = getattr(job, "crew_required", 0) or 0
            assigned = getattr(job, "crew_assigned", 0) or 0
            if required <= assigned:
                continue
            days_notice = (job.event_date - today).days
            items.append(InsightItem(
                priority=1 if days_notice <= 3 else 2,
                title=(
                    f"{(job.display_name or '?')[:40]} "
                    f"needs {required - assigned} more crew "
                    f"({days_notice}d notice)"
                ),
                detail=(
                    f"{required - assigned} of {required} crew "
                    f"slots open with {days_notice} days notice. "
                    f"Recommend freelancer outreach today."
                ),
                source_ref={
                    "model": "commercial.event.job",
                    "res_id": job.id,
                },
            ))
            if len(items) >= _MAX_INSIGHTS:
                return

    def _rule_cert_expiry(self, items, ctx):
        """neon.training.certification expiring within 30 days."""
        Cert = self.env["neon.training.certification"].sudo()
        today = self.env["neon.dashboard"]._today_harare()
        horizon = today + timedelta(days=30)
        certs = Cert.search([
            ("state", "=", "active"),
            ("date_expires", ">=", today),
            ("date_expires", "<=", horizon),
        ], order="date_expires asc", limit=3)
        for cert in certs:
            days = (cert.date_expires - today).days
            tech_name = cert.user_id.name or "?"
            cert_name = (cert.type_id.name if cert.type_id else "?")
            items.append(InsightItem(
                priority=2 if days <= 14 else 3,
                title=(
                    f"{tech_name[:30]} -- {cert_name[:30]} "
                    f"expires in {days}d"
                ),
                detail=(
                    f"{tech_name}'s {cert_name} certification "
                    f"expires in {days} days. Schedule renewal "
                    f"now to avoid gating job assignments."
                ),
                source_ref={
                    "model": "neon.training.certification",
                    "res_id": cert.id,
                },
            ))

    def _rule_pipeline_behind_target(self, items, ctx):
        """forecast_vs_target_pct < 80 with > 50% of period elapsed."""
        kpi = ctx.get("kpi_forecast") or {}
        pct = kpi.get("forecast_vs_target_pct")
        days_elapsed_pct = kpi.get("days_elapsed_pct")
        if pct is None or days_elapsed_pct is None:
            return
        try:
            pct_f = float(pct)
            days_elapsed_f = float(days_elapsed_pct)
        except (TypeError, ValueError):
            return
        if pct_f >= 80 or days_elapsed_f <= 50:
            return
        items.append(InsightItem(
            priority=2,
            title=(
                f"Pipeline {pct_f:.0f}% to target with "
                f"{100 - days_elapsed_f:.0f}% of period remaining"
            ),
            detail=(
                f"Forecast at {pct_f:.0f}% of monthly target with "
                f"only {100 - days_elapsed_f:.0f}% of the period "
                f"left. Push acceptance on top-of-funnel deals."
            ),
            source_ref=None,
        ))

    def _rule_cash_low(self, items, ctx):
        """cash_on_hand vs payroll + payables.

        We approximate via KPI display: when AR overdue exceeds
        cash on hand (USD-eqv) by >50%, flag.
        """
        kpi_cash = ctx.get("kpi_cash") or {}
        kpi_ar = ctx.get("kpi_ar_overdue") or {}
        cash = kpi_cash.get("value_usd") or kpi_cash.get("value") or 0
        ar = kpi_ar.get("value_usd") or kpi_ar.get("value") or 0
        try:
            cash_f = float(cash or 0)
            ar_f = float(ar or 0)
        except (TypeError, ValueError):
            return
        if cash_f <= 0:
            return
        if ar_f <= cash_f * 1.5:
            return
        items.append(InsightItem(
            priority=1,
            title=(
                f"AR overdue (${ar_f:,.0f}) is "
                f"{(ar_f / cash_f):.1f}x cash on hand"
            ),
            detail=(
                f"Overdue receivables of ${ar_f:,.0f} are "
                f"{(ar_f / cash_f):.1f}x current cash position. "
                f"Prioritise collection calls this week."
            ),
            source_ref=None,
        ))

    def _rule_slow_lead_followup(self, items, ctx):
        """crm.lead create_date < today-3 with no activity."""
        Lead = self.env["crm.lead"].sudo()
        today = self.env["neon.dashboard"]._today_harare()
        cutoff = today - timedelta(days=3)
        try:
            stale = Lead.search([
                ("active", "=", True),
                ("type", "=", "lead"),
                ("create_date", "<", cutoff),
                ("activity_ids", "=", False),
            ], limit=5)
        except Exception:  # noqa: BLE001
            return
        if not stale:
            return
        count = len(stale)
        items.append(InsightItem(
            priority=3,
            title=f"{count} lead{'s' if count != 1 else ''} with no contact in 3+ days",
            detail=(
                f"{count} active lead{'s' if count != 1 else ''} "
                f"created before {cutoff.isoformat()} have no "
                f"recorded activity. Assign owner + first-contact "
                f"call this week."
            ),
            source_ref=(
                {"model": "crm.lead", "res_id": stale[0].id}
                if stale else None
            ),
        ))
