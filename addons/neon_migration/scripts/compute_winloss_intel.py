# -*- coding: utf-8 -*-
"""Win/Loss + Realisation intelligence — the L2.3 aggregation (PURE READ).

Two halves over the quote + invoice archive, cut by CLIENT / REP / PERIOD
(year×month) / CATEGORY:
  * WIN/LOSS  — win-rate (won/total quotes), by cut. Matches L1 client board
    (count-based, cross-board checked: British Embassy 9/17, etc.).
  * REALISATION — the quoted -> won -> invoiced value flow, by cut. Deepens the
    live L1 Realisation pivot (neon.finance.realisation.report) and reconciles
    to it EXACTLY using UNTAXED values:
      quoted   = Σ quote.amount_untaxed
      won      = Σ won-quote.amount_untaxed
      invoiced = Σ invoice.archive.amount_untaxed   (invoice-side; 301 invoices)

STORED aggregates; this module computes ONLY (reads, returns dicts, never
writes). Mirrors the L2.1/L2.2 parse/loader split.

HONEST NOTES (from real data, surfaced at the gate):
  * zoho_invoice_number is populated on EXACTLY the 257 won quotes (won≡linked)
    -> the won->invoiced LINK coverage is 100% by construction of the archive's
    won-link populate; it is NOT a real conversion funnel. The meaningful
    realisation signal is the VALUE flow (invoiced/won value), not a link rate.
  * Realisation value uses UNTAXED (to reconcile to the L1 pivot, which is
    line_total ≈ untaxed). Win-rate stays count-based.
  * Invoiced is by INVOICE date (when realised), quoted/won by quotation date.
  * MONEY = USD only; non-USD disclosed separately, NEVER blended.
  * CATEGORY cut: win-rate counts ONLY (a quote spans categories -> value would
    double-count). Category key normalised (upper/strip/collapse).
"""
import re

USD = "USD"


def _norm_cat(c):
    return re.sub(r"\s+", " ", (c or "").upper()).strip()


def _new(label="", partner_id=False, year=None, month=None):
    return {"label": label, "partner_id": partner_id, "year": year,
            "month": month, "q": 0, "won": 0, "lost": 0, "open": 0, "hist": 0,
            "quoted_unt": 0.0, "won_unt": 0.0, "nonusd": 0.0,
            "inv_count": 0, "inv_unt": 0.0, "nonusd_inv": 0.0}


def _acc_quote(b, st, usd, unt, with_value=True):
    b["q"] += 1
    if st == "won":
        b["won"] += 1
    elif st == "lost":
        b["lost"] += 1
    elif st == "open":
        b["open"] += 1
    else:
        b["hist"] += 1
    if not with_value:
        return
    if usd:
        b["quoted_unt"] += unt
        if st == "won":
            b["won_unt"] += unt
    elif unt:
        b["nonusd"] += unt


def _acc_invoice(b, usd, unt):
    b["inv_count"] += 1
    if usd:
        b["inv_unt"] += unt
    elif unt:
        b["nonusd_inv"] += unt


def _rate(num, den):
    return round(num / den, 4) if den else 0.0


def _rows_from(dim, d, with_value=True):
    out = []
    for b in d.values():
        q, wl = b["q"], b["won"] + b["lost"]
        out.append({
            "dimension": dim, "key_label": b["label"],
            "partner_id": b["partner_id"], "year": b["year"],
            "month": b["month"],
            "quotes_count": q, "won_count": b["won"], "lost_count": b["lost"],
            "open_count": b["open"], "historical_count": b["hist"],
            "win_rate": _rate(b["won"], q),
            "decided_win_rate": _rate(b["won"], wl),
            "quoted_value_usd": round(b["quoted_unt"], 2) if with_value else 0.0,
            "won_value_usd": round(b["won_unt"], 2) if with_value else 0.0,
            "invoiced_count": b["inv_count"] if with_value else 0,
            "invoiced_value_usd": round(b["inv_unt"], 2) if with_value else 0.0,
            "win_value_rate": _rate(b["won_unt"], b["quoted_unt"])
            if with_value else 0.0,
            "realisation_rate": _rate(b["inv_unt"], b["won_unt"])
            if with_value else 0.0,
            "nonusd_quote_value": round(b["nonusd"], 2) if with_value else 0.0,
        })
    return out


def compute_winloss_rows(env):
    """Return (rows, stats). rows = long-format dicts (one per dimension×key).
    PURE READ — no writes."""
    Q = env["neon.finance.quote.archive"].sudo()
    QL = env["neon.finance.quote.archive.line"].sudo()
    IA = env["neon.finance.invoice.archive"].sudo()

    by_client, by_rep, by_period = {}, {}, {}
    qstatus = {}
    stats = {"quotes": 0, "won": 0, "lost": 0, "open": 0, "historical": 0,
             "nonusd_quote_value": 0.0, "nonusd_quotes": 0, "years": set(),
             "undated_q": 0, "invoices": 0, "invoiced_value_usd": 0.0,
             "quoted_value_usd": 0.0, "won_value_usd": 0.0,
             "won_with_link": 0}

    # ---- quotes: win/loss + quoted/won value (untaxed) ----
    for q in Q.search([]):
        stats["quotes"] += 1
        st = q.status_bucket
        qstatus[q.id] = st
        stats[st if st in ("won", "lost", "open") else "historical"] += 1
        usd = (q.currency_code or USD).upper() == USD
        unt = float(q.amount_untaxed or 0.0)
        if st == "won" and q.zoho_invoice_number:
            stats["won_with_link"] += 1
        if usd:
            stats["quoted_value_usd"] += unt
            if st == "won":
                stats["won_value_usd"] += unt
        elif unt:
            stats["nonusd_quote_value"] += unt
            stats["nonusd_quotes"] += 1
        d = q.quotation_date
        if q.partner_id:
            _acc_quote(by_client.setdefault(
                q.partner_id.id, _new(q.partner_id.name, q.partner_id.id)),
                st, usd, unt)
        rep = q.salesperson_display or "Unassigned"
        _acc_quote(by_rep.setdefault(rep, _new(rep)), st, usd, unt)
        if d:
            stats["years"].add(d.year)
            _acc_quote(by_period.setdefault(
                (d.year, d.month),
                _new("%04d-%02d" % (d.year, d.month), year=d.year,
                     month=d.month)), st, usd, unt)
        else:
            stats["undated_q"] += 1

    # ---- invoices: realised value (untaxed), by the SAME segment keys ----
    for inv in IA.search([]):
        stats["invoices"] += 1
        usd = (inv.currency_code or USD).upper() == USD
        unt = float(inv.amount_untaxed or 0.0)
        if usd:
            stats["invoiced_value_usd"] += unt
        if inv.partner_id:
            _acc_invoice(by_client.setdefault(
                inv.partner_id.id,
                _new(inv.partner_id.name, inv.partner_id.id)), usd, unt)
        rep = (inv.salesperson_id.name or inv.salesperson_name or "Unassigned")
        _acc_invoice(by_rep.setdefault(rep, _new(rep)), usd, unt)
        d = inv.invoice_date
        if d:
            _acc_invoice(by_period.setdefault(
                (d.year, d.month),
                _new("%04d-%02d" % (d.year, d.month), year=d.year,
                     month=d.month)), usd, unt)

    # ---- category: win-rate counts only (value double-counts across cats) ----
    qcats = {}
    for ln in QL.search([]):
        c = _norm_cat(ln.category_prefix)
        if c:
            qcats.setdefault(ln.archive_id.id, set()).add(c)
    by_cat = {}
    for qid, cats in qcats.items():
        st = qstatus.get(qid)
        if st is None:
            continue
        for c in cats:
            _acc_quote(by_cat.setdefault(c, _new(c)), st, False, 0.0,
                       with_value=False)

    rows = (_rows_from("client", by_client)
            + _rows_from("rep", by_rep)
            + _rows_from("period", by_period)
            + _rows_from("category", by_cat, with_value=False))
    stats["years"] = sorted(stats["years"])
    stats["clients"] = len(by_client)
    stats["reps"] = len(by_rep)
    stats["categories"] = len(by_cat)
    for k in ("quoted_value_usd", "won_value_usd", "invoiced_value_usd",
              "nonusd_quote_value"):
        stats[k] = round(stats[k])
    return rows, stats
