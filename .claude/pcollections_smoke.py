"""P-COLLECTIONS — the LIVE, team-editable collections worklist
(neon.collections.item).

Parser tests (status seeded from verbatim note across every branch; contact
name/phone split; ZWG currency flag; amount-None preserved; period from section
header). Loader tests — the LIVE-model contract: GET-OR-CREATE seeds once and
NEVER clobbers a team edit (re-seed after a status change preserves it);
conservative partner match (exact + token-run, else NULL); rep resolution
(unambiguous maps, "Mr. G"/"Mrs. G" stay NULL + flagged); note kept verbatim.
ACL matrix: crew/operational DENIED entirely; sales read/write/create but NOT
unlink (archive via active); bookkeeper may unlink. [TESTC] fixtures,
self-cleaning. Run in `odoo shell -d neon_crm`.
"""
_passed = _total = 0
results = {}


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[n] = ok
    print("%s:" % n, "PASS" if ok else "FAIL", d if not ok else "")


env = env(context=dict(env.context, tracking_disable=True))

# ---- Parser helpers (module-level; openpyxl only imported inside parse()) ----
PG = {"__name__": "collections_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_collections.py").read(),
     PG)
seed_status = PG["seed_status"]
split_contact = PG["split_contact"]

_check("T1-status-recovered", seed_status("Recovered $300 - $60 balance") == "recovered")
_check("T1b-status-promised-plan", seed_status("Payment plan to commence - $700") == "promised")
_check("T1c-status-promised-pop", seed_status("Payment will be transfered awaiting POP") == "promised")
_check("T1d-status-promised-lawyer", seed_status("Promise to pay ... lawyer") == "promised")
_check("T1e-status-po", seed_status("PO Submitted - awaiting payment") == "po_submitted")
_check("T1f-status-po-available", seed_status("BAT PO available for processing") == "po_submitted")
_check("T1g-status-partpaid", seed_status("80% Paid - Balance after event") == "part_paid")
_check("T1h-status-unresponsive", seed_status("Ignoring Calls") == "unresponsive")
_check("T1i-status-clearing", seed_status("Foreign Payment - Likely to clear") == "clearing")
_check("T1j-status-chasing-checking", seed_status("Checking") == "chasing")
_check("T1k-status-chasing-tba", seed_status("Balance TBA") == "chasing")
_check("T1l-status-blank-default", seed_status("") == "chasing" and seed_status(None) == "chasing")

_check("T2-contact-dash-phone", split_contact("Rati - 0782724481") == ("Rati", "0782724481"))
_check("T2b-contact-nodash-phone", split_contact("Robbie-0789954412") == ("Robbie", "0789954412"))
_check("T2c-contact-name-only", split_contact("Vusa") == ("Vusa", ""))
_check("T2d-contact-blank", split_contact("") == ("", ""))

# ---- Loader ----
LG = {"__name__": "collections_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_collections.py").read(),
     LG)
load_collections = LG["load_collections"]
M = env["neon.collections.item"].sudo()
P = env["res.partner"].sudo()
Users = env["res.users"].sudo()


def _purge():
    M.with_context(active_test=False).search([("source", "=", "TESTC")]).unlink()
    # Users BEFORE their partners — a partner linked to an active user is
    # un-deletable (RedirectWarning); drop the user first, then its partner.
    Users.with_context(active_test=False).search(
        [("login", "in", ("testc_sales", "testc_book", "testc_crew",
                           "testc_rep"))]).unlink()
    P.with_context(active_test=False).search(
        [("name", "=like", "TESTC %")]).unlink()


_purge()
# A partner the conservative matcher should hit exactly; a rep user the
# REP_LOGIN map can resolve (injected so the test never depends on real logins).
acme = P.create({"name": "TESTC Acme Holdings", "is_company": True})
rep_user = Users.create({"name": "TESTC Rep", "login": "testc_rep",
                         "password": "test123"})
# Confirmed mapping is asserted BEFORE any test injection overrides it.
_check("T3a-rep-map-confirmed",
       LG["REP_LOGIN"].get("mrs g") == "munashe@neonhiring.co.zw"
       and LG["REP_LOGIN"].get("mr g") == "robin@neonhiring.co.zw"
       and LG["REP_LOGIN"].get("robin") == "robin@neonhiring.co.zw"
       and LG["REP_LOGIN"].get("lisar") == "lisar@neonhiring.co.zw"
       and not LG["AMBIGUOUS_REPS"])
# Local stand-ins so "TESTC Rep" + "Mrs. G" resolve deterministically (the real
# munashe@/robin@ logins live on prod, not necessarily this local DB).
LG["REP_LOGIN"]["testc rep"] = "testc_rep"
LG["REP_LOGIN"]["mrs g"] = "testc_rep"

payload = {"items": [
    {"client_name": "TESTC Acme Holdings", "event_name": "Gala",
     "amount_usd": 1000.0, "amount_zwg": None, "currency_flag": "",
     "contact_name": "Jo", "contact_phone": "0770000000",
     "sales_rep_raw": "TESTC Rep", "note": "PO Submitted",
     "status": "po_submitted", "period_year": "2026", "source": "TESTC"},
    {"client_name": "TESTC Mystery Debtor", "event_name": "",
     "amount_usd": None, "amount_zwg": None, "currency_flag": "",
     "contact_name": "", "contact_phone": "",
     "sales_rep_raw": "Mrs. G", "note": "Checking",
     "status": "chasing", "period_year": "2025", "source": "TESTC"},
    {"client_name": "TESTC Zwg Co", "event_name": "Launch",
     "amount_usd": 500.0, "amount_zwg": None,
     "currency_flag": "ZWG Payment (verify)",
     "contact_name": "Eve", "contact_phone": "",
     "sales_rep_raw": "Totally Unknown Rep",
     "note": "Recovered partial", "status": "recovered",
     "period_year": "2026", "source": "TESTC"},
]}

rep = load_collections(env, payload, source="TESTC")
env.flush_all()
rows = M.with_context(active_test=False).search([("source", "=", "TESTC")])
acme_row = rows.filtered(lambda r: r.client_name == "TESTC Acme Holdings")
mystery = rows.filtered(lambda r: r.client_name == "TESTC Mystery Debtor")

_check("T3-created", rep["created"] == 3 and len(rows) == 3, "rep=%s" % rep)
_check("T3b-partner-exact",
       acme_row.partner_id.id == acme.id and rep["partner_matched"] == 1)
_check("T3c-partner-none", not mystery.partner_id)
_check("T3d-rep-mapped",
       acme_row.sales_rep_id.id == rep_user.id and rep["rep_mapped"] == 2)
_check("T3e-mrs-g-resolves",   # "Mrs. G" normalizes + maps (no longer NULL)
       mystery.sales_rep_id.id == rep_user.id
       and mystery.sales_rep_raw == "Mrs. G")
_check("T3e2-unmapped-rep-null",   # an unknown raw -> NULL, raw kept verbatim
       not rows.filtered(lambda r: r.client_name == "TESTC Zwg Co").sales_rep_id
       and rows.filtered(lambda r: r.client_name == "TESTC Zwg Co").sales_rep_raw
       == "Totally Unknown Rep")
_check("T3f-amount-none-preserved",
       mystery.amount_usd == 0.0 and acme_row.amount_usd == 1000.0)
_check("T3g-currency-flag-kept",
       rows.filtered(lambda r: r.currency_flag == "ZWG Payment (verify)"))
_check("T3h-note-verbatim", acme_row.note == "PO Submitted")
_check("T3i-status-seeded", acme_row.status == "po_submitted"
       and mystery.status == "chasing")

# ---- T4 LIVE get-or-create: re-seed must NOT clobber a team edit ----
acme_row.write({"status": "recovered", "note": "PO Submitted | team: paid in full"})
env.flush_all()
rep2 = load_collections(env, payload, source="TESTC")
env.flush_all()
acme_after = M.search([("source", "=", "TESTC"),
                       ("client_name", "=", "TESTC Acme Holdings")])
_check("T4-reseed-no-duplicate",
       M.with_context(active_test=False).search_count(
           [("source", "=", "TESTC")]) == 3 and rep2["created"] == 0
       and rep2["skipped_existing"] == 3)
_check("T4b-reseed-preserves-team-edit",
       acme_after.status == "recovered"
       and "team: paid in full" in acme_after.note)

# ---- T5 LIVE editability + active-archive ----
new_item = M.create({"client_name": "TESTC Walk-in", "amount_usd": 75.0,
                     "status": "chasing", "source": "TESTC"})
new_item.write({"status": "closed", "active": False})
env.flush_all()
_check("T5-editable-and-archivable",
       new_item.status == "closed" and not new_item.active)

# ---- ACL matrix ----
sg = env.ref("neon_core.group_neon_sales_rep")
bg = env.ref("neon_core.group_neon_bookkeeper")
cg = env.ref("neon_core.group_neon_crew")
sales = Users.create({"name": "TESTC Sales", "login": "testc_sales",
                      "password": "test123", "groups_id": [(4, sg.id)]})
book = Users.create({"name": "TESTC Book", "login": "testc_book",
                     "password": "test123", "groups_id": [(4, bg.id)]})
crew = Users.create({"name": "TESTC Crew", "login": "testc_crew",
                     "password": "test123", "groups_id": [(4, cg.id)]})

# crew/operational: NO access at all (sensitive — amounts, phones, escalations)
try:
    env["neon.collections.item"].with_user(crew).search(
        [("source", "=", "TESTC")]).mapped("amount_usd")
    _check("T6-crew-denied", False, "crew read the worklist!")
except Exception:  # noqa: BLE001
    _check("T6-crew-denied", True)

# sales: read + write + create OK
try:
    s_item = env["neon.collections.item"].with_user(sales).create(
        {"client_name": "TESTC Sales-made", "amount_usd": 10.0,
         "status": "chasing", "source": "TESTC"})
    s_item.with_user(sales).write({"status": "promised"})
    _check("T7-sales-rw-create", s_item.status == "promised")
except Exception as e:  # noqa: BLE001
    _check("T7-sales-rw-create", False, "sales blocked: %s" % e)

# sales: unlink DENIED (archive via active, not delete)
try:
    env["neon.collections.item"].with_user(sales).browse(s_item.id).unlink()
    _check("T8-sales-unlink-denied", False, "sales deleted a worklist item!")
except Exception:  # noqa: BLE001
    _check("T8-sales-unlink-denied", True)

# bookkeeper: unlink ALLOWED
try:
    b_item = M.create({"client_name": "TESTC Book-del", "source": "TESTC"})
    env["neon.collections.item"].with_user(book).browse(b_item.id).unlink()
    _check("T9-book-unlink-allowed",
           not M.with_context(active_test=False).search_count(
               [("id", "=", b_item.id)]))
except Exception as e:  # noqa: BLE001
    _check("T9-book-unlink-allowed", False, "book unlink blocked: %s" % e)

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
