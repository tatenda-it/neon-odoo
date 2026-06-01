# -*- coding: utf-8 -*-
"""P-B4 -- Sub-hire request generator (orchestrator).

Pattern mirrors B3's DeploymentPlanGenerator:
  gather -> Claude (via B13) -> validate -> persist (with one
  auto-retry on validator failure; quarantine if the retry also
  fails).

⚠️ DECISION (B4, D2): fact-gather via SubhireRequestFactGatherer
which wraps DeploymentPlanFactGatherer. NO conflict recomputation.

⚠️ DECISION (B4, D3): refuse when event_job.state == 'draft'
(mirror B2-DM-2 + B3-D6).

⚠️ DECISION (B4 / B3-DM-1 cycle): the B13 ClaudeDocGenAdapter is
imported LAZILY inside _call_claude. neon_doc_gen is NOT a hard
depends of neon_jobs (cycle: neon_jobs <- neon_doc_gen <- neon_core
<- neon_jobs).

⚠️ DECISION (B4, D8): zero deficits in the gathered facts -> reject
generation with a clear "no sub-hire needed" message. Generating an
empty sub-hire request would carry no signal + create stale audit
trail.
"""
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from .subhire_request_fact_gatherer import (
    SubhireRequestFactGatherer,
)
from .subhire_request_validator import (
    SubhireRequestValidator, SubhireValidationError,
)


_logger = logging.getLogger(__name__)


_DRAFT_JSON_SCHEMA = {
    "type": "object",
    "required": ["enquiry_subject", "enquiry_body",
                  "line_briefs", "data_quality_note"],
    "properties": {
        "enquiry_subject": {"type": "string"},
        "enquiry_body": {"type": "string"},
        "line_briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["product_name", "qty_short",
                              "event_window",
                              "competing_event_names",
                              "brief"],
            },
        },
        "data_quality_note": {"type": ["string", "null"]},
    },
}


_SYSTEM_PROMPT = (
    "You are the Neon Events sub-hire enquiry drafter. The "
    "Conflict Engine (B2) has flagged equipment shortfalls for "
    "an event; the team needs to source these items from a "
    "third-party supplier. You produce the supplier-facing "
    "enquiry text + a per-line brief.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Quantities (qty_short), product names, event names, and "
    "concrete datetimes MUST come VERBATIM from the facts dict. "
    "Do NOT invent or paraphrase numbers. Do NOT paraphrase names.\n"
    "2. For EVERY B2 deficit line in facts['subhire_lines'], you "
    "MUST include a matching entry in line_briefs[]. Omitting a "
    "known shortfall is the cardinal failure mode -- the line "
    "won't get sub-hired.\n"
    "3. For each line_brief: qty_short MUST equal the matching "
    "B2 line's deficit_qty EXACTLY; product_name MUST match; "
    "competing_event_names MUST be a subset of B2's set; "
    "event_window MUST be the Python-computed string in "
    "facts['event_window_label'] (copy it character-for-"
    "character).\n"
    "4. Prefer relative phrasing ('the morning of the event', "
    "'over the load-in window') over concrete datetimes. Any "
    "concrete datetime not in the facts will trigger rejection.\n"
    "5. data_quality_note: if facts['b2_conflict']"
    "['data_quality_note'] is set, copy it VERBATIM into the "
    "draft. If null, set the draft's data_quality_note to null.\n\n"
    "Tone: professional, concise, supplier-friendly. The "
    "enquiry_subject is one line. The enquiry_body is the cover "
    "text the team will email or paste into the RFQ -- 3-5 short "
    "paragraphs. Each line_brief.brief is 1-2 sentences naming "
    "the item + qty + when needed.")


class SubhireRequestGenerator:
    """One instance per generate call."""

    def __init__(self, env):
        self.env = env

    def generate_for_event(self, event_job, replaces=None):
        """Generate a sub-hire request for event_job.

        Returns the new neon.subhire.request at status='generated'.
        Raises UserError on any user-surfaced failure (B13 typed
        errors mapped + validator failure after retry).
        """
        event_job.ensure_one()
        self._check_state_gate(event_job)

        facts = SubhireRequestFactGatherer(
            self.env).gather(event_job)

        if not facts.get("subhire_lines"):
            raise UserError(_(
                "No deficits to draft -- nothing to sub-hire. "
                "B2 hasn't flagged any deficit / zero-margin "
                "items for this event."))

        provider = self._get_provider()
        if not provider:
            raise UserError(_(
                "Doc-gen provider is not configured. Ask an OD/MD "
                "to set the Anthropic key in Settings -> Doc-Gen."))

        validator = SubhireRequestValidator(facts)
        attempt_messages = []
        last_error = None
        bad_output = None
        for attempt in range(2):
            try:
                claude_out = self._call_claude(
                    provider, facts, attempt_messages)
            except Exception as exc:  # noqa: BLE001
                raise self._map_docgen_error(exc)
            result = claude_out.get("result") or {}
            try:
                validator.validate(result)
                return self._persist(
                    event_job, facts, claude_out,
                    replaces=replaces)
            except SubhireValidationError as exc:
                last_error = str(exc)
                bad_output = result
                _logger.warning(
                    "Sub-hire validator rejected attempt %s for "
                    "event %s: %s", attempt + 1,
                    event_job.name, last_error)
                attempt_messages.append({
                    "role": "assistant",
                    "content": json.dumps(result),
                })
                attempt_messages.append({
                    "role": "user",
                    "content": (
                        "Your previous response was rejected by "
                        "the strict validator with this error:\n\n"
                        + last_error
                        + "\n\nRegenerate the draft, fixing the "
                        "issue. Keep everything else identical. "
                        "Respond with ONLY the JSON object."),
                })
        # Second attempt also failed -- quarantine + raise.
        self._persist_quarantine(
            event_job, facts, bad_output, last_error,
            replaces=replaces)
        raise UserError(_(
            "Generated sub-hire draft contradicted known facts "
            "after a retry. Please regenerate.\n\nValidator "
            "error: %(e)s") % {
                "e": last_error or "(no error message)"})

    # --- guards ----------------------------------------------------

    def _check_state_gate(self, event_job):
        if event_job.state == "draft":
            raise UserError(_(
                "Move event %(n)s out of draft (to planning or "
                "later) before drafting a sub-hire request -- "
                "equipment demand is not yet authoritative."
            ) % {"n": event_job.name})

    def _get_provider(self):
        Provider = self.env["neon.doc.gen.provider"].sudo()
        return Provider.search(
            [("provider_key", "=", "anthropic"),
             ("is_enabled", "=", True)], limit=1)

    # --- Claude call -----------------------------------------------

    def _call_claude(self, provider, facts, attempt_messages):
        # Lazy import per B3-DM-1 cycle pattern.
        try:
            from odoo.addons.neon_doc_gen.models.ai_doc_gen.claude_docgen_adapter import (  # noqa: E501
                ClaudeDocGenAdapter,
            )
        except ImportError as exc:
            raise UserError(_(
                "Doc-gen module (neon_doc_gen) is not installed. "
                "Install it before drafting sub-hire requests."
            )) from exc
        adapter = ClaudeDocGenAdapter(provider)
        facts_with_retry = dict(facts)
        if attempt_messages:
            facts_with_retry["_retry_context"] = {
                "previous_attempt": attempt_messages[-2]["content"],
                "validator_error": attempt_messages[-1]["content"],
            }
        return adapter.generate(
            system_prompt=_SYSTEM_PROMPT,
            facts=facts_with_retry,
            json_schema=_DRAFT_JSON_SCHEMA,
        )

    @staticmethod
    def _map_docgen_error(exc):
        from odoo.addons.neon_doc_gen.models.ai_doc_gen.claude_docgen_adapter import (  # noqa: E501
            DocGenConfigError, DocGenRateLimitError,
            DocGenServerError, DocGenTimeoutError,
            DocGenAPIError, DocGenJSONError, DocGenError,
        )
        name = type(exc).__name__
        msg = str(exc)
        if isinstance(exc, DocGenConfigError):
            return UserError(_(
                "AI doc-gen is not configured. Contact the OD/MD."))
        if isinstance(exc, DocGenRateLimitError):
            return UserError(_(
                "Anthropic rate limit hit. Try again in a few "
                "minutes."))
        if isinstance(exc, DocGenServerError):
            return UserError(_(
                "Anthropic service is unavailable. Please retry."))
        if isinstance(exc, DocGenTimeoutError):
            return UserError(_(
                "Sub-hire generation took too long; retry or "
                "split the event into smaller pieces."))
        if isinstance(exc, DocGenAPIError):
            return UserError(_(
                "Anthropic API error: %(m)s") % {"m": msg})
        if isinstance(exc, DocGenJSONError):
            return UserError(_(
                "Model returned unparseable output after one "
                "retry. Please regenerate."))
        if isinstance(exc, DocGenError):
            return UserError(_(
                "Doc-gen failed (%(n)s): %(m)s") % {
                    "n": name, "m": msg})
        return exc

    # --- persistence -----------------------------------------------

    def _persist(self, event_job, facts, claude_out,
                 replaces=None):
        Request = self.env["neon.subhire.request"].sudo()
        Line = self.env["neon.subhire.request.line"].sudo()
        Product = self.env["product.template"].sudo()
        revision, replaced = self._resolve_revision(
            event_job, replaces)
        result = claude_out.get("result") or {}
        usage = claude_out.get("usage") or {}
        b2 = facts.get("b2_conflict", {}) or {}
        src_conflict_id = b2.get("conflict_id") or False
        src_start = src_end = False
        if src_conflict_id:
            src_rec = self.env["neon.equipment.conflict"].sudo() \
                .browse(int(src_conflict_id)).exists()
            if src_rec:
                src_start = src_rec.window_start or False
                src_end = src_rec.window_end or False

        req = Request.create({
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "generated",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "source_conflict_id": src_conflict_id,
            "source_conflict_window_start": src_start,
            "source_conflict_window_end": src_end,
            "draft_json": json.dumps(result, default=str),
            "data_quality_note": b2.get("data_quality_note"),
            "model_used": claude_out.get("model") or "",
            "prompt_tokens": int(usage.get("prompt_tokens", 0)
                                    or 0),
            "completion_tokens": int(
                usage.get("completion_tokens", 0) or 0),
            "latency_ms": int(claude_out.get("latency_ms", 0)
                                or 0),
        })

        # Persist lines (one per B2 deficit; the validator already
        # asserted line_briefs[] covers them all).
        b2_lines_by_name = {ln["product_name"]: ln
                             for ln in (facts.get(
                                 "subhire_lines") or [])}
        for brief in result.get("line_briefs", []):
            pname = (brief or {}).get("product_name") or ""
            b2_ln = b2_lines_by_name.get(pname)
            if not b2_ln:
                continue
            product = Product.browse(
                b2_ln["product_template_id"]).exists()
            if not product:
                continue
            Line.create({
                "request_id": req.id,
                "product_template_id": product.id,
                "qty_short": int(brief.get("qty_short", 0) or 0),
                "event_window": (brief.get("event_window")
                                  or facts.get("event_window_label")
                                  or ""),
                "competing_event_names_csv": ", ".join(
                    brief.get("competing_event_names") or []),
                "sub_hire_priority": int(b2_ln.get(
                    "sub_hire_priority", 0) or 0),
                "brief": brief.get("brief") or "",
            })

        if replaced:
            replaced.sudo().write({
                "status": "superseded",
                "superseded_at": fields.Datetime.now(),
                "superseded_by_request_id": req.id,
            })
        return req

    def _persist_quarantine(self, event_job, facts, bad_output,
                             error_msg, replaces=None):
        Request = self.env["neon.subhire.request"].sudo()
        revision, _replaced = self._resolve_revision(
            event_job, replaces, dry=True)
        Request.create({
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "draft",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "quarantine_json": (json.dumps(bad_output, default=str)
                                  if bad_output else ""),
            "error_message": (
                "SubhireValidationError after retry: " + (
                    error_msg or "")),
        })

    def _resolve_revision(self, event_job, replaces, dry=False):
        """Mirror B3's max+1 strategy (so quarantines + supersedes
        + new generations all stack without UNIQUE collision)."""
        Request = self.env["neon.subhire.request"].sudo()
        max_rev = Request.search([
            ("event_job_id", "=", event_job.id),
        ], order="revision desc", limit=1).revision or 0
        next_rev = int(max_rev) + 1
        if dry:
            return (next_rev, None)
        if replaces:
            return (next_rev, replaces)
        prior = Request.search([
            ("event_job_id", "=", event_job.id),
            ("status", "not in", ("superseded", "draft")),
        ], order="revision desc", limit=1)
        return (next_rev, prior if prior else None)
