#!/usr/bin/env python3
"""
ZOHO BOOKS -> the two import JSON files (run by Tatenda with Zoho creds).

Emits, in the agreed schema (consumed by scripts/import_zoho_reference.py):
  zoho_customers.json   (ALL Books customers; NO balances/ledger figures)
  zoho_estimates.json   (line-item level)
into $ZOHO_SRC (default current dir).

Zoho is READ-ONLY here: only GET on Books data (+ the standard OAuth token POST).
Never POST/PUT/DELETE any Books record.

AUTH — Tatenda sets these env vars; this script reads them. Claude Code / the
assistant NEVER handle the credentials:
  ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN   (self-client; scopes
    ZohoBooks.contacts.READ + estimates.READ + invoices.READ)
  ZOHO_API_DOMAIN        default https://www.zohoapis.com      (region-specific)
  ZOHO_ACCOUNTS_DOMAIN   default https://accounts.zoho.com     (region-specific)
  ZOHO_ORG_ID            default 824936520
Optional:
  ZOHO_SRC      output dir (default ".")
  ZOHO_LIMIT    cap items per entity for a cheap smoke run (0 = all). Run with
                ZOHO_LIMIT=5 FIRST to validate auth + schema before the full pull.
  ZOHO_THROTTLE inter-request sleep seconds (default 0.2)

Usage:
  ZOHO_CLIENT_ID=... ZOHO_CLIENT_SECRET=... ZOHO_REFRESH_TOKEN=... \
  ZOHO_API_DOMAIN=https://www.zohoapis.com python3 scripts/export_zoho_to_json.py

Self-check baseline (prints PASS/WARN, never hard-fails after writing):
  ~895 customers · 2,019 estimates · ~257 with a zoho_invoice_number ·
  currency ~1,938 USD / 61 ZWG / 1 ZAR.

`requests` is imported lazily (inside the network calls) so the pure mapping
functions remain importable + unit-testable without the dependency or live Zoho.
"""
import json
import os
import sys
import time

API_DOMAIN = os.environ.get("ZOHO_API_DOMAIN", "https://www.zohoapis.com").rstrip("/")
ACCOUNTS_DOMAIN = os.environ.get(
    "ZOHO_ACCOUNTS_DOMAIN", "https://accounts.zoho.com").rstrip("/")
ORG_ID = os.environ.get("ZOHO_ORG_ID", "824936520")
OUT_DIR = os.environ.get("ZOHO_SRC", ".")
LIMIT = int(os.environ.get("ZOHO_LIMIT", "0") or "0")
THROTTLE = float(os.environ.get("ZOHO_THROTTLE", "0.2") or "0.2")

_token = {"value": None}


# ======================================================================
# Pure mapping (no network / no deps) — unit-tested by pexport_*_smoke.
# ======================================================================
def _join(*parts):
    return " ".join(p for p in parts if p).strip()


def map_customer(d):
    """Books contact detail -> the customers-schema dict. No balance fields."""
    billing = d.get("billing_address") or {}
    persons = []
    for p in (d.get("contact_persons") or []):
        persons.append({
            "name": _join(p.get("first_name"), p.get("last_name"))
            or p.get("contact_person_name") or "(contact)",
            "email": p.get("email") or "",
            "phone": p.get("phone") or p.get("mobile") or "",
            "primary": bool(p.get("is_primary_contact")),
        })
    email = d.get("email") or ""
    if not email:
        prim = next((p for p in (d.get("contact_persons") or [])
                     if p.get("is_primary_contact")), None)
        email = (prim or {}).get("email") or ""
    return {
        "zoho_source_id": str(d.get("contact_id") or ""),
        "name": d.get("contact_name") or d.get("company_name") or "",
        "company_type": ("individual"
                         if d.get("customer_sub_type") == "individual"
                         else "company"),
        "email": email,
        "phone": d.get("phone") or d.get("mobile") or "",
        "billing": {
            "street": _join(billing.get("address"), billing.get("street2")),
            "city": billing.get("city") or "",
            "country": billing.get("country") or "",
            "attention": billing.get("attention") or "",
        },
        "contacts": persons,
    }


def _category_prefix(name):
    name = name or ""
    return name.split(" - ", 1)[0] if " - " in name else name


def map_estimate(d, inv_map):
    """Books estimate detail -> the estimates-schema dict."""
    lines = []
    for li in (d.get("line_items") or []):
        nm = li.get("name") or li.get("description") or ""
        lines.append({
            "name": nm,
            "description": li.get("description") or "",
            "unit": li.get("unit") or "",
            "quantity": li.get("quantity") or 0,
            "unit_rate": li.get("rate") or 0,
            "line_total": li.get("item_total") or 0,
            "zoho_item_id": str(li.get("item_id") or ""),
            "category_prefix": _category_prefix(nm),
        })
    est_id = str(d.get("estimate_id") or "")
    return {
        "zoho_estimate_number": d.get("estimate_number") or "",
        "zoho_customer_source_id": str(d.get("customer_id") or ""),
        "quotation_date": d.get("date") or "",
        "zoho_status": d.get("status") or "",
        "currency_code": d.get("currency_code") or "USD",
        "salesperson_name": d.get("salesperson_name") or "",
        "event_summary": d.get("subject_content") or d.get("custom_subject") or "",
        "zoho_invoice_number": inv_map.get(est_id) or "",
        "amount_untaxed": d.get("sub_total") or 0,
        "amount_tax": d.get("tax_total") or 0,
        "amount_total": d.get("total") or 0,
        "lines": lines,
    }


def build_invoice_map(invoices):
    """[invoice list] -> {estimate_id -> invoice_number} for won-row links."""
    m = {}
    for inv in invoices:
        num = inv.get("invoice_number")
        est_id = inv.get("estimate_id") or inv.get("invoiced_estimate_id")
        if est_id and num:
            m[str(est_id)] = num
    return m


def map_invoice(d, est_id_to_number):
    """Books invoice DETAIL -> the invoice-schema dict. OMITS balance/balance_due
    (Zoho = AR system of record). estimate_id (detail-only) -> estimate NUMBER via
    the estimates-list map -> links to neon.finance.quote.archive + the won-link."""
    lines = []
    for li in (d.get("line_items") or []):
        nm = li.get("name") or li.get("description") or ""
        lines.append({
            "name": nm,
            "description": li.get("description") or "",
            "unit": li.get("unit") or "",
            "quantity": li.get("quantity") or 0,
            "unit_rate": li.get("rate") or 0,
            "line_total": li.get("item_total") or 0,
            "zoho_item_id": str(li.get("item_id") or ""),
            "category_prefix": _category_prefix(nm),
        })
    est_id = str(d.get("estimate_id") or "")
    return {
        "zoho_invoice_number": d.get("invoice_number") or "",
        "zoho_customer_source_id": str(d.get("customer_id") or ""),
        "zoho_estimate_number": est_id_to_number.get(est_id, "") if est_id else "",
        "invoice_date": d.get("date") or "",
        "status": d.get("status") or "",
        "currency_code": d.get("currency_code") or "USD",
        "salesperson_name": d.get("salesperson_name") or "",
        "event_summary": d.get("subject_content") or d.get("custom_subject") or "",
        "amount_untaxed": d.get("sub_total") or 0,
        "amount_tax": d.get("tax_total") or 0,
        "amount_total": d.get("total") or 0,
        "lines": lines,
    }


def map_expense(d):
    """Books expense DETAIL -> the expense-schema dict. NO vendor field at all;
    billable-to CUSTOMER only (customer_id, null if none)."""
    lines = []
    for li in (d.get("line_items") or []):
        lines.append({
            "description": li.get("description") or "",
            "account_name": li.get("account_name") or "",
            "amount": li.get("amount") or li.get("item_total") or 0,
        })
    return {
        "zoho_expense_id": str(d.get("expense_id") or ""),
        "expense_date": d.get("date") or "",
        "account_name": d.get("account_name") or "",
        "description": d.get("description") or "",
        "reference_number": d.get("reference_number") or "",
        "status": d.get("status") or "",
        "is_billable": bool(d.get("is_billable")),
        "zoho_customer_source_id": str(d.get("customer_id") or ""),
        "currency_code": d.get("currency_code") or "USD",
        "amount": d.get("total") or d.get("amount") or 0,
        "tax": d.get("tax_total") or d.get("tax_amount") or 0,
        "lines": lines,
    }


# ======================================================================
# Network (lazy requests) — only exercised on a real run with creds.
# ======================================================================
def _requests():
    try:
        import requests
        return requests
    except ImportError:
        sys.exit("This script needs `requests`:  pip install requests")


def get_token(force=False):
    if _token["value"] and not force:
        return _token["value"]
    cid = os.environ.get("ZOHO_CLIENT_ID")
    secret = os.environ.get("ZOHO_CLIENT_SECRET")
    refresh = os.environ.get("ZOHO_REFRESH_TOKEN")
    if not (cid and secret and refresh):
        sys.exit("Missing ZOHO_CLIENT_ID / ZOHO_CLIENT_SECRET / "
                 "ZOHO_REFRESH_TOKEN env vars.")
    requests = _requests()
    # creds in the POST BODY (data=), NOT the query string — so they never
    # appear in a URL and cannot leak via an HTTPError/exception message.
    r = requests.post(ACCOUNTS_DOMAIN + "/oauth/v2/token", data={
        "refresh_token": refresh, "client_id": cid, "client_secret": secret,
        "grant_type": "refresh_token"}, timeout=30)
    # Surface the Zoho error BODY (Zoho's reply, no creds) rather than
    # raise_for_status (whose message includes the URL). Helps tell apart a
    # rate-limit / invalid-grant / scope problem.
    if r.status_code != 200:
        sys.exit("Token request HTTP %s: %s" % (r.status_code, (r.text or "")[:200]))
    data = r.json()
    if not data.get("access_token"):
        sys.exit("Token refresh failed: %s" % data)
    _token["value"] = data["access_token"]
    return _token["value"]


def api_get(path, params=None):
    requests = _requests()
    p = dict(params or {})
    p["organization_id"] = ORG_ID
    url = API_DOMAIN + path
    refreshed = False
    for attempt in range(6):
        headers = {"Authorization": "Zoho-oauthtoken " + get_token()}
        r = requests.get(url, params=p, headers=headers, timeout=60)
        if r.status_code == 401 and not refreshed:
            # refresh the access token ONCE — a persistent 401 is a scope/perm
            # problem, NOT token expiry, so do not storm the refresh endpoint
            # (that burns the refresh rate-limit).
            get_token(force=True)
            refreshed = True
            continue
        if r.status_code == 429:
            wait = min(60, 2 ** attempt)
            print("  rate-limited (429) — backing off %ds" % wait)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise RuntimeError("GET %s -> HTTP %s: %s"
                               % (path, r.status_code, (r.text or "")[:160]))
        return r.json()
    raise RuntimeError("Repeated failures on GET %s" % path)


def list_all(path, key, extra=None):
    page, out = 1, []
    while True:
        params = {"page": page, "per_page": 200}
        params.update(extra or {})
        data = api_get(path, params)
        out.extend(data.get(key, []))
        if LIMIT and len(out) >= LIMIT:
            return out[:LIMIT]
        ctx = data.get("page_context") or {}
        if not ctx.get("has_more_page"):
            return out
        page += 1
        time.sleep(THROTTLE)


def export_customers():
    print("Listing customers ...")
    lst = list_all("/books/v3/contacts", "contacts", {"contact_type": "customer"})
    print("  %d customers; fetching details ..." % len(lst))
    out = []
    for i, c in enumerate(lst, 1):
        detail = api_get("/books/v3/contacts/%s" % c.get("contact_id"))
        out.append(map_customer(detail.get("contact", {})))
        if i % 50 == 0 or i == len(lst):
            print("  customers %d/%d" % (i, len(lst)))
        time.sleep(THROTTLE)
    return out


def export_estimates(inv_map):
    print("Listing estimates ...")
    lst = list_all("/books/v3/estimates", "estimates")
    print("  %d estimates; fetching details ..." % len(lst))
    out = []
    for i, e in enumerate(lst, 1):
        detail = api_get("/books/v3/estimates/%s" % e.get("estimate_id"))
        out.append(map_estimate(detail.get("estimate", {}), inv_map))
        if i % 100 == 0 or i == len(lst):
            print("  estimates %d/%d" % (i, len(lst)))
        time.sleep(THROTTLE)
    return out


def export_invoices(est_id_to_number):
    print("Listing invoices ...")
    lst = list_all("/books/v3/invoices", "invoices")
    print("  %d invoices; fetching details (estimate_id + line_items) ..."
          % len(lst))
    out = []
    for i, inv in enumerate(lst, 1):
        detail = api_get("/books/v3/invoices/%s" % inv.get("invoice_id"))
        out.append(map_invoice(detail.get("invoice", {}), est_id_to_number))
        if i % 100 == 0 or i == len(lst):
            print("  invoices %d/%d" % (i, len(lst)))
        time.sleep(THROTTLE)
    return out


def export_expenses():
    print("Listing expenses ...")
    lst = list_all("/books/v3/expenses", "expenses")
    print("  %d expenses; fetching details ..." % len(lst))
    out = []
    for i, exp in enumerate(lst, 1):
        detail = api_get("/books/v3/expenses/%s" % exp.get("expense_id"))
        out.append(map_expense(detail.get("expense", {})))
        if i % 100 == 0 or i == len(lst):
            print("  expenses %d/%d" % (i, len(lst)))
        time.sleep(THROTTLE)
    return out


def _write(name, data):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    print("  wrote %s (%d records)" % (path, len(data)))


def _self_check(customers, estimates):
    print("\n" + "=" * 60)
    print("SELF-CHECK (vs the assistant baseline)")
    cur = {}
    for e in estimates:
        c = (e.get("currency_code") or "").upper()
        cur[c] = cur.get(c, 0) + 1
    won = sum(1 for e in estimates if e.get("zoho_invoice_number"))

    def line(label, actual, expect, tol):
        ok = abs(actual - expect) <= tol
        print("  [%s] %-22s actual=%s  expect~%s"
              % ("PASS" if ok else "WARN", label, actual, expect))

    line("customers", len(customers), 895, 60)
    line("estimates", len(estimates), 2019, 60)
    line("won (invoice link)", won, 257, 40)
    print("  currency mix: %s  (expect ~USD 1938 / ZWG 61 / ZAR 1)"
          % ", ".join("%s=%d" % kv for kv in sorted(cur.items())))
    if LIMIT:
        print("  NB: ZOHO_LIMIT=%d in effect — counts are a SMOKE subset, not "
              "the full pull." % LIMIT)
    print("=" * 60)


def _self_check_finance(invoices, expenses):
    print("\n" + "=" * 60)
    print("SELF-CHECK — FINANCE (invoices + expenses)")
    cur = {}
    for r in invoices + expenses:
        c = (r.get("currency_code") or "").upper()
        cur[c] = cur.get(c, 0) + 1
    won = sum(1 for inv in invoices if inv.get("zoho_estimate_number"))
    billable = sum(1 for e in expenses if e.get("is_billable"))
    print("  invoices: %d (with estimate link: %d)" % (len(invoices), won))
    print("  expenses: %d (billable: %d)" % (len(expenses), billable))
    print("  currency mix: %s" % ", ".join(
        "%s=%d" % kv for kv in sorted(cur.items())))
    if LIMIT:
        print("  NB: ZOHO_LIMIT=%d in effect — SMOKE subset, not the full pull."
              % LIMIT)
    print("=" * 60)


def main():
    finance = os.environ.get("ZOHO_FINANCE") == "1"
    print("Zoho export — org %s, api %s%s%s" % (
        ORG_ID, API_DOMAIN, " [FINANCE]" if finance else "",
        (" (LIMIT=%d smoke)" % LIMIT) if LIMIT else ""))
    get_token()
    print("auth OK")

    if finance:
        # invoices + expenses (Option A reference-only). The won-link needs the
        # estimates LIST (id->number) to resolve invoice.estimate_id. That is
        # OPTIONAL: a finance self-client scoped to invoices+expenses only will
        # be DENIED estimates.READ, so degrade to an empty map rather than abort
        # — invoices + expenses still extract; the won-link just won't populate
        # (add ZohoBooks.estimates.READ to the self-client to enable it).
        print("Listing estimates (id->number map for the won-link; OPTIONAL) ...")
        est_id_to_number = {}
        try:
            est_list = list_all("/books/v3/estimates", "estimates")
            est_id_to_number = {
                str(e.get("estimate_id")): e.get("estimate_number")
                for e in est_list if e.get("estimate_id")}
        except (SystemExit, Exception) as _e:  # noqa: BLE001
            # NEVER interpolate the exception (it can carry a URL/creds) — print
            # only the class name.
            print("  WARN: estimates list unavailable (%s) — won-link map EMPTY "
                  "(add ZohoBooks.estimates.READ to enable); invoices + expenses "
                  "proceed." % type(_e).__name__)
        invoices = export_invoices(est_id_to_number)
        expenses = export_expenses()
        _write("zoho_invoices.json", invoices)
        _write("zoho_expenses.json", expenses)
        _self_check_finance(invoices, expenses)
        print("\nDone. Next: bash scripts/run_zoho_finance_import.sh  (dry-run)")
        return

    invoices = list_all("/books/v3/invoices", "invoices")
    inv_map = build_invoice_map(invoices)
    print("invoices: %d, with estimate link: %d" % (len(invoices), len(inv_map)))
    customers = export_customers()
    estimates = export_estimates(inv_map)
    _write("zoho_customers.json", customers)
    _write("zoho_estimates.json", estimates)
    _self_check(customers, estimates)
    print("\nDone. Next: bash scripts/run_zoho_import.sh   (stage + dry-run)")


if __name__ == "__main__":
    main()
