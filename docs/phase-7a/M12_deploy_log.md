# Phase 7a M12 Deploy Log

**Date:** 21 May 2026
**Deployer:** Tatenda via Claude Code SSH
**Target:** `crm.neonhiring.com` (Hetzner; `root@188.245.154.84:/opt/neon-odoo`, DB `neon_crm`)
**Deploy type:** Test deployment of Phase 7a (Training & Certification). Real users + ACL cleanup deferred to Phase 11 cutover per Tatenda's 21 May 2026 direction.

---

## Pre-flight

| Check | Result |
|---|---|
| SSH connectivity | ✅ `connected` (`neon-odoo-prod`, root) |
| Prod working tree | ✅ Clean (one untracked artefact `config/odoo.conf.pre-phase1-backup`, irrelevant to git ops) |
| Prod HEAD before deploy | `9d1c817` (tag `v17.0.7.9.1-phase6-walkthrough-fixes`) |
| Backup directory | `/root/backups/` (pre-existing) |
| `neon_training` install state pre-deploy | `uninstalled` (latest_version null) |

## Backup

- **File:** `/root/backups/neon_crm_pre_p7a_20260521_142958.dump`
- **Size:** 5.3 MB (pg_dump -Fc compressed format)
- **Verification:** file size > 0; not truncated
- **Rollback path if needed:** `pg_restore --clean --if-exists -d neon_crm /root/backups/neon_crm_pre_p7a_20260521_142958.dump`

## Code pull

```
git fetch origin → new branch: feat/training-phase-7a
git checkout feat/training-phase-7a
git pull origin feat/training-phase-7a → Already up to date
HEAD: 33461cd90bb187d72a6604b579cbc53198305df4
```

Target commit `33461cd` confirmed.

## Module install

**Deviation from prompt:** prompt specified `-u neon_training` (upgrade). Prod's `neon_training` was `uninstalled` (never previously installed — this IS the first deployment). Used `-i neon_training` (install) instead.

**Impact on migration scripts:** the four post-migrate scripts (`17.0.7.12.1`, `.3`, `.4`, `.5`) **do NOT fire on fresh install** — they are upgrade-only by Odoo's migration framework. The fixes they apply are already baked into the current code state:

- `17.0.7.12.1` → `application=True` in current manifest ✅
- `17.0.7.12.3` → admin-grant via `_post_init_hook` (runs on `-i`) ✅
- `17.0.7.12.4` → ORM-based admin-grant in `_post_init_hook` (correct propagation) ✅
- `17.0.7.12.5` → `_compute_display_name` override in current model code ✅

End state is identical to "upgrade-from-12.0 with all 4 migrations run." Verified in step 6 below.

**Install log key lines:**

```
loading neon_training/security/neon_training_groups.xml
loading neon_training/security/ir.model.access.csv
loading neon_training/security/neon_training_certification_rules.xml
loading neon_training/security/neon_training_cross_competency_rules.xml
loading neon_training/security/neon_training_assignment_gate_log_rules.xml
loading neon_training/data/neon_training_data.xml
loading neon_training/data/neon_training_cron.xml
loading neon_training/data/neon_training_mail_templates.xml
loading neon_training/views/... (15 view files)
loading neon_training/report/... (3 report files)
loading neon_training/views/neon_training_menu.xml
Module neon_training loaded in 0.99s, 1215 queries (+1215 other)
```

All 24 data files loaded in declared order. **No ERROR or CRITICAL** in install output.

## Container restart

```
docker compose restart odoo → Started
HTTP service up at d229d6e2ccee:8069
Registry loaded in 0.767s
```

Clean startup. No ERROR / CRITICAL.

## Verification (step 6)

Six assertions via odoo shell:

```
installed_version: 17.0.7.12.5
application: True
state: installed
admin in training_admin: True
admin in training_signoff (implied): True
admin in training_user (implied): True
cert types seeded: 32
Training root visible to admin: True  (root_id=318, top apps=13)
ALL VERIFICATIONS PASSED
```

| # | Check | Result |
|---|---|---|
| 1 | `neon_training` installed at `17.0.7.12.5` | ✅ |
| 2 | `application=True` | ✅ |
| 3 | `base.user_admin` (Robin) in `group_neon_training_admin` | ✅ |
| 4 | Admin in `group_neon_training_signoff` via implied chain | ✅ |
| 5 | Admin in `group_neon_training_user` via implied chain | ✅ |
| 6 | 32 cert types seeded | ✅ |
| 7 | Training root menu visible to admin via `load_web_menus` | ✅ (root_id=318, admin sees 13 top-level apps total) |

The implied-ids cascade landed via `_post_init_hook`'s ORM write — the fix from pre-deploy session #3 (`reference_odoo17_implied_ids_orm_vs_sql.md`) was the exact path that made this work on fresh install too.

## Tag

```
git tag v17.0.8.0.0-phase7a-live 33461cd
git push origin v17.0.8.0.0-phase7a-live
→ [new tag] v17.0.8.0.0-phase7a-live -> v17.0.8.0.0-phase7a-live
```

Tag now points at the deployed commit. Phase 6's tag (`v17.0.7.9.1-phase6-walkthrough-fixes` at `9d1c817`) remains valid as the rollback target.

## What's live on prod now

- **Module:** `neon_training` at `17.0.7.12.5`
- **Cert types:** 32 seeded (4 categories: Equipment, Role Tier, Safety, Soft Skill)
- **Models:** certification + category + type + cross_competency + assignment_gate_log + 2 wizards (quote_gate_override, event_start_gate_override) + find_qualified_user wizard + dashboard
- **Cross-cutting touches on Phase 7a's neighbours:** `commercial.job.crew` + `commercial.event.job` extensions (gate inference + log o2m); `neon.finance.quote.action_accept` extension (tier-2 wizard); `res.users` reverse o2m to cross-competency
- **Surfaces:** apps switcher ("Neon Training" visible to Robin); Dashboard; Find Qualified User; Certifications; Cross-Competencies; Gate Log; Reports (3 QWeb PDFs); Configuration → Categories + Types
- **3-tier gating engine:** info toast (M9) + warn wizard (M10) + block wizard (M11) all live and ready to fire on crew assignment / quote accept / event start
- **Reports:** Expiring Soon, Compliance Roster (signoff+admin only), Cross-Competency Log

## What's NOT done yet (deferred per Tatenda's 21 May 2026 direction)

- **Real user provisioning** — Munashe, Tatenda, Lisa, Evrill, Kudzi, Ranganai (when created), and the 9 paused tech crew (Arnold M et al.) have NOT been granted training groups. Per pre-deploy session #2 + #3 checklist (`docs/phase-7a/chrome-session-1-pre-deploy.md`), this is a manual Settings → Users pass.
- **ACL cleanup** — the 4 unintended `base.group_user.implied_ids` (`group_no_one`, `group_multi_currency`, `group_product_pricelist`, `mail.group_mail_template_editor`) remain on every internal user. Migration deferred to Phase 11 cutover per Tatenda's call. Memory: `project_phase7a_status.md` "PROD ACL FINDING" section captures the deferred decision.
- **Crew onboarding resume** — the 9 paused tech crew users (Arnold M, John, Bothwell, Kelvin, Stanley, Kudzai M, Trymore, Oswell, Lovejoy) are NOT created on prod. Will be created via Phase 7b's onboarding workflow (Skip Onboarding × 9) once 7b ships.
- **Phase 11 polish items** (6) — pagination "1 / 1", drill-through button wrap, dashboard whitespace, cert form duplicate User field, state pipeline display, Verify button visibility on Draft cert. All cosmetic, all logged in `chrome-session-1-pre-deploy.md`.

## Phase 7a is officially DEPLOYED + LIVE on prod

Test-deploy state. No real users on the system yet. Ready for:

- Robin walkthrough (script: `docs/phase-7a/walkthrough-script.md`) — 90–120 min meeting
- Phase 7b build (after walkthrough confirms Phase 7b open questions)
- Phase 11 cutover (real users + ACL cleanup, separately scheduled)

## Rollback plan (reference; not invoked)

If any post-deploy issue surfaces and rollback is needed:

1. `docker compose stop odoo`
2. `docker compose exec -T db psql -U odoo -c "DROP DATABASE neon_crm"`
3. `docker compose exec -T db psql -U odoo -c "CREATE DATABASE neon_crm OWNER odoo"`
4. `docker compose exec -T db pg_restore -U odoo -d neon_crm /root/backups/neon_crm_pre_p7a_20260521_142958.dump`
5. `cd /opt/neon-odoo && git checkout v17.0.7.9.1-phase6-walkthrough-fixes`
6. `docker compose start odoo`
7. Verify Phase 6 surfaces work
8. Report failure mode

Rollback path not invoked — deploy clean.

---

## Timestamps

| Event | Time (server UTC) |
|---|---|
| Pre-flight | 14:29:54 |
| Backup created | 14:29:58 |
| Code pulled (HEAD `33461cd`) | 14:30:25 |
| `-i neon_training` started | 14:30:43 |
| Module loaded (0.99s) | 14:30:50 |
| Container restart | 14:31:48 |
| HTTP up + Registry loaded | 14:31:53 |
| Verification all passed | 14:32:15 |
| Tag created + pushed | 14:32:30 |
| Deploy log committed | (this commit) |

Total deploy time: ~3 minutes (excluding deploy-log authoring).
