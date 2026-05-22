# Cert verification routing -- Neon-specific override

**Status:** Active as of 2026-05-22 (`neon_training` 17.0.8.0.1)
**Scope:** Training cert verification TODO routing only.
**Code location:** `addons/neon_training/models/neon_training_certification.py`
**Constant:** `_CERT_VERIFIER_LOGINS`

## Summary

Phase 7a's M7 introduced sign-off authority routing: cert TODOs
fanned out by `cert_type.sign_off_authority` (lead_tech / od_md /
external_trainer / self_with_peer) to the corresponding Odoo group.
After `neon_core` landed (Phase 11), superuser-tier members got
cascaded into every authority group, so first-by-id pick collapsed
to Robin for everything.

Tatenda's direction (22 May 2026): the cascade is fine; routing is
the problem. Cert verifications should ALWAYS route to managerial
superusers regardless of cert type. Either Robin OR Munashe can
sign; dual signoff is NOT required. Tatenda is explicitly excluded
from the verifier pool (developer-superuser, not managerial).

The `sign_off_authority` field on `neon.training.certification.type`
stays as documentation. M5's renewal-CC broadcast
(`_resolve_cc_partners`) and M7's `action_verify` authority gate
both continue to consume it. Only the verification-TODO routing
helper (`_resolve_verify_authority_partners`) is overridden.

## CERT_VERIFIER_LOGINS

```python
_CERT_VERIFIER_LOGINS = (
    "robin@neonhiring.co.zw",
    "munashe@neonhiring.co.zw",
)
```

To add or change verifiers: edit this tuple, bump the manifest
patch version, redeploy. The override picks the alphabetically
first verifier as the TODO assignee; both are subscribed as
followers of the cert thread so both receive notifications.

## Routing semantics

`_resolve_verify_authority_partners` (signature preserved for
caller compatibility) returns `(target_user, fallback_applied,
group_xmlid)`:

- `target_user`: first verifier sorted by login. Empty recordset
  if neither verifier exists / is active on this DB.
- `fallback_applied`: always `False` under the override. No
  group-based fallback semantics; verifiers are explicit logins.
- `group_xmlid`: sentinel string `"cert_verifier_managerial"`
  (not a real Odoo group). Used in chatter when verifiers are
  absent so deploy-gap detection still works.

`_create_verification_todo` schedules the TODO on
`target_user`, then subscribes ALL active verifiers as
followers via `message_subscribe`. Either verifier completing
`action_verify` clears the cert; the unused TODO can be
discarded manually or left dangling (the dedup search keys on
`summary=ilike Verify%` so re-submission is idempotent).

## When both verifiers are absent (deploy gap)

`_create_verification_todo` posts a "Verifier routing gap"
chatter note listing the expected logins. No TODO is created.
This catches the case where neither managerial superuser is
provisioned on the target DB -- e.g., fresh-install on a new
prod tenant before the first user-creation step.

## Reasoning behind the override location

Lives in `neon_training`, not `neon_core`, because the policy is
training-specific. Other modules needing similar overrides
(Phase 7e LMS course-completion signoff, future approval flows)
follow the same pattern: define a module-local
`_<MODULE>_VERIFIER_LOGINS` tuple, override the routing helper.

`neon_core` provides the meta-group infrastructure; `neon_training`
makes the policy decision about who-can-sign for training certs
specifically.

## Test contract (p7a_m7_smoke.py)

T7700-T7702 assert TODO recipient is IN `CERT_VERIFIER_LOGINS`
and both verifiers are subscribed as followers. T7704 verifies
the deploy-gap chatter when verifiers are absent. T7718 verifies
the gap chatter names both expected verifier logins.

Tests for `_SIGN_OFF_AUTHORITY_GROUP` (T7720) and `_resolve_cc_
partners` (T7721) stay unchanged -- those code paths still
consume the per-authority group mapping.

## Migration pattern (Phase 11 cutover)

For DBs with existing pending-verification certs whose TODOs
were assigned to the old authority-group recipients:

```python
existing_pending_certs = env['neon.training.certification'].search([
    ('state', '=', 'pending_verification'),
])

verifier_partners = env['res.users'].search([
    ('login', 'in', list(_CERT_VERIFIER_LOGINS)),
    ('active', '=', True),
]).mapped('partner_id')

for cert in existing_pending_certs:
    cert.message_subscribe(partner_ids=verifier_partners.ids)
    activity = env['mail.activity'].search([
        ('res_model', '=', 'neon.training.certification'),
        ('res_id', '=', cert.id),
        ('summary', 'ilike', 'Verify'),
    ], limit=1)
    if activity and verifier_partners[:1].user_ids:
        activity.user_id = verifier_partners[:1].user_ids[:1]

env.cr.commit()
```

Local + prod DBs are effectively no-op (zero pending-verification
certs at 17.0.8.0.1 deploy time). Pattern documented for future
re-routes if `_CERT_VERIFIER_LOGINS` changes.
