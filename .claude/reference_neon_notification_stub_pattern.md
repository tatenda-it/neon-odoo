# Neon notification stub pattern (P7b M12 -> Phase 9 wiring)

Established in P7b M12. Phase 9 will override `_notify_send` to wire actual WhatsApp + email dispatch; the 6 event methods stay stable.

## Dispatcher (single override point)

```python
def _notify_send(self, event, channels, subject, body):
    """Stub dispatcher. Phase 9 overrides to send actual
    WhatsApp + email via the dispatch engine.
    """
    self.ensure_one()
    channel_str = ", ".join(channels)
    full_body = (
        "<p><strong>[Notification stub - Phase 9 will send]</strong></p>"
        "<p><b>Event:</b> %s</p>"
        "<p><b>Channels:</b> %s</p>"
        "<p><b>To:</b> %s / %s</p>"
        "<hr/>%s"
    ) % (event, channel_str,
         self.contact_email or "(no email)",
         self.contact_phone or "(no phone)",
         body)
    self.message_post(
        subject=subject, body=full_body,
        message_type="comment",
        subtype_xmlid="mail.mt_note",
    )
```

## 6 event hook methods (all on `neon.onboarding.candidate`)

| Event | Fired by | Channels |
|---|---|---|
| `_notify_portal_user_created` | M8 cert_collection entry hook | email |
| `_notify_cert_uploaded(cert_type)` | M9 portal upload controller | email, whatsapp |
| `_notify_cert_verified(cert)` | Phase 7a cert constrains (M4) | email, whatsapp |
| `_notify_promoted_active()` | M6 Promote wizard | email, whatsapp |
| `_notify_skipped(reason)` | M7 Skip wizard | email |
| `_notify_probationary_gate_block(event_job, role)` | M5 gate log hook | email |

## Defensive triple-guard for cross-module calls

When Phase 7a code calls a notify method on a candidate, three guards stack:

```python
Candidate = self.env.get("neon.onboarding.candidate")    # 1. model present?
if Candidate is not None and violation.get("candidate_id"):
    candidate = Candidate.sudo().browse(violation["candidate_id"])
    if candidate.exists() and hasattr(                    # 2. record exists + method
            candidate, "_notify_probationary_gate_block"):
        candidate.sudo()._notify_probationary_gate_block( # 3. sudo for message_post
            event_job, role)
```

The three guards cover:
1. `env.get()` -- neon_onboarding not installed -> None
2. `hasattr()` -- older neon_onboarding version (pre-17.0.1.10.0) -> no method
3. `sudo()` -- env.user lacks ACL or email config -> message_post would fail

All three are required for Phase 7a to load cleanly with arbitrary neon_onboarding state.

## Phase 9 override pattern

Phase 9 inherits the candidate model:

```python
class NeonOnboardingCandidate(models.Model):
    _inherit = "neon.onboarding.candidate"

    def _notify_send(self, event, channels, subject, body):
        # Phase 9 wiring:
        if "email" in channels and self.contact_email:
            self._send_email(subject, body)
        if "whatsapp" in channels and self.contact_phone:
            self._send_whatsapp(subject, body)
        # Also chatter -- preserve M12 audit trail
        super()._notify_send(event, channels, subject, body)
```

Only `_notify_send` is overridden. The 6 event-specific methods (`_notify_portal_user_created` etc.) stay frozen -- their `channels=[...]` + body content is the API contract.

## Why this pattern (vs separate channel hooks per event)

Considered: separate `_notify_via_email_portal_user_created`, `_notify_via_whatsapp_cert_verified` etc. Rejected because:
- 6 events × 2 channels = 12 methods to maintain
- Channel-specific logic (retry, delivery tracking, template lookup) duplicated
- Body content varies by event, not channel

Single-dispatcher pattern centralises:
- Channel selection (Phase 9 may add SMS, Slack, etc.)
- Retry + delivery tracking (Phase 9)
- Template management (Phase 9)
- Audit trail (chatter post)

## Body marker (do not change without coordinating with Phase 9)

Phase 9's regression smoke greps for the stub marker `[Notification stub - Phase 9 will send]` to confirm fallback path. If a notify message in chatter contains the marker post-Phase-9-deploy, dispatch failed and the M12 stub fired as a backstop.

**Use ASCII hyphen `-` (U+002D), not em-dash `—` (U+2014) or en-dash `–` (U+2013).** Phase 7c M7 first tripped this when the brief used an em-dash; T7c704 caught it pre-deploy.

## Marker greppability — rendered body, not source (Phase 7d M7)

The marker text may live in source as adjacent string literals split across multiple lines:

```python
full_body = (
    "<p><strong>[Notification stub - Phase 9 will "
    "send]</strong></p>"
    "<p><b>Event:</b> %s</p>"
    ...
) % (...)
```

Python concatenates adjacent string literals at compile time, so the **rendered** chatter body has the marker as a single greppable substring. But `inspect.getsource()` sees the split form — a smoke test that checks the source for the literal marker string will report false-negative.

**Lesson** (caught in Phase 7d M7's T7d704):

- Smokes verifying the marker MUST check the rendered body (e.g., `article.message_ids[-1].body`), not the source via `inspect.getsource()`.
- Phase 9's grep regression operates on rendered bodies — it works correctly regardless of source layout. Smokes should follow the same path.

Quick check pattern for a smoke:

```python
bodies = "\n".join(record.message_ids.mapped("body"))
has_marker = "[Notification stub - Phase 9 will send]" in bodies
```

This works whether the source has the marker on one line or split across many.
