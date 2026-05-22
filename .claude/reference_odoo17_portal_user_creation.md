# Path A portal user lifecycle

Established in P7b M8 (per Tatenda direction 22 May 2026). Confirmed end-to-end via P7b integration smoke.

## The problem Path A solves

Phase 7a's `neon.training.certification.user_id` is **required** (`required=True`). During the onboarding cert_collection state -- when a candidate is uploading their certs -- they don't yet have a backend user (those are created at activation, M6).

Two ways to resolve:
- **Path A** -- create a portal-only `res.users` at cert_collection entry. Certs link to that portal user via the existing `user_id` field. **Zero Phase 7a constraint relax.**
- **Path B** -- relax `cert.user_id` to nullable. Wide-blast Phase 7a touch.

Robin / Tatenda decision: Path A.

## At cert_collection entry

In `neon.onboarding.candidate.write()` override (M8):

```python
new_user = self.env["res.users"].sudo().create({
    "name": self.name,
    "login": self.contact_email,
    "email": self.contact_email,
    "password": "NeonPortal2026!",
    "groups_id": [(6, 0, [
        self.env.ref("base.group_portal").id,
    ])],
})
self.user_id = new_user.id
```

Crucially: `groups_id` contains `base.group_portal` ONLY. NOT `base.group_user`. Portal users cannot log into the backend; they only see `/my/*` routes via the portal layout.

Plus audit log entry:
```python
self.env["neon.onboarding.audit.log"].sudo().create({
    "candidate_id": self.id,
    "action": "portal_user_created",
    "actor_id": self.env.user.id or SUPERUSER_ID,
    "reason": "Portal user provisioned on cert_collection entry: " + login,
    "previous_state": self.state,
    "new_state": self.state,
})
```

`previous_state == new_state` because the audit isn't about a state transition -- the candidate stays at `cert_collection`. The `action` enum is the audit discriminator.

## On promote / skip (M6 / M7)

If `candidate.user_id` is already set AND points at a portal user, UPGRADE:

```python
portal_grp = self.env.ref("base.group_portal", raise_if_not_found=False)
if portal_grp and portal_grp in existing_user.groups_id:
    existing_user.sudo().write({
        "groups_id": [
            (3, portal_grp.id),                                    # remove portal
            (4, self.env.ref("base.group_user").id),               # add backend user
            (4, self.env.ref("neon_jobs.group_neon_jobs_crew").id),
            (4, self.env.ref("neon_training.group_neon_training_user").id),
        ],
    })
    # Audit: portal_user_upgraded
```

Critical:
- `(3, portal_grp.id)` REMOVES the portal group. Without this, the user has BOTH portal AND backend groups, which is contradictory and produces confusing UX.
- The 4 `(4, group_id)` adds use ORM tuple syntax so Odoo's `_setup_attrs` / implied_ids cascade fires per `reference_odoo17_implied_ids_orm_vs_sql.md`.
- Same `res.users` record; user keeps their login + cert linkages. Phase 9 sends + cron history all preserved.

## Lifecycle invariants

| State | user_id present? | Group |
|---|---|---|
| candidate | No (typically) | -- |
| cert_collection | YES (just created, portal) | `base.group_portal` only |
| probationary | YES (still portal at this point) | `base.group_portal` only |
| active | YES (upgraded on promote) | `base.group_user + jobs_crew + training_user` |

Downgrade (backend → portal) is **not supported**. One-way ratchet.

## Defensive note for cross-module callers

When Phase 7a code wants to nudge a candidate's notify (M12 pattern), check for portal-vs-backend group state before deciding what UX to show:

```python
if portal_grp in user.groups_id:
    # Portal user -- direct them to /my/onboarding
else:
    # Backend user -- direct them to /web#action=...
```
