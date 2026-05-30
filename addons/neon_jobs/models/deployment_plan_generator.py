# -*- coding: utf-8 -*-
"""P-B3 -- DeploymentPlanGenerator.

Orchestrator: fact-gather -> Claude via B13 -> validator -> persist.
One auto-retry inside the call: if the validator raises on the
first attempt, the error message is fed back to Claude as a
corrective user message and the call is re-tried ONCE. A second
validator failure persists the bad output to quarantine_json and
raises to the UI.

⚠️ DECISION (B3, D8): all six typed B13 DocGen* exceptions are
caught + mapped to friendly UI messages. No silent fallback to a
rule-based plan -- the value of B3 IS the LLM narrative; absent
that the user has the event-job form already.
"""
import json
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from .deployment_plan_fact_gatherer import (
    DeploymentPlanFactGatherer,
)
from .deployment_plan_validator import (
    DeploymentPlanValidator, PlanValidationError,
)


_logger = logging.getLogger(__name__)


_PLAN_JSON_SCHEMA = {
    "type": "object",
    "required": ["sections", "deficits", "data_quality_note"],
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "title", "narrative"],
                "properties": {
                    "key": {
                        "enum": ["load_in", "setup", "show_time",
                                  "strike", "return", "risks"]},
                    "title": {"type": "string"},
                    "narrative": {"type": "string"},
                    "checklist": {
                        "type": "array",
                        "items": {"type": "string"}},
                },
            },
        },
        "crew_call_times": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["crew_partner_name", "call_at",
                              "role", "duty"],
            },
        },
        "deficits": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["product_name", "required_qty",
                              "available_qty", "deficit_qty",
                              "competing_event_names",
                              "sub_hire_priority"],
            },
        },
        "data_quality_note": {"type": ["string", "null"]},
    },
}


_SYSTEM_PROMPT = (
    "You are the Neon Events deployment-plan generator. You are "
    "producing a STRUCTURED deployment plan for an event the "
    "Operations team will execute. The plan is consumed by humans "
    "who already know the event details -- your job is structure, "
    "narrative, and sequencing, NOT to invent facts.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Quantities, partner names, event names, and concrete "
    "datetimes MUST come VERBATIM from the facts you are given. "
    "Do not invent or paraphrase numbers. Do not paraphrase names.\n"
    "2. If the facts include a B2 conflict line with status "
    "'deficit' or 'zero_margin', you MUST include a corresponding "
    "entry in deficits[] -- omitting a known deficit is the "
    "single most dangerous failure mode.\n"
    "3. For each deficit entry, the required_qty / available_qty / "
    "deficit_qty / competing_event_names MUST match the B2 "
    "conflict line EXACTLY. Don't round, don't restate.\n"
    "4. crew_call_times MUST match the pre-computed entries in the "
    "facts EXACTLY (same names, same call_at ISO strings, same "
    "role). You may narrate around them; you do NOT set them.\n"
    "5. When narrating times, prefer relative phrasing ('morning "
    "of the event', 'after strike') over concrete datetimes. "
    "Concrete datetimes are validated against the facts dict; any "
    "concrete datetime not in the facts triggers rejection.\n"
    "6. sections[].key must be one of: load_in, setup, show_time, "
    "strike, return, risks.\n"
    "7. data_quality_note: if the facts['b2_conflict']"
    "['data_quality_note'] is set, copy it VERBATIM into the plan. "
    "If null, set the plan's data_quality_note to null.\n\n"
    "Tone: concise, professional, action-oriented. Each "
    "section.narrative is 1-3 short sentences. checklist items "
    "are imperative single-line tasks.")


class DeploymentPlanGenerator:
    """One instance per generate call. Wraps fact-gather, the
    B13 adapter, and the validator."""

    def __init__(self, env):
        self.env = env

    def generate_for_event(self, event_job, replaces=None):
        """Generate a new plan for ``event_job``. If ``replaces`` is
        a previous plan, that record is marked superseded and the
        new record gets ``revision = replaces.revision + 1``.

        Returns the new neon.deployment.plan record (status =
        'generated' on success). Raises UserError on failure."""
        event_job.ensure_one()
        self._check_state_gate(event_job)

        facts = DeploymentPlanFactGatherer(self.env).gather(event_job)

        provider = self._get_provider()
        if not provider:
            raise UserError(_(
                "Doc-gen provider is not configured. Ask an OD/MD "
                "to set the Anthropic key in Settings -> Doc-Gen."))

        # First attempt + ONE retry on PlanValidationError. We
        # don't catch DocGen* on retry -- a 429 deserves to bubble.
        validator = DeploymentPlanValidator(facts)
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
                # All good -- persist + return
                return self._persist(
                    event_job, facts, claude_out, replaces=replaces)
            except PlanValidationError as exc:
                last_error = str(exc)
                bad_output = result
                _logger.warning(
                    "Plan validator rejected attempt %s for event "
                    "%s: %s", attempt + 1,
                    event_job.name, last_error)
                # Feed the validator error back to Claude for
                # ONE retry.
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
                        + "\n\nRegenerate the plan, fixing the "
                        "issue. Keep everything else identical. "
                        "Respond with ONLY the JSON object."),
                })
        # Second attempt also failed -- quarantine + raise.
        self._persist_quarantine(
            event_job, facts, bad_output, last_error,
            replaces=replaces)
        raise UserError(_(
            "Generated plan contradicted known facts after a "
            "retry. Please regenerate.\n\nValidator error: "
            "%(e)s") % {"e": last_error or "(no error message)"})

    # --- guards ----------------------------------------------------

    def _check_state_gate(self, event_job):
        """D6: refuse to generate when event_job is in draft.
        Mirrors B2-DM-2 -- demand isn't authoritative yet."""
        if event_job.state == "draft":
            raise UserError(_(
                "Move event %(n)s out of draft (to planning or "
                "later) before generating the deployment plan -- "
                "equipment demand is not yet authoritative."
            ) % {"n": event_job.name})

    def _get_provider(self):
        Provider = self.env["neon.doc.gen.provider"].sudo()
        return Provider.search(
            [("provider_key", "=", "anthropic"),
             ("is_enabled", "=", True)], limit=1)

    # --- Claude call -----------------------------------------------

    def _call_claude(self, provider, facts, attempt_messages):
        # Lazy import: neon_doc_gen is NOT a hard depends to avoid
        # the neon_jobs <- neon_doc_gen <- neon_core <- neon_jobs
        # cycle. ImportError here means the doc-gen module isn't
        # installed; surface a friendly message.
        try:
            from odoo.addons.neon_doc_gen.models.ai_doc_gen.claude_docgen_adapter import (  # noqa: E501
                ClaudeDocGenAdapter,
            )
        except ImportError as exc:
            raise UserError(_(
                "Doc-gen module (neon_doc_gen) is not installed. "
                "Install it before generating deployment plans."
            )) from exc
        adapter = ClaudeDocGenAdapter(provider)
        # For the retry case we want to inject the prior attempt +
        # the validator error. The B13 adapter's generate() takes
        # facts -- not arbitrary messages -- so we encode the retry
        # context as a `_retry_context` key on facts that the
        # system prompt instructions reference.
        facts_with_retry = dict(facts)
        if attempt_messages:
            facts_with_retry["_retry_context"] = {
                "previous_attempt": attempt_messages[-2]["content"],
                "validator_error": attempt_messages[-1]["content"],
            }
        out = adapter.generate(
            system_prompt=_SYSTEM_PROMPT,
            facts=facts_with_retry,
            json_schema=_PLAN_JSON_SCHEMA,
        )
        return out

    @staticmethod
    def _map_docgen_error(exc):
        """Convert B13 typed exceptions into friendly UserError."""
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
                "Plan generation took too long. Consider splitting "
                "the event into shorter sections, or retrying."))
        if isinstance(exc, DocGenAPIError):
            # Includes the per-key usage-cap 400 -- surface the
            # upstream Anthropic message verbatim so OD/MD can
            # diagnose.
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
        # Non-DocGen exception -- let it bubble unchanged so the
        # traceback isn't hidden.
        return exc

    # --- persistence -----------------------------------------------

    def _persist(self, event_job, facts, claude_out,
                 replaces=None):
        Plan = self.env["neon.deployment.plan"].sudo()
        revision, replaced = self._resolve_revision(
            event_job, replaces)
        result = claude_out.get("result") or {}
        usage = claude_out.get("usage") or {}
        b2 = facts.get("b2_conflict", {}) or {}
        # Re-read source conflict's Datetime objects directly --
        # facts uses .isoformat() (T-separator) which Odoo's
        # Datetime field rejects (it wants space-separator or a
        # datetime instance).
        src_conflict_id = b2.get("conflict_id") or False
        src_start = src_end = False
        if src_conflict_id:
            src_rec = self.env["neon.equipment.conflict"].sudo() \
                .browse(int(src_conflict_id)).exists()
            if src_rec:
                src_start = src_rec.window_start or False
                src_end = src_rec.window_end or False
        plan = Plan.create({
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "generated",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "source_conflict_id": src_conflict_id,
            "source_conflict_window_start": src_start,
            "source_conflict_window_end": src_end,
            "plan_json": json.dumps(result, default=str),
            "data_quality_note": b2.get("data_quality_note"),
            "model_used": claude_out.get("model") or "",
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(
                usage.get("completion_tokens", 0) or 0),
            "latency_ms": int(claude_out.get("latency_ms", 0) or 0),
        })
        if replaced:
            replaced.sudo().write({
                "status": "superseded",
                "superseded_at": fields.Datetime.now(),
                "superseded_by_plan_id": plan.id,
            })
        return plan

    def _persist_quarantine(self, event_job, facts, bad_output,
                             error_msg, replaces=None):
        """When the validator rejects after the retry, park the
        bad output in a DRAFT plan with quarantine_json populated.
        Useful for debugging -- never shown to users as a plan."""
        Plan = self.env["neon.deployment.plan"].sudo()
        revision, _replaced = self._resolve_revision(
            event_job, replaces, dry=True)
        # NOTE: we DO NOT mark the replaces plan as superseded on
        # a quarantine -- the previous good plan stays active.
        Plan.create({
            "event_job_id": event_job.id,
            "revision": revision,
            "status": "draft",
            "generated_at": fields.Datetime.now(),
            "generated_by_id": self.env.uid,
            "quarantine_json": json.dumps(
                bad_output, default=str) if bad_output else "",
            "error_message": (
                "PlanValidationError after retry: " + (error_msg
                                                       or "")),
        })

    def _resolve_revision(self, event_job, replaces, dry=False):
        """Returns (next_revision, replaces_record_or_None).

        next_revision is always max(existing revisions for this
        event) + 1 so the (event_id, revision) unique constraint
        never collides -- prior quarantine plans + active plans
        + superseded plans all count.

        replaces_record_or_None: in non-dry mode, the prior
        ACTIVE plan that should be marked superseded. None in
        quarantine path (dry=True keeps the active plan alive).
        """
        Plan = self.env["neon.deployment.plan"].sudo()
        max_rev = Plan.search([
            ("event_job_id", "=", event_job.id),
        ], order="revision desc", limit=1).revision or 0
        next_rev = int(max_rev) + 1
        if dry:
            return (next_rev, None)
        if replaces:
            return (next_rev, replaces)
        prior = Plan.search([
            ("event_job_id", "=", event_job.id),
            ("status", "not in", ("superseded", "draft")),
        ], order="revision desc", limit=1)
        return (next_rev, prior if prior else None)
