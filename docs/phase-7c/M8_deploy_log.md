# Phase 7c External Training — Sub-phase Close Log

**Sub-phase**: Phase 7c — External Training Booking
**Build window**: 23 May 2026
**Branch**: `feat/external-training-phase-7c`
**Final HEAD pre-deploy**: `a0a2ac7` (M7) — M8 commit lands on top
**Module versions at close**:
- `neon_external_training` 17.0.1.5.0 (new module)
- `neon_training` 17.0.8.9.0 (Phase 7a extensions for M4 + M6)

---

## 1. Milestones

| M | Commits | Scope | Phase 7a touched? |
|---|---|---|---|
| M1 | `3902e1a` | vendor model + 5 seeds + tier ACLs + LMS-style admin menu root | no |
| M2 | `99d5a2b` | booking model + 8-state machine + reference sequence + cost groups attr + record rules + vendor booking_count compute swap | no |
| M3 | `25a4a6a` | superuser approval workflow + reject wizard + activity routing to Robin + Munashe | no |
| M4 | `751803c` + `e49781d` | auto-cert issuance on cert_issued + FK fixup migration | **yes** |
| M5 | `d03349a` | kanban grouped by state + write() override for drag-drop state graph + filter chips + vendor smart button | no |
| M6 | `aab7026` + `fd77fb2` | dashboard 2 counters (upcoming 30d / pending completion 7d) + drill-through actions | **yes** |
| M7 | `a0a2ac7` | 4 notification stubs + dispatcher + 3d reminder cron | no |
| M8 | (this commit) | integration smoke + 2 reference docs + this deploy log | no |

Total: 8 milestones, 9 commits (M4 and M6 doubled for Phase 7a + Phase 7c separation per CLAUDE.md M4 amendment).

---

## 2. Smoke progression

| Milestone | Smoke | Cumulative |
|---|---|---|
| M1 | 8/8 | 8/8 |
| M2 | 11/11 | 19/19 |
| M3 | 8/8 | 27/27 |
| M4 | 11/11 | 38/38 |
| M5 | 8/8 | 46/46 |
| M6 | 7/7 | 53/53 |
| M7 | 9/9 | 62/62 |
| M8 integration | 1/1 (10 stages) | **63/63** |

**Cumulative: 63/63 PASS** across the 8 milestones plus integration.

Canonical `.claude/run_regression.sh` baseline carried through this sub-phase: **1224/1226** (Phase 7e close + login-bypass + LMS admin polish), unchanged. M8 adds the 8 Phase 7c suites to the canonical list (see § 6 below).

Known-noise carried forward (unchanged):
- `p2m2`, `p2m4`, `p2m5` — pre-existing fixture issues
- `p2m7_7` — pre-existing test selector drift (6/8)
- `p6m3` — calendar-induced fixture collision

---

## 3. Phase 7a extensions (2 minor version bumps)

| From | To | Driver |
|---|---|---|
| `17.0.8.7.0` | `17.0.8.8.0` | M4: `external_booking_id` M2O on `neon.training.certification` |
| `17.0.8.8.0` | `17.0.8.9.0` | M6: 2 external-training counters + drill-through actions on `neon.training.dashboard` |

Total Phase 7a files modified across Phase 7c: **7** (cert model, dashboard model, dashboard view, manifest, 2 migrations, plus `__init__.py` indirectly via models package — counted once).

`neon_jobs` / `neon_core` / `neon_onboarding` / `neon_lms` / `neon_finance` modifications: **0**.

---

## 4. Phase 7c module versions

`neon_external_training` versions land in order:

```
17.0.1.0.0  (M1)
17.0.1.1.0  (M2)
17.0.1.2.0  (M3)
17.0.1.3.0  (M4 first round; bumped to .3.1 below)
17.0.1.3.1  (M4 FK fixup migration; manifest re-bump needed
              to fire the migration because the prior install
              had already recorded 17.0.1.3.0)
17.0.1.4.0  (M5)
17.0.1.5.0  (M7)
```

The `.3.0 → .3.1` step is the migration-version-increment hygiene Phase 11 candidate referenced below — bumping the manifest after the fact to force a migration re-run is ugly but the only path Odoo 17 provides for retroactively fixing a missed FK.

---

## 5. Architectural decisions (chronological)

1. **Vendor model with 5 placeholder seeds** (M1). VID, Red Cross Zim, Allen & Heath, Avolites, Yamaha Pro Audio. Contact fields seeded with `(pending)` strings; Tatenda populates real contacts via the admin form post-deploy. `noupdate="0"` for now — Phase 11 candidate to flip to `noupdate="1"` after real data lands so subsequent `-u` doesn't overwrite.

2. **State machine guards in action methods, not `@api.constrains`** (M2). Odoo constrains can't see prior state (only post-write values), so the transition graph (`_ALLOWED_TRANSITIONS` dict + `_transition_to` helper) lives where the user invokes them. Invalid jumps raise `UserError` with the allowed-next-state list. Only invariants without history (cost non-negative, past-date guard on submit) live in constrains-style code.

3. **Cost field admin-only via `groups=` attribute** (M2). Odoo's per-field `groups` attr excludes the field from reads (silently filtered) AND raises `AccessError` on explicit reads. Cleaner than splitting cost into a separate model with its own ACL. Visible to `neon_core.group_neon_superuser` + `neon_core.group_neon_bookkeeper` only.

4. **sudo() inside workflow methods as security boundary** (M2 + M3). ACL grants crew read-only access; record rule scopes which records they see. Workflow methods sudo() the actual write so crew can flip state on their own bookings. Approve/reject explicitly assert superuser tier — the form button gates via `groups=` but the method enforcement survives xmlrpc/shell.

5. **Approval activity routing reuses Phase 7a M7's `_CERT_VERIFIER_LOGINS`** (M3). Runtime deferred import per `reference_odoo17_deferred_external_dep.md`. Single source of truth for Robin + Munashe routing.

6. **Booking-side post-migrate for FK fixup** (M4). The atomic two-commit pattern (Phase 7a extension → Phase 7c extension) skipped FK creation because the upstream module upgraded standalone before the downstream model was registered. T7c407 caught it; idempotent ALTER TABLE migration on the dependent side resolved. See new reference doc `reference_odoo17_forward_string_m2o_fk.md`.

7. **`signed_off_by_id` is `res.users` not `res.partner`** (M4). The brief's draft suggested `.partner_id.id` — corrected at build time. `external_trainer_name = vendor.name` is set unconditionally to short-circuit Phase 7a's `_check_external_trainer_when_required` constraint regardless of cert type category.

8. **Kanban drag-drop respects state machine via `write()` override + context flag** (M5). See new reference doc `reference_odoo17_kanban_drag_state_machine.md`. Internal transitions set `neon_p7c_internal_transition=True` to avoid re-entry recursion.

9. **Dashboard counters use defensive `env.get`** (M6). Same pattern as Phase 7e M11 LMS counters. If `neon_external_training` is missing, both counters return 0 and drill-through actions return `False`. Compute method short-circuits in one branch.

10. **Notification dispatcher posts on `self` (booking)**, not `self.crew_user_id.partner_id` (M7). Matches the canonical pattern in `reference_neon_notification_stub_pattern.md`. The brief's partner-side post was a draft variation; correcting at build time keeps Phase 9's grep-based regression working.

11. **ASCII hyphen in stub marker** (M7). Brief used em-dash (`—`); the canonical marker is `[Notification stub - Phase 9 will send]` (hyphen-minus). Phase 9 greps for the exact substring; em-dash would silently break it.

12. **`@api.model` on the cron entry method** (M7). The cron passes an empty recordset; `@api.model` lets the method run with `self` as the model class. Cron walks bookings via `self.search([...])` from there.

---

## 6. Reference docs produced (M8)

| File | Subject |
|---|---|
| `.claude/reference_odoo17_forward_string_m2o_fk.md` | Forward-string M2O FK creation: when it works, when it silently skips, idempotent fixup migration pattern, Phase 11 helper candidate |
| `.claude/reference_odoo17_kanban_drag_state_machine.md` | Kanban drag-drop interception via write() override + context-flag re-entry guard; security boundaries; Phase 11 confirmation-dialog candidate |

Plus the M7 work referenced an existing doc: `reference_neon_notification_stub_pattern.md` (Phase 7b M12).

---

## 7. Phase 11 amendment candidates queued this sub-phase

1. **Generic `register_forward_fk(table, column, ref_table, on_delete)` helper** in `neon_core` — avoids per-field migration boilerplate when cross-module Many2one drops the FK.
2. **Kanban drag-drop confirmation dialog** for terminal / destructive transitions (`cert_issued`, `cancelled`). Owl popup before commit.
3. **Cron idempotency window** with suppression Datetime field (mirror Phase 7a M5's `last_notification_sent_urgency` pattern) so re-running `_cron_send_3d_reminders` same day doesn't duplicate chatter.
4. **Per-booking notification audit row model** — when Phase 9 ships actual dispatch, replace chatter mining with a dedicated `neon.external.training.notification_log`.
5. **Migration version-increment hygiene tooling** — bumping a manifest to force a migration re-run is ugly. Detector + helper that says "this migration directory exists but `ir.module.module.latest_version` already matches; bump to .N+1 to fire it."
6. **ACL / record-rule alignment for crew tier** — M2 ACL is read-only but rule grants write/create/unlink; sudo() in workflow methods papers over the gap. Either align ACL to write+create or trim the rule's perms.
7. **`lead_tech` placeholder rule** — M2 ships `[(1,'=',1)]` (see all); refine to `crew_user_id.parent_id == user.id` (or similar crew → lead mapping) once that mapping surfaces in M5/M6 of a future sub-phase.
8. **Vendor seeds `noupdate` flip** — after Tatenda populates real contact data via the form, flip seeds to `noupdate="1"` so subsequent module `-u` doesn't overwrite.
9. **Booking confirmation includes location** — `_notify_reminder_3d` includes location; `_notify_booking_confirmed` should too.
10. **Forward-string FK warning escalation** — Odoo logs the missing-comodel as a warning, not an error. A startup-time check that surfaces unresolved forward strings would catch this at install time instead of at delete-cascade test time.

---

## 8. Cross-cutting touches summary

| Module | Files modified across Phase 7c |
|---|---|
| `neon_external_training` | new module (M1) — manifest, init, models (2), wizards (1), security (2), data (3), views (4), migrations (1), smokes (8) |
| `neon_training` | 5 (cert model + dashboard model + dashboard view + manifest + 2 migrations) |
| `neon_jobs` | 0 |
| `neon_core` | 0 |
| `neon_onboarding` | 0 |
| `neon_lms` | 0 |
| `neon_finance` | 0 |

Phase 7c's reach: the new module plus 5 surgical files in Phase 7a. Everywhere else, untouched.

---

## 9. Module count growth

- Pre-Phase-7c on local: 93 installed modules
- Post-Phase-7c on local: 94 installed modules
- Delta: +1 (`neon_external_training`)

---

## 10. Deferred to admin run / Phase 9

- **WhatsApp + email actual dispatch** — `_notify_send` is a stub. Phase 9 (pending Meta business-account approval) overrides it to wire the dispatch engine.
- **Real vendor contact data** — Tatenda populates the 5 vendor records' contact fields via the admin form. Sub-phase ships with `(pending)` placeholders.
- **`lead_tech` rule refinement** — placeholder permissive rule for now; tighten when crew-to-lead mapping surfaces.

---

## 11. Ready for prod deploy

Tag target: `v17.0.8.9.0-phase7c-live` on the commit including M8.

Deploy operation outline (executed in a separate session per Tatenda's M1–M3 wrap-up direction):

```
# Pre-flight
ssh root@188.245.154.84
cd /opt/neon-odoo
git status
git log --oneline -1   # expect feat/external-training-phase-7c HEAD

# Backup
docker exec neon-odoo-db pg_dump -Fc -U odoo -d neon_crm \
    > /root/backups/neon_crm_pre_phase7c_<timestamp>.dump

# Code pull
git fetch origin
git checkout feat/external-training-phase-7c
git pull origin feat/external-training-phase-7c

# Upgrade (i for the new module, u for the extended one)
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -i neon_external_training -u neon_training \
    --stop-after-init --no-http

# Restart (no JS assets shipped in this sub-phase so asset
# regen is not required, but a restart picks up the new
# cron registration)
docker compose restart odoo

# Tag
git tag v17.0.8.9.0-phase7c-live
git push origin v17.0.8.9.0-phase7c-live
```

Expected post-deploy verifications:
- `neon_external_training` installed at 17.0.1.5.0
- `neon_training` installed at 17.0.8.9.0
- 5 vendor seeds present (env.ref on each)
- `cron_external_training_reminder_3d` ir.cron record present + active
- Dashboard form shows new "External Training" card group with 2 counters
- T7cI001 integration smoke runs clean against prod DB

## Total deploy time estimate

~10-15 minutes (matches Phase 7e + login-bypass deploys; one new module + one upgrade with log-only migration + cron-only data load).

---

## 12. Status: ready for deploy

Phase 7c functionally complete. All 8 milestones land on `feat/external-training-phase-7c`; integration smoke 10/10 stages; no regression hits on the canonical baseline.

---

## 13. Production Deploy: Phase 7c live (23 May 2026, ~11:57 UTC)

**Deployer:** Tatenda via Claude Code SSH
**Tag:** `v17.0.8.9.0-phase7c-live` -> `dec36bb`
**Branch:** `feat/external-training-phase-7c`

### Pre-flight

| Check | Result |
|---|---|
| SSH | OK |
| Prod HEAD before | `6646bb6` (v17.0.1.14.0-lms-admin-polish) |
| Branch before | `feat/lms-admin-polish` |
| Working tree | clean (only pre-existing untracked `config/odoo.conf.pre-phase1-backup`) |

### Backup

- **File:** `/root/backups/neon_crm_pre_p7c_20260523_135617.dump`
- **Size:** 6.7 MB (pg_dump -Fc compressed)

### Code pull

`git checkout feat/external-training-phase-7c && git pull` → HEAD = `dec36bb`. Fast-forward; no merge conflicts.

### Combined install + upgrade

```
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -i neon_external_training -u neon_training \
    --stop-after-init --no-http
```

Migration log excerpts:

```
WARNING Field neon.training.certification.external_booking_id
  with unknown comodel_name 'neon.external.training.booking'
INFO module neon_training: Running migration [17.0.8.8.0>] post-migrate
INFO neon_training 17.0.8.8.0: external_booking_id field added
  to neon.training.certification for Phase 7c M4 auto-cert issuance.
INFO module neon_training: Running migration [17.0.8.9.0>] post-migrate
INFO neon_training 17.0.8.9.0: 2 external-training counters
  (upcoming 30d / pending completion 7d) + drill-through actions
  added to neon.training.dashboard.
INFO Module neon_training loaded in 0.93s, 942 queries
INFO Loading module neon_external_training (90/92)
INFO module neon_external_training: creating or updating database tables
INFO loading neon_external_training/security/neon_external_training_security.xml
INFO loading neon_external_training/security/ir.model.access.csv
INFO loading neon_external_training/data/neon_external_training_sequences.xml
INFO loading neon_external_training/data/neon_external_training_cron.xml
INFO loading neon_external_training/data/neon_external_training_vendors.xml
INFO loading neon_external_training/views/...  (4 view XMLs + reject wizard view + menu)
INFO Module neon_external_training loaded in 0.54s, 318 queries
INFO Modules loaded.
INFO Registry loaded in 6.511s
```

Registry loaded clean. No ERROR / CRITICAL. The `unknown comodel_name` warning is the same forward-string-reference symptom from M4 — harmless here because the combined `-i + -u` install loaded both modules into the registry before the table-init pass that creates FK constraints. The FK was created correctly without needing the M4 idempotent fixup migration to fire (see § 13.6 below).

### Restart + asset regen

`docker compose restart odoo` clean. `curl /web/login` → 200 first poll.

Asset regen via odoo shell:

| Stage | Count |
|---|---|
| Stale `/web/assets/*` cleared | 15 |
| Bundles compiled | 4 (assets_backend, assets_web, backend_assets_wysiwyg, assets_frontend) |
| Final `/web/assets/*` attachments | 8 |
| `/web/assets/%backend%` attachments | 4 (js + css × 2 backend bundles) |

### 7 deploy verifications

| V | Check | Result |
|---|---|---|
| V1 | `neon_training.installed_version` | **17.0.8.9.0** ✓ |
| V1 | `neon_external_training.installed_version` | **17.0.1.5.0** ✓ |
| V2 | 5 vendor seeds (`vendor_vid`, `vendor_red_cross_zim`, `vendor_allen_heath`, `vendor_avolites`, `vendor_yamaha_pro`) | All 5 resolved ✓ |
| V3 | FK constraint `neon_training_certification_external_booking_id_fkey` | **Present** (false-negative in initial Python smoke due to multi-line SQL string concat ambiguity; confirmed via direct `psql` + the idempotent fixup script logging "FK already present; no-op.") ✓ |
| V4 | Dashboard external counters render for Robin | `upcoming=0` `pending_completion=0` ✓ (no bookings yet) |
| V5 | Booking reference sequence | Present, prefix `BKG-%(year)s-`, padding 3 ✓ |
| V6 | 3d reminder cron `cron_external_training_reminder_3d` | Present, active=True, 1-day interval ✓ |
| V7 | `website.login_layout.active` | `False` ✓ (login bypass holds) |

### V3 false-negative — note

The initial verification used a multi-line Python SQL string that relied on SQL's adjacent-string concatenation rule (`'foo'\n'bar'` → `'foobar'`). The constraint name didn't resolve as expected and V3 reported FK absent. Direct `psql` query against the same `pg_constraint` row showed the FK was in fact created cleanly during the combined install. The idempotent fixup script (`p7c_prod_fk_fixup.py`) then ran and confirmed "FK already present; no-op."

Phase 11 candidate filed: prefer single-line literal SQL strings in verification scripts; don't rely on cross-line concatenation.

### Module count growth

- Pre-Phase-7c on prod: 91 installed modules (post-LMS-polish state)
- Post-Phase-7c on prod: 92 installed modules
- Delta: +1 (`neon_external_training`)

(The M8 deploy log earlier estimated 92→93 based on a stale baseline. Actual pre-deploy count was 91, so the +1 lands at 92.)

### Tag push

```
git tag v17.0.8.9.0-phase7c-live dec36bb
git push origin v17.0.8.9.0-phase7c-live
* [new tag]  v17.0.8.9.0-phase7c-live -> v17.0.8.9.0-phase7c-live
```

### Deploy status: SUCCESS

Phase 7c live on `crm.neonhiring.com` at `v17.0.8.9.0-phase7c-live`. All 7 verifications green. Booking workflow + auto-cert + dashboard counters + 3d cron + notifications stub all live.

### Rollback target (in case of issue)

```
docker compose stop odoo
docker compose exec -T db pg_restore -U odoo -d neon_crm \
    --clean --if-exists \
    /root/backups/neon_crm_pre_p7c_20260523_135617.dump
cd /opt/neon-odoo
git checkout v17.0.1.14.0-lms-admin-polish
docker compose start odoo
```

Phase 7c deploy complete.

---

## 14. Lessons captured (post-deploy)

1. **Forward-string M2O FK creates correctly on combined `-i + -u` install.** The M4 fixup migration covers the staged-upgrade case (upstream `-u` alone, then downstream `-u` later). Fresh install via `-i` of the dependent alongside `-u` of the upstream in the SAME pass loads both into the registry before the table-init pass, and Odoo's FK creator finds the comodel. Both paths now confirmed.

2. **Multi-line SQL string literal concatenation in verification scripts is unreliable.** Use a single-line string or explicit Python string concatenation. Phase 11 candidate filed.

3. **The "unknown comodel_name" warning at registry-init is informational, not a deploy-blocker** — but only when followed by the dependent module loading in the same pass. Standalone upstream upgrade still needs the fixup migration.
