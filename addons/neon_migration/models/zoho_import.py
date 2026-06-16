# -*- coding: utf-8 -*-
"""Zoho reference-import service (AbstractModel).

The import LOGIC lives here so the loader script (file reader) and the
pimport_* tests (fixture-driven) exercise the identical code path. Pure
get-or-create; gated by `apply` (dry-run computes the same classification
with ZERO writes, so a post-APPLY dry-run reports all-matched/zero-new).

INTERMEDIATE FILE SCHEMA (exported Zoho-side by Tatenda; the loader reads
two JSON files — Books API line-item level, never header-only CSV):

  customers: [ {
      "zoho_source_id": "460000000123",     # Books contact_id / CRM id (KEY)
      "name": "Goldridge Pvt Ltd",
      "company_type": "company" | "individual",
      "email": "ops@goldridge.co.zw",
      "phone": "+263772000000",
      "billing": {"street": "...", "city": "Harare",
                  "country": "Zimbabwe", "attention": "..."},
      "contacts": [ {"name": "Jane", "email": "...", "phone": "...",
                     "primary": true} ]
      # NB: NO balance / receivable — never import ledger figures.
  } ]

  estimates: [ {
      "zoho_estimate_number": "QT-001234",  # original Zoho number (KEY)
      "zoho_customer_source_id": "460000000123",
      "quotation_date": "2025-03-08",
      "zoho_status": "invoiced",            # raw Zoho status -> bucket
      "currency_code": "USD" | "ZWG" | "ZAR",
      "salesperson_name": "lisar",          # Zoho label
      "zoho_salesperson_id": "990000000045",
      "event_summary": "Goldridge AGM — 8 Mar 2025, 18:00",
      "zoho_invoice_number": "INV-000327",  # won rows (optional)
      "amount_untaxed": 1200.0, "amount_tax": 186.0, "amount_total": 1386.0,
      "lines": [ {"name": "RGB LED CAN", "description": "...",
                  "unit": "qty", "quantity": 8, "unit_rate": 15.0,
                  "line_total": 120.0, "zoho_item_id": "...",
                  "category_prefix": "LIGHTING"} ]
  } ]
"""
import re

from odoo import api, models

# Zoho status -> bucket. Unknown -> 'historical' (+ a warning), never guessed
# into won/lost.
STATUS_MAP = {
    "draft": "open",
    "sent": "open",
    "pending_approval": "open",
    "accepted": "open",
    "approved": "historical",
    "invoiced": "won",
    "declined": "lost",
    "rejected": "lost",
    "expired": "lost",
}

# Zoho salesperson label (lower) -> Odoo user search term. Former reps (Hamu
# Mutasa / Ruvimbo / Arnold) are deliberately ABSENT -> free-text only. NB:
# 'arnold' must NOT map to crew user "Arnold M" — different person.
SALES_MAP = {
    "lisar": "Lisa",
    "lisa": "Lisa",
    "evrill": "Evrill",
    "evy": "Evrill",
    "munashe": "Munashe",
    "munashe goneso": "Munashe",
    "robin": "Robin",
    "robin goneso": "Robin",
}

_SUFFIXES = (
    "pvt ltd", "pvt", "ltd", "limited", "private limited", "p l", "pl",
    "t/a", "ta", "inc", "incorporated", "co", "company", "(pvt) ltd",
)


def _norm_name(value):
    """Lower, strip punctuation, drop common company suffixes, collapse ws."""
    if not value:
        return ""
    s = re.sub(r"[^\w\s]", " ", value.lower())
    s = re.sub(r"\s+", " ", s).strip()
    for suf in sorted(_SUFFIXES, key=len, reverse=True):
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
    return s


def _norm_phone(value):
    return re.sub(r"\D", "", value or "")


def _names_agree(a, b):
    """Conservative name-agreement guard for an email-exact match. A shared
    email is a strong signal, so name VARIANTS still agree (a real org entered
    twice -- "Imani Consultants"/"Imani Consulting", "X"/"The X" -- which the
    Zoho import proved are true dupes). But a WHOLLY different name on the same
    email (a generic shared inbox like info@) is a likely over-merge -> do NOT
    silently collapse. Agree when one normalized name contains the other OR
    token overlap >= 0.5; lean to agree when either name is empty (email already
    matched, nothing to disprove)."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return True
    if na == nb or na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return True
    return len(ta & tb) / max(len(ta), len(tb)) >= 0.5


class ZohoImporter(models.AbstractModel):
    _name = "neon.zoho.importer"
    _description = "Zoho Reference Import Service"

    # ----- helpers -------------------------------------------------
    @api.model
    def _status_bucket(self, zoho_status):
        return STATUS_MAP.get((zoho_status or "").strip().lower(), "historical")

    @api.model
    def _resolve_salesperson(self, label):
        """(user_id|False, original_label). Maps current reps to a res.users;
        former reps / blanks -> (False, label)."""
        if not label:
            return False, False
        term = SALES_MAP.get(label.strip().lower())
        if not term:
            return False, label
        Users = self.env["res.users"].sudo()
        user = Users.search(
            ["|", ("name", "ilike", term), ("login", "ilike", term)], limit=1)
        return (user.id if user else False), label

    @api.model
    def _classify_partner(self, cust):
        """Return (action, partner) where action in
        match | create | create_flag. Idempotent on zoho_source_id; then a
        conservative fuzzy match; ambiguous -> create_flag (never wrong-merge).
        """
        Partner = self.env["res.partner"].sudo()
        zid = (cust.get("zoho_source_id") or "").strip()
        if zid:
            hit = Partner.search([("zoho_source_id", "=", zid)], limit=1)
            if hit:
                return "match", hit

        email = (cust.get("email") or "").strip().lower()
        phone_norm = _norm_phone(cust.get("phone"))
        name_norm = _norm_name(cust.get("name"))

        # Strongest signal: exact email -- but guard against a generic shared
        # inbox collapsing DISTINCT entities. Name variants still merge; a
        # wholly different name on the same email -> create_flag (not silent).
        if email:
            by_email = Partner.search([("email", "=ilike", email)])
            if len(by_email) == 1:
                if _names_agree(cust.get("name"), by_email.name):
                    return "match", by_email
                return "create_flag", None  # same email, disagreeing names
            if len(by_email) > 1:
                return "create_flag", None  # ambiguous duplicate email

        # Name match, corroborated by phone/email or clean uniqueness.
        if name_norm:
            candidates = Partner.search(
                [("name", "ilike", cust.get("name") or name_norm)])
            exact = candidates.filtered(
                lambda p: _norm_name(p.name) == name_norm)
            if len(exact) == 1:
                p = exact
                same_phone = phone_norm and _norm_phone(p.phone) == phone_norm
                same_email = email and (p.email or "").lower() == email
                if same_phone or same_email or (not phone_norm and not email):
                    return "match", p
                return "create_flag", None  # name matches but contacts differ
            if len(exact) > 1:
                return "create_flag", None  # several same-name partners

        return "create", None

    # ----- the run -------------------------------------------------
    @api.model
    def run(self, customers, estimates, apply=False):
        """Import customers (pass A) then estimates (pass B). Returns a report
        dict. apply=False => zero writes (counts only)."""
        Partner = self.env["res.partner"].sudo()
        Archive = self.env["neon.finance.quote.archive"].sudo()

        report = {
            "apply": bool(apply),
            "partners": {"matched": 0, "created": 0, "flagged_review": 0,
                         "enriched": 0},
            "quotes": {"created": 0, "skipped_existing": 0,
                       "skipped_unmatched_customer": 0, "no_customer_id": 0,
                       "open": 0, "historical": 0, "won": 0, "lost": 0},
            "currency": {},
            "unmatched_customers": [],
            "unmatched_salespeople": set(),
            "unknown_status": set(),
            "warnings": [],
        }

        # ---- PASS A: customers -> res.partner ----
        partner_by_zoho = {}
        for cust in customers:
            zid = (cust.get("zoho_source_id") or "").strip()
            action, partner = self._classify_partner(cust)
            if action == "match":
                report["partners"]["matched"] += 1
                if apply and partner:
                    vals = self._partner_enrich_vals(partner, cust, zid)
                    if vals:
                        partner.write(vals)
                        report["partners"]["enriched"] += 1
                if zid and partner:
                    partner_by_zoho[zid] = partner.id
            else:  # create | create_flag
                report["partners"]["created"] += 1
                if action == "create_flag":
                    report["partners"]["flagged_review"] += 1
                if apply:
                    new = Partner.create(self._partner_create_vals(
                        cust, zid, flag=(action == "create_flag")))
                    if zid:
                        partner_by_zoho[zid] = new.id

        seen_customer_ids = {
            (c.get("zoho_source_id") or "").strip() for c in customers}

        # ---- PASS B: estimates -> archive ----
        for est in estimates:
            number = (est.get("zoho_estimate_number") or "").strip()
            if not number:
                report["warnings"].append("estimate with no number — skipped")
                continue

            bucket = self._status_bucket(est.get("zoho_status"))
            cur = (est.get("currency_code") or "USD").strip().upper()
            # bucket + currency reflect the FULL Zoho distribution (every
            # estimate seen), independent of whether this run imports it.
            report["quotes"][bucket] += 1
            report["currency"][cur] = report["currency"].get(cur, 0) + 1

            raw_status = (est.get("zoho_status") or "").strip().lower()
            if raw_status and raw_status not in STATUS_MAP:
                report["unknown_status"].add(est.get("zoho_status"))

            sp_id, sp_name = self._resolve_salesperson(
                est.get("salesperson_name"))
            if est.get("salesperson_name") and not sp_id:
                report["unmatched_salespeople"].add(est.get("salesperson_name"))

            cust_id = (est.get("zoho_customer_source_id") or "").strip()
            # UNMATCHED customer (has an id, but it's absent from the customers
            # file) -> SKIP + report. Self-healing: once the customer is added
            # and the import re-runs, this estimate imports LINKED (it was never
            # created, so no permanent unlink). Never silent — the dry-run
            # unmatched count is the review gate before APPLY.
            if cust_id and cust_id not in seen_customer_ids:
                report["unmatched_customers"].append(number)
                report["quotes"]["skipped_unmatched_customer"] += 1
                continue
            if not cust_id:
                # No customer id at all -> import UNLINKED (no id to ever match)
                # + report, so it's never silently dropped.
                report["quotes"]["no_customer_id"] += 1

            existing = Archive.search(
                [("zoho_estimate_number", "=", number)], limit=1)
            if existing:
                report["quotes"]["skipped_existing"] += 1
                continue
            report["quotes"]["created"] += 1

            if apply:
                Archive.create(self._archive_vals(
                    est, number, bucket, cur, sp_id, sp_name,
                    partner_by_zoho.get(cust_id)))

        # JSON-friendly: sets -> sorted lists
        report["unmatched_salespeople"] = sorted(
            report["unmatched_salespeople"])
        report["unknown_status"] = sorted(report["unknown_status"])
        return report

    # ----- vals builders -------------------------------------------
    @api.model
    def _partner_create_vals(self, cust, zid, flag=False):
        ctype = cust.get("company_type") or "company"
        billing = cust.get("billing") or {}
        vals = {
            "name": cust.get("name") or "(unnamed Zoho customer)",
            "company_type": ("person" if ctype == "individual" else "company"),
            "email": cust.get("email") or False,
            "phone": cust.get("phone") or False,
            "street": billing.get("street") or False,
            "city": billing.get("city") or False,
            "zoho_source_id": zid or False,
            "zoho_dedup_review": flag,
        }
        # child contacts (no balances, ever)
        children = []
        for person in (cust.get("contacts") or []):
            children.append((0, 0, {
                "name": person.get("name") or "(contact)",
                "email": person.get("email") or False,
                "phone": person.get("phone") or False,
                "type": "contact",
            }))
        if children:
            vals["child_ids"] = children
        return vals

    @api.model
    def _partner_enrich_vals(self, partner, cust, zid):
        """Backfill ONLY empty fields on a matched partner; never overwrite."""
        vals = {}
        if zid and not partner.zoho_source_id:
            vals["zoho_source_id"] = zid
        billing = cust.get("billing") or {}
        if cust.get("email") and not partner.email:
            vals["email"] = cust.get("email")
        if cust.get("phone") and not partner.phone:
            vals["phone"] = cust.get("phone")
        if billing.get("street") and not partner.street:
            vals["street"] = billing.get("street")
        if billing.get("city") and not partner.city:
            vals["city"] = billing.get("city")
        return vals

    @api.model
    def _archive_vals(self, est, number, bucket, cur, sp_id, sp_name, partner_id):
        lines = []
        for seq, ln in enumerate(est.get("lines") or [], start=1):
            lines.append((0, 0, {
                "sequence": seq * 10,
                "category_prefix": ln.get("category_prefix") or False,
                "name": ln.get("name") or "(line)",
                "description": ln.get("description") or False,
                "unit": ln.get("unit") or False,
                "quantity": ln.get("quantity") or 0.0,
                "unit_rate": ln.get("unit_rate") or 0.0,
                "line_total": ln.get("line_total") or 0.0,
                "zoho_item_id": ln.get("zoho_item_id") or False,
            }))
        return {
            "zoho_estimate_number": number,
            "partner_id": partner_id or False,
            "zoho_customer_source_id":
                (est.get("zoho_customer_source_id") or "").strip() or False,
            "quotation_date": est.get("quotation_date") or False,
            "status_bucket": bucket,
            "zoho_status": est.get("zoho_status") or False,
            "currency_code": cur,
            "amount_untaxed": est.get("amount_untaxed") or 0.0,
            "amount_tax": est.get("amount_tax") or 0.0,
            "amount_total": est.get("amount_total") or 0.0,
            "salesperson_id": sp_id or False,
            "salesperson_name": sp_name or False,
            "event_summary": est.get("event_summary") or False,
            "zoho_invoice_number": est.get("zoho_invoice_number") or False,
            "line_ids": lines,
        }
