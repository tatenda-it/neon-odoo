"""P-EXPORT — Zoho extractor MAPPING contract test (host python, no Zoho/container).

Feeds Zoho-shaped sample payloads through the pure mappers in
scripts/export_zoho_to_json.py and asserts they emit EXACTLY the schema the
loader (neon.zoho.importer) consumes — closing the extractor<->loader contract
without live Zoho. Also guards: no balance/ledger leak, category_prefix split,
email fallback to the primary contact, won-invoice link.

Run on the host:  python .claude/pexport_zoho_mapping_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import export_zoho_to_json as ex  # noqa: E402

_passed = _total = 0


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    print("%s: %s %s" % (n, "PASS" if ok else "FAIL", "" if ok else d))


# The keys the LOADER (zoho_import.py) actually reads — the contract the mapper
# must satisfy. Mapper output must be a superset of each.
LOADER_CUSTOMER_KEYS = {"zoho_source_id", "name", "company_type", "email",
                        "phone", "billing", "contacts"}
LOADER_BILLING_KEYS = {"street", "city"}            # loader reads street + city
LOADER_CONTACT_KEYS = {"name", "email", "phone"}
LOADER_ESTIMATE_KEYS = {"zoho_estimate_number", "zoho_customer_source_id",
                        "quotation_date", "zoho_status", "currency_code",
                        "salesperson_name", "event_summary",
                        "zoho_invoice_number", "amount_untaxed", "amount_tax",
                        "amount_total", "lines"}
LOADER_LINE_KEYS = {"name", "description", "unit", "quantity", "unit_rate",
                    "line_total", "zoho_item_id", "category_prefix"}

_BALANCE_WORDS = ("balance", "receivable", "outstanding", "unused_credit")

# ---------------- customers ----------------
CUST_COMPANY = {
    "contact_id": 460000000123, "contact_name": "Goldridge Pvt Ltd",
    "company_name": "Goldridge Pvt Ltd", "customer_sub_type": "business",
    "email": "ops@goldridge.co.zw", "phone": "+263772000000",
    "outstanding_receivable_amount": 5000.0,  # MUST NOT leak
    "billing_address": {"address": "5 Stand Rd", "street2": "Msasa",
                        "city": "Harare", "country": "Zimbabwe",
                        "attention": "Accounts"},
    "contact_persons": [
        {"first_name": "Jane", "last_name": "Moyo", "email": "jane@goldridge.co.zw",
         "mobile": "+263773000000", "is_primary_contact": True}],
}
c = ex.map_customer(CUST_COMPANY)
_check("T1-customer-keys", set(c) >= LOADER_CUSTOMER_KEYS,
       "keys=%s" % set(c))
_check("T1b-billing+contact-keys",
       set(c["billing"]) >= LOADER_BILLING_KEYS
       and set(c["contacts"][0]) >= LOADER_CONTACT_KEYS,
       "billing=%s contact=%s" % (set(c["billing"]), set(c["contacts"][0])))
_check("T1c-company-mapped",
       c["zoho_source_id"] == "460000000123" and c["company_type"] == "company"
       and c["billing"]["street"] == "5 Stand Rd Msasa"
       and c["billing"]["city"] == "Harare"
       and c["contacts"][0]["name"] == "Jane Moyo"
       and c["contacts"][0]["primary"] is True,
       "c=%s" % c)
_check("T1d-NO-balance-leak",
       not any(w in k.lower() for k in c for w in _BALANCE_WORDS),
       "leaked balance key: %s" % set(c))

CUST_INDIV = {
    "contact_id": 99, "contact_name": "Tariro (Wedding)",
    "customer_sub_type": "individual", "email": "",
    "contact_persons": [
        {"first_name": "Tariro", "email": "tariro@gmail.com",
         "is_primary_contact": True}],
}
ci = ex.map_customer(CUST_INDIV)
_check("T2-individual+email-fallback",
       ci["company_type"] == "individual" and ci["email"] == "tariro@gmail.com",
       "ci=%s" % ci)

# ---------------- estimates ----------------
INV_MAP = ex.build_invoice_map([
    {"invoice_number": "INV-000327", "estimate_id": 7001},
    {"invoice_number": "INV-000400", "invoiced_estimate_id": 7002},
    {"invoice_number": "INV-NOEST"},  # no estimate link -> ignored
])
_check("T3-invoice-map",
       INV_MAP == {"7001": "INV-000327", "7002": "INV-000400"},
       "map=%s" % INV_MAP)

EST = {
    "estimate_id": 7001, "estimate_number": "QT-001234", "customer_id": 460000000123,
    "date": "2025-03-08", "status": "invoiced", "currency_code": "USD",
    "salesperson_name": "lisar", "subject_content": "Goldridge AGM — 8 Mar 2025",
    "sub_total": 1200.0, "tax_total": 186.0, "total": 1386.0,
    "line_items": [
        {"name": "LIGHTING EQUIPMENT - RGB LED CAN", "description": "indoor",
         "unit": "qty", "quantity": 8, "rate": 15.0, "item_total": 120.0,
         "item_id": 5001},
        {"name": "TRANSPORT", "quantity": 1, "rate": 50.0, "item_total": 50.0,
         "item_id": 5002}],
}
e = ex.map_estimate(EST, INV_MAP)
_check("T4-estimate-keys", set(e) >= LOADER_ESTIMATE_KEYS, "keys=%s" % set(e))
_check("T4b-line-keys", set(e["lines"][0]) >= LOADER_LINE_KEYS,
       "line=%s" % set(e["lines"][0]))
_check("T5-estimate-mapped",
       e["zoho_estimate_number"] == "QT-001234"
       and e["zoho_customer_source_id"] == "460000000123"
       and e["zoho_status"] == "invoiced" and e["currency_code"] == "USD"
       and e["zoho_invoice_number"] == "INV-000327"   # won-link via inv_map
       and abs(e["amount_total"] - 1386.0) < 0.01
       and e["event_summary"].startswith("Goldridge AGM"),
       "e=%s" % {k: e[k] for k in LOADER_ESTIMATE_KEYS if k != "lines"})
_check("T6-category-prefix-split",
       e["lines"][0]["category_prefix"] == "LIGHTING EQUIPMENT"   # split on ' - '
       and e["lines"][1]["category_prefix"] == "TRANSPORT"        # no ' - ' -> whole
       and e["lines"][0]["name"] == "LIGHTING EQUIPMENT - RGB LED CAN"
       and abs(e["lines"][0]["unit_rate"] - 15.0) < 0.01
       and abs(e["lines"][0]["line_total"] - 120.0) < 0.01
       and e["lines"][0]["zoho_item_id"] == "5001",
       "lines=%s" % e["lines"])
_check("T7-no-currency-constraint-passthrough",
       ex.map_estimate({"estimate_id": 1, "currency_code": "ZAR"},
                       {})["currency_code"] == "ZAR",
       "ZAR not passed through")

print("=" * 56)
print("Total: %d/%d passed" % (_passed, _total))
sys.exit(0 if _passed == _total else 1)
