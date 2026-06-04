# -*- coding: utf-8 -*-
"""Phase 12.1 / 12.1.1 — Chat orchestrator.

Drives the multi-turn LLM<->tool-call loop. Persists every turn to
neon.finance.ai.chat.message as an audit log.

⚠️ DECISION (M12.1, marker inline): rate limit lives at module
scope as an in-memory dict keyed on user_id. 30 req / hour / user.
Sliding 1-hour window via timestamp list per user.

⚠️ DECISION (M12.1, marker inline): max 3 tool-call iterations
per user turn. After the 3rd iteration we return the partial
output with a guardrail message.

⚠️ DECISION (M12.1.1, D17): tool-call deduplication within one
user turn. A duplicate (tool_name + normalised params) reuses the
prior result instead of re-running + re-rendering.

⚠️ DECISION (M12.1.1, D18): history pruning counts ALL message
roles (user / assistant / tool), but never splits an assistant
tool-emit from its matching tool responses. Walk backwards from
the end; if the cutoff lands mid-pairing, extend back to the
preceding assistant turn.

⚠️ DECISION (M12.1.1, D24): tool advertisement intersects user
groups with the variant's TOOLS_BY_VARIANT set. Manager+director
sees all tools (no intersection).

⚠️ DECISION (M12.1.1, D25): role_label in system prompt derives
from the active variant, not the user's primary group. Director
peeking Bookkeeper variant gets "Finance Copilot" framing.

⚠️ DECISION (M12.2, D33): active_variant comes from the request
(chat panel state, not the user's stored dashboard_variant).
Validated here against the user's allowed-variants set so a
non-superuser can't peek a variant outside their tier. Manager +
group_neon_superuser members may peek any variant.

⚠️ DECISION (M12.2, D34): write-tool results don't loop back to
the LLM. When dispatch returns is_proposal=True, the orchestrator
persists a pending_action row, builds a confirmation card payload,
appends a synthetic tool-role message so the next user turn has
clean Groq protocol shape, and EXITS the iteration loop without
calling the LLM again. The user must click Confirm/Cancel before
the LLM sees a follow-up.

⚠️ DECISION (M12.2, D36): write rate limit is a SEPARATE counter
from the chat rate limit. 10 confirmed writes / user / hour. The
counter is incremented in ChatOrchestrator.confirm_pending_action
on successful execute, not at propose time.

⚠️ DECISION (M12.2, D37): the system prompt gains a writes clause
reminding the LLM that actions require confirmation and it must
never claim a write is done until the user confirms.
"""
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

from odoo import fields

from .groq_chat_adapter import GroqChatAdapter, ChatTurnResult
from . import tool_registry


_logger = logging.getLogger(__name__)


_RATE_LIMIT_PER_HOUR = 30
_RATE_LIMIT_WINDOW_SECONDS = 3600
_RATE_LIMIT_BY_USER: dict = defaultdict(list)

# D36 — stricter ceiling on confirmed writes per user per hour.
_WRITE_RATE_LIMIT_PER_HOUR = 10
_WRITE_RATE_LIMIT_BY_USER: dict = defaultdict(list)

_MAX_TOOL_ITERATIONS = 3
# D18 — count ALL message rows, not just user+assistant turns.
_HISTORY_MESSAGE_LIMIT = 10

# D25 — variant → "Copilot" role label mapping.
_ROLE_LABELS = {
    "director": "Director",
    "sales": "Sales",
    "bookkeeper": "Finance",
    "lead_tech": "Operations",
}

_DEFAULT_SYSTEM_PROMPT = (
    "You are the Neon Events {role_label} Copilot. You help "
    "{user_name} at Neon Events Elements (event production "
    "company in Harare, Zimbabwe). Their role is {role_label}. "
    "You have tools relevant to their work -- never suggest "
    "actions outside this role. Use tools to answer factual "
    "questions -- never guess or invent numbers, dates, or "
    "names. When you don't have a tool, say so. Keep responses "
    "concise (2-3 sentences max unless asked for detail). "
    "Currency: USD or ZiG (Zimbabwe Gold). VAT: 15%. Today's "
    "date is {today_date}. "
    # D37 — writes always require confirmation.
    "You can also take actions (log a lead, move a deal's stage, "
    "update a deal value, post a chatter note) but you never act "
    "silently -- you always describe what you will do and the "
    "user must confirm it via the on-screen card. Never claim an "
    "action is done until the user confirms; if a proposal "
    "renders, simply tell the user to confirm or cancel it."
)

_SYSTEM_PROMPT_CONFIG_KEY = "neon_finance.ai_chat_system_prompt"


@dataclass
class OrchestratorResponse:
    success: bool
    assistant_message: str = ""
    tool_cards: List[dict] = field(default_factory=list)
    is_fallback: bool = False
    error_message: str = ""
    provider_key: str = ""
    model_version: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0

    def to_dict(self):
        return {
            "ok": self.success,
            "assistant_message": self.assistant_message,
            "tool_cards": self.tool_cards,
            "is_fallback": self.is_fallback,
            "error_message": self.error_message,
            "provider_key": self.provider_key,
            "model_version": self.model_version,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
        }


def _check_rate_limit(user_id):
    now = time.time()
    bucket = _RATE_LIMIT_BY_USER[user_id]
    fresh = [t for t in bucket
             if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    _RATE_LIMIT_BY_USER[user_id] = fresh
    if len(fresh) >= _RATE_LIMIT_PER_HOUR:
        return False
    fresh.append(now)
    return True


def _check_write_rate_limit(user_id, consume=True):
    """D36 — 10 confirmed writes / user / hour. ``consume=False``
    peeks the bucket without incrementing (used at propose time as a
    soft check so the LLM gets a clean error before a doomed
    confirm)."""
    now = time.time()
    bucket = _WRITE_RATE_LIMIT_BY_USER[user_id]
    fresh = [t for t in bucket
             if now - t < _RATE_LIMIT_WINDOW_SECONDS]
    _WRITE_RATE_LIMIT_BY_USER[user_id] = fresh
    if len(fresh) >= _WRITE_RATE_LIMIT_PER_HOUR:
        return False
    if consume:
        fresh.append(now)
    return True


# D33 — variant access rules. Manager + superuser may peek any
# variant; primary-tier users get only their stored variant.
_SUPERUSER_GROUP = "neon_core.group_neon_superuser"
# ⚠️ DECISION (B11 ai-core extraction, R6): the manager group is a
# neon_jobs xmlid. neon_ai_core does NOT depend on neon_jobs, so this
# is a SOFT reference -- user.has_group() returns False (no crash) when
# neon_jobs is absent. On every real deployment (dev + prod) neon_jobs
# is installed, so peek/superset behaviour is byte-identical to Phase 12.
_MANAGER_GROUP = "neon_jobs.group_neon_jobs_manager"

# ⚠️ DECISION (B11 ai-core extraction): core fallback role resolver.
# Used ONLY when neon.dashboard is not installed (a WhatsApp-only /
# channels deployment). Mirrors the neon_core tier priority but WITHOUT
# the dashboard-specific preferred_dashboard_type override or the HR
# lens -- those stay in neon.dashboard._default_dashboard_type_for_user.
_CORE_TIER_GROUPS = [
    ("neon_core.group_neon_superuser", "director"),
    ("neon_core.group_neon_bookkeeper", "bookkeeper"),
    ("neon_core.group_neon_lead_tech", "lead_tech"),
    ("neon_core.group_neon_sales_rep", "sales"),
]


def _core_role_for_user(env, user):
    """neon_core-tier-only variant resolver (no dashboard dependency)."""
    for xmlid, role in _CORE_TIER_GROUPS:
        try:
            if user.has_group(xmlid):
                return role
        except Exception:  # noqa: BLE001
            continue
    return "sales"


def _stored_variant_for(env, user):
    """Resolve the user's stored landing variant.

    ⚠️ DECISION (B11 ai-core extraction, R4 parity): when neon.dashboard
    is installed we delegate to its _default_dashboard_type_for_user so
    the live Copilot keeps EXACT Phase-12 behaviour (preferred_dashboard_
    type override + HR lens + superuser-trumps). The reference is a
    runtime registry lookup (model name string), NOT a Python import --
    neon_ai_core carries zero dependency on neon_dashboard. When the
    model is absent (channels-only), fall back to the neon_core tier
    resolver above.
    """
    try:
        if "neon.dashboard" in env:
            return env["neon.dashboard"].sudo(
            )._default_dashboard_type_for_user(user.id)
    except Exception:  # noqa: BLE001
        pass
    return _core_role_for_user(env, user)


def _validate_active_variant(env, user, requested_variant):
    """Return the variant the orchestrator should treat as active.

    - Empty/None requested -> fall back to the user's stored variant.
    - Manager + superuser: any of the 4 dashboard variants is OK
      (they may peek freely via the dashboard's View-as dropdown).
    - Other users: must match their stored variant; mismatch falls
      back to the stored variant silently (D33 — the chat panel
      shouldn't be able to escalate the user's effective tier).
    """
    valid = {"director", "sales", "bookkeeper", "lead_tech"}
    requested = (requested_variant or "").lower()
    stored = _stored_variant_for(env, user) or "director"
    if requested not in valid:
        return stored
    is_peeker = False
    try:
        is_peeker = (user.has_group(_SUPERUSER_GROUP)
                      or user.has_group(_MANAGER_GROUP))
    except Exception:  # noqa: BLE001
        pass
    if is_peeker:
        return requested
    if requested != stored:
        return stored
    return requested


def _dedup_key(tool_name, params):
    """Stable canonical key for D17 dedup. Sort dict keys, coerce
    string values to lowercase, leave numerics/dates alone."""
    canonical = []
    for k in sorted((params or {}).keys()):
        v = (params or {})[k]
        if isinstance(v, str):
            canonical.append((k, v.strip().lower()))
        elif isinstance(v, (int, float, bool)) or v is None:
            canonical.append((k, v))
        else:
            canonical.append((k, json.dumps(v, sort_keys=True,
                                              default=str)))
    return (tool_name, tuple(canonical))


class ChatOrchestrator:
    """One instance per request. Persists messages, calls the
    adapter, loops on tool calls."""

    def __init__(self, env):
        self.env = env
        self.Message = env["neon.finance.ai.chat.message"].sudo()
        self.WriteLog = env[
            "neon.finance.ai.chat.write.log"].sudo()

    # ==============================================================
    # Public entry
    # ==============================================================
    def handle_user_message(self, user, session, text,
                             active_variant=None):
        """Append the user turn, call the LLM, dispatch tools,
        persist intermediate turns, return the final response.

        ``active_variant`` is the dashboard variant the user is
        currently looking at — drives tool advertisement (D24) and
        the system prompt's role label (D25).
        """
        if not _check_rate_limit(user.id):
            return OrchestratorResponse(
                success=False, is_fallback=True,
                assistant_message=(
                    "Slow down -- you've hit 30 messages this hour. "
                    "Try again in a few minutes."),
                error_message="rate_limit_exceeded",
            ).to_dict()

        # D33 — pin the active variant for the whole turn (validated
        # against the user's allowed-variants set).
        active_variant = _validate_active_variant(
            self.env, user, active_variant)

        self._append(session, role="user", content=text or "")

        provider = self._active_provider()
        if not provider:
            msg = (
                "AI provider not configured. Ask an administrator "
                "to set the Groq key in Settings -> Neon -> AI "
                "Insights.")
            self._append(session, role="assistant", content=msg,
                         is_fallback=True,
                         error_message="no_active_provider")
            return OrchestratorResponse(
                success=False, is_fallback=True,
                assistant_message=msg,
                error_message="no_active_provider",
            ).to_dict()

        adapter = GroqChatAdapter(provider)
        history = self._load_history(session)
        messages = self._build_messages(
            history, text, user=user, variant=active_variant)
        # D24 + D30 — advertise both read AND write tools to the
        # LLM (filtered by variant + user groups). dispatch() still
        # enforces the group filter defensively, and write tools'
        # propose() functions are pure (no DB mutation).
        tools = tool_registry.filter_tools_for_variant_and_user(
            user, active_variant, category=None)
        tools_schema = tool_registry.groq_tool_schemas(tools=tools)

        tool_cards: List[dict] = []
        # D17 — dedup cache per user turn. Key: (tool_name, params).
        dedup_cache: dict = {}
        last_result: Optional[ChatTurnResult] = None
        total_prompt = 0
        total_completion = 0
        total_latency = 0

        for iteration in range(_MAX_TOOL_ITERATIONS):
            result = adapter.chat(messages, tools=tools_schema)
            last_result = result
            total_prompt += result.prompt_tokens
            total_completion += result.completion_tokens
            total_latency += result.latency_ms

            if not result.success:
                msg = result.error_message or "Chat failed."
                # D18 — log diagnostic metrics on 4xx-class errors
                # (payload size + message count) so we can tune the
                # history limit if Groq starts rejecting again.
                diag = (
                    f"messages_sent={len(messages)} "
                    f"payload_chars={len(json.dumps(messages, default=str))}"
                )
                self._append(
                    session, role="assistant",
                    content=msg, is_fallback=True,
                    error_message=f"{msg} | {diag}",
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    latency_ms=result.latency_ms,
                    # P12.M1.1.1 — capture the outgoing payload
                    # for forensic inspection. Adapter already
                    # truncated to 10k chars.
                    request_body_snapshot=result.request_body_snapshot,
                )
                return OrchestratorResponse(
                    success=False, is_fallback=True,
                    assistant_message=(
                        "Sorry -- I can't reach the AI service "
                        "right now. " + msg),
                    error_message=msg,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    latency_ms=total_latency,
                ).to_dict()

            # Persist this assistant turn.
            self._append(
                session,
                role="assistant",
                content=result.assistant_message or "",
                tool_calls_json=(
                    json.dumps(result.tool_calls)
                    if result.tool_calls else ""),
                provider_key=provider.provider_key,
                model_version=provider.model_id,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=result.latency_ms,
            )

            if not result.tool_calls:
                return OrchestratorResponse(
                    success=True,
                    assistant_message=result.assistant_message or "",
                    tool_cards=tool_cards,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    latency_ms=total_latency,
                ).to_dict()

            messages.append({
                "role": "assistant",
                "content": result.assistant_message or "",
                "tool_calls": [
                    {
                        "id": tc["tool_call_id"],
                        "type": "function",
                        "function": {
                            "name": tc["tool_name"],
                            "arguments": json.dumps(tc["params"]),
                        },
                    } for tc in result.tool_calls
                ],
            })

            # Dispatch each tool call with D17 dedup.
            saw_proposal = False
            for tc in result.tool_calls:
                key = _dedup_key(tc["tool_name"], tc["params"])
                cached = dedup_cache.get(key)
                if cached is not None:
                    # D17 — Groq re-emitted an identical call. Reuse
                    # the prior result without dispatching again
                    # AND without pushing a second tool_card. The
                    # tool-role message in `messages` still needs to
                    # be present (Groq protocol requires one tool
                    # response per tool_call_id).
                    tool_result = cached
                    # Annotate so audit log can see this was a dedup
                    # reuse rather than a fresh tool execution.
                    tool_result_for_msg = dict(tool_result)
                    tool_result_for_msg["_dedup_reused"] = True
                else:
                    tool_result = tool_registry.dispatch(
                        tc["tool_name"], self.env, user,
                        tc["params"])
                    dedup_cache[key] = tool_result
                    # D28/D34 — write tool result. Persist a pending
                    # action row, attach the confirmation_token to
                    # the card payload, mark the card as a
                    # confirmation card so the UI renders it as such.
                    if tool_result.get("is_proposal"):
                        prop_res = self.WriteLog.propose(
                            session, user, tool_result)
                        if not prop_res.get("ok"):
                            # 3-pending cap, surfaced as a tool
                            # error the user can read.
                            tool_result = {
                                "ok": False,
                                "error": prop_res.get(
                                    "error", "Proposal rejected."),
                                "tool": tc["tool_name"],
                            }
                            tool_cards.append({
                                "tool": tc["tool_name"],
                                "tool_call_id": tc["tool_call_id"],
                                "params": tc["params"],
                                "result": tool_result,
                            })
                        else:
                            rec = prop_res["record"]
                            card = {
                                "tool": tc["tool_name"],
                                "tool_call_id": tc["tool_call_id"],
                                "params": tc["params"],
                                "is_confirmation_card": True,
                                "confirmation_token": (
                                    rec.confirmation_token),
                                "write_log_id": rec.id,
                                "action_type": rec.action_type,
                                "target_model": rec.target_model,
                                "human_summary": rec.human_summary,
                                "before_state": (
                                    json.loads(rec.before_json)
                                    if rec.before_json else None),
                                "after_state": (
                                    json.loads(rec.after_json)
                                    if rec.after_json else None),
                                "expires_at": (
                                    rec.expires_at.isoformat()
                                    if rec.expires_at else ""),
                                "result": tool_result,
                            }
                            tool_cards.append(card)
                            saw_proposal = True
                    else:
                        tool_cards.append({
                            "tool": tc["tool_name"],
                            "tool_call_id": tc["tool_call_id"],
                            "params": tc["params"],
                            "result": tool_result,
                        })
                    tool_result_for_msg = tool_result
                self._append(
                    session,
                    role="tool",
                    content=json.dumps(tool_result_for_msg),
                    tool_call_id=tc["tool_call_id"],
                    tool_name=tc["tool_name"],
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["tool_call_id"],
                    "name": tc["tool_name"],
                    "content": json.dumps(tool_result_for_msg),
                })

            # D34 — a write proposal ends the LLM turn. The user must
            # confirm or cancel before another iteration. Provide a
            # short steering assistant message so the chat shows
            # context next to the card.
            if saw_proposal:
                steer = (
                    "I have an action ready -- please review and "
                    "confirm or cancel the card above.")
                self._append(
                    session, role="assistant", content=steer,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                )
                return OrchestratorResponse(
                    success=True,
                    assistant_message=steer,
                    tool_cards=tool_cards,
                    provider_key=provider.provider_key,
                    model_version=provider.model_id,
                    prompt_tokens=total_prompt,
                    completion_tokens=total_completion,
                    latency_ms=total_latency,
                ).to_dict()

        # Loop exhausted -- graceful exit message.
        guard_msg = (
            "I've gathered some information but need your guidance "
            "to proceed.")
        self._append(
            session, role="assistant", content=guard_msg,
            is_fallback=True,
            error_message="tool_loop_exhausted",
            provider_key=provider.provider_key,
            model_version=provider.model_id,
        )
        return OrchestratorResponse(
            success=True,
            assistant_message=guard_msg,
            tool_cards=tool_cards,
            is_fallback=True,
            provider_key=provider.provider_key,
            model_version=provider.model_id,
            prompt_tokens=total_prompt,
            completion_tokens=total_completion,
            latency_ms=total_latency,
            error_message="tool_loop_exhausted",
        ).to_dict()

    # ==============================================================
    # Confirm / Cancel (D28 phase 2)
    # ==============================================================
    def confirm_pending_action(self, user, confirmation_token,
                                active_variant=None):
        """Execute the write tied to ``confirmation_token`` under
        ``user`` identity inside a savepoint. Returns a result card
        dict the controller forwards to the UI.

        D29 single-use + replay-safe: a token whose row already has
        status in {executed, cancelled, error, expired} returns the
        recorded result without re-executing. D35 savepoint: any
        exception during execute() rolls back the target write and
        flips status to error.
        """
        rec, code = self.WriteLog.consume_token(
            confirmation_token, user, mode="confirm")
        if code == "not_found":
            return {"ok": False, "error_code": "not_found",
                    "error": "Confirmation token not found."}
        if code == "forbidden":
            return {"ok": False, "error_code": "forbidden",
                    "error": "This action belongs to another user."}
        if code == "expired":
            return {
                "ok": False, "error_code": "expired",
                "error": (
                    "This action expired, please ask again."),
                "write_log_id": rec.id if rec else 0,
            }
        if code == "replay":
            return self._replay_card(rec)
        if code != "ok":
            return {"ok": False, "error_code": code,
                    "error": "Unexpected confirm state."}

        # D36 — write rate limit (consumed only on successful
        # transition out of 'proposed').
        if not _check_write_rate_limit(user.id, consume=True):
            rec.sudo().write({
                "status": "error",
                "error_message": (
                    "write_rate_limit_exceeded: 10 confirmed writes "
                    "per hour cap reached. Try again later."),
                "confirmed_by": user.id,
                "executed_at": fields.Datetime.now(),
            })
            return {
                "ok": False, "error_code": "write_rate_limit_exceeded",
                "error": (
                    "You've hit the 10 writes / hour cap. Try again "
                    "in a few minutes."),
                "write_log_id": rec.id,
            }

        rec.mark_confirmed(user)
        executor = tool_registry.get_executor(rec.action_type)
        if not executor:
            rec.record_execution(
                error_message=(
                    "No executor registered for action_type={}"
                ).format(rec.action_type))
            return {"ok": False, "error_code": "no_executor",
                    "error": "This action cannot be executed.",
                    "write_log_id": rec.id}

        # D35 — savepoint so a forced exception rolls back the
        # mutation without contaminating the parent transaction.
        try:
            params = json.loads(rec.params_json or "{}")
        except json.JSONDecodeError:
            params = {}
        try:
            with self.env.cr.savepoint():
                exec_result = executor(
                    self.env, user, params)
        except Exception as exc:  # noqa: BLE001
            err = "{}: {}".format(type(exc).__name__, exc)
            rec.record_execution(error_message=err)
            return {
                "ok": False, "error_code": "execute_error",
                "error": err,
                "write_log_id": rec.id,
            }
        rec.record_execution(
            created_target_id=exec_result.get("created_target_id"))
        # Append a "result" tool-role chat row so the audit shows the
        # confirmed write in line with the proposal turn.
        session = rec.session_id
        result_payload = {
            "ok": True,
            "action_type": rec.action_type,
            "target_model": (exec_result.get("target_model")
                              or rec.target_model),
            "target_id": (exec_result.get("target_id")
                           or rec.target_id or 0),
            "created_target_id": int(
                rec.created_target_id or 0),
            "target_name": exec_result.get("target_name") or "",
            "human_summary": rec.human_summary,
        }
        self._append(
            session, role="tool",
            content=json.dumps(result_payload),
            tool_name=rec.action_type,
            tool_call_id="confirm:{}".format(rec.id),
        )
        return {
            "ok": True,
            "status": "executed",
            "write_log_id": rec.id,
            "result": result_payload,
        }

    def cancel_pending_action(self, user, confirmation_token):
        rec, code = self.WriteLog.consume_token(
            confirmation_token, user, mode="cancel")
        if code == "not_found":
            return {"ok": False, "error_code": "not_found",
                    "error": "Confirmation token not found."}
        if code == "forbidden":
            return {"ok": False, "error_code": "forbidden",
                    "error": "This action belongs to another user."}
        if code == "expired":
            return {"ok": False, "error_code": "expired",
                    "error": "This action already expired."}
        if code == "replay":
            return self._replay_card(rec)
        # consume_token in 'cancel' mode flips status when starting
        # from 'proposed'. Defensive double-check:
        if code != "cancelled":
            return {"ok": False, "error_code": code,
                    "error": "Unexpected cancel state."}
        return {
            "ok": True,
            "status": "cancelled",
            "write_log_id": rec.id,
        }

    def _replay_card(self, rec):
        """D29 replay-safe: a second submission returns the recorded
        outcome rather than re-executing."""
        result_payload = {
            "ok": rec.status == "executed",
            "action_type": rec.action_type,
            "target_model": rec.target_model,
            "target_id": rec.target_id,
            "created_target_id": int(rec.created_target_id or 0),
            "human_summary": rec.human_summary,
        }
        return {
            "ok": True,
            "status": rec.status,
            "write_log_id": rec.id,
            "result": result_payload,
            "replay": True,
            "error": rec.error_message or "",
        }

    # ==============================================================
    # Helpers
    # ==============================================================
    def _active_provider(self):
        return self.env["neon.dashboard.ai.provider"].sudo().search([
            ("is_default", "=", True),
            ("is_enabled", "=", True),
            ("provider_key", "=", "groq"),
        ], limit=1)

    def _load_history(self, session):
        """D18: count ALL message rows (user / assistant / tool),
        keep the last _HISTORY_MESSAGE_LIMIT, never split an
        assistant turn from its tool replies. Returns rows in
        chronological order (oldest first)."""
        # Fetch ALL non-system messages oldest-first; the slice +
        # tool-pairing fixup happens in memory below.
        rows = self.Message.search(
            [("session_id", "=", session.id),
             ("role", "!=", "system")],
            order="created_at, id",
        )
        if len(rows) <= _HISTORY_MESSAGE_LIMIT:
            return rows
        # Take the last N rows; then walk backwards to find a safe
        # cutoff that doesn't strand a tool message from its
        # parent assistant turn.
        cut_index = len(rows) - _HISTORY_MESSAGE_LIMIT
        # If rows[cut_index] is a tool-role message, we need to
        # back the cut up to the assistant turn that emitted it.
        while (cut_index > 0
               and rows[cut_index].role == "tool"):
            cut_index -= 1
        # If the new cut points AT an assistant turn carrying
        # tool_calls, include that assistant turn (the loop above
        # left us pointing at the assistant). If by chance it is
        # an assistant with NO tool_calls, that's fine — still
        # include it.
        return rows[cut_index:]

    def _build_messages(self, history, latest_user_text,
                         user=None, variant=None):
        sys_prompt = self._system_prompt(user=user, variant=variant)
        messages = [{"role": "system", "content": sys_prompt}]
        for m in history:
            if m.role == "user":
                messages.append({"role": "user",
                                  "content": m.content or ""})
            elif m.role == "assistant":
                msg = {"role": "assistant",
                       "content": m.content or ""}
                if m.tool_calls_json:
                    try:
                        calls = json.loads(m.tool_calls_json)
                        msg["tool_calls"] = [
                            {
                                "id": c["tool_call_id"],
                                "type": "function",
                                "function": {
                                    "name": c["tool_name"],
                                    "arguments": json.dumps(
                                        c.get("params", {})),
                                },
                            } for c in calls
                        ]
                    except (json.JSONDecodeError, KeyError):
                        pass
                messages.append(msg)
            elif m.role == "tool":
                messages.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "name": m.tool_name or "",
                    "content": m.content or "",
                })
        # Ensure the just-appended user turn is the trailing entry.
        if not (messages and messages[-1].get("role") == "user"
                and (messages[-1].get("content") or "")
                == (latest_user_text or "")):
            messages.append({"role": "user",
                             "content": latest_user_text or ""})
        return messages

    def _system_prompt(self, user=None, variant=None):
        Config = self.env["ir.config_parameter"].sudo()
        template = (Config.get_param(_SYSTEM_PROMPT_CONFIG_KEY, "")
                    or _DEFAULT_SYSTEM_PROMPT)
        today = fields.Date.context_today(
            self.env["res.users"].browse(self.env.uid))
        role_label = _ROLE_LABELS.get(
            (variant or "director").lower(), "Sales")
        user_name = (user.name if user else
                      self.env.user.name) or ""
        return (template
                .replace("{today_date}", today.isoformat())
                .replace("{role_label}", role_label)
                .replace("{user_name}", user_name))

    def _append(self, session, role, content="", **kw):
        vals = {
            "session_id": session.id,
            "role": role,
            "content": content,
        }
        for k in ("tool_calls_json", "tool_call_id", "tool_name",
                  "provider_key", "model_version", "prompt_tokens",
                  "completion_tokens", "latency_ms", "is_fallback",
                  "error_message", "request_body_snapshot"):
            if k in kw and kw[k] is not None:
                vals[k] = kw[k]
        msg = self.Message.create(vals)
        session.touch()
        return msg
