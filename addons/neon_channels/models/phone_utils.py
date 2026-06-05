# -*- coding: utf-8 -*-
"""B11 / WA-1 -- phone-number normalization (single source of truth).

The phone-format mismatch class (Meta sends '263...' without '+';
neon.bot.user stores '+263...'; users type spaces/dashes/leading-0) was
patched three times in three places. This helper is THE one place: every
WhatsApp boundary -- webhook/handle_inbound entry, resolve(),
_build_messages history match, lead-intake -- routes the number through
to_e164, so the stored DATA is canonical and a plain == just works.
Default country = Zimbabwe (263).
"""
import re

_DEFAULT_CC = "263"


def to_e164(raw, default_cc=_DEFAULT_CC):
    """Canonicalise a phone number to '+<digits>' E.164.

    Handles: '+263...', '263...', '00263...' (intl prefix), local
    leading-0 ('0772...' -> '+263772...'), spaces/dashes, and bare local.
    Returns '' for empty / no-digit input (never raises). A full
    international number for a DIFFERENT country (>=11 digits, not
    starting with default_cc) is kept as '+<digits>' (not mangled).
    """
    if not raw:
        return ""
    s = str(raw).strip()
    plus = s.startswith("+")
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if digits.startswith("00"):                      # intl 00 prefix
        digits = digits[2:]
    elif not plus and digits.startswith("0"):         # local leading-0
        digits = default_cc + digits[1:]
    # bare local (short, no country code) -> prepend the default country
    if not digits.startswith(default_cc) and len(digits) <= 10:
        digits = default_cc + digits
    return "+" + digits


def to_msisdn(raw, default_cc=_DEFAULT_CC):
    """Digits-only E.164 (no '+'), for APIs/callers that want the bare
    form. '' if uncanonicalisable."""
    e = to_e164(raw, default_cc=default_cc)
    return e[1:] if e.startswith("+") else e
