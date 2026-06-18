# -*- coding: utf-8 -*-
"""Client / account intelligence — the L2.1 aggregation (PURE READ).

Aggregates the loaded INERT archives + the LIVE collections worklist into
per-client rollups. This module computes ONLY — it reads and returns dicts; it
NEVER writes. The model's cron_recompute() calls compute_client_intel_rows()
then persists; the gate dry-run probe calls the same function and prints,
writing nothing. Mirrors the parse/loader split used across neon_migration.

Sources (verified field names):
  neon.finance.quote.archive   partner_id, amount_total, status_bucket(=='won'),
                               quotation_date, currency_code
  neon.finance.invoice.archive partner_id, amount_total, invoice_date,
                               currency_code
  neon.job.history (is_job)    partner_id, date_start, event_type
  neon.collections.item        partner_id, amount_usd, status   [SENSITIVE]

CONVENTIONS:
  * MONEY = USD only (sums filter currency_code == 'USD'); COUNTS span all
    currencies. Non-USD value is disclosed, never blended (hist-intel guard).
  * Records with NO partner link bucket into ONE 'unmatched' row (partner_id
    False) — never dropped, never guessed; reported at the gate.
  * Conservative: a metric is attributed to a client only where the link exists.

SEGMENT RULES (transparent, rule-based — shown in the field tooltip):
  active_years = distinct calendar years across JOBS + QUOTES (quotes are 100%
  partner-matched; counting them avoids the repeat undercount from the ~398
  unmatched FamCal jobs). recency = days since the last job/quote (may be
  NEGATIVE for a future-dated event; undated-only clients have recency=None ->
  unknown, so they are neither dormant nor forced out).
  evaluated top-down, first match wins:
    dormant                 recency_days is known AND > DORMANT_DAYS (>12 mo)
    high_value_repeat       active_years >= 2 AND won_value >= HIGH_VALUE_USD
    quote_heavy_low_convert quotes_count >= QUOTE_HEAVY_MIN AND
                            win_rate < LOW_CONVERT_RATE
    new                     first activity within NEW_DAYS AND active_years <= 1
    steady                  active_years >= 2
    one_off                 otherwise
"""
from datetime import date


# --- segment thresholds (tunable; surfaced at the gate) ---------------------
HIGH_VALUE_USD = 10000.0     # won_value at/above => "high value"
QUOTE_HEAVY_MIN = 4          # quotes_count at/above => "quote heavy"
LOW_CONVERT_RATE = 0.25      # win_rate below => "low convert"
DORMANT_DAYS = 365           # no activity beyond 12 months => dormant
NEW_DAYS = 365               # first activity within a year => new
# ranking-only: a min-quotes floor so 1/1 = 100% can't top the win-rate board
MIN_QUOTES_FOR_WINRATE_RANK = 3

USD = "USD"


def _year(dt):
    return dt.year if dt else None


def _as_date(dt):
    """Datetime/Date -> date (job.history.date_start is a Datetime)."""
    if not dt:
        return None
    return dt.date() if hasattr(dt, "date") else dt


def _seg(active_years, won_value, quotes_count, win_rate, recency_days,
         first_days):
    if recency_days is not None and recency_days > DORMANT_DAYS:
        return "dormant"
    if active_years >= 2 and won_value >= HIGH_VALUE_USD:
        return "high_value_repeat"
    if quotes_count >= QUOTE_HEAVY_MIN and win_rate < LOW_CONVERT_RATE:
        return "quote_heavy_low_convert"
    if first_days is not None and first_days <= NEW_DAYS and active_years <= 1:
        return "new"
    if active_years >= 2:
        return "steady"
    return "one_off"


def _payment_behaviour(outstanding_usd, coll_statuses, invoiced_value):
    """HEURISTIC label (NOT a credit fact) from collections status + whether
    the client has been invoiced. Flagged as a heuristic in the field help."""
    if outstanding_usd and outstanding_usd > 0:
        if "unresponsive" in coll_statuses:
            return "at_risk"
        if coll_statuses & {"promised", "po_submitted", "clearing",
                            "part_paid", "chasing"}:
            return "slow_paying"
        return "owing"
    if invoiced_value and invoiced_value > 0:
        return "settled"
    return "unknown"


def _bucket():
    return {
        "quotes_count": 0, "quotes_value": 0.0,
        "won_count": 0, "won_value": 0.0,
        "invoices_count": 0, "invoiced_value": 0.0,
        "jobs_count": 0, "job_dates": [], "event_types": set(),
        "quote_dates": [], "outstanding_usd": 0.0, "coll_statuses": set(),
        "nonusd_quote_value": 0.0, "nonusd_invoice_value": 0.0,
    }


def compute_client_intel_rows(env, today=None):
    """Return (rows, stats). rows = list of vals dicts for neon.client.intel
    (partner_id False = the unmatched bucket). PURE READ — no writes."""
    today = today or date.today()
    Q = env["neon.finance.quote.archive"].sudo()
    I = env["neon.finance.invoice.archive"].sudo()
    J = env["neon.job.history"].sudo()
    C = env["neon.collections.item"].sudo()

    data = {}   # partner_id (or False) -> bucket

    def b(pid):
        return data.setdefault(pid, _bucket())

    # ---- quotes ----
    for q in Q.search([]):
        pid = q.partner_id.id or False
        bk = b(pid)
        bk["quotes_count"] += 1
        if q.quotation_date:
            bk["quote_dates"].append(q.quotation_date)
        usd = (q.currency_code or USD).upper() == USD
        amt = float(q.amount_total or 0.0)
        if usd:
            bk["quotes_value"] += amt
        else:
            bk["nonusd_quote_value"] += amt
        if q.status_bucket == "won":
            bk["won_count"] += 1
            if usd:
                bk["won_value"] += amt

    # ---- invoices ----
    for inv in I.search([]):
        pid = inv.partner_id.id or False
        bk = b(pid)
        bk["invoices_count"] += 1
        amt = float(inv.amount_total or 0.0)
        if (inv.currency_code or USD).upper() == USD:
            bk["invoiced_value"] += amt
        else:
            bk["nonusd_invoice_value"] += amt

    # ---- jobs (is_job only) ----
    for j in J.search([("is_job", "=", True)]):
        pid = j.partner_id.id or False
        bk = b(pid)
        bk["jobs_count"] += 1
        d = _as_date(j.date_start)
        if d:
            bk["job_dates"].append(d)
        if j.event_type and j.event_type.strip():
            bk["event_types"].add(j.event_type.strip())

    # ---- collections (SENSITIVE) ----
    for c in C.search([]):
        pid = c.partner_id.id or False
        bk = b(pid)
        bk["outstanding_usd"] += float(c.amount_usd or 0.0)
        if c.status:
            bk["coll_statuses"].add(c.status)

    # partner names (one read for all matched ids)
    pids = [p for p in data if p]
    names = {p.id: p.name for p in env["res.partner"].sudo().browse(pids)
             if p.exists()}

    rows = []
    stats = {
        "clients": 0, "unmatched_quotes": 0, "unmatched_quotes_value": 0.0,
        "unmatched_invoices": 0, "unmatched_jobs": 0,
        "nonusd_quote_value": 0.0, "nonusd_invoice_value": 0.0,
        "segments": {},
    }
    for pid, bk in data.items():
        job_dates = sorted(bk["job_dates"])
        quote_dates = sorted(bk["quote_dates"])
        last_dates = [d for d in (job_dates[-1] if job_dates else None,
                                  quote_dates[-1] if quote_dates else None)
                      if d]
        first_dates = [d for d in (job_dates[0] if job_dates else None,
                                   quote_dates[0] if quote_dates else None)
                       if d]
        last_act = max(last_dates) if last_dates else None
        first_act = min(first_dates) if first_dates else None
        # recency may be NEGATIVE for future-dated events ("days until next
        # event") — left unclamped on purpose (real upcoming-work signal).
        recency_days = (today - last_act).days if last_act else None
        first_days = (today - first_act).days if first_act else None
        # active_years from JOBS + QUOTES (quotes are 100% partner-matched, so
        # this avoids the repeat-client undercount from unmatched FamCal jobs).
        active_years = len({_year(d) for d in (job_dates + quote_dates) if d})
        win_rate = (bk["won_count"] / bk["quotes_count"]
                    if bk["quotes_count"] else 0.0)
        stats["nonusd_quote_value"] += bk["nonusd_quote_value"]
        stats["nonusd_invoice_value"] += bk["nonusd_invoice_value"]

        if not pid:
            stats["unmatched_quotes"] = bk["quotes_count"]
            stats["unmatched_quotes_value"] = bk["quotes_value"]
            stats["unmatched_invoices"] = bk["invoices_count"]
            stats["unmatched_jobs"] = bk["jobs_count"]
            segment = "one_off"           # not meaningful for the bucket
            client_name = "(unmatched — no partner link)"
            payment_behaviour = "unknown"
        else:
            stats["clients"] += 1
            segment = _seg(active_years, bk["won_value"], bk["quotes_count"],
                           win_rate, recency_days, first_days)
            client_name = names.get(pid) or "(partner #%s)" % pid
            payment_behaviour = _payment_behaviour(
                bk["outstanding_usd"], bk["coll_statuses"],
                bk["invoiced_value"])
        stats["segments"][segment] = stats["segments"].get(segment, 0) + 1

        rows.append({
            "partner_id": pid or False,
            "client_name": client_name,
            "quotes_count": bk["quotes_count"],
            "quotes_value": round(bk["quotes_value"], 2),
            "won_count": bk["won_count"],
            "won_value": round(bk["won_value"], 2),
            "win_rate": round(win_rate, 4),
            "invoices_count": bk["invoices_count"],
            "invoiced_value": round(bk["invoiced_value"], 2),
            "jobs_count": bk["jobs_count"],
            "first_job_date": job_dates[0] if job_dates else False,
            "last_job_date": job_dates[-1] if job_dates else False,
            "active_years": active_years,
            "recency_days": recency_days if recency_days is not None else 0,
            "event_types": ", ".join(sorted(bk["event_types"]))[:512],
            "outstanding_usd": round(bk["outstanding_usd"], 2),
            "outstanding_status": ", ".join(sorted(bk["coll_statuses"])),
            "payment_behaviour": payment_behaviour,
            "segment": segment,
        })
    return rows, stats
