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
    # WA-7: crew selection (MAPPED OD/superuser; routed by the
    # neon_crew_comms bridge intercept BEFORE WA-6). The list-then-pick
    # steps (job / people / chief) use NUMBER replies via the crew session
    # FSM; only the final buttons carry intents (each = the session id):
    #   wa7_confirm:<session_id>  -- create the crew rows (as the real OD)
    #   wa7_change:<session_id>   -- re-pick the team (back to people step)
    #   wa7_notify:<session_id>   -- fire the EXISTING WA-2 confirm/decline
    "wa7_confirm", "wa7_change", "wa7_notify",
    # WA-10: post-event feedback loop (MAPPED staff; routed by the
    # neon_crew_comms bridge intercept AFTER WA-8, before WA-6). The
    # check-in push sends sentiment buttons; a tap records a
    # commercial.event.feedback row + opens a short note session.
    #   wa10_fb:<event_job_id>:<role>:<sentiment>  -- record the sentiment
    #   wa10_notes:<fb_id>:done                    -- close the note session
    #   wa10_pull (reserved; the "feedback" PULL pick uses NUMBER replies
    #     via the fb_pull session, not a tap)
    "wa10_fb", "wa10_notes", "wa10_pull",
    # WA-12: quote-by-WhatsApp (MAPPED sales-capable staff; routed by the
    # neon_crew_comms bridge intercept AFTER WA-10, before WA-6). The MD/OD
    # approval ping's cold-window TEMPLATE quick-reply buttons route by their
    # button TEXT ("Approve"/"Reject"/"View PDF" -- Meta strips emoji), the
    # SAME mechanism as WA-2's crew_confirm; the IN-WINDOW interactive buttons
    # carry these HMAC payloads (each = the quote id):
    #   wa12_approve:<quote_id>   -- MD/OD approves -> action_approve
    #   wa12_reject:<quote_id>    -- MD/OD rejects  -> prompt for a comment
    #   wa12_view_pdf:<quote_id>  -- send the (draft|final) quote PDF in-chat
    #   wa12_send:<quote_id>      -- requester sends the approved quote to client
    "wa12_approve", "wa12_reject", "wa12_view_pdf", "wa12_send",
    # WA-12.3 -- tappable candidate/variant pick on a q_items buffer line
    # (stable lid) OR a q_confirm draft line (real line id). Routed by the
    # neon_crew_comms bridge intercept (q_items/q_confirm session), NOT Copilot.
    #   wa12_pick:<session_id>:<target>:<product_id>  -- bind product to target
    #       target = 'b<lid>'  (a q_items buffer line, stable lid)
    #             | 'l<line_id>' (a q_confirm draft quote.line)
    #   wa12_pick_more:<session_id>:<target>   -- ">10" overflow: re-prompt narrow
    #   wa12_pick_skip:<session_id>:<target>   -- "none of these" -> leave unmatched
    "wa12_pick", "wa12_pick_more", "wa12_pick_skip",
    # WA-12.4 -- one-item stepper confident-line confirm/change. Each carries
    # (session_id, 'b<lid>', seq); the product is on the buffer line, not the
    # payload. The LIST taps reuse wa12_pick/_more/_skip with a trailing :<seq>.
    #   wa12_ok:<session_id>:b<lid>:<seq>      -- ✓ Correct -> confirmed, advance
    #   wa12_change:<session_id>:b<lid>:<seq>  -- ✗ Change  -> open the pick LIST
    "wa12_ok", "wa12_change",
    # WA-12 menu entry: the deterministic Hello/menu "Quote a client" row taps
    # straight into the structured quote flow (begin_structured). Carries the
    # bot_user id only (identity comes from the inbound phone; the handler
    # re-checks _wa12_can_quote). Caught by the neon_crew_comms WA-12 intercept.
    #   wa12_start:<bot_user_id>
    "wa12_start",
    # WA-13: quote/invoice retrieval + invoice-from-quote (routed by the
    # neon_crew_comms bridge intercept AFTER WA-12, before WA-6). Retrieval and
    # the schedule-stage pick use NUMBER replies via the doc_pick / inv_pick
    # sessions (not taps); the Face-2 two-phase generate CONFIRM is HMAC
    # buttons. Registered unconditionally -- encode() raises on an unknown
    # intent, so the interactive [Confirm]/[Cancel] buttons need the names here:
    #   wa13_inv_confirm:<schedule_id>  -- the approver confirms generation ->
    #                                      schedule.action_trigger_now (DRAFT)
    #   wa13_inv_cancel:<schedule_id>   -- the approver cancels the generation
    #   wa13_inv_pick:<schedule_id>     -- (reserved) tap-to-pick a scheduled
    #     stage; the live build uses NUMBER replies via the inv_pick session
    "wa13_inv_confirm", "wa13_inv_cancel", "wa13_inv_pick",
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
