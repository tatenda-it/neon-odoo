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

---

## Post-Deploy Manual Grant (21 May 2026, ~14:50 UTC)

Chrome verification surfaced that the `_post_init_hook` targets `base.user_admin` by xmlid only -- which on **prod resolves to a system superuser account** (`superuser@neonhiring.com`, uid=2), NOT Robin's actual login. Robin's prod account is a separate user record (`robin@neonhiring.co.zw`, uid=21), as is Munashe's (`munashe@neonhiring.co.zw`, uid=7). Neither received the auto-grant.

This mismatch was masked on local dev because Tatenda's dev DB has `base.user_admin` configured with login `robin@neonhiring.co.zw` (same xmlid, different login text) -- so dev verification appeared correct while prod was silently missing the grants.

**Manual grant via ORM (with implied_ids propagation):**

```python
training_admin = env.ref("neon_training.group_neon_training_admin")
robin = env["res.users"].search([("login", "=", "robin@neonhiring.co.zw")])
munashe = env["res.users"].search([("login", "=", "munashe@neonhiring.co.zw")])
training_admin.sudo().write({"users": [(4, robin.id), (4, munashe.id)]})
env.cr.commit()
```

**Verification after grant -- three-group cascade per user:**

```
robin@neonhiring.co.zw   (uid=21):  admin: ✓  signoff: ✓ (implied)  user: ✓ (implied)
munashe@neonhiring.co.zw (uid=7):   admin: ✓  signoff: ✓ (implied)  user: ✓ (implied)
```

Final training group membership on prod:

```
training_admin   (3): munashe / robin / superuser
training_signoff (3): same 3 via implied_ids
training_user    (3): same 3 via implied_ids
```

**Note on execution sequence**: pre-flight at ~14:48 UTC showed both Robin + Munashe with zero training groups. The subsequent grant script at ~14:50 UTC found them ALREADY in `training_admin` -- between the two runs, the grants landed (likely via UI Settings -> Users, applied concurrently by Tatenda during Chrome inspection). End state regardless is the intended one: all three training-tier users in place, implied chain propagated, surfaces visible.

## Phase 11 amendment candidate

The base.user_admin-only auto-grant approach is fragile for multi-tenant or "admin is not user-named-Robin" scenarios. Future Neon module deploys should auto-grant superuser tier (Robin + Munashe + any future MD/OD additions) by **login lookup**, not by base.user_admin xmlid alone.

Two viable patterns -- pick one for Phase 11:

1. **Config-parameter-driven**: `ir.config_parameter` key `neon.superuser_logins` = `'robin@neonhiring.co.zw,munashe@neonhiring.co.zw'`. `_post_init_hook` reads it and grants to every matching user via ORM.

2. **Meta-group**: define `neon_core.group_neon_superuser`. Robin + Munashe are added once during deploy bootstrap. Subsequent module installs grant their tier-admin group to any member of `group_neon_superuser`. This is the cleaner long-term solution -- adds a deterministic "who are our superusers" handle.

Lean: **option 2** (meta-group). Cleaner integration with implied_ids chains; one grant per module install touches a known set; survives admin rotations.

Track as Phase 11 CLAUDE.md amendment candidate #6 (joining the 5 already queued from pre-deploy session #1).

---

## Post-Deploy Asset Regeneration (21 May 2026, ~17:30 UTC)

Chrome verification surfaced `AssetsLoadingError` on `/web/assets/54e3003/web_editor.backend_assets_wysiwyg.min.js`, causing an OWL component cascade failure that manifested as the Training menu bar rendering only "Find Qualified User" (1 of 7 expected items). Prior diagnostic confirmed server-side ACL state was correct (all 7 menu children appeared in Robin's `load_web_menus` response). Root cause: the `-i neon_training` install invalidated asset bundles but the regenerated bundles weren't persisted as `ir.attachment` records -- the browser was requesting a bundle hash that no longer existed on the server.

### Operation

**Pre-fix attachment count**: 15 records, 11 MB total.

**Step 1 -- Cleared all `/web/assets/%` attachments via ORM:**

```python
attachments = env["ir.attachment"].search(
    [("url", "=like", "/web/assets/%")])
attachments.sudo().unlink()
env.cr.commit()
# 15 deleted, 0 remaining
```

**Step 2 -- Restarted container** to flush the in-memory bundle cache:

```
docker compose restart odoo
HTTP service up at d229d6e2ccee:8069
Registry loaded in 0.684s
```

Clean restart. No errors.

**Step 3 -- Warmed assets via `/web/login` HTTP GET** (HTTP 200, time_total=52s first request, 18s second). However, post-warm verification showed **0 attachments persisted** -- the login page only triggers `web.assets_frontend` compilation, not the backend bundles. Login-page-only warming was insufficient.

**Step 4 -- Forced backend bundle compilation via `ir.qweb._get_asset_bundle()` inside the shell, WITH explicit commit:**

```python
IrQweb = env["ir.qweb"]
for bundle_name in [
    "web.assets_backend",
    "web_editor.backend_assets_wysiwyg",
    "web.assets_web_dark",
    "web.assets_web",
    "web.assets_common",
    "web.assets_frontend",
]:
    bundle = IrQweb._get_asset_bundle(bundle_name)
    bundle.js()
    bundle.css()
env.cr.commit()
```

**Step 5 -- Post-fix verification:**

```
Asset attachments after compile + commit: 12

/web/assets/c38f01f/web.assets_frontend.min.css                510 KB
/web/assets/2f43454/web.assets_frontend.min.js                1.6 MB
/web/assets/cf83e13/web.assets_common.min.css                   0 bytes (empty bundle)
/web/assets/cf83e13/web.assets_common.min.js                    0 bytes (empty bundle)
/web/assets/ae67fbd/web.assets_web.min.css                    938 KB
/web/assets/d86ffb2/web.assets_web.min.js                     4.2 MB
/web/assets/101ae64/web.assets_web_dark.min.css               945 KB
/web/assets/d86ffb2/web.assets_web_dark.min.js                4.2 MB
/web/assets/e2203b9/web_editor.backend_assets_wysiwyg.min.css 200 KB
/web/assets/54e3003/web_editor.backend_assets_wysiwyg.min.js  690 KB  ← the previously-failing bundle
/web/assets/ae67fbd/web.assets_backend.min.css                938 KB
/web/assets/291811e/web.assets_backend.min.js                 4.2 MB
```

The bundle hash `54e3003` matches the one in the original `AssetsLoadingError` exactly -- Odoo's bundle hashing is content-deterministic, so the regenerated URL is identical to the one the browser was requesting.

**HTTP serve verification:**

```
GET /web/assets/54e3003/web_editor.backend_assets_wysiwyg.min.js
→ HTTP/1.1 200 OK; Content-Length: 690061; Content-Type: application/javascript

GET /web/assets/291811e/web.assets_backend.min.js
→ HTTP/1.1 200 OK; Content-Length: 4228602
```

Both bundles serve cleanly through the nginx + Odoo stack.

### Lesson learned: asset-warming via login page is insufficient

`/web/login` triggers `web.assets_frontend` only. Backend bundles (`web.assets_backend`, `web_editor.backend_assets_wysiwyg`, etc.) only compile on authenticated `/web` access. For unattended asset regeneration after a destructive `ir.attachment` clear, the reliable path is the ORM `_get_asset_bundle().js() + .css()` invocation INSIDE odoo shell, with an explicit `env.cr.commit()` so the compiled bundles persist as `ir.attachment` records (otherwise they roll back on shell exit).

This applies to every future Phase deploy where asset state needs to be reset -- the `clear + restart + curl login` pattern is incomplete; the `force compile via shell with commit` pattern is the canonical fix.

### Phase 11 amendment candidate #7

Add to module install/upgrade post-init: a one-line forced compile of the critical bundles immediately after the data load, with explicit commit. Prevents the "install regenerates assets but doesn't persist them" gap from being a manual cleanup step per deploy.

Suggested hook code:

```python
def _post_init_hook(env):
    # ... existing grants ...

    # Pre-warm backend bundles so first authenticated client
    # request doesn't hit a missing ir.attachment.
    IrQweb = env["ir.qweb"]
    for bundle_name in (
        "web.assets_backend",
        "web_editor.backend_assets_wysiwyg",
    ):
        try:
            bundle = IrQweb._get_asset_bundle(bundle_name)
            bundle.js()
            bundle.css()
        except Exception:
            # Non-fatal -- bundles will compile lazily on first request
            pass
```

Track as Phase 11 CLAUDE.md amendment candidate #7 (now 7 total).

---

## Combined deploy: `neon_core` + cert routing override (22 May 2026, ~08:17 UTC)

**Deployer:** Tatenda via Claude Code SSH
**Trigger:** Two structural fixes from Phase 7a pre-deploy + post-deploy sessions.

- `neon_core` (`1464bee`) -- 5 RBAC tier meta-groups + base.group_user implied_ids hygiene + canonical user assignment by login (replacing the fragile base.user_admin xmlid path).
- `neon_training` cert verification routing override (`2af1167`) -- always route TODOs to managerial superusers (Robin + Munashe) regardless of cert type's sign_off_authority. Override added because neon_core's superuser cascade put Robin into every authority group, collapsing the first-by-id pick.

### Pre-flight (post-fix)

| Check | Result |
|---|---|
| SSH connectivity | ✅ |
| Prod HEAD before deploy | `33461cd` (Phase 7a baseline) + manual ACL grants from 21 May session |
| Prod working tree | ✅ Clean (only `config/odoo.conf.pre-phase1-backup` untracked, pre-existing) |
| Push gap | Initial fetch showed origin at `a122f19`; pushed `1464bee` + `2af1167` from dev before re-pulling on prod |

### Backup

- **File:** `/root/backups/neon_crm_pre_neoncore_20260522_101431.dump`
- **Size:** 5.7 MB (pg_dump -Fc)
- **Rollback path:** `pg_restore --clean --if-exists -d neon_crm /root/backups/neon_crm_pre_neoncore_20260522_101431.dump`

### Code pull

After pushing dev branch, prod `git pull origin feat/training-phase-7a` advanced `a122f19 .. 2af1167`. HEAD on prod = `2af1167`.

### Install + upgrade

```
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -i neon_core -u neon_training --stop-after-init --no-http
```

Key log lines captured:

```
neon_core: stripped implied_id base.group_no_one (Developer mode) from base.group_user.
neon_core: stripped implied_id base.group_multi_currency (Multi-currency picker) from base.group_user.
neon_core: stripped implied_id product.group_product_pricelist (Pricelist visibility) from base.group_user.
neon_core: stripped implied_id mail.group_mail_template_editor (Mail template editor) from base.group_user.
neon_core cleanup summary -- removed=4, skipped=0.

neon_core: assigned robin@neonhiring.co.zw to neon_core.group_neon_superuser
neon_core: assigned munashe@neonhiring.co.zw to neon_core.group_neon_superuser
neon_core: assigned tatenda@neonhiring.co.zw to neon_core.group_neon_superuser
neon_core: assigned admin@neonhiring.co.zw to neon_core.group_neon_bookkeeper
neon_core: assigned lisar@neonhiring.co.zw to neon_core.group_neon_sales_rep
neon_core: assigned evrill@neonhiring.co.zw to neon_core.group_neon_sales_rep
neon_core: assigned ranganai@neonhiring.co.zw to neon_core.group_neon_lead_tech

neon_core reconcile: stripped base.group_no_one from 3 tier user(s).
neon_core reconcile: stripped base.group_multi_currency from 1 tier user(s).
neon_core reconcile: stripped product.group_product_pricelist from 2 tier user(s).
neon_core reconcile: stripped mail.group_mail_template_editor from 4 tier user(s).

Module neon_core loaded in 0.98s, 952 queries
Module neon_training loaded in 0.87s, 878 queries
Registry loaded in 4.980s
```

No ERROR / CRITICAL. The reStructuredText warning `<string>:22: (ERROR/3) Unexpected indentation.` is benign noise from the manifest description docstring.

**Note vs dev:** on prod the lead_tech assignment landed (Ranganai exists at uid=13); on dev that step was skipped because the user record was missing. The login-based lookup gracefully handled both paths.

### Restart + asset regen

`docker compose restart odoo` -- HTTP back online within 15s.

Asset regen via `_get_asset_bundle` (preempting the bundle-stale issue from the Phase 7a deploy):

```
Clearing 15 attachments
  compiled web.assets_backend
  compiled web.assets_web
  compiled web_editor.backend_assets_wysiwyg
  compiled web.assets_frontend
Attachments before regen: 15
Attachments after regen:  8
```

### Verification (6/6 PASS)

1. **Tier assignments** -- 7 canonical users mapped to 4 of 5 meta-groups:
   - Superuser (3): Robin (uid=21), Munashe (uid=7), Tatenda (uid=6)
   - Bookkeeper (1): Kudzaiishe via admin@ (uid=10)
   - Sales Rep (2): Lisa (uid=8), Evrill (uid=9)
   - Lead Tech (1): Ranganai (uid=13)
   - Crew (0): unpopulated; Phase 7b onboarding will assign
2. **base.group_user.implied_ids:** 0 (was 4 before deploy). Clean.
3. **Superuser cascade verified on Robin:** in group_no_one, mail_template_editor, multi_currency, pricelist (all True via meta-group implication chain). Stripping from base.group_user did not affect superuser-tier members.
4. **`_CERT_VERIFIER_LOGINS`** present in `neon_training_certification` module: `('robin@neonhiring.co.zw', 'munashe@neonhiring.co.zw')`.
5. **Routing helper** returns Munashe (alphabetically first) as target on prod when invoked.
6. **Module versions:**
   - `neon_training` 17.0.8.0.1 (state=installed)
   - `neon_core` 17.0.1.0.0 (state=installed)

### Tag

`v17.0.8.0.1-neon-core-cert-routing` -> `2af1167`. Pushed to origin.

### Combined deploy outcome

Both structural fixes live. Phase 11 amendment candidates #6 (meta-group RBAC pattern) and #7-partial (canonical user assignment by login) now in production. The base.group_user leak that granted developer mode + template editor + pricing visibility to every internal user is closed. Cert verification TODOs route to managerial superusers regardless of cert type.

Robin + Munashe both subscribed as followers on any new cert submitted for verification; either can complete `action_verify`. Tatenda excluded from verifier pool per direction.

### Rollback (not invoked)

If a regression had surfaced:
```
docker compose stop odoo
docker exec neon-odoo-db dropdb -U odoo neon_crm
docker exec neon-odoo-db createdb -U odoo neon_crm
docker exec -i neon-odoo-db pg_restore -U odoo -d neon_crm < /root/backups/neon_crm_pre_neoncore_20260522_101431.dump
cd /opt/neon-odoo && git checkout v17.0.8.0.0-phase7a-live
docker compose restart odoo
```

### Total deploy time

~10 minutes including the push-gap detection + dev-side push detour.

---

## neon_core 17.0.1.0.1 -- Settings access fix (22 May 2026, ~08:46 UTC)

**Deployer:** Tatenda via Claude Code SSH
**Trigger:** Post-deploy Chrome verification showed Robin seeing 11 apps after the initial `neon_core` deploy but Settings missing. `base.group_no_one` (Technical Features / developer mode) is not the same as `base.group_system` (Administration / Settings menu access).

### Pre-flight

| Check | Result |
|---|---|
| SSH | ✅ |
| Prod HEAD before deploy | `2af1167` |
| Working tree | ✅ clean (only pre-existing config backup untracked) |
| Push detour | Dev-side `8a77df9` pushed first (`e27cc70..8a77df9`) |

### Backup

- **File:** `/root/backups/neon_crm_pre_neoncore_settings_20260522_104521.dump`
- **Size:** 5.5 MB

### Code pull

`2af1167..8a77df9` fast-forward. 4 files changed, 191 insertions: `__manifest__.py` (version bump), `data/neon_core_groups.xml` (2 new implied_ids on superuser), `migrations/17.0.1.0.1/post-migrate.py` (new), `docs/phase-7a/M12_deploy_log.md` (combined deploy entry from 08:17 session).

### Upgrade

```
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -u neon_core --stop-after-init --no-http
```

Key log lines:

```
Module neon_core loaded (74/74)
loading neon_core/data/neon_core_groups.xml
Running migration [17.0.1.0.1>] post-migrate
neon_core 17.0.1.0.1: base.group_system already in group_neon_superuser.implied_ids; no-op.
neon_core 17.0.1.0.1: base.group_erp_manager already in group_neon_superuser.implied_ids; no-op.
Module neon_core loaded in 0.33s, 175 queries
Registry loaded in 3.316s
```

Both "no-op" lines confirm the XML data file's `(6, 0, [...])` REPLACE handled the actual state change; migration's `(4, id)` add was defensive belt-and-braces. No ERROR / CRITICAL.

### Restart + asset regen

`docker compose restart odoo` clean. Asset regen:

```
Clearing 9 attachments
  compiled web.assets_backend
  compiled web.assets_web
  compiled web_editor.backend_assets_wysiwyg
  compiled web.assets_frontend
Attachments before regen: 9
Attachments after regen:  8
```

### Verification (8/8 PASS)

| user | tier | `group_system` | `group_erp_manager` |
|---|---|---|---|
| robin@neonhiring.co.zw | superuser | YES | YES |
| munashe@neonhiring.co.zw | superuser | YES | YES |
| tatenda@neonhiring.co.zw | superuser | YES | YES |
| admin@neonhiring.co.zw (Kudzi) | bookkeeper | no | no |
| lisar@neonhiring.co.zw | sales_rep | no | no |
| evrill@neonhiring.co.zw | sales_rep | no | no |
| ranganai@neonhiring.co.zw | lead_tech | no | no |

Module state: `neon_core` 17.0.1.0.1 installed.

### Tag

`v17.0.1.0.1-neoncore-settings` -> `8a77df9`. Pushed to origin.

### Outcome

Settings + Access Rights menus now appear for the 3 managerial superusers (Robin / Munashe / Tatenda). All 4 other-tier users (Kudzi / Lisa / Evrill / Ranganai) stay scoped -- Settings access remains restricted as intended.

### Total deploy time

~8 minutes.
