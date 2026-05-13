# `.claude/` — local dev fixtures & smoke tests

This folder holds dev-only material that runs against the local
`neon_crm` database via the Odoo shell. Nothing here is part of
the released `neon_jobs` addon — these files are tooling.

## Test users (`p2m75_*`) — fixture policy

The `p2m75_*` test users (`sales`, `mgr`, `lead`, `crew`, `other`,
`t20`) are **stable fixtures** created once during P2.M7. They have
correct group bindings and password hashes. They **should not be
recreated** as part of normal workflow.

### If a session reports "Wrong login/password"

**1. First diagnosis: clear browser cookies for `localhost:8069`
   and Ctrl+F5.**

Stale session cookies referencing old UIDs are the most common
cause. Auth rejection in the browser ≠ broken password in the DB.

**2. Verify via `authenticate()`** — the exact code path the web
login uses:

```bash
docker compose exec -T odoo odoo shell -d neon_crm <<EOF
for login in ['p2m75_sales', 'p2m75_mgr', 'p2m75_lead', 'p2m75_crew']:
    uid = env['res.users'].authenticate(env.cr.dbname, login,
        'test123', None)
    print(f'{login}: {"OK uid=" + str(uid) if uid else "REJECTED"}')
EOF
```

If `OK`: the issue is browser-side. Reset is unnecessary.
If `REJECTED`: passwords need re-setting via `.write()`:

```bash
docker compose exec -T odoo odoo shell -d neon_crm <<EOF
for login in ['p2m75_sales', 'p2m75_mgr', 'p2m75_lead', 'p2m75_crew']:
    u = env['res.users'].sudo().search([('login', '=', login)], limit=1)
    if u:
        u.write({'password': 'test123'})
env.cr.commit()
EOF
```

### The destructive recreate scripts (`.deprecated`)

Two retired scripts live under `.deprecated` for historical
reference. **Do not run either.**

- `recreate_test_users.py.deprecated` — original (P2.M7)
- `recreate_users_v3.py.deprecated` — variant that also manufactures
  a confirmed `commercial.job.crew` assignment for `p2m75_crew`

Both:

- Cascade `unlink()` on `commercial.job.crew` and `mail.activity`
  rows that reference the test users.
- Burn a fresh `res.users` ID range each invocation, which:
  - Invalidates session cookies (the browser starts rejecting auth
    until cookies are cleared)
  - Invalidates `action.centre.item.history` actor references and
    other audit-trail FKs across the DB
  - Was the root cause of repeated "password" blockers during
    Phase 4 development (P4.M1.1 / P4.M3 / P4.M4 sessions)

If group bindings ever genuinely drift on a test user, fix them
via targeted `write({'groups_id': [...]})` on the existing user
record. Do not recreate.

If a fresh confirmed-crew assignment is genuinely needed for
browser deep-link testing, create the assignment directly via the
shell — don't recreate the user just to bundle the assignment:

```python
crew = env['res.users'].search([('login', '=', 'p2m75_crew')], limit=1)
job = env['commercial.job'].search([('state', 'in', ['active', 'pending'])], limit=1)
env['commercial.job.crew'].create({
    'job_id': job.id, 'user_id': crew.id,
    'role': 'tech', 'state': 'confirmed',
})
```

## Smoke test files

- `p2m*_smoke.py`, `p3m*_smoke.py`, `p4m*_smoke.py` — milestone
  regression suites. Run via:
  ```
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < .claude/p4m3_smoke.py
  ```
- `p4m1_smoke.py`, `p4m2_smoke.py`, `p4m3_smoke.py` are tracked in
  git as project regression infrastructure. The Phase 2 / Phase 3
  smokes are untracked dev artefacts but follow the same pattern.

## Other untracked ad-hoc scripts

`set_test_passwords.py`, `p2m7_diagnose.py`, `fix_implications.py`
— leftover one-shot diagnostics. Keep or delete per your
judgement; none should run as part of a routine workflow.
