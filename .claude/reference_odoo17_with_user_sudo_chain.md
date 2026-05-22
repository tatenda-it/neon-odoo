# `with_user().sudo()` chain for owner-checked methods

Surfaced during P7b M9 build. Lesson learned the hard way (one smoke iteration burned).

## The problem

Phase 7a action methods often have an internal "must be owner OR admin" check:

```python
def action_submit_for_verification(self):
    for rec in self:
        if (rec.user_id != self.env.user
                and not self.env.user.has_group(
                    "neon_training.group_neon_training_signoff")
                and not self.env.user.has_group(
                    "neon_training.group_neon_training_admin")):
            raise AccessError(...)
        rec.write({"state": "pending_verification"})
        ...
```

When called via plain `.sudo()`, `env.user` becomes SUPERUSER. SUPERUSER usually does NOT match `rec.user_id`, AND SUPERUSER's `has_group()` may return False for non-implied groups. Result: `AccessError` raised.

If the calling code wraps in `try/except`, the error is silently swallowed -- the user-facing operation appears to succeed (cert created, attachment linked) but the underlying state transition never happens. Hours of debugging.

## The fix

Chain `with_user()` BEFORE `sudo()`:

```python
cert.with_user(cert.user_id).sudo().action_submit_for_verification()
```

Effect:
- `with_user(cert.user_id)` sets `env.user = cert.user_id`
- `.sudo()` flips `su=True` (ACL bypass)
- `env.user` STAYS as `cert.user_id` (sudo only changes su flag, not uid)

The owner-check sees `env.user == cert.user_id` -- True -- and the check passes. The internal `write()` proceeds under `su=True` regardless of the portal user's ACL on the model.

## When to use

Whenever you're calling a Phase 7a (or any) method that:
1. Has an internal env.user check (owner OR specific group)
2. AND the calling context lacks the required ACL (portal controller, cron, async worker)
3. AND the legitimate "owner" is known and authorized for that operation

## Anti-patterns

```python
# WRONG -- silently fails the owner check
cert.sudo().action_submit_for_verification()

# WRONG -- changes uid AND su=False (back to default), may pass owner check
# but fails ACL on internal write
cert.with_user(cert.user_id).action_submit_for_verification()

# WRONG -- order matters; sudo() resets uid
cert.sudo().with_user(cert.user_id).action_submit_for_verification()
```

## Right pattern (in M9 controller)

```python
cert.with_user(candidate.user_id).sudo().action_submit_for_verification()
```

The portal user is the cert owner. with_user sets env.user to them, sudo bypasses portal-tier ACL on the rest of the call.

## Audit trail consequence

The chatter post inside `action_submit_for_verification` will show the **with_user** user as the author (not SUPERUSER). That's usually what you want -- the audit reads "Submitted for verification by <portal user>" rather than "by SUPERUSER".
