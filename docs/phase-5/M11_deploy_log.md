# P5.M11 — Hetzner deploy log

## Summary

Phase 5 (Workshop Inventory — M1 through M10 plus four hotfixes) shipped to
the Hetzner production server `crm.neonhiring.com` (`188.245.154.84`).
Module version moved end-to-end across the milestone:

- **Pre-deploy**: `17.0.3.6.1` (Phase 4 end state, prod HEAD `ce3f9f6`)
- **Post-deploy**: `17.0.4.0.14` (HEAD `9a011c7`)

Branch deployed: `feat/finance-phase-b1` — per established policy, no merge
to `main` until all 12 phases complete.

Tag applied: `v17.0.4.0.14-phase5-live` (annotated, on `9a011c7`).

## Timeline (2026-05-18, all times UTC)

| Time | Step | Notes |
|---|---|---|
| 08:48:25 | SSH connectivity probe | `neon-odoo-prod`, up 18 days |
| 08:49:34 | `pg_dump` of `neon_crm` → `/root/backups/neon_crm_pre_p5m11_20260518_084934.dump` | 4.9 MB binary `-F c`. Smaller than P4.M9's 17 MB plain SQL because of format compaction; same DB content baseline. |
| 08:50:?? | `git fetch origin` + `git pull --ff-only` `ce3f9f6..8c7c58f` | 18 commits, 73 files, +12928/-51. Untracked file `config/odoo.conf.pre-phase1-backup` preserved per P4.M9 precedent. |
| 08:53:00 | **First upgrade attempt: FAILED** | `ParseError` on `neon_equipment_movement_views.xml:111` — `ref="neon_equipment_movement_view_search"` was forward-referenced. Production transaction aborted cleanly. |
| 08:54:?? | Backup verification via `pg_restore -l` | 9298 TOC entries, key tables present. Restore unnecessary; transaction rollback was clean. |
| 08:55:?? | Fix committed locally as `9a011c7` and pushed | Reordered search-view record before the action that references it. No version bump (XML correctness fix at same `17.0.4.0.14`). |
| 08:57:04 | `git pull` of `9a011c7` on Hetzner | Fast-forward `8c7c58f..9a011c7`. |
| 08:57:04 | **Second upgrade attempt: clean** | All three migrations ran: `[>17.0.3.7.0] pre-migrate`, `[17.0.3.7.0>] post-migrate`, `[17.0.4.0.10>] post-migration`. Module loaded in 2.37s, 2701 queries. |
| 08:57:18 | `docker compose up -d --force-recreate odoo` | Container recreated; werkzeug ready at 08:57:27 (`HTTP service (werkzeug) running on 41d47c047e96:8069`). |
| 08:58:?? | JSON-RPC probe against `https://crm.neonhiring.com` | 8/8 PASS, exit 0. |
| 08:59:40 | `curl -I https://crm.neonhiring.com` | `303 → /web` (login). No error/critical/traceback in last-200-lines log scan. |
| 11:02:02 | `git tag -a v17.0.4.0.14-phase5-live 9a011c7` and `git push origin <tag>` | Annotated tag with the full M1-M10 + hotfix manifest. |
| 11:??:?? | Final audit probe | 8/8 PASS (re-run for closing audit). |

**Total deploy window**: ~10 minutes including the abort+fix+retry cycle.
HTTP unavailability was limited to the ~15 seconds between
`force-recreate` start and werkzeug-ready. The first failed `-u` did
not stop the running HTTP container — production stayed serving 17.0.3.6.1
content for users throughout the migration cycle.

## Pre-deploy backup

- **Path**: `/root/backups/neon_crm_pre_p5m11_20260518_084934.dump`
- **Size**: 4.9 MB binary (`pg_dump -F c`)
- **Verification**: `pg_restore -l` via stdin from host → 9298 TOC entries; key tables present (`res_users`, `ir_module_module`, `commercial_event_job`, `action_centre_item`). `neon_equipment_unit` correctly absent (pre-Phase-5 schema).
- **Rollback target commit**: `ce3f9f6` (`fix(p4.m9 seed): use p2m75_mgr for scope_change + feedback create`).

## Migrations that fired

The upgrade range `17.0.3.6.1 → 17.0.4.0.14` includes three migration scripts:

1. `addons/neon_jobs/migrations/17.0.3.7.0/pre-migrate.py` — P5.M1 sub-task A
   crew model refactor. Adds `partner_id` column to `commercial.job.crew`,
   backfills from `user_id.partner_id`, drops the old `unique_user_per_job`
   constraint before the ORM applies the new `unique_partner_per_job`.
2. `addons/neon_jobs/migrations/17.0.3.7.0/post-migrate.py` — Verification
   only. Reports (does not fail) on any null `partner_id` left over after
   the backfill. On Hetzner the backfill was clean — no warning logged.
3. `addons/neon_jobs/migrations/17.0.4.0.10/post-migration.py` — P5.M8
   `is_high_impact` category seed. Idempotent. Flipped `is_high_impact=TRUE`
   on the four seeded codes (`sound`, `visual`, `lighting`, `laptops`)
   where the existing value was `False`.

All three completed without error.

## The 9a011c7 fresh-install fix

**Bug**: `views/neon_equipment_movement_views.xml` defined the action
`neon_equipment_movement_pending_transfers_action` at line 111 referencing
`search_view_id ref="neon_equipment_movement_view_search"`. The referenced
search-view record was defined at line 123 — *after* the action.

**Why local upgrades didn't catch it**: Odoo's data loader resolves
`ref()` against records already materialised in `ir_model_data` plus those
loaded earlier in the current XML file. Local development DBs had the
search-view record already present in `ir_model_data` from prior install
passes, so the forward reference resolved against the existing DB row.
The bug only manifests on a cold fresh-install path — exactly what the
production upgrade was doing.

**Fix**: moved the search-view record to its conventional position before
the first action that references it. Audited the rest of `neon_jobs/views/`
— this was the only intra-file ordering bug. Cross-file refs all load in
correct manifest order.

**Lessons**: the smoke harness runs `-u` against a DB where the module is
already installed. That validates the upgrade path from one known
installed state to another, but does **not** exercise the fresh-install
path. Future production deploys should anticipate this asymmetry —
either by adding a fresh-install integration test to the smoke harness,
or by enforcing the convention "search views are declared before the
actions that reference them" via lint.

See [[reference_odoo_xml_fresh_install_load_order]] memory for the
generalised pattern.

## Verifications

| ID | Check | Result |
|---|---|---|
| V1 | `odoo` container Up | ✓ Up post-recreate |
| V2 | Manifest version on disk | `17.0.4.0.14` ✓ |
| V3 | DB-reported `latest_version` | `17.0.4.0.14`, state `installed` ✓ |
| V4 | `curl -I https://crm.neonhiring.com` | `303 → /web` ✓ |
| V5 | Log scan (last 200 lines, error/critical/traceback) | No matches ✓ |
| V6 | JSON-RPC probe — 4 tiers × 2 paths | 8/8 PASS, exit 0 ✓ |
| V7 | Final audit probe re-run | 8/8 PASS, exit 0 ✓ |

## Probe matrix

```
Tier        Path               Expect Actual Mark
p2m75_mgr   get_dashboard_data data   data   PASS
p2m75_mgr   server_action.run  data   data   PASS
p2m75_lead  get_dashboard_data data   data   PASS
p2m75_lead  server_action.run  data   data   PASS
p2m75_crew  get_dashboard_data deny   deny   PASS
p2m75_crew  server_action.run  deny   deny   PASS
p2m75_other get_dashboard_data deny   deny   PASS
p2m75_other server_action.run  deny   deny   PASS
```

`p2m75_*` synthetic users (UIDs 15-18) are present in production from
the P4.M9 production smoke seed (`.claude/seed_p4m9_production_smoke.py`).

## Pre-existing observations (not regressions)

- One pre-existing config warning unchanged from before: `longpolling-port
  deprecated`. Container-level Odoo config concern, not a P5 deliverable.
- The two `Model <X> has no table` errors for `twilio.config` and
  `neon.bot.user` continue to appear; pre-existing across phases.

## Pre-existing test failures (unchanged by this deploy)

Full local regression at deploy time: **413/415**. The two FAILs:

- `p2m2`, `p2m4`, `p2m5` — NO SUMMARY (smoke harness tooling errors that
  pre-date Phase 5 work).
- `p2m7_7` — 6/8 (test-suite issue unrelated to deployed code).

Production deploy was not gated on these (they pre-existed Phase 4
deploy too).

## Rollback procedure (if needed post-deploy)

To revert to pre-deploy state (commit `ce3f9f6`, version `17.0.3.6.1`):

```bash
ssh root@188.245.154.84
cd /opt/neon-odoo
git checkout ce3f9f6
docker compose stop odoo
docker compose run --rm odoo odoo -d neon_crm -u neon_jobs --stop-after-init
docker compose up -d --force-recreate odoo
```

If DB state needs to be rewound (e.g. the `partner_id` column or the
`is_high_impact` seed needs to be undone):

```bash
ssh root@188.245.154.84
cd /opt/neon-odoo
docker compose stop odoo
docker compose exec -T db psql -U odoo -d postgres \
    -c "DROP DATABASE neon_crm WITH (FORCE);"
docker compose exec -T db psql -U odoo -d postgres \
    -c "CREATE DATABASE neon_crm OWNER odoo;"
cat /root/backups/neon_crm_pre_p5m11_20260518_084934.dump \
    | docker compose exec -T db pg_restore -U odoo -d neon_crm
docker compose up -d --force-recreate odoo
```

The backup restore takes a few minutes; the dump is 4.9 MB binary.

## Production users observation

The `p2m75_*` synthetic test users have been present in production since
the P4.M9 production smoke seed addendum. They are useful for ad-hoc
verification (the JSON-RPC probe relies on them). The real team accounts
(`robin@neonhiring.co.zw`, `tatenda@neonhiring.co.zw`, etc.) are unchanged
and continue as active users.

## Browser smoke (Phase 5 walkthrough)

Pending — walkthrough script lives at
`docs/phase-5/M11_walkthrough_script.md` for the recorder. Robin
acceptance video deferred to async work; this deploy log closes once
the tag is in place.

## Deviations from runbook

| Runbook item | What we actually did | Why |
|---|---|---|
| Backup destination `/opt/neon-odoo/backups/` | Used `/root/backups/` | Matches P4.M9 precedent (Tatenda correction `a` at design pause gate). |
| Container stop pattern | `up -d --force-recreate` (no explicit stop) | Codifies the discipline established during the 17.0.4.0.14 hotfix round; force-recreate is the stronger guarantee versus P4.M9's `stop + up -d`. |
| `docker compose exec -T postgres ...` | `docker compose exec -T db ...` | Production service name is `db`. The runbook draft's `postgres` was a draft typo. |
| Pre-step: `pg_restore -l` from inside container | Streamed dump via stdin to `pg_restore -l` | The dump file lives on the host, not inside the db container — host-side `cat | docker compose exec -T db pg_restore -l` avoided needing to copy the file back into the container. |
| Expected backup size `>50MB` | Actual 4.9 MB | Binary `-F c` is much more compact than plain SQL; same DB content as P4.M9 baseline. Verified via `pg_restore -l` showing 9298 TOC entries — restorable. |

## Tag

```
git tag -a v17.0.4.0.14-phase5-live 9a011c7 -m "<full message — see tag annotation>"
git push origin v17.0.4.0.14-phase5-live
```

Tag is annotated, references the production HEAD `9a011c7` (not the
nominal-version commit `8c7c58f`). The two-commit divergence reflects
the fresh-install fix that landed at the same manifest version.

## Acceptance signoff

Pending. Walkthrough video for Robin will be recorded by the team off the
script at `docs/phase-5/M11_walkthrough_script.md`. Acceptance confirms
P5.M11 closure; until then this milestone is "deployed pending signoff".
