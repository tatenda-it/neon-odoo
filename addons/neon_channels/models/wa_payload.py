# -*- coding: utf-8 -*-
"""B11 / WA-1 -- WhatsApp interactive tap-back payload-id scheme.

Pure, request-free helpers (like ``phone_utils``). A reply button /
list row carries a stable id we control; Meta echoes it back verbatim on
the tap. We encode ``intent + targets`` into that id and HMAC-sign it
(truncated SHA-256 over the body, keyed by Odoo's ``database.secret``).

On the inbound tap, :func:`decode` verifies the signature AND that the
intent is known. A tampered, unknown, or malformed id -> ``None`` so the
caller falls back safely -- the SAME fail-safe discipline as the WA
resolver's ``>1-match -> UNRESOLVED``. The signature is the FIRST of two
layers; every route then re-checks against the user's scope / ACL /
write.log token (so a stolen-but-valid id still can't act out of scope).

⚠️ DECISION (WA-1): reuse ``database.secret`` as the signing key rather
than minting a new parameter -- it already exists, is per-DB, and is
Odoo's canonical signing secret. The secret is passed IN by the caller
so this module stays env-free and unit-testable.
"""
import hashlib
import hmac
import logging

_logger = logging.getLogger(__name__)

SEP = ":"
_SIG_LEN = 10  # hex chars kept from the HMAC (collision-safe for ids)

# Known intents. An id whose prefix is not here -> decode returns None.
# WA-2 adds crew_confirm / crew_decline -- carried as the PAYLOAD of a
# template quick-reply button (inbound type 'button'), routed by the
# neon_crew_comms bridge, NOT by the Copilot handle_tap router.
INTENTS = frozenset({
    "confirm", "cancel", "stage", "pick_lead", "pick_job", "menu",
    "crew_confirm", "crew_decline",
    # WA-4: dual-role lens pick. lens:<variant>:<inbound_msg_id>:<sig> --
    # the ambiguous-intent 2-button ask; the tap sets the lens for that
    # turn and re-runs the original message under it.
    "lens",
    # WA-5: client-lane handoff -> sales assignment loop (MAPPED staff
    # taps, routed via the Copilot handle_tap -> _wa5_handle_assign_tap).
    #   assign_open:<lead_id>            -- Munashe opens the assignee list
    #   assign_pick:<lead_id>:<user_id>  -- Munashe picks the salesperson
    #   assignee_decline:<lead_id>:<user_id> -- assignee bounces it back
    # WA-5.3: the assignee message is THREE reply-buttons (Chat / Odoo /
    # decline); a reply-button can't BE a URL (D3), so Chat/Odoo REPLY
    # with the wa.me / Odoo deep-link when tapped.
    #   assignee_chat:<lead_id>  -- bot replies with the client wa.me link
    #   assignee_odoo:<lead_id>  -- bot replies with the Odoo lead link
    # WA-5.5: the MANAGER (escalation) message gets the SAME 3-button
    # treatment -- Chat / Odoo reply-buttons alongside the existing
    # assign_open (the assignee list). Same lead-based link replies.
    #   escalation_chat:<lead_id>  -- bot replies with the client wa.me link
    #   escalation_odoo:<lead_id>  -- bot replies with the Odoo lead link
    "assign_open", "assign_pick", "assignee_decline",
    "assignee_chat", "assignee_odoo",
    "escalation_chat", "escalation_odoo",
    # WA-6: crew + OD equipment face (MAPPED staff; routed by the
    # neon_crew_comms bridge's handle_inbound intercept BEFORE super(),
    # never by the Copilot handle_tap -- same pattern as crew_confirm).
    # Face 2 -- OD initiate 3-button choice (each carries event_job_id):
    #   wa6_fin_self:<event_job_id>   -- "I'll finalize" (OD keeps it)
    #   wa6_fin_route:<event_job_id>  -- "Send to crew chief" (routes)
    #   wa6_fin_odoo:<event_job_id>   -- "Open in Odoo" (deep-link reply)
    # Face 2 -- finalize review (carry the equip session id):
    #   wa6_confirm:<session_id>          -- confirm the matched list
    #   wa6_fix:<session_id>              -- "Fix an item" (open row list)
    #   wa6_fixrow:<session_id>:<index>   -- pick the row to patch
    # Face 3 -- warehouse checkout (event_job_id / line_id):
    #   wa6_co_all:<event_job_id>   -- check out ALL gear
    #   wa6_co_item:<event_job_id>  -- item-by-item (open line list)
    #   wa6_co_line:<line_id>       -- check out ONE line
    # Face 3 -- warehouse check-in (event_job_id):
    #   wa6_ci_good:<event_job_id>  -- all returned good (headless wizard)
    #   wa6_ci_flag:<event_job_id>  -- flag an item (bounce to Odoo)
    "wa6_fin_self", "wa6_fin_route", "wa6_fin_odoo",
    "wa6_confirm", "wa6_fix", "wa6_fixrow",
    "wa6_co_all", "wa6_co_item", "wa6_co_line",
    "wa6_ci_good", "wa6_ci_flag",
})


def _sig(secret, body):
    key = (secret or "").encode("utf-8")
    return hmac.new(
        key, body.encode("utf-8"), hashlib.sha256).hexdigest()[:_SIG_LEN]


def encode(secret, intent, *parts):
    """``intent`` + ``parts`` -> ``'intent:p1:...:sig'``.

    Parts are stringified and must not contain the separator (ids are
    numeric / uuid hex in practice, so this never bites legitimately).
    Raises ValueError on an unknown intent or a separator in a part --
    both are programming errors at SEND time, not attacker input.
    """
    if intent not in INTENTS:
        raise ValueError("unknown WA payload intent %r" % (intent,))
    clean = [str(p) for p in parts]
    for p in clean:
        if SEP in p:
            raise ValueError("WA payload part contains %r: %r" % (SEP, p))
    body = SEP.join([intent] + clean)
    return body + SEP + _sig(secret, body)


def decode(secret, payload_id):
    """``'intent:...:sig'`` -> ``(intent, [parts])`` iff the signature
    verifies and the intent is known; otherwise ``None``. Never raises --
    any malformed input is treated as a safe-fallback miss."""
    if not payload_id or SEP not in payload_id:
        return None
    try:
        body, sig = payload_id.rsplit(SEP, 1)
        bits = body.split(SEP)
        intent = bits[0]
        if intent not in INTENTS:
            return None
        if not hmac.compare_digest(sig, _sig(secret, body)):
            _logger.warning(
                "WA tap: payload signature mismatch (intent=%s) -- "
                "treating as UNRESOLVED.", intent)
            return None
        return (intent, bits[1:])
    except Exception:  # noqa: BLE001 -- decode must never raise
        return None
