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
INTENTS = frozenset({
    "confirm", "cancel", "stage", "pick_lead", "pick_job", "menu",
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
