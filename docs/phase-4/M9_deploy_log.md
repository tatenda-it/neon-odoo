# P4.M9 — Hetzner deploy log

## Summary

Phase 4 (Action Centre engine + 9 triggers + UI polish + hotfix) shipped
to the Hetzner production server. Module version jumped end-to-end across
the milestone:

- **Pre-deploy**: `17.0.2.7.2` (end of P3.M8, prod hotfix HEAD `0d682e4`)
- **Post-deploy**: `17.0.3.6.1` (HEAD `4489d35`, P4.M8.1 hotfix)

Branch deployed: `feat/finance-phase-b1` (per D1 — no merge to `main` yet;
that comes at end-of-build).

## Timeline (2026-05-14, all times UTC)

| Time | Step |
|---|---|
| 09:59:02 | Pre-deploy `pg_dump` of `neon_crm` → `/root/backups/pre_p4m9_20260514_095902.sql` (17 MB) |
| 09:59:30 | `git fetch origin` + `git pull --ff-only origin feat/finance-phase-b1` — clean fast-forward `0d682e4..4489d35`, 39 files, +6593 lines |
| 09:59:35 | `docker compose stop odoo` — graceful stop of the live HTTP container |
| 09:59:38 | `docker compose run --rm odoo odoo -d neon_crm -u neon_jobs --stop-after-init` — module upgrade ran in ~2s; only one migration fired (17.0.3.5.0 post-migrate, no-op because the `trigger_config_scope_change` record was created fresh as `lead_tech` rather than migrated from a pre-existing `sales` value) |
| 09:59:40 | `docker compose up -d odoo` — fresh HTTP container started |
| 09:59:55 | HTTP 200 on `/web/login` |
| 10:00:21 | V1–V6 verification via `odoo shell` — all passed |

**Total deploy window**: ~80 seconds end to end, with ~25 seconds of
HTTP unavailability between `docker compose stop` and the new container
serving 200.

## Verifications

| ID | Check | Result |
|---|---|---|
| V1 | `odoo` container Up | `Up 22 seconds` post-start ✓ |
| V2 | Manifest version on disk | `17.0.3.6.1` ✓ |
| V3 | No upgrade-related ERROR/CRITICAL in `docker compose logs --tail=400` | Only pre-existing scanner-traffic 400/505 errors from a remote IP (timestamps from 07:20, hours before deploy) ✓ |
| V4 | `env["res.users"].search_count([])` | 9 active users (13 rows total, 4 inactive system rows) ✓ |
| V5 | `env.ref("neon_jobs.menu_action_centre")` resolves | True ✓ |
| V6 | `len(TRIGGER_REGISTRY)` | 10 entries ✓ |
| — | DB-reported `ir_module_module.neon_jobs.installed_version` | `17.0.3.6.1`, state=`installed` ✓ |

## Migration that fired

The upgrade range `17.0.2.7.2 → 17.0.3.6.1` includes one post-migrate
script:

- `addons/neon_jobs/migrations/17.0.3.5.0/post-migrate.py` — flips
  `trigger_config_scope_change.primary_role` from `sales` to `lead_tech`
  if and only if the existing value is still the old default `sales`.
  On Hetzner, the trigger_config row did not exist pre-deploy (Phase 4
  had never run here), so the data file created it directly with the
  current XML value `lead_tech`, and the migration's defensive check
  saw `lead_tech ≠ sales` and skipped. **Logged no-op as designed:**
  `"trigger_config_scope_change primary_role is 'lead_tech' (already
  customised); leaving it."`

## Pre-existing observations (not regressions)

- Two view-load warnings in the upgrade output, both pre-existing in
  the codebase:
  - `<i>` with `fa` class missing `title` attribute in
    `commercial_job_dashboard_views.xml:106` (accessibility hint, not
    a blocker).
  - `active_id` in expressions deprecated, in `crm_lead_views.xml` and
    `sale_order_views.xml` (Odoo 17 deprecation, not P4-introduced).

- The `1 Untracked` working-tree file noted in pre-deploy discovery
  (`config/odoo.conf.pre-phase1-backup`) is untouched and remains in
  place — it's a local config backup outside git's scope.

## Production users observation

The Hetzner DB already has the real team's accounts provisioned with
corporate emails:

```
robin@neonhiring.co.zw       (active)
tatenda@neonhiring.co.zw     (active)
munashe@neonhiring.co.zw     (active)
lisar@neonhiring.co.zw       (active)
evrill@neonhiring.co.zw      (active)
ranganai@neonhiring.co.zw    (active)
admin@neonhiring.co.zw       (active)
neonbot@neonhiring.co.zw     (active)
n8n@neonhiring.co.zw         (active)
```

No `p2m75_*` synthetic test users exist on production — Hetzner has
never received the dev-only fixture seed (`.claude/p2m7_5_smoke.py`),
which is the correct steady state per D5.

## Rollback procedure (if needed post-deploy)

To revert to pre-deploy state (commit `0d682e4`, version `17.0.2.7.2`):

```bash
ssh root@188.245.154.84
cd /opt/neon-odoo
git checkout 0d682e4
docker compose stop odoo
docker compose run --rm odoo odoo -d neon_crm -u neon_jobs --stop-after-init
docker compose up -d odoo
```

**Caveat on data state**: rollback does **not** restore database state
from before the `17.0.3.5.0` post-migrate. Since that migration was a
logged no-op on Hetzner (the `trigger_config_scope_change` record was
created fresh during this deploy, not migrated from an older `sales`
value), rollback is effectively code-only — Postgres will keep the
trigger_config rows created during this upgrade, plus any new
action_centre_item rows created post-deploy. If you specifically need
the pre-deploy DB state, restore from the backup:

```bash
ssh root@188.245.154.84
docker compose -f /opt/neon-odoo/docker-compose.yml exec -T db psql -U odoo -d postgres -c "DROP DATABASE neon_crm WITH (FORCE);"
docker compose -f /opt/neon-odoo/docker-compose.yml exec -T db psql -U odoo -d postgres -c "CREATE DATABASE neon_crm OWNER odoo;"
docker compose -f /opt/neon-odoo/docker-compose.yml exec -T db psql -U odoo -d neon_crm < /root/backups/pre_p4m9_20260514_095902.sql
```

(restore takes a few minutes; the dump is 17 MB).

## Browser smoke

Pending. Will be exercised from a local Chrome session against
`http://188.245.154.84:8069/` once the user has time. The 12-point
M8 + M8.1 visual checklist applies — kanban priority chips,
overdue/due-soon decorations, form Overdue banner, Mark Done
button visibility, the three hotfix checks (Due Soon filter
without UncaughtPromiseError, generic "My Items" pill label,
hidden Mark Done for non-authorised users).

## Deviations from procedure

None. The tighter sequencing (stop → upgrade → start, replacing the
original overlap pattern) per Tatenda's refinement was the only
modification, and it worked cleanly.

## Addendum — production smoke seed (2026-05-14)

After the code deploy and verification, a dummy-data seed was applied
to populate Action Centre with diverse records spanning all 9 trigger
paths and the M8 visual states. The seed is fully scripted and Phase 9
removal is a single command.

### Files

- `.claude/seed_p4m9_production_smoke.py` — the seed
- `.claude/teardown_p4m9_dummy_data.py` — the Phase 9 cleanup

Both scripts live under `.claude/` and are never loaded from the addon
manifest — they run only manually via `docker compose exec -T odoo
odoo shell -d neon_crm`.

### What the seed creates

| Kind | Count | Marker |
|---|---|---|
| `res.partner` | 2 | name contains `[TEST-DELETE]` |
| `res.users` (`p2m75_*`) | 6 | `partner_id.comment` warning |
| `commercial.job` | 10 | `equipment_summary` contains `[TEST-DELETE]` |
| `commercial.event.job` | 10 (auto-spawned) | cascade-removed |
| `commercial.scope.change` | 3 | description contains `[TEST-DELETE]` |
| `commercial.event.feedback` | 5 | feedback_text contains `[TEST-DELETE]` |
| `action.centre.item` | ~25-30 | bound to seed records via polymorphic source |

### Trigger coverage exercised

Every entry in the registry fires at least once. The two cron-driven
triggers (`closeout_overdue`, `sla_passed`) fire because the seed
script invokes `_cron_evaluate_time_based_triggers()` in-process at
the end — no need to wait for the 02:30 nightly cron.

If you want to re-trigger the cron later via the UI: navigate to
**Settings → Technical → Scheduled Actions →** the Action Centre
time-based-triggers cron **→ Run Manually**.

### Phase 9 cleanup

Single command removes everything the seed created:

```bash
ssh root@188.245.154.84
cd /opt/neon-odoo
docker compose exec -T odoo odoo shell -d neon_crm \
    < .claude/teardown_p4m9_dummy_data.py
```

The teardown is idempotent — running twice is a no-op the second time.
It reports counts of what it removed so cutover verification can
confirm clean state.

### TODO surfaced by seeding

`readiness_score` is a computed field that aggregates many sub-fields;
deterministically seeding a particular score (e.g. exactly 65 to
exercise `readiness_70`) requires populating all sub-inputs. For P4.M9
we accept the natural fall-through — fresh event_jobs land near zero,
which fires `readiness_50` (and `readiness_70` when event_date is
within 3 days). Phase 5+ may want to make readiness inputs
deterministically seedable for test scenarios; flagged as enhancement,
not a blocker.
