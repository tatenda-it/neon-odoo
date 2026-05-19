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

## Browser smokes

The in-container Python smokes (`p*_smoke.py`) cover the ORM layer
authoritatively but cannot see the rendered user-facing surface:
whether a menu is visible to a role, whether an action's tree view
loads with the expected row count, whether a form's notebook tabs
populate. The browser smokes close that gap.

### Architecture

`.claude/browser_smoke.py` is a Playwright-based harness; each
milestone owns one concrete smoke (`pXmY_browser_smoke.py`) that
drives the harness through the journeys relevant to that milestone.
Failure of any scenario aborts the regression pipeline with the
same exit-1 discipline as the Python smokes; per-run artefacts land
under `.claude/smoke-output/<smoke>/<YYYY-MM-DD_HHMMSS>/`.

```text
.claude/
  browser_smoke.py             # harness: BrowserSmoke context manager
  p6m1_browser_smoke.py        # concrete: 4 scenarios, 4 tier checks
  smoke-output/                # gitignored
    p6m1/
      2026-05-19_094939/
        01_book_pricing_rules_list.png
        02_book_pricing_rule_form_brackets.png
        ...
        result.json            # machine-readable summary
      latest.txt               # timestamp of the most recent run
```

`run_regression.sh` runs every Python smoke first; if all pass, the
browser-smoke gate fires next, iterating over every smoke listed in
the `BROWSER_SMOKES` array.

### One-time install (already done on this box)

```powershell
winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements --scope user
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -m venv C:\Users\Neon\neon-odoo\.claude\.venv-browser
$venvPy = "C:\Users\Neon\neon-odoo\.claude\.venv-browser\Scripts\python.exe"
& $venvPy -m pip install "playwright==1.49.*"
& $venvPy -m playwright install chromium
```

The venv + Chromium download total ~250 MB. `.claude/.venv-browser/`
and `.claude/smoke-output/` are both gitignored.

### Running a smoke manually

```powershell
.\.claude\.venv-browser\Scripts\python.exe .\.claude\p6m1_browser_smoke.py
```

The harness prints a per-assertion log, writes `result.json`, updates
`latest.txt`, and exits 0 on PASS / 1 on FAIL.

### The depth principle

> For every menu the smoke verifies as visible, CLICK INTO IT and
> assert at least one piece of content --- row count, a specific
> cell value, a form's notebook tab populated.

Menu visibility alone proves the route is exposed; depth assertions
prove the action behind the menu still works. P6.M1's bug post-mortem
showed 3 of 4 bugs surfaced as "menu visible but action broken" --- a
visibility-only smoke would have caught one. The harness contract
applied here would have caught all four.

Negative tests (menu NOT visible / app NOT in launcher) don't need
depth --- absence is its own evidence. For ACL boundaries the ORM
smokes still own the authoritative proof; the browser smoke includes
at most one `assert_rpc_denied(...)` per negative tier when proving
the negative from positive UI evidence alone would be too soft (e.g.
"app icon not in launcher" doesn't preclude a hand-crafted URL
reaching the model).

### Adding a new browser smoke for a future milestone

1. Copy `.claude/p6m1_browser_smoke.py` to `pXmY_browser_smoke.py`.
2. Replace the action xmlid + expected row counts + menu xmlids.
3. Apply the depth principle: for each visible menu, open the action
   and assert at least one content fact. For each row-list scenario
   open one row and assert one fact on the form (notebook tab, field
   value, computed total).
4. Add `pXmY` to the `BROWSER_SMOKES` array in `run_regression.sh`.
5. Run the smoke locally. Expect green; if red, see spot-check below.

The harness exposes (see `browser_smoke.py` for full signatures):

| Method | Purpose |
|---|---|
| `login(username, password='test123')` | /web/login form auth; switches context if username changes |
| `assert_menu_visible(xmlid)` / `assert_menu_hidden(xmlid)` | Via `ir.ui.menu.load_web_menus` — same source the web client uses |
| `open_action(xmlid)` | Resolves xmlid → numeric id, navigates `/web#action=<id>` |
| `goto_home()` | `/web` (NOT `/odoo` — that path 404s on this build) |
| `assert_visible(selector, name)` | First matching element becomes visible within timeout |
| `assert_count(selector, expected, name)` | OWL views render async; helper polls until count settles |
| `click(selector, name=None)` | First matching element |
| `assert_rpc_denied(model, method, name, args, kwargs)` | Asserts `odoo.exceptions.AccessError` |
| `screenshot(label)` | Numbered, full-page PNG into the run's output dir |

### Spot-check protocol (when to pause for review)

When a scenario fails, the harness drops three artefacts next to the
PASS screenshots:

* `99_FAIL_<assertion>.png` — full-page screenshot at the moment of failure
* `99_FAIL_<assertion>.txt` — assertion + URL + selector + DOM snippet around the locator + a heuristic diagnosis line + the explicit prompt: *"PAUSE — recommend fix direction X; second opinion before applying?"*
* The `result.json` carries the `expect`/`actual` and the per-scenario `fail` message.

Routine PASS flows through to the next gate without intervention.
**FAIL is the cue to pause** and surface the bundle to Tatenda:

* Which assertion failed (path + expected vs actual)
* The screenshot at the point of failure
* The DOM snippet around the failed element
* The harness's heuristic diagnosis
* Proposed fix direction with the question "second opinion before applying?"

The heuristic in `BrowserSmoke._diagnose` covers the common drift
patterns (group gating, OWL render timing, selector drift after an
Odoo upgrade, ACL regression). It is best-effort guidance, not
diagnosis-of-record.
