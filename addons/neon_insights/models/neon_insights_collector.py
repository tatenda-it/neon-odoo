# -*- coding: utf-8 -*-
"""WA-11 — feedback INSIGHTS collector (read-only, manager-tier).

A tableless AbstractModel that aggregates the post-event feedback corpus
(commercial.event.feedback, built by WA-10) into the three v1 views: a
per-client satisfaction timeline, a recent-feedback stream, and simple
sentiment aggregates. Every public method is a READ (search / read_group via
.sudo() for the aggregate, but the ACCESS GATE runs as the real user FIRST) —
there is no create/write/unlink anywhere. Audience = Neon Superuser + Jobs
Manager ONLY; the gate is re-checked here (the data layer), so a sales/crew
user who reaches the RPC directly is denied, not merely menu-hidden.
"""
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

# Audience: OD/superuser + managers ONLY (route + menu + this RPC re-check).
_INSIGHTS_GROUPS = (
    "neon_core.group_neon_superuser",
    "neon_jobs.group_neon_jobs_manager",
)
# Month buckets follow Harare time (Phase-8.5 dashboard-tz decision) so a
# late-night month-end event lands in the right month, not UTC's.
_TZ = "Africa/Harare"
_TOP_CLIENTS = 10
_STREAM_LIMIT = 50
_AGG_MONTHS = 12
# Recurring-negative flag: this many negative rows within this window.
_RECUR_NEG_THRESHOLD = 2
_RECUR_WINDOW_DAYS = 30

_SENTIMENTS = ("positive", "neutral", "negative", "mixed")


class NeonInsightsCollector(models.AbstractModel):
    _name = "neon.insights.collector"
    _description = "Neon Feedback Insights Collector (read-only)"

    # ---- access gate (real user; raises -> RPC-layer denial) ----------
    @api.model
    def _user_may_view(self, user=None):
        user = user or self.env.user
        if user.share:                       # portal/public never
            return False
        return any(user.has_group(g) for g in _INSIGHTS_GROUPS)

    @api.model
    def _check_access(self):
        if not self._user_may_view():
            raise AccessError(_(
                "Feedback Insights is restricted to the OD and managers."))

    # ---- helpers ------------------------------------------------------
    @api.model
    def _Fb(self):
        # sudo for the aggregate read ONLY -- the gate already ran as the
        # real user; in the Harare tz so date buckets align.
        return self.env["commercial.event.feedback"].sudo().with_context(
            tz=_TZ)

    @api.model
    def _snippet(self, text, n=80):
        return " ".join((text or "").split())[:n]

    @api.model
    def _empty_sentiments(self):
        return {s: 0 for s in _SENTIMENTS}

    # ---- view 1: per-client satisfaction ------------------------------
    @api.model
    def collect_top_clients(self, limit=_TOP_CLIENTS):
        """Top clients by feedback volume, each with a sentiment breakdown +
        event count. The OD walking in sees the answer, not a form."""
        self._check_access()
        Fb = self._Fb()
        groups = Fb.read_group(
            [("partner_id", "!=", False)],
            ["partner_id"], ["partner_id"],
            orderby="__count desc", limit=limit)
        out = []
        for g in groups:
            pid = g["partner_id"][0]
            recs = Fb.search([("partner_id", "=", pid)])
            sent = self._empty_sentiments()
            for r in recs:
                if r.sentiment in sent:
                    sent[r.sentiment] += 1
            out.append({
                "partner_id": pid,
                "name": g["partner_id"][1],
                "feedback_count": g["partner_id_count"],
                "event_count": len(recs.mapped("event_job_id")),
                "sentiment": sent,
            })
        return out

    @api.model
    def collect_partner_timeline(self, partner_id):
        """One client's events, most-recent first, with the sentiment PER
        VOICE (sales relayed-CSAT / OD / crew) on each event."""
        self._check_access()
        Fb = self._Fb()
        recs = Fb.search([("partner_id", "=", int(partner_id))],
                         order="event_date desc, captured_at desc")
        by_event = {}
        for r in recs:
            ej = r.event_job_id
            key = ej.id
            if key not in by_event:
                by_event[key] = {
                    "event_id": ej.id, "event_name": ej.name or _("(event)"),
                    "event_date": str(r.event_date or ""), "voices": []}
            by_event[key]["voices"].append({
                "role": r.wa_role or "client",
                "sentiment": r.sentiment or "",
                "client_relayed": bool(r.client_relayed),
                "snippet": self._snippet(r.feedback_text),
            })
        return list(by_event.values())

    # ---- view 2: recent stream ----------------------------------------
    @api.model
    def collect_stream(self, role_filter="all", sentiment_filter="all",
                       limit=_STREAM_LIMIT):
        """Recent feedback, newest first. role_filter: all|client|staff;
        sentiment_filter: all|positive|neutral|negative|mixed."""
        self._check_access()
        domain = []
        if role_filter == "client":
            domain.append(("wa_role", "=", False))
        elif role_filter == "staff":
            domain.append(("wa_role", "!=", False))
        if sentiment_filter in _SENTIMENTS:
            domain.append(("sentiment", "=", sentiment_filter))
        recs = self._Fb().search(domain, order="captured_at desc, id desc",
                                 limit=limit)
        return [{
            "id": r.id,
            "date": str(r.captured_at or ""),
            "partner": r.partner_id.name or "",
            "event": r.event_job_id.name or "",
            "role": r.wa_role or "client",
            "sentiment": r.sentiment or "",
            "snippet": self._snippet(r.feedback_text, 120),
        } for r in recs]

    # ---- view 3: aggregates -------------------------------------------
    @api.model
    def collect_aggregates(self, months=_AGG_MONTHS):
        """Sentiment counts by month (Harare buckets) + recurring-negative
        client flags (>= threshold negatives in the window)."""
        self._check_access()
        Fb = self._Fb()
        groups = Fb.read_group(
            [], ["captured_at", "sentiment"],
            ["captured_at:month", "sentiment"], lazy=False)
        months_map = {}
        for g in groups:
            label = g.get("captured_at:month") or _("Undated")
            row = months_map.setdefault(label, self._empty_sentiments())
            s = g.get("sentiment")
            if s in row:
                row[s] += g.get("__count", 0)
        month_rows = [{"month": k, **v} for k, v in months_map.items()]
        month_rows = month_rows[-months:] if months else month_rows
        # recurring-negative: clients with >= threshold negatives in window
        cutoff = fields.Datetime.now() - timedelta(days=_RECUR_WINDOW_DAYS)
        neg = Fb.read_group(
            [("sentiment", "=", "negative"), ("partner_id", "!=", False),
             ("captured_at", ">=", fields.Datetime.to_string(cutoff))],
            ["partner_id"], ["partner_id"])
        recurring = [{
            "partner_id": g["partner_id"][0], "partner": g["partner_id"][1],
            "count": g["partner_id_count"],
        } for g in neg if g["partner_id_count"] >= _RECUR_NEG_THRESHOLD]
        recurring.sort(key=lambda r: -r["count"])
        return {"months": month_rows, "recurring": recurring,
                "window_days": _RECUR_WINDOW_DAYS,
                "threshold": _RECUR_NEG_THRESHOLD, "tz": _TZ}

    # ---- the page's initial payload -----------------------------------
    @api.model
    def collect_all(self):
        self._check_access()
        top = self.collect_top_clients()
        stream = self.collect_stream()
        agg = self.collect_aggregates()
        return {
            "top_clients": top,
            "stream": stream,
            "aggregates": agg,
            "has_data": bool(self._Fb().search_count([])),
            "tz": _TZ,
        }
