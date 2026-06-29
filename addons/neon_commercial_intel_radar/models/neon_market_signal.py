# -*- coding: utf-8 -*-
import json
import logging
import re

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Selections kept value-identical to crm.lead (2A) so a promoted signal maps
# cleanly onto a lead candidate without translation.
_SECTORS = [
    ("corporate", "Corporate"), ("ngo", "NGO"), ("government", "Government"),
    ("social", "High-End Social"), ("religious", "Religious"),
    ("education", "Education"), ("other", "Other"),
]
_EVENT_TYPES = [
    ("conference", "Conference"), ("awards_dinner", "Awards Dinner"),
    ("launch", "Product Launch"), ("expo", "Expo"), ("gala", "Gala"),
    ("church", "Church Event"), ("roadshow", "Roadshow"),
    ("summit", "Summit"), ("agm", "AGM"),
]

# Strict-JSON extraction contract (brief s6). The model must return ONLY JSON.
_EXTRACT_SYSTEM_PROMPT = (
    "You are a procurement-tender classifier for an events-production company. "
    "Read the tender/award text and return STRICT JSON only (no prose, no code "
    "fences) of the form {\"items\":[{...}]}. One object per distinct tender. "
    "Each item: procuring_entity (str), sector "
    "(corporate|ngo|government|social|religious|education|other), "
    "event_relevant (bool - true only if events/AV/conference/decor work), "
    "event_type (conference|awards_dinner|launch|expo|gala|church|roadshow|"
    "summit|agm|null), estimated_value (number|0), currency (USD|ZiG|null), "
    "deadline (YYYY-MM-DD|null), location (str|null), reference_number "
    "(str|null), source_url (str|null), summary (<=240 chars), fit_score "
    "(0-100), confidence (high|medium|low), is_award (bool), awarded_to "
    "(str|null), next_best_action (str)."
)


class NeonMarketSignal(models.Model):
    """One ingested tender/award item. RAW on receipt; enriched by AI classify;
    promoted to the 2B review queue. Never auto-creates a crm.lead."""

    _name = "neon.market.signal"
    _description = "Neon Market Radar Signal"
    _inherit = ["mail.thread"]  # enables the message_new mail-gateway hook
    _order = "received_date desc, id desc"

    name = fields.Char(string="Subject", required=True, default="(unclassified)")
    source_id = fields.Many2one("neon.market.source", string="Source",
                                ondelete="set null", index=True)
    received_date = fields.Datetime(default=lambda s: fields.Datetime.now())
    raw_subject = fields.Char()
    raw_body = fields.Text()

    # --- AI-extracted ---
    procuring_entity = fields.Char()
    sector = fields.Selection(_SECTORS)
    event_type = fields.Selection(_EVENT_TYPES)
    event_relevant = fields.Boolean(default=False)
    estimated_value = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda s: s.env.company.currency_id.id)
    deadline = fields.Date()
    location = fields.Char()
    reference_number = fields.Char()
    source_url = fields.Char()
    summary = fields.Text()
    fit_score = fields.Integer(
        help="0-100. PLACEHOLDER weights; non-authoritative until tuned.")
    confidence = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")])

    is_award = fields.Boolean(default=False)
    awarded_to = fields.Char(string="Awarded To (competitor)")

    dedupe_hash = fields.Char(index=True)
    state = fields.Selection(
        [
            ("new", "New (raw)"),
            ("classified", "Classified"),
            ("promoted", "Promoted to Queue"),
            ("duplicate", "Duplicate"),
            ("rejected", "Rejected"),
        ],
        default="new", required=True, index=True, tracking=True)
    classify_error = fields.Char(
        readonly=True,
        help="Set when AI classify could not parse; left in 'new' for triage.")

    recommendation_id = fields.Many2one(
        "neon.shadow.recommendation", string="Review Item",
        ondelete="set null", readonly=True)

    # ==================================================================
    # ADAPTER A - mail gateway. Admin binds a mail.alias/fetchmail to this
    # model; inbound mail lands here as a RAW signal. No live server in this
    # build - test by calling message_new() with a synthetic dict.
    # ==================================================================
    @api.model
    def _neon_radar_match_source(self, email_from):
        """Attribute inbound mail to a source via email_match substring; fall
        back to the seeded 'Unattributed' source for triage."""
        addr = (email_from or "").lower()
        if addr:
            for src in self.env["neon.market.source"].search(
                    [("ingest_method", "=", "email_alias"),
                     ("email_match", "!=", False)]):
                if src.email_match and src.email_match.lower() in addr:
                    return src
        return self.env.ref(
            "neon_commercial_intel_radar.source_unattributed",
            raise_if_not_found=False) or self.env["neon.market.source"]

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        custom_values = dict(custom_values or {})
        subject = msg_dict.get("subject") or _("(no subject)")
        body = msg_dict.get("body") or msg_dict.get("body_html") or ""
        email_from = msg_dict.get("email_from") or msg_dict.get("from") or ""
        source = self._neon_radar_match_source(email_from)
        custom_values.update({
            "name": subject,
            "raw_subject": subject,
            "raw_body": body,
            "source_id": source.id if source else False,
            "state": "new",
        })
        return super().message_new(msg_dict, custom_values)

    # ==================================================================
    # ADAPTER B - public-bulletin poller. NO live HTTP in this build. The
    # parser takes an already-fetched string so it is testable on a saved
    # sample. Wiring the real fetch is a gated activation step.
    # ==================================================================
    @api.model
    def _neon_radar_fetch_egp_html(self):
        """Placeholder for the gated live fetch. Returns '' so the cron is a
        safe no-op until an admin wires the real polite GET at activation.
        Deliberately makes NO network request."""
        _logger.info("neon_radar: live eGP fetch is disabled (gated). No-op.")
        return ""

    @api.model
    def _neon_radar_parse_egp_bulletin(self, text, source=None):
        """Parse an already-fetched eGP public-bulletin string into RAW
        signals. Sample fixture format (one tender per line):
            REF | Procuring Entity | Title | Deadline | URL
        Robust to blank lines / short lines. Creates state='new' signals."""
        source = source or self.env.ref(
            "neon_commercial_intel_radar.source_egp", raise_if_not_found=False)
        created = self.browse()
        for line in (text or "").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            ref = parts[0] if len(parts) > 0 else ""
            entity = parts[1] if len(parts) > 1 else ""
            title = parts[2] if len(parts) > 2 else (ref or _("(tender)"))
            url = parts[4] if len(parts) > 4 else ""
            body = " | ".join(parts)
            created |= self.create({
                "name": title or _("(tender)"),
                "raw_subject": title,
                "raw_body": body,
                "reference_number": ref or False,
                "procuring_entity": entity or False,
                "source_url": url or False,
                "source_id": source.id if source else False,
                "state": "new",
            })
        return created

    @api.model
    def _neon_radar_sample_text(self):
        """Built-in eGP-style fixture for the 'Poll from sample' test button /
        verification. NOT live data; lets the parser run with zero network."""
        return (
            "# REF | Procuring Entity | Title | Deadline | URL\n"
            "PRAZ/2026/001 | Ministry of Tourism | Supply and setup of "
            "conference AV for the national tourism summit | 2026-07-15 | "
            "https://egp.praz.org.zw/t/001\n"
            "PRAZ/2026/002 | City of Harare | Catering and decor for the civic "
            "awards dinner | 2026-07-20 | https://egp.praz.org.zw/t/002\n"
        )

    @api.model
    def _cron_neon_radar_poll_egp(self):
        """INACTIVE cron. Would fetch the eGP public bulletin then parse it.
        No-op fetch in this build; parse runs only on whatever the (gated)
        fetch returns."""
        html = self._neon_radar_fetch_egp_html()
        if not html:
            return
        self._neon_radar_parse_egp_bulletin(html)

    # ==================================================================
    # AI CLASSIFY (async; INACTIVE cron). Provider-agnostic + hard-guarded.
    # ==================================================================
    def _neon_radar_ai_extract(self, text):
        """Call the configured default AI provider for strict-JSON extraction.
        Returns (items_list, error_str). HARD GUARD: if no enabled default
        provider OR no API key is configured, returns ([], reason) and makes
        NO network call - so this is safe to run in a keyless sandbox.

        DECISION (spec vs reality): the spec named 'Claude primary / Grok
        fallback', but neon_ai_core actually wires Groq + Gemini (Anthropic is
        a commented future provider; xAI is not wired at all). This binds to
        neon_ai_core's *default* provider via its adapter factory, so it works
        today on whatever is_default (Groq) and auto-upgrades the day an
        Anthropic/Claude adapter is added - no change here needed."""
        self.ensure_one()
        provider = self.env["neon.dashboard.ai.provider"].sudo().search(
            [("is_default", "=", True), ("is_enabled", "=", True)], limit=1)
        if not provider:
            return [], "no default AI provider configured"
        if provider.provider_key == "rule_based":
            return [], "default provider is rule-based (no extraction)"
        if not provider._get_decrypted_api_key():
            return [], "no API key configured (safe no-op)"
        try:
            from odoo.addons.neon_ai_core.models.ai.chat_adapter_factory \
                import get_chat_adapter
            adapter = get_chat_adapter(provider)
            if not adapter:
                return [], "no chat adapter for provider %s" % provider.provider_key
            result = adapter.chat(
                [{"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                 {"role": "user", "content": text or ""}],
                temperature=0)
            return self._neon_radar_parse_ai_json(getattr(result, "text", "")), None
        except Exception as e:  # noqa: BLE001 - never let a slow/failed AI call break ingest
            _logger.warning("neon_radar AI extract failed: %s", e)
            return [], str(e)

    @api.model
    def _neon_radar_parse_ai_json(self, raw):
        """Defensively parse the model's JSON. Strips code fences; tolerates a
        bare object or an {'items':[...]} envelope. Returns a list (possibly
        empty). Never raises."""
        if not raw:
            return []
        s = raw.strip()
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()
        try:
            data = json.loads(s)
        except Exception:
            return []
        if isinstance(data, dict) and "items" in data:
            return data.get("items") or []
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return []

    def action_neon_radar_classify_now(self):
        """Manual classify button (testing before any cron runs)."""
        for sig in self.filtered(lambda s: s.state == "new"):
            sig._neon_radar_classify_one()
        return True

    @api.model
    def _cron_neon_radar_classify(self):
        """INACTIVE cron: classify a batch of raw signals."""
        for sig in self.search([("state", "=", "new")], limit=50):
            sig._neon_radar_classify_one()

    def _neon_radar_classify_one(self):
        self.ensure_one()
        text = "%s\n\n%s" % (self.raw_subject or self.name or "",
                             self.raw_body or "")
        items, err = self._neon_radar_ai_extract(text)
        if err or not items:
            # Leave in 'new' for manual triage; never fabricate.
            self.classify_error = err or "no items extracted"
            return
        self.classify_error = False
        # First item enriches this signal; extras become sibling signals
        # (parent keeps the raw, children carry classifications).
        self._neon_radar_apply_item(items[0])
        for extra in items[1:]:
            child = self.create({
                "name": self.raw_subject or self.name,
                "raw_subject": self.raw_subject,
                "raw_body": self.raw_body,
                "source_id": self.source_id.id,
                "state": "new",
            })
            child._neon_radar_apply_item(extra)

    # ------------------------------------------------------------------
    # Core (pure, no AI call) - directly testable with a synthetic item.
    # ------------------------------------------------------------------
    def _neon_radar_apply_item(self, item):
        """Write extracted fields, compute dedupe hash, then dedupe/promote."""
        self.ensure_one()
        vals = {
            "procuring_entity": item.get("procuring_entity") or self.procuring_entity,
            "event_relevant": bool(item.get("event_relevant")),
            "estimated_value": item.get("estimated_value") or 0.0,
            "deadline": item.get("deadline") or False,
            "location": item.get("location") or False,
            "reference_number": item.get("reference_number") or self.reference_number,
            "source_url": item.get("source_url") or self.source_url,
            "summary": (item.get("summary") or "")[:1000],
            "fit_score": int(item.get("fit_score") or 0),
            "is_award": bool(item.get("is_award")),
            "awarded_to": item.get("awarded_to") or False,
            "state": "classified",
        }
        sector = item.get("sector")
        if sector in dict(_SECTORS):
            vals["sector"] = sector
        etype = item.get("event_type")
        if etype in dict(_EVENT_TYPES):
            vals["event_type"] = etype
        conf = item.get("confidence")
        if conf in ("high", "medium", "low"):
            vals["confidence"] = conf
        self.write(vals)
        self.dedupe_hash = self._neon_radar_compute_hash()
        if self._neon_radar_is_duplicate():
            self.state = "duplicate"
            return
        if self.event_relevant or self.is_award:
            self._neon_radar_promote()

    @staticmethod
    def _neon_radar_norm(text):
        return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

    def _neon_radar_compute_hash(self):
        self.ensure_one()
        if self.reference_number:
            return "%s|%s" % (self.source_id.id or 0,
                              self._neon_radar_norm(self.reference_number))
        return self._neon_radar_norm("%s %s %s" % (
            self.procuring_entity or "", self.name or "",
            self.deadline or ""))

    def _neon_radar_is_duplicate(self):
        self.ensure_one()
        if not self.dedupe_hash:
            return False
        return bool(self.search_count([
            ("id", "!=", self.id),
            ("dedupe_hash", "=", self.dedupe_hash),
            ("state", "!=", "rejected"),
        ]))

    # ------------------------------------------------------------------
    # PROMOTE -> 2B review queue. Never creates a crm.lead (that is the human
    # Accept->Execute path in 2D). Award path creates reference/proposal data
    # only: a neon.competitor + a PROPOSED neon.competitor.account.map row.
    # ------------------------------------------------------------------
    def _neon_radar_promote(self):
        self.ensure_one()
        Rec = self.env["neon.shadow.recommendation"]
        link = self.source_url or ""
        rationale = "%s%s" % (self.summary or self.name,
                              ("\nSource: " + link) if link else "")
        if self.is_award:
            competitor = self._neon_radar_find_or_create_competitor()
            account = self._neon_radar_find_or_create_account()
            if competitor and account:
                self.env["neon.competitor.account.map"].create({
                    "name": _("Award: %s -> %s") % (
                        competitor.name, account.display_name),
                    "competitor_id": competitor.id,
                    "account_id": account.id,
                    "status": "proposed",
                    "positioning_note": rationale,
                })
            rec = Rec.create({
                "name": _("Competitor award: %s") % (self.awarded_to or _("unknown")),
                "rec_type": "competitor_mention",
                "rationale": rationale,
                "recommendation": _("Award notice ingested via Market Radar."),
                "confidence": self.confidence or "low",
                "competitor_id": competitor.id if competitor else False,
                "partner_id": account.id if account else False,
                "market_signal_id": self.id,
            })
        else:
            rec = Rec.create({
                "name": _("Tender: %s") % (self.procuring_entity or self.name),
                "rec_type": "market_signal",
                "rationale": rationale,
                "recommendation": item_action(self),
                "confidence": self.confidence or "low",
                "market_signal_id": self.id,
            })
        self.recommendation_id = rec.id
        self.state = "promoted"
        return rec

    def _neon_radar_find_or_create_competitor(self):
        self.ensure_one()
        if not self.awarded_to:
            return self.env["neon.competitor"]
        Comp = self.env["neon.competitor"]
        existing = Comp.search(
            [("name", "=ilike", self.awarded_to.strip())], limit=1)
        return existing or Comp.create({"name": self.awarded_to.strip()})

    def _neon_radar_find_or_create_account(self):
        self.ensure_one()
        if not self.procuring_entity:
            return self.env["res.partner"]
        Partner = self.env["res.partner"]
        existing = Partner.search(
            [("name", "=ilike", self.procuring_entity.strip())], limit=1)
        # Thin company shell as the proposed account; persists as reference
        # only - NOT a lead. Prunable if the proposal is rejected.
        return existing or Partner.create({
            "name": self.procuring_entity.strip(), "is_company": True})


def item_action(signal):
    """Next-best-action string for a tender review item."""
    return _("Review tender from %s; if a fit, Accept -> Execute creates a "
             "lead candidate.") % (signal.procuring_entity or _("source"))
