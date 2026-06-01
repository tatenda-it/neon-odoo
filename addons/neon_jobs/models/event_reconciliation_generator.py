# -*- coding: utf-8 -*-
"""P-B5 -- Post-event reconciliation generator (orchestrator).

Pattern mirrors B3/B4: gather -> Claude (via B13) -> validate ->
persist. One auto-retry on validator failure; quarantine on second
failure.

⚠️ DECISION (B5, D6): reuses the B3-DM-1 cycle pattern -- B13's
ClaudeDocGenAdapter is imported LAZILY inside _call_claude.
neon_doc_gen is NOT a hard depends of neon_jobs.

⚠️ DECISION (B5, D2): refuses to generate unless event_job.state
in ('returned', 'completed', 'closed'). Reconciliation is the
backward view; running it pre-event has no signal.

⚠️ DECISION (B5, D4): the orchestrator never writes to any
financial model. The facts dict carries variance figures; the
persisted reconciliation stores those for display only.
"""
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from .event_reconciliation_fact_gatherer import (
    EventReconciliationFactGatherer,
)
from .event_reconciliation_validator import (
    EventReconciliationValidator, ReconValidationError,
)


_logger = logging.getLogger(__name__)


_POST_EVENT_STATES = ("returned", "completed", "closed")


_SUMMARY_JSON_SCHEMA = {
    "type": "object",
    "required": ["headline", "executive_summary",
                  "what_went_well", "what_didnt",
                  "equipment_outcomes", "subhire_outcomes",
                  "cost_narrative", "lessons",
                  "event_window", "data_quality_note"],
    "properties": {
        "headline": {"type": "string"},
        "executive_summary": {"type": "string"},
        "what_went_well": {
            "type": "array",
            "items": {"type": "string"},
        },
        "what_didnt": {
            "type": "array",
            "items": {"type": "string"},
        },
        "equipment_outcomes": {
            "type": "object",
            "required": ["written_off_count",
                          "needs_repair_count",
                          "narrative", "flagged_units"],
            "properties": {
                "written_off_count": {"type": "integer"},
                "needs_repair_count": {"type": "integer"},
                "narrative": {"type": "string"},
                "flagged_units": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
        },
        "subhire_outcomes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["request_name",
                              "qty_short_total",
                              "line_count",
                              "narrative"],
            },
        },
        "cost_narrative": {"type": "string"},
        "lessons": {
            "type": "array",
            "items": {"type": "string"},
        },
        "event_window": {"type": "string"},
        "data_quality_note": {"type": ["string", "null"]},
    },
}


_SYSTEM_PROMPT = (
    "You are the Neon Events post-event reconciliation drafter. "
    "An event has finished; the system has gathered Python facts "
    "for what was planned (B3 deployment plan + B4 sub-hires) + "
    "what actually happened (equipment condition deltas, "
    "planned-vs-actual cost). You produce a structured narrative "
    "that closes the loop -- what went well, what didn't, "
    "outcomes per workstream, lessons.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Every quantity, unit serial_number, sub-hire request name, "
    "supplier name, and concrete datetime MUST come VERBATIM from "
    "the facts dict. Do NOT invent or paraphrase numbers, names, "
    "or dates.\n"
    "2. For EVERY written-off unit in facts['condition_deltas'] "
    "(new_status='written_off'), you MUST include a matching entry "
    "in equipment_outcomes.flagged_units. Omitting a written-off "
    "unit is the cardinal failure mode -- the workshop alert "
    "won't fire.\n"
    "3. For EVERY non-superseded sub-hire request in "
    "facts['subhire_snapshot'], you MUST include a matching entry "
    "in subhire_outcomes referencing its `name` field verbatim. "
    "qty_short_total + line_count MUST match the snapshot EXACTLY.\n"
    "4. supplier_name in subhire_outcomes (if you set it) MUST "
    "match the snapshot's supplier_name verbatim.\n"
    "5. event_window MUST be the Python-computed "
    "facts['event_window_label'] string copied character-for-"
    "character.\n"
    "6. Prefer relative phrasing ('on the morning of the event', "
    "'over the load-out window') over concrete datetimes. Any "
    "concrete datetime not in the facts triggers rejection.\n"
    "7. data_quality_note: if facts['b2_conflict']"
    "['data_quality_note'] is set, copy it VERBATIM into the "
    "draft. If null, set the draft's data_quality_note to null.\n"
    "8. cost_narrative: report the planned/actual/variance figures "
    "from facts['cost_variance']. NEVER invent currency or amounts. "
    "Note that the reconciliation does NOT post journal entries -- "
    "your narrative is informational only; the user acts on it.\n\n"
    "Tone: professional, factual, concise. The headline is one "
    "line. The executive_summary is one paragraph. what_went_well "
    "and what_didnt are short bullet lists (2-5 each). lessons is "
    "1-4 forward-looking bullets.")


class EventReconciliationGenerator:
    """One instance per generate call."""

    def __init__(self, env):
        self.env = env

    def generate_for_event(self, event_job, replaces=None):
        """Generate a reconciliation for event_job.

        Returns the new neon.event.reconciliation at status='generated'.
        Raises UserError on any user-surfaced failure.
        """
        event_job.ensure_one()
        self._check_state_gate(event_job)

        facts = EventReconciliationFactGatherer(
            self.env).gather(event_job)

        provider = self._get_provider()
        if not provider:
            raise UserError(_(
                "Doc-gen provider is not configured. Ask an OD/MD "
                "to set the Anthropic key in Settings -> Doc-Gen."))

        validator = EventReconciliationValidator(facts)
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
            except ReconValidationError as exc:
                last_error = str(exc)
                bad_output = result
                _logger.warning(
                    "Reconciliation validator rejected attempt %s "
                    "for event %s: %s", attempt + 1,
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
                        + "\n\nRegenerate the reconciliation, "
                        "fixing the issue. Keep everything else "
                        "identical. Respond with ONLY the JSON "
                        "object."),
                })
        # Second attempt also failed -- quarantine + raise.
        self._persist_quarantine(
            event_job, facts, bad_output, last_error,
            replaces=replaces)
        raise UserError(_(
            "Generated reconciliation contradicted known facts "
            "after a retry. Please regenerate.\n\nValidator "
            "error: %(e)s") % {
                "e": last_error or "(no error message)"})

    # --- guards ----------------------------------------------------
    def _check_state_gate(self, event_job):
        if event_job.state not in _POST_EVENT_STATES:
            raise UserError(_(
                "Cannot reconcile event %(n)s (state=%(s)s). The "
                "reconciliation is the BACKWARD view -- it can "
                "only run once the event is in one of: %(e)s. "
                "Move the event to a post-event state first."
            ) % {
                "n": event_job.name,
                "s": event_job.state,
                "e": ", ".join(_POST_EVENT_STATES),
            })

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
                "Install it before generating reconciliations."
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
            json_schema=_SUMMARY_JSON_SCHEMA,
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
                "Reconciliation generation took too long; retry "
                "or split the event into smaller pieces."))
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
        Recon = self.env["neon.event.reconciliation"].sudo()
        revision, replaced = self._resolve_revision(
            event_job, replaces)
        result = claude_out.get("result") or {}
        usage = claude_out.get("usage") or {}
        b2 = facts.get("b2_conflict", {}) or {}
        plan_id = (facts.get("plan_snapshot", {})
                   .get("plan_id") or False)

        # Collect active sub-hire request IDs for the m2m
        subhire_ids = [
            int(s["request_id"])
            for s in (facts.get("subhire_snapshot") or [])
            if s.get("request_id")
        ]

        rec_vals = {
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "generated",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "source_plan_id": plan_id or False,
            "facts_json": json.dumps(facts, default=str),
            "summary_json": json.dumps(result, default=str),
            "data_quality_note": b2.get("data_quality_note"),
            "model_used": claude_out.get("model") or "",
            "prompt_tokens": int(usage.get("prompt_tokens", 0)
                                    or 0),
            "completion_tokens": int(
                usage.get("completion_tokens", 0) or 0),
            "latency_ms": int(claude_out.get("latency_ms", 0)
                                or 0),
        }
        if subhire_ids:
            rec_vals["source_subhire_request_ids"] = [
                (6, 0, subhire_ids)]
        rec = Recon.create(rec_vals)

        if replaced:
            replaced.sudo().write({
                "status": "superseded",
                "superseded_at": fields.Datetime.now(),
                "superseded_by_recon_id": rec.id,
            })
        return rec

    def _persist_quarantine(self, event_job, facts, bad_output,
                             error_msg, replaces=None):
        Recon = self.env["neon.event.reconciliation"].sudo()
        revision, _replaced = self._resolve_revision(
            event_job, replaces, dry=True)
        Recon.create({
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "draft",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "facts_json": json.dumps(facts, default=str),
            "quarantine_json": (
                json.dumps(bad_output, default=str)
                if bad_output else ""),
            "error_message": (
                "ReconValidationError after retry: " + (
                    error_msg or "")),
        })

    def _resolve_revision(self, event_job, replaces, dry=False):
        """Mirror B3/B4's max+1 strategy."""
        Recon = self.env["neon.event.reconciliation"].sudo()
        max_rev = Recon.search([
            ("event_job_id", "=", event_job.id),
        ], order="revision desc", limit=1).revision or 0
        next_rev = int(max_rev) + 1
        if dry:
            return (next_rev, None)
        if replaces:
            return (next_rev, replaces)
        prior = Recon.search([
            ("event_job_id", "=", event_job.id),
            ("status", "not in", ("superseded", "draft")),
        ], order="revision desc", limit=1)
        return (next_rev, prior if prior else None)
