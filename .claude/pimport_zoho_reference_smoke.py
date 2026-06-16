"""P-IMPORT — Zoho reference import (neon_migration). Exercises the REAL import
service (neon.zoho.importer.run) against the REAL models with [TEST-ZIMP]
fixtures. Asserts: dry-run zero-writes, APPLY creates, idempotent re-run, status
buckets, salesperson mapping, partner dedupe (match/create/flag), currency char
incl. ZAR, line fidelity, partner link, and INERTNESS (live neon.finance.quote
count + QUO sequence untouched). Run in `odoo shell -d neon_crm`. Self-cleaning.
"""
_passed = 0
_total = 0
results = {}


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[n] = ok
    print("%s:" % n, "PASS" if ok else "FAIL", d if not ok else "")


env = env(context=dict(env.context, tracking_disable=True,
                       mail_create_nosubscribe=True,
                       mail_notify_force_send=False))
P = env["res.partner"].sudo()
A = env["neon.finance.quote.archive"].sudo()
AL = env["neon.finance.quote.archive.line"].sudo()
IMP = env["neon.zoho.importer"].sudo()
Seq = env["ir.sequence"].sudo()
Q = env["neon.finance.quote"].sudo()
AM = env["account.move"].sudo()

TAG = "[TEST-ZIMP]"
_INV_DOMAIN = [("move_type", "in", ("out_invoice", "out_refund"))]


def _purge():
    A.with_context(active_test=False).search(
        [("zoho_estimate_number", "=like", "TESTQT-%")]).unlink()
    parts = P.with_context(active_test=False).search(
        ["|", ("zoho_source_id", "=like", "TESTZ-%"),
         ("name", "=like", TAG + "%")])
    # children first
    parts.filtered(lambda p: p.parent_id).unlink()
    parts.exists().unlink()


_purge()

# ---- baseline: prove inertness later ----
LIVE_Q_BEFORE = Q.search_count([])
_seq_usd = Seq.search([("code", "=", "neon.finance.quote.usd")], limit=1)
SEQ_USD_BEFORE = _seq_usd.number_next_actual if _seq_usd else -1
INV_BEFORE = AM.search_count(_INV_DOMAIN)   # ledger invariant (must not move)

# ---- fixtures: an existing partner to match on zoho_source_id, and one to
#      fuzzy-match on email ----
p_exist = P.create({"name": TAG + " Existing Co", "zoho_source_id": "TESTZ-EXIST",
                    "email": "zimp-exist@test", "company_type": "company"})
p_fuzzy = P.create({"name": TAG + " Goldridge", "email": "zimp-gold@test",
                    "company_type": "company"})

# ============================================================ sample payloads
CUSTOMERS = [
    {"zoho_source_id": "TESTZ-EXIST", "name": TAG + " Existing Co",
     "email": "zimp-exist@test"},                                 # -> match (id)
    {"zoho_source_id": "", "name": TAG + " Goldridge",
     "email": "zimp-gold@test"},                                  # -> match (email)
    {"zoho_source_id": "TESTZ-NEW", "name": TAG + " Brand New Pvt Ltd",
     "company_type": "company", "email": "zimp-new@test",
     "phone": "+263772111222",
     "billing": {"street": "5 Stand Rd", "city": "Harare"},
     "contacts": [{"name": TAG + " Jane", "email": "zimp-jane@test",
                   "primary": True}]},                            # -> create
    {"zoho_source_id": "TESTZ-AMB", "name": TAG + " Goldridge",
     "email": "zimp-other@test"},                                 # -> create_flag
]
ESTIMATES = [
    {"zoho_estimate_number": "TESTQT-001",
     "zoho_customer_source_id": "TESTZ-NEW", "quotation_date": "2025-03-08",
     "zoho_status": "invoiced", "currency_code": "USD",
     "salesperson_name": "lisar", "event_summary": "AGM 8 Mar",
     "zoho_invoice_number": "INV-000327",
     "amount_untaxed": 120.0, "amount_tax": 18.6, "amount_total": 138.6,
     "lines": [{"name": "RGB LED CAN", "description": "indoor",
                "unit": "qty", "quantity": 8, "unit_rate": 15.0,
                "line_total": 120.0, "zoho_item_id": "Z1",
                "category_prefix": "LIGHTING"}]},
    {"zoho_estimate_number": "TESTQT-002",
     "zoho_customer_source_id": "TESTZ-NEW", "zoho_status": "approved",
     "currency_code": "ZWG", "salesperson_name": "Hamu Mutasa",
     "amount_total": 500.0, "lines": []},
    {"zoho_estimate_number": "TESTQT-003",
     "zoho_customer_source_id": "TESTZ-EXIST", "zoho_status": "sent",
     "currency_code": "ZAR", "salesperson_name": "arnold",
     "amount_total": 90.0, "lines": []},
    {"zoho_estimate_number": "TESTQT-004",
     "zoho_customer_source_id": "TESTZ-MISSING", "zoho_status": "declined",
     "currency_code": "USD", "salesperson_name": "",
     "amount_total": 0.0, "lines": []},
    {"zoho_estimate_number": "TESTQT-005",
     "zoho_customer_source_id": "TESTZ-NEW", "zoho_status": "weird_status",
     "currency_code": "USD", "amount_total": 10.0, "lines": []},
]

# ============================================================ T1 dry-run zero writes
a_before = A.search_count([])
p_before = P.search_count([])
rep = IMP.run(CUSTOMERS, ESTIMATES, apply=False)
_check("T1-dryrun-zero-writes",
       A.search_count([]) == a_before and P.search_count([]) == p_before,
       "archives/partners changed in dry-run")
_check("T1b-dryrun-counts",
       rep["partners"] == {"matched": 2, "created": 2, "flagged_review": 1,
                           "enriched": 0}
       and rep["quotes"]["created"] == 4              # TESTQT-004 cust absent -> skip
       and rep["quotes"]["skipped_unmatched_customer"] == 1
       and rep["quotes"]["skipped_existing"] == 0
       and "TESTQT-004" in rep["unmatched_customers"],
       "partners=%s quotes=%s unmatched=%s"
       % (rep["partners"], rep["quotes"], rep["unmatched_customers"]))
_check("T1c-dryrun-buckets",
       rep["quotes"]["won"] == 1 and rep["quotes"]["historical"] == 2
       and rep["quotes"]["open"] == 1 and rep["quotes"]["lost"] == 1,
       "buckets=%s" % rep["quotes"])

# ============================================================ T2 APPLY creates
rep2 = IMP.run(CUSTOMERS, ESTIMATES, apply=True)
env.cr.commit()
_check("T2-apply-archives-created", A.search_count([]) == a_before + 4,
       "got %d want %d" % (A.search_count([]), a_before + 4))
_check("T2b-apply-partners-created",
       rep2["partners"]["created"] == 2 and rep2["partners"]["matched"] == 2,
       "partners=%s" % rep2["partners"])

# ============================================================ T3 idempotent re-run
rep3 = IMP.run(CUSTOMERS, ESTIMATES, apply=True)
env.cr.commit()
_check("T3-idempotent-no-new-quotes",
       rep3["quotes"]["created"] == 0 and rep3["quotes"]["skipped_existing"] == 4
       and rep3["quotes"]["skipped_unmatched_customer"] == 1
       and A.search_count([("zoho_estimate_number", "=like", "TESTQT-%")]) == 4,
       "created=%d skipped=%d unmatched=%d total=%d" % (
           rep3["quotes"]["created"], rep3["quotes"]["skipped_existing"],
           rep3["quotes"]["skipped_unmatched_customer"],
           A.search_count([("zoho_estimate_number", "=like", "TESTQT-%")])))
_check("T3b-idempotent-no-new-partners", rep3["partners"]["created"] == 0,
       "created=%d" % rep3["partners"]["created"])

# ============================================================ T4 status buckets
q1 = A.search([("zoho_estimate_number", "=", "TESTQT-001")], limit=1)
q2 = A.search([("zoho_estimate_number", "=", "TESTQT-002")], limit=1)
q3 = A.search([("zoho_estimate_number", "=", "TESTQT-003")], limit=1)
q4 = A.search([("zoho_estimate_number", "=", "TESTQT-004")], limit=1)
q5 = A.search([("zoho_estimate_number", "=", "TESTQT-005")], limit=1)
_check("T4-status-map",
       q1.status_bucket == "won" and q2.status_bucket == "historical"
       and q3.status_bucket == "open" and q5.status_bucket == "historical"
       and not q4,                       # TESTQT-004 skipped (customer absent)
       "%s/%s/%s/q4=%s/%s" % (q1.status_bucket, q2.status_bucket,
                              q3.status_bucket, bool(q4), q5.status_bucket))
_check("T4b-unknown-status-flagged", "weird_status" in rep2["unknown_status"],
       "unknown=%s" % rep2["unknown_status"])

# ============================================================ T4c self-healing
# Add the previously-absent customer + re-run: TESTQT-004 now imports LINKED
# (never permanently dropped/unlinked).
CUSTOMERS_HEAL = CUSTOMERS + [
    {"zoho_source_id": "TESTZ-MISSING", "name": TAG + " Found Later",
     "email": "zimp-found@test"}]
rep_heal = IMP.run(CUSTOMERS_HEAL, ESTIMATES, apply=True)
env.cr.commit()
q4b = A.search([("zoho_estimate_number", "=", "TESTQT-004")], limit=1)
found_p = P.search([("zoho_source_id", "=", "TESTZ-MISSING")], limit=1)
_check("T4c-unmatched-customer-self-heals-on-rerun",
       bool(q4b) and bool(found_p) and q4b.partner_id == found_p
       and q4b.status_bucket == "lost" and rep_heal["quotes"]["created"] == 1
       and rep_heal["quotes"]["skipped_unmatched_customer"] == 0,
       "q4=%s partner=%s created=%s" % (
           bool(q4b), q4b.partner_id.id if q4b else None,
           rep_heal["quotes"]["created"]))

# ============================================================ T5 salesperson map
lisa = env["res.users"].sudo().search(
    ["|", ("name", "ilike", "Lisa"), ("login", "ilike", "lisa")], limit=1)
_check("T5-lisar-maps-to-user",
       bool(q1.salesperson_id) and (q1.salesperson_id == lisa if lisa else True)
       and q1.salesperson_name == "lisar",
       "sp_id=%s name=%s" % (q1.salesperson_id, q1.salesperson_name))
_check("T5b-former-rep-freetext-no-user",
       not q2.salesperson_id and q2.salesperson_name == "Hamu Mutasa"
       and not q3.salesperson_id and q3.salesperson_name == "arnold",
       "q2=%s/%s q3=%s/%s" % (q2.salesperson_id, q2.salesperson_name,
                              q3.salesperson_id, q3.salesperson_name))
_check("T5c-arnold-NOT-merged-to-crew",
       "arnold" in rep2["unmatched_salespeople"]
       and "Hamu Mutasa" in rep2["unmatched_salespeople"],
       "unmatched=%s" % rep2["unmatched_salespeople"])

# ============================================================ T6 partner dedupe
new_p = P.search([("zoho_source_id", "=", "TESTZ-NEW")], limit=1)
amb_p = P.search([("zoho_source_id", "=", "TESTZ-AMB")], limit=1)
_check("T6-create-new-not-flagged",
       bool(new_p) and not new_p.zoho_dedup_review
       and new_p.child_ids and new_p.street == "5 Stand Rd",
       "new=%s review=%s kids=%d" % (
           bool(new_p), new_p.zoho_dedup_review if new_p else None,
           len(new_p.child_ids) if new_p else 0))
_check("T6b-ambiguous-created-and-flagged",
       bool(amb_p) and amb_p.zoho_dedup_review,
       "amb=%s review=%s" % (bool(amb_p), amb_p.zoho_dedup_review if amb_p else None))
_check("T6c-match-by-zoho-id-no-dup",
       P.search_count([("zoho_source_id", "=", "TESTZ-EXIST")]) == 1,
       "p_exist not uniquely matched")
_check("T6d-match-by-email-no-dup",
       P.search_count([("name", "=", TAG + " Goldridge"),
                       ("email", "=", "zimp-gold@test")]) == 1,
       "fuzzy email match created a dup")

# ============================================================ T7 currency char incl ZAR
_check("T7-currency-char-incl-ZAR",
       q3.currency_code == "ZAR" and q2.currency_code == "ZWG"
       and q1.currency_code == "USD" and abs(q1.amount_total - 138.6) < 0.01,
       "%s/%s/%s tot=%s" % (q3.currency_code, q2.currency_code,
                            q1.currency_code, q1.amount_total))

# ============================================================ T8 line fidelity
ln = q1.line_ids[:1]
_check("T8-line-fidelity",
       len(q1.line_ids) == 1 and ln.name == "RGB LED CAN"
       and abs(ln.quantity - 8) < 0.01 and abs(ln.unit_rate - 15.0) < 0.01
       and abs(ln.line_total - 120.0) < 0.01 and ln.category_prefix == "LIGHTING"
       and ln.unit == "qty" and ln.zoho_item_id == "Z1",
       "line=%r" % (ln.read()[0] if ln else None))

# ============================================================ T9 partner link + won fields
_check("T9-partner-link-count",
       q1.partner_id == new_p and new_p.archived_quote_count >= 1,
       "partner=%s count=%s" % (q1.partner_id, new_p.archived_quote_count))
act = new_p.action_view_archived_quotes()
_check("T9b-view-action-domain",
       act.get("res_model") == "neon.finance.quote.archive"
       and ("partner_id", "=", new_p.id) in act.get("domain", []),
       "act=%s" % act)
_check("T9c-won-stores-invoice+event",
       q1.zoho_invoice_number == "INV-000327" and q1.event_summary == "AGM 8 Mar",
       "inv=%s evt=%s" % (q1.zoho_invoice_number, q1.event_summary))

# ============================================================ T10 INERTNESS
_seq_usd2 = Seq.search([("code", "=", "neon.finance.quote.usd")], limit=1)
SEQ_USD_AFTER = _seq_usd2.number_next_actual if _seq_usd2 else -1
_check("T10-live-quote-count-untouched", Q.search_count([]) == LIVE_Q_BEFORE,
       "live quote count moved %d -> %d" % (LIVE_Q_BEFORE, Q.search_count([])))
_check("T10b-QUO-sequence-untouched", SEQ_USD_AFTER == SEQ_USD_BEFORE,
       "QUO-USD seq moved %s -> %s" % (SEQ_USD_BEFORE, SEQ_USD_AFTER))
_check("T10c-ledger-invoices-untouched",
       AM.search_count(_INV_DOMAIN) == INV_BEFORE,
       "customer invoice count moved %d -> %d (import must create NO account.move)"
       % (INV_BEFORE, AM.search_count(_INV_DOMAIN)))

# ============================================================ T11 email-match name-agreement guard
from odoo.addons.neon_migration.models.zoho_import import _names_agree  # noqa: E402
# fixture keyed on zoho_source_id (so _purge cleans it); name tokens chosen so
# the "different" case shares NO tokens (avoids the [TEST-ZIMP] prefix polluting
# the overlap ratio).
p_shared = P.create({"name": "Zqx Alpha Events Co", "email": "zimp-guard@test",
                     "zoho_source_id": "TESTZ-GUARD", "company_type": "company"})
act_v, par_v = IMP._classify_partner(
    {"email": "zimp-guard@test", "name": "Zqx Alpha Events"})        # variant
act_d, par_d = IMP._classify_partner(
    {"email": "zimp-guard@test", "name": "Mediterranean Catering Group"})  # different
_check("T11-email+variant-name-still-merges",
       act_v == "match" and par_v == p_shared,
       "act=%s par=%s" % (act_v, par_v))
_check("T11b-email+different-name-FLAGS-not-silent-merge",
       act_d == "create_flag" and not par_d,
       "act=%s par=%s" % (act_d, par_d))
_check("T11c-names_agree-real-variants-merge-distinct-flag",
       _names_agree("Imani Consultants", "Imani Consulting")
       and _names_agree("The Institute of Bankers of Zimbabwe",
                        "Institute of Bankers of Zimbabwe")
       and _names_agree("The National Chamber of Commerce",
                        "The Zimbabwe National Chamber of Commerce")
       and not _names_agree("Alpha Events", "Zeta Productions"),
       "agreement logic off")

# ---- teardown ----
_purge()
env.cr.commit()
print("=" * 64)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 64)
