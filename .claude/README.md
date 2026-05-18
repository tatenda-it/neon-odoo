# `.claude/` — local dev fixtures & smoke tests

This folder holds dev-only material that runs against the local
`neon_crm` database via the Odoo shell. Nothing here is part of
the released `neon_jobs` addon — these files are tooling.

## Test users (`p2m75_*`) — fixture policy

> **Local dev only.** These test users live ONLY on the local dev
> database. They do NOT exist on the Hetzner production database.
> The real Neon team accounts (`robin@neonhiring.co.zw`,
> `munashe@neonhiring.co.zw`, `lisar@neonhiring.co.zw`,
> `evrill@neonhiring.co.zw`, `ranganai@neonhiring.co.zw`,
> `admin@neonhiring.co.zw`) are reserved for cutover and are
> **never** used for automated testing.

Eight persistent test fixtures, managed by `.claude/p2m7_5_smoke.py`
via a `_get_or_create_user` helper. `user_id`s are **stable across
regression runs** — the smoke does not unlink-and-recreate. On every
setUp the helper re-asserts the **baseline** `groups_id` set via
`(6, 0, [...])` replace semantics; manual UI customisations on these
users (an admin adding a group via Settings → Users) are wiped on
next setUp. If a scenario needs a user with non-baseline groups,
**add a new fixture** — don't mutate an existing one.

| Login           | Role                  | Groups                                                       | Purpose                                                            |
|-----------------|-----------------------|--------------------------------------------------------------|--------------------------------------------------------------------|
| p2m75_sales     | Sales rep             | `base.group_user`, `neon_jobs.group_neon_jobs_user`          | Quote drafting; read-only on operations                            |
| p2m75_mgr       | Operations manager    | `base.group_user`, `neon_jobs.group_neon_jobs_manager`       | Full ops authority. **NOT a finance role.**                        |
| p2m75_lead      | Lead Tech             | `base.group_user`, `neon_jobs.group_neon_jobs_crew_leader`   | Workshop ops, crew assignment authority                            |
| p2m75_crew      | Crew member           | `base.group_user`, `neon_jobs.group_neon_jobs_crew`          | Own-assignment edit; "self" tier in ownership-isolation tests      |
| p2m75_other     | Other crew            | `base.group_user`, `neon_jobs.group_neon_jobs_crew`          | Counterpart for "other person's record" tests                      |
| p2m75_t20       | Throwaway crew        | `base.group_user`, `neon_jobs.group_neon_jobs_crew`          | Spawned mid-T20 to dodge a UNIQUE (job_id, user_id) constraint     |
| p2m75_book      | Bookkeeper            | `base.group_user`, `neon_finance.group_neon_finance_bookkeeper` | Phase 6+ rate-card / conversion-rate maintenance role            |
| p2m75_approver  | Approver              | `base.group_user`, `neon_finance.group_neon_finance_approver`   | Phase 6+ quote / cost-line approval authority                    |

To wipe completely (rare — only when group bindings or
implications genuinely drift): drop the database and re-install.
A normal `-u` does **not** advance the `res_users_id_seq` because
the helper finds existing rows by login and reuses them.

The P2.M7-era guidance below — referring to "stable fixtures created
once during P2.M7" — was aspirational until the P2.M7.5.1 refactor
(2026-05-18); from that commit forward, the description matches the
implementation.

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

These pre-date the P2.M7.5.1 fixture refactor when `p2m7_5_smoke.py`
also did unlink-and-recreate on every run; the refactor removed
that anti-pattern from the active smoke, and the scripts below
remain only for historical reference. **Do not run either.**

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
