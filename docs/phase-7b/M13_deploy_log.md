# Phase 7b Onboarding -- M13 sub-phase close

**Date:** 22 May 2026
**Maintainer:** Tatenda via Claude Code
**Branch:** `feat/onboarding-phase-7b`
**Ready-for-deploy commit:** TBD (this commit)
**Target tag on prod deploy:** `v17.0.8.4.0-phase7b-live`

---

## Build summary

13 milestones complete (M1-M12 plus M6 amendment + M13 close). Full crew-onboarding state machine shipped end-to-end with portal stream, self-upload wizard, jobs view, dashboard counters, and notification trigger points ready for Phase 9 dispatch wiring.

## Milestone commit ledger

| Milestone | Commit | Scope | Phase 7a files touched |
|---|---|---|---|
| M1 | `2785fe2` | candidate model + state machine + Skip wizard + audit log | 0 |
| M2 | `22deb96` | requirement template model + 4 seed records + candidate compute | 0 |
| M3 | `117aad3` | kanban + polished form + menu structure | 0 |
| M4a | `be20441` | Phase 7a extension: cert.candidate_id + constrains hook | 3 |
| M4b | `3bd3d17` | collected_cert_ids o2m + cert satisfaction + auto-transition | 0 |
| M5a | `ca2d77e` | Phase 7a gate engine 4th condition (probationary role restriction) | 4 |
| M5b | `46fb930` | probationary_jobs_completed compute + M5 smoke | 0 |
| M6 | `5ed2dd2` | Promote to Active wizard + res.users creation + ready badge | 0 |
| M6+ | `03e7a73` | real-time refresh + OVERRIDE audit capture (amendment) | 0 |
| M7 | `7624bac` | Skip wizard polish + user creation parity | 0 |
| M8 | `8e6d839` | portal user creation + /my/onboarding route + wizard upgrade pattern | 0 |
| M9 | `dbb8a34` | portal self-upload cert wizard | 0 |
| M10 | `d696450` | portal jobs view + filter chips + detail page | 0 |
| M11a | `4b60451` | Phase 7a dashboard 2 onboarding counters + drill-through | 4 |
| M11b | `187126b` | M11 smoke | 0 |
| M12a | `3b140a3` | Phase 7a notify hooks (cert verify + M5 block) | 4 |
| M12b | `20d6612` | 6 notification stub methods + dispatcher + wiring | 0 |
| M13 | (this commit) | integration smoke + 4 reference docs + this log | 0 |

## Phase 7a extensions

5 minor version bumps on `neon_training`:

| Version | Triggered by | Schema change |
|---|---|---|
| 17.0.8.0.1 → 17.0.8.1.0 | M4a | `candidate_id` Many2one on cert (nullable, ondelete=set null) |
| → 17.0.8.2.0 | M5a | `fire_reason` Char on gate_log + M5 hook in crew create/write |
| → 17.0.8.3.0 | M11a | 2 non-stored Integer computes on dashboard + drill-through |
| → 17.0.8.4.0 | M12a | notify hooks wired into M4 constrains + M5 gate log helper |

All Phase 7a extensions are non-breaking: defensive `env.get('neon.onboarding.candidate')` + `hasattr()` guards mean neon_training installs cleanly with or without neon_onboarding present.

## Phase 7b version progression

`neon_onboarding`: 17.0.1.0.0 → 17.0.1.10.0 (one version per milestone, plus M6 amendment patch).

## Test progression

| Phase / milestone | Regression baseline |
|---|---|
| Pre-Phase-7b (Phase 7a + neon_core baseline) | 1045/1047 |
| After M1 | 1051/1053 |
| After M2 | 1057/1059 |
| After M3 | 1064/1066 |
| After M4 | 1073/1075 |
| After M5 | 1081/1083 |
| After M6 | 1091/1093 |
| After M6 amendment | 1094/1096 |
| After M7 | 1103/1105 |
| After M8 | 1113/1115 |
| After M9 | 1122/1124 |
| After M10 | 1130/1132 |
| After M11 | 1137/1139 |
| After M12 | 1145/1147 |
| **After M13 (this commit)** | **1146/1148** |

100 new tests added across Phase 7b. The 4 known-noise failures (`p2m2`, `p2m4`, `p2m5`, `p2m7_7` 6/8) are unchanged from baseline.

## Architectural decisions (chronological)

1. **Skip wizard superuser-only** (M1 design call -- Tatenda): only `neon_core.group_neon_superuser` can trigger Skip Onboarding. Bookkeeper / training_admin / sales_rep / crew explicitly excluded.
2. **Path A portal user pattern** (M8 -- Tatenda 22 May): provision inactive portal user at cert_collection entry rather than relax Phase 7a's `cert.user_id` required constraint. Zero Phase 7a constraint touches.
3. **M6 amendment** (22 May): real-time `probationary_jobs_completed` refresh on event_job completion via `_inherit` hook. Retires the Phase 11 cron polish item from M5.
4. **Notification stubs ready for Phase 9** (M12): single `_notify_send` override point; 6 event-specific methods frozen as API contract.

## Deferrals (queued by sub-phase)

| Item | Deferred to |
|---|---|
| WhatsApp dispatch | Phase 9 |
| Email dispatch (production-grade) | Phase 9 |
| Skip wizard kanban quick-actions | Phase 11 |
| Bulk-skip for the 9 paused crew users | Phase 11 cutover |
| Per-tier dashboard variants | Phase 11 |
| Onboarding icon design (currently OCA queue_job placeholder) | Phase 12 visual polish |
| Cert.user_id constraint relax | NOT NEEDED (Path A covers) |

## Reference docs produced (M13)

| File | Topic |
|---|---|
| `.claude/reference_neon_jobs_schema.md` | commercial.job + event.job + crew schema (field name corrections from M5/M6/M10) |
| `.claude/reference_odoo17_with_user_sudo_chain.md` | M9's pattern for calling owner-checked action methods from portal controllers |
| `.claude/reference_odoo17_portal_user_creation.md` | M8's Path A portal user lifecycle + UPGRADE on promotion |
| `.claude/reference_neon_notification_stub_pattern.md` | M12 stub dispatcher + Phase 9 override hook + defensive triple-guard |

## Phase 11 amendment candidates queued

Items surfaced during Phase 7b that should be considered when the Phase 11 polish/cleanup sub-phase opens:

1. **OCA-placeholder icon** for `neon_onboarding` (M3 finding -- copy from OCA queue_job)
2. **Notification HTML body brittleness** (M12 finding -- smoke filter on Odoo-rewritten HTML needs loose matching, not literal substring)
3. **Defensive triple-guard pattern** documented (M12) -- standardize across future cross-module calls
4. **Bulk-skip wizard for 9 paused crew** -- bulk-import existing crew at deploy time
5. **Kanban quick-actions on Skip + Promote** -- right-click contextual actions on the kanban card
6. **Cancelled/released event_job filter on portal jobs view** -- currently excluded; surface separately if Robin asks
7. **Phase 9 WhatsApp dispatch wiring** -- consume the M12 stub framework

Plus the 7 candidates carried forward from Phase 7a + neon_core sessions.

## Integration smoke

`.claude/p7b_integration_smoke.py` -- single test threading the full lifecycle:

```
Stage 1: create candidate (state=candidate)
Stage 2: requirement_template auto-applied
Stage 3: cert_collection -> portal user created
Stage 4: 2 cert uploads via M9 controller
Stage 5: cert verification -> auto-transition probationary
Stage 6: M6 Promote -> portal user upgraded
Stage 7: final aggregates (audit + notify counts)
```

Test asserts 6 audit log entries + 6 notification stub messages on a single candidate. **Pass status: ALL 7 STAGES PASS.**

## Ready for prod deploy

Tag will be `v17.0.8.4.0-phase7b-live` on the commit including M13.

Deploy operation outline (executed in a separate session after Tatenda gives the word):

```
# Pre-flight
ssh root@188.245.154.84
cd /opt/neon-odoo
git status
git log --oneline -1   # expect feat/training-phase-7a HEAD

# Backup
docker exec neon-odoo-db pg_dump -Fc -U odoo -d neon_crm \
    > /root/backups/neon_crm_pre_phase7b_<timestamp>.dump

# Code pull
git fetch origin
git checkout feat/onboarding-phase-7b
git pull origin feat/onboarding-phase-7b

# Upgrade (i for the new module, u for the extended one)
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -i neon_onboarding -u neon_training --stop-after-init --no-http

# Restart + asset regen
docker compose restart odoo
# (asset regen script same as v17.0.8.0.0-phase7a-live deploy)

# Tag
git tag v17.0.8.4.0-phase7b-live
git push origin v17.0.8.4.0-phase7b-live
```

Expected post-deploy verifications:
- All 7 canonical users still in their meta-groups (Robin/Munashe/Tatenda superuser; Kudzi bookkeeper; Lisa/Evrill sales_rep; Ranganai lead_tech)
- `base.group_user.implied_ids` count = 0 (Phase 7a + neon_core invariant preserved)
- `neon_training` installed_version = 17.0.8.4.0
- `neon_onboarding` installed_version = 17.0.1.10.0
- Portal home shows "My Onboarding" card for any prod portal user with a candidate record (currently 0; will populate as crew onboarding starts)
- Dashboard form shows new Onboarding card group with both counters

## Total deploy time estimate

~10-15 minutes (matches the pattern of v17.0.8.0.0-phase7a-live + v17.0.1.0.1-neoncore-settings deploys).
