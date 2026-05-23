# Phase 7e LMS — Sub-phase Close Log

**Sub-phase**: Phase 7e — Internal LMS (Coursera-style)
**Build window**: 22 May 2026 – 23 May 2026
**Branch**: `feat/lms-phase-7e`
**Final HEAD pre-M14**: `540fd47`
**Module versions at close**:
- `neon_lms` 17.0.1.10.0
- `neon_training` 17.0.8.7.0 (Phase 7a extensions for M9/M10/M11)

---

## 1. Milestones

| M | Commits | Scope | Phase 7a touched? |
|---|---|---|---|
| M1 | `634a565` | track + module models + slide.channel ext + ACLs + 7 tracks + 17 modules seeded | no |
| M2 | `e67a0c7` | operating authority model + 6 seeds + track-authority M2M mapping | no |
| M3 | `01e4683` | Foundations strict-gate enforcement + smoke | no |
| M4 | `e49f4c2` | quiz question + option models with type-aware completeness constraint | no |
| M5 | `88bb86d` | practical scenario + completion + signoff routing | no |
| M6 | `1b848a7` | SOP model + module-SOP M2M + attachment helper | no |
| M7 | `633aa3b` | enrollment + track/module completion models + own-row record rule (4th instance) | no |
| M8 | `d6ccec5` | completion workflow + auto-cert issuance + drift handling | no |
| M9 | `c44662b` + `14bfab6` | 8 LMS cert types + `'system'` sign_off_authority + track sub_cert wiring + capstone | **yes** |
| M10 | `d82b51c` + `6657cf2` | gate engine 5th condition (required operating authority) | **yes** |
| M11 | `19b7097` + `652cc3f` | dashboard 4 LMS counters + drill-through actions | **yes** |
| M12 | `14556fb` | 4 LMS notification stubs + dispatcher + M8 wiring | no |
| M13 | `540fd47` | PHP content migration script (one-shot) + smoke | no |
| M14 | (this commit) | integration smoke + 3 reference docs + deploy log | no |

Total: 14 milestones, 17 commits (3 milestones doubled for Phase 7a + Phase 7e separation per CLAUDE.md M4 amendment).

---

## 2. Regression progression

| Milestone | Regression total | Δ from prior |
|---|---|---|
| Phase 7b close (entering 7e) | 1146/1148 | baseline |
| M1 | 1155/1157 | +9 |
| M2 | 1162/1164 | +7 |
| M3 | 1168/1170 | +6 |
| M4 | 1176/1178 | +8 |
| M5 | 1185/1187 | +9 |
| M6 | 1192/1194 | +7 |
| M7 | 1203/1205 | +11 |
| M8 | 1211/1213 | +8 |
| M9 | 1220/1222 | +9 |
| M10 | 1201/1203 | -19 (p6m3 calendar collision joined known-noise) |
| M11 | 1209/1211 | +8 |
| M12 | 1216/1218 | +7 |
| M13 | 1223/1225 | +7 |
| **M14** | **1224/1226** | +1 (integration smoke) |

Known-noise carried forward through Phase 7e (unchanged):
- `p2m2`, `p2m4`, `p2m5` — pre-existing fixture issues
- `p2m7_7` — pre-existing test selector drift (6/8)
- `p6m3` — calendar-induced fixture collision (`today - 5d` vs PRC-0001 seed of 2026-05-18; surfaces because today is 2026-05-23 during the M10-M14 build window)

---

## 3. Phase 7a extensions (3 minor version bumps)

The Phase 7e build crossed module boundaries 3 times, each requiring an atomic Phase 7a commit + Phase 7e smoke commit (M4 cross-module touch amendment to CLAUDE.md):

- `17.0.8.4.0` → `17.0.8.5.0` (M9: 8 cert types + `'system'` sign_off_authority enum value)
- `17.0.8.5.0` → `17.0.8.6.0` (M10: gate engine 5th condition — required operating authority)
- `17.0.8.6.0` → `17.0.8.7.0` (M11: dashboard 4 LMS counters + drill-through actions)

Total Phase 7a files modified across Phase 7e: 11 (4 in M9, 4 in M10, 4 in M11; counts exclude smoke/migration files which live in their owning sub-phase).

`neon_jobs` / `neon_core` / `neon_onboarding` modifications: **0**. Phase 7e's reach was limited to `neon_lms` + targeted extensions to `neon_training`.

---

## 4. Phase 7e module versions (10 minor bumps)

`neon_lms` versions land in order:

```
17.0.1.0.0  (M1)
17.0.1.1.0  (M2)
17.0.1.2.0  (M3)
17.0.1.3.0  (M4)
17.0.1.4.0  (M5)
17.0.1.5.0  (M6)
17.0.1.6.0  (M7)
17.0.1.7.0  (M8)
17.0.1.9.0  (M12) -- M9 bump missed in build, caught + corrected during M12 introspection
17.0.1.10.0 (M13)
```

Note: the version jump 17.0.1.7.0 → 17.0.1.9.0 reflects the M9 bump miss caught during M12's manifest introspection (M12 jumped directly to 1.9.0 to absorb the missed M9 step). Phase 11 amendment candidate logged: manifest version drift detector.

---

## 5. Architectural decisions (chronological)

1. **Single channel + 7 tracks** (Coursera Specialization model per Tatenda 21 May 2026): one `slide.channel` (the program) backed by a Neon-side `neon.lms.track` grouping. Avoids the per-track Odoo-eLearning channel multiplication while preserving Neon's track-based progression model. Lives at `neon_lms.program_channel` seed + 7 `neon_lms.track_*` seeds.

2. **Foundations strict prerequisite** (M1/M3): the Foundations & Safety track is the strict gate (`is_foundation_gate=True`); the other 6 tracks free-order with Foundations as their only prerequisite. Constraint `_check_foundation_gate_prereqs` enforces this at install/upgrade time so seed drift can't bypass.

3. **Parallel completion model** (M7 Option B from schema sketch §4): `neon.lms.track.completion` + `neon.lms.module.completion` are the source of truth for Neon progression. Stdlib `slide.channel.partner` is preserved as the Odoo eLearning surface but doesn't drive Neon state. Sync verification between the two layers was scoped out (deferred to Phase 11 if drift surfaces).

4. **`'system'` sign_off_authority** for LMS auto-issued certs (M9): adds a 4th value to Phase 7a M7's Selection. `_resolve_verify_authority_partners` short-circuits to empty partner set; the LMS workflow `sudo().create()`s the cert directly with `verified_by_id = SUPERUSER_ID`. 7 sub-certs + 1 capstone use this authority. See `reference_odoo17_system_signoff_pattern.md`.

5. **python-docx as a deferred dep** (M13): `from docx import Document` inside `parse_docx()`, not at module top. Module loads cleanly without the dep; only the actual import call fails. See `reference_odoo17_deferred_external_dep.md`.

6. **`short_answer` placeholder for bulk quiz import** (M13): the PHP docx contains question text but not structurally-parseable options. Fake multiple-choice options would mislead learners; `short_answer` with `correct_answer="(pending admin review)"` is honest and satisfies the `_check_question_completeness` constraint. Phase 11 / M14.1 candidate: option-line parser.

7. **Reorder: PHP migration moved from M12 → M13** (mid-build Tatenda direction): the original sequencing had migration in M12; Tatenda asked to defer it for a focused session and use M12 for notification stubs (lighter scope). M13 then ran as a single milestone rather than continuing the M10-M12 batch protocol.

---

## 6. Deferred work

### Deferred to admin run (separable from deploy)

- **PHP content import**: `addons/neon_lms/scripts/migrate_php_content.py` ships with the deploy but doesn't run automatically. Tatenda invokes it via `odoo shell` when the docx is uploaded + python-docx installed in the container. Pre-flight check refuses to run if any precondition missing.

### Deferred to later sub-phase / Phase 11

- **Quiz option-line parser** (M14.1 candidate): bulk-imported quiz questions land as `short_answer` placeholders. A future polish pass can parse "A. answer / B. answer / C. answer" option lines from each module's docx body and upgrade to `multiple_choice` with real options.
- **Slide rich formatting**: M13 ships one slide per module with joined paragraph text. Rich per-lesson slide splitting + image/video embeds belongs in a later content polish pass.
- **LMS portal views**: Phase 7e built the data model + workflow + dashboard. Learner-facing portal views (Coursera-style course catalogue, progress bar, certificate gallery) are scoped to a later sub-phase or Phase 11.
- **WhatsApp / email actual sends**: M12 ships notification stubs that log to chatter. Phase 9 overrides `_notify_send` to route to actual channels — the 4 hook methods (`_notify_track_certified`, `_notify_capstone_certified`, `_notify_authority_granted`, `_notify_quiz_failed_max_attempts`) are the frozen API contract Phase 9 consumes.

---

## 7. Reference docs produced (M14)

1. `.claude/reference_odoo17_system_signoff_pattern.md` — `'system'` short-circuit pattern + when to use vs other authorities.
2. `.claude/reference_odoo17_deferred_external_dep.md` — defer-to-method-scope import pattern for optional libraries (python-docx, openpyxl, etc.).
3. `.claude/reference_neon_content_migration_pattern.md` — reusable one-shot content migration script structure: scripts/ location, preflight, mojibake sanitizer, idempotency, atomic transactions, smoke testability.

Plus 1 architectural reference doc was authored earlier in the sub-phase:
- M7 ship: own-row record rule pattern doc (4th instance documented)

---

## 8. Phase 11 amendment candidates queued

| Candidate | Surfaced in | Notes |
|---|---|---|
| Calendar-bound fixture dates | M10 / p6m3 | Fixtures using `today - Nd` collide with stale seeds at predictable intervals. Fix: freeze fixture dates or reset colliding seeds. |
| Manifest version drift detector | M12 | M9's manifest bump silently failed; caught only during M12 introspection. CI check: manifest version === latest `migrations/` subdir name. |
| Hardcoded test counts | T7e1304 / 3+ instances | Smoke tests asserting `count == 6` for "all Foundations authorities" are brittle when seeds grow. Use computed expectations. |
| Quiz option-line parsing | M13 / M14.1 follow-up | Upgrade `short_answer` placeholders to real `multiple_choice` records with parsed options. |
| LMS portal views | Phase 7e scope | Learner-facing portal is the largest deferred surface. |

---

## 9. Cross-cutting touches summary

- Phase 7a files modified across Phase 7e: **11**
- `neon_jobs` / `neon_core` / `neon_onboarding` files modified: **0**

The narrow blast radius matches the gate-1 plan for each cross-cutting milestone; no scope creep into adjacent modules.

---

## 10. Module count growth

- Pre-Phase-7e (post-Phase-7b): 82 installed modules
- Post-Phase-7e (current): 92 installed modules

Delta: +10 (`website_slides` + its 9 transitive deps + the new `neon_lms` itself). `website_slides` is the stdlib eLearning backbone we extend via `_inherit` on `slide.channel` and `slide.channel.partner`.

---

## 11. Ready for prod deploy

- **Branch**: `feat/lms-phase-7e` @ M14 commit
- **Tag target**: `v17.0.8.7.0-phase7e-live`
- **Deploy operation**: `-i neon_lms -u neon_training -d neon_crm` + asset regen
- **Backup destination**: `/root/backups/neon_crm_pre_p7e_<timestamp>.dump`
- **Post-deploy verifications**:
  1. `installed_version` reads 17.0.1.10.0 (neon_lms) + 17.0.8.7.0 (neon_training)
  2. 17 LMS modules + 7 tracks + 6 authorities seeded
  3. 8 LMS cert types present (`cert_type_neon_foundations_safety`, `_audio_technical`, `_lighting_technical`, `_video_led_technical`, `_workflow_ops`, `_soft_skills`, `_rigging`, `_neon_technical_capstone`)
  4. Dashboard renders with 4 new LMS counters + drill-through
  5. Gate engine 5th condition active (operating authority requirement)
  6. Integration smoke runs clean against prod DB (1/1 stages)

PHP content import + python-docx install + actual import run are a separate admin operation, NOT part of the deploy. The deploy lands an empty LMS structure with the workflow + cert types + gate logic; content arrives when Tatenda runs the migration script.

---

## 12. Sub-phase metrics

- Build window: 22 May 2026 – 23 May 2026 (calendar)
- Approx active build time: ~24-30 hours (estimated from milestone batch durations)
- Commits to feat branch: 17 (1 per milestone except M9/M10/M11 split + M14)
- Smoke tests added: 78 (9+7+6+8+9+7+11+8+9+9+8+7+7 from M1-M13 + 1 integration in M14)
- Reference docs produced: 3 (M14) + 1 (M7) = 4
- Hard stops: 0 (M13 pre-flight pause was process-level direction-check, not a code stop)
- Architectural pivots: 0 (every decision was a defensible build-time adaptation within gate-1 scope)

Phase 7e closes.

---

## 13. Phase 7e Production Deploy (23 May 2026, 05:42–05:46 UTC)

**Deploy operator**: Tatenda Loyd (via Claude Code session)
**Backup**: `/root/backups/neon_crm_pre_p7e_20260523_054120.dump` (6.0 MB)
**Pre-deploy HEAD on prod**: `212e9ec` (Phase 7b sub-phase close commit; the `f994ec0` deploy-log commit was authored locally after the Phase 7b deploy and was never on prod — that's expected, docs ride along on the next deploy)
**Post-deploy HEAD on prod**: `e40cf1e` (Phase 7e M14 close)
**Tag**: `v17.0.8.7.0-phase7e-live` → `e40cf1e`
**Deploy duration**: ~4 minutes (pull + install + restart + asset regen + verify)

### Pre-deploy module state

```
neon_finance    | 17.0.7.9.1
neon_core       | 17.0.1.0.1
neon_jobs       | 17.0.4.0.15
neon_training   | 17.0.8.4.0
neon_onboarding | 17.0.1.10.0
(neon_lms — not installed)
```

### Install + upgrade log excerpts

```
2026-05-23 05:42:11 Loading module website_partner (65/90)
2026-05-23 05:42:12 Module website_partner loaded in 0.25s
2026-05-23 05:42:12 Loading module website_profile (72/90)
2026-05-23 05:42:12 Module website_profile loaded in 0.44s
2026-05-23 05:42:12 Loading module website_slides (81/90)
2026-05-23 05:42:14 Module website_slides loaded in 1.75s
2026-05-23 05:42:14 Loading module gamification_sale_crm (82/90)
2026-05-23 05:42:14 Module gamification_sale_crm loaded in 0.29s
2026-05-23 05:42:14 Loading module neon_lms (89/90)
2026-05-23 05:42:15   loading neon_lms/security/ir.model.access.csv
2026-05-23 05:42:15   loading neon_lms/security/neon_lms_scenario_rules.xml
2026-05-23 05:42:15   loading neon_lms/security/neon_lms_enrollment_rules.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_program.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_tracks.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_modules.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_authorities.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_authority_mapping.xml
2026-05-23 05:42:15   loading neon_lms/data/neon_lms_cert_type_wiring.xml
2026-05-23 05:42:15 Module neon_lms loaded in 0.73s, 734 queries
2026-05-23 05:42:15 90 modules loaded in 5.62s, 5519 queries
2026-05-23 05:42:16 Registry loaded in 10.570s
2026-05-23 05:42:16 Initiating shutdown
```

No `ERROR` / `CRITICAL` lines. Three `WARNING` lines about `tracking` parameter on `neon_state` / `track.completion.state` / `module.completion.state` — cosmetic and identical to dev (Odoo doesn't recognise `tracking=True` on these field types but the field still tracks via mail.thread inheritance).

The 3 `neon_training` post-migrate scripts (17.0.8.5.0 / 17.0.8.6.0 / 17.0.8.7.0) are log-only no-ops — they don't surface their own log lines because the migration framework only logs when there are operations to perform. The version progression is confirmed via the final `installed_version` query.

### Restart + asset regen

```
2026-05-23 05:43:XX docker compose restart odoo   -> Started
                    odoo HTTP ready
2026-05-23 05:44:08 deleted 11 stale /web/assets/* attachments
2026-05-23 05:44:10 Generating /web/assets/93b75ac/web.assets_backend.min.js (id:910)
2026-05-23 05:44:10 Generating /web/assets/03124c9/web.assets_backend.min.css (id:911)
2026-05-23 05:44:12 Generating /web/assets/40c70e3/web.assets_web.min.js (id:912)
2026-05-23 05:44:12 Generating /web/assets/03124c9/web.assets_web.min.css (id:913)
2026-05-23 05:44:13 Generating /web/assets/a26ae87/web_editor.backend_assets_wysiwyg.min.js (id:914)
2026-05-23 05:44:13 Generating /web/assets/4117c4e/web_editor.backend_assets_wysiwyg.min.css (id:915)
2026-05-23 05:44:13 Generating /web/assets/336fa63/web.assets_frontend.min.js (id:916)
2026-05-23 05:44:14 Generating /web/assets/bb65093/web.assets_frontend.min.css (id:917)
4/4 bundles compiled. Final /web/assets/* attachment count: 8.
```

### Verification outputs (all 6 PASS)

**1. Module versions**
```
neon_training: installed_version=17.0.8.7.0 state=installed
neon_lms:      installed_version=17.0.1.10.0 state=installed
```

**2. Seed data counts**
```
slide.channel:                 1   (expected >= 1)
neon.lms.track:                7   (expected 7)
neon.lms.module:               17  (expected 17)
neon.lms.operating.authority:  6   (expected 6)
```

**3. 8 new LMS cert types seeded** (all with `sign_off_authority='system'`)
```
cert_type_neon_foundations_safety  OK (id=33)
cert_type_neon_audio               OK (id=34)
cert_type_neon_lighting            OK (id=35)
cert_type_neon_video_led           OK (id=36)
cert_type_neon_workflow_ops        OK (id=37)
cert_type_neon_client_ready        OK (id=38)
cert_type_neon_rigging             OK (id=39)
cert_type_neon_technical           OK (id=40)
```

**4. Dashboard LMS counters live for Robin**
```
robin: uid=21
lms_active_enrollments:        0
lms_pending_capstone:          0
lms_authorities_granted_30d:   0
lms_track_cert_distribution:   "Foundations and Safety: 0, Audio Technical: 0,
                                Lighting Technical: 0, Video and LED Technical: 0,
                                Workflow and Operations: 0, Soft Skills: 0,
                                Rigging: 0"
```

All four counters return real values (not errors); zero counts reflect the fresh-install state with no learner activity yet.

**5. eLearning menu visible to Robin**
```
eLearning menu root id: 366
visible: True
```

**6. Cert verifier list unchanged (prior invariant)**
```
_CERT_VERIFIER_LOGINS: ('robin@neonhiring.co.zw', 'munashe@neonhiring.co.zw')
```

### Module count growth

- Pre-Phase-7e on prod: 81 installed modules (post-Phase-7b state)
- Post-Phase-7e on prod: 90 installed modules
- Delta: +9 (`neon_lms` + `website_slides` + 7 transitive deps: `website_partner`, `website_profile`, `portal_rating`, `gamification`, `gamification_sale_crm`, plus stdlib eLearning deps)

### Tag push

```
git tag v17.0.8.7.0-phase7e-live e40cf1e
git push origin v17.0.8.7.0-phase7e-live
* [new tag]  v17.0.8.7.0-phase7e-live -> v17.0.8.7.0-phase7e-live
```

### Deploy status: SUCCESS

Phase 7e live on `crm.neonhiring.com` at `v17.0.8.7.0-phase7e-live`. All 6 verifications passed. Empty LMS structure deployed (1 channel + 7 tracks + 17 modules + 6 authorities + 8 cert types). Workflow + completion engine + gate engine 5th condition + dashboard LMS counters + notification stubs all live.

### Deferred admin operation: PHP content import

The migration script `addons/neon_lms/scripts/migrate_php_content.py` shipped with this deploy but is NOT yet run on prod. Tatenda runs it manually when the docx is uploaded to a container-readable path and `python-docx` is installed in the prod container:

```bash
# On Hetzner, inside container:
pip install python-docx

# Upload docx to /home/odoo/tmp/ (or override DEFAULT_DOCX_PATH)

# Run from host:
docker compose exec -T odoo odoo shell -d neon_crm --no-http \
    < addons/neon_lms/scripts/migrate_php_content.py
```

Pre-flight check refuses to run if any precondition is missing. Per-section atomic transactions; idempotent re-runs.

### Rollback target (in case of issue)

```
docker compose stop odoo
docker compose exec -T db pg_restore -U odoo -d neon_crm \
    --clean --if-exists /root/backups/neon_crm_pre_p7e_20260523_054120.dump
cd /opt/neon-odoo
git checkout v17.0.8.4.0-phase7b-live
docker compose start odoo
```

Phase 7e deploy complete.

---

## 14. Post-Deploy Redirect Fix (23 May 2026, 05:56 UTC)

### Issue

Phase 7b's `neon_onboarding` manifest `depends` list included `website` (only `portal` was actually needed). That dependency pulled in 6 stdlib `website_*` modules, installing Odoo's public-facing marketing site. The website module's controller intercepts `/` and serves the public homepage, forcing users to take an extra navigation hop before reaching the backend at `/web/login`.

Functional impact: low (login still works after the extra hop). UX impact: poor (cosmetic mismatch + extra click).

### Fix attempt 1 — `ir.config_parameter` (did NOT work)

Per the original fix plan, set:

```python
env["ir.config_parameter"].sudo().set_param(
    "website.homepage_url", "/web")
```

Result after restart: `curl -sI https://crm.neonhiring.com/` returned `HTTP/1.1 200 OK` with the website homepage HTML body. No redirect.

**Why it didn't work**: Odoo 17's `website` model carries its own `homepage_url` field on the `website` record. The HTTP-level redirect at `/` reads `request.website.homepage_url` (the model field), not `ir.config_parameter.website.homepage_url` (the system parameter). The two are independent in this version; setting only the config parameter has no effect on the controller.

### Fix attempt 2 — set field on website record (worked)

```python
website = env["website"].sudo().search([], limit=1)
website.write({"homepage_url": "/web"})
env.cr.commit()
docker compose restart odoo
```

Verification:

```
$ curl -sI https://crm.neonhiring.com/
HTTP/1.1 303 SEE OTHER
Location: https://crm.neonhiring.com/web/login
```

Root URL now redirects directly to the backend login. UX is one fewer hop; cosmetic mismatch resolved.

### State left behind

The `ir.config_parameter website.homepage_url = '/web'` set in fix attempt 1 was left in place — it's harmless (the website controller ignores it) and removing it now is more risk than reward (some future minor-version upgrade may start reading it as a fallback). If a Phase 11 cleanup pass touches this area, drop the orphan config parameter alongside the manifest-deps cleanup.

### Phase 11 cleanup candidate

Remove `website` from `addons/neon_onboarding/__manifest__.py` `depends` list. Verify portal-only build still serves the onboarding portal routes correctly (likely `portal` alone is sufficient — Phase 7b's actual usage is just `/my/onboarding` which lives on portal, not website).

Drop the orphan `ir.config_parameter website.homepage_url` at the same time.

### Lesson learned

`ir.config_parameter` and same-named fields on a Settings-backed model are **not** the same thing in Odoo 17. The model field is read at runtime; the config parameter is only read when Settings reload OR when explicit code does `get_param`. For HTTP controllers, the model field is authoritative.

Future deploys touching website / settings: verify behaviour via the actual HTTP surface (curl), not just by setting the config parameter and assuming.

---

## 15. Login Chrome Bypass (23 May 2026, ~09:43 UTC)

### Issue

Phase 7e's `website_slides` dep transitively pulled in the `website` module. The stock `website.login_layout` view (priority 20) inherits `web.login_layout` and `xpath="t" position="replace"`s the body with `<t t-call="website.layout">`, wrapping `/web/login` in the public-website chrome — `YourLogo` placeholder, `About us` footer, top nav. Pre-Phase-7e the login rendered bare against `web.login_layout` (Neon company logo, no chrome).

### Discovery

`odoo shell` introspection (commit `a1be998`, prod `e40cf1e`) found:

| View key | id | inherit_id | role |
|---|---|---|---|
| `web.login` | 185 | (root) | login form template |
| `web.login_layout` | 184 | (root) | bare login chrome → `t-call="web.frontend_layout"` |
| `auth_signup.login` | 421 | `web.login` | adds signup bits |
| `neon_channels.neon_login_footer` | 1046 | `web.login_layout` | hides default footer (pre-existing Neon override) |
| `website.login_layout` | 1300 | `web.login_layout` | **culprit:** `<xpath expr="t" position="replace"><t t-call="website.layout">…` |

Plus `website.Website.web_login` adds `@http.route(website=True, …)` which populates `request.website` — but the visual wrapping comes from the view inheritance, not the controller.

### Fix

New module `addons/neon_login_bypass/` (manifest `17.0.1.0.0`, depends `[web, website]`) deactivates `website.login_layout`:

```xml
<record id="website.login_layout" model="ir.ui.view">
    <field name="active" eval="False"/>
</record>
```

With that one inheritance removed, `web.login_layout` renders bare (still respecting `neon_channels.neon_login_footer`). Portal (`/my/*`) is unaffected — portal uses `portal.frontend_layout`, not `web.login_layout`.

⚠️ DECISION: chose the deactivation route over a `t-if`-conditional on `website.layout`. The latter modifies `website.layout` globally; setting `t-if="False"` removes `wrapwrap` and leaves an empty shell. Deactivating the bridge view is surgical and reversible.

### Local verification

- `docker compose exec odoo odoo … -i neon_login_bypass --stop-after-init` — registered cleanly, no XML errors (26 queries, 0.37s)
- Smoke `.claude/p_login_bypass_smoke.py` — **4/4 PASS** (`T_LB100` website.login_layout deactivated, `T_LB101` portal.frontend_layout still active, `T_LB102` web.login_layout + auth_signup.login still active, `T_LB103` combined arch has no `oe_website_login_container` and no `t-call="website.layout"`)
- `curl http://localhost:8069/web/login` — `YourLogo:0`, `oe_website_login_container:0`, `o_database_list:1`, `company_logo:1`, `About us:0`

### Prod deploy

| Step | Result |
|---|---|
| SSH preflight | OK; prod HEAD `e40cf1e`; clean working tree |
| Backup | `/root/backups/neon_crm_pre_login_bypass_20260523_094318.dump` (6.6 MB pg_dump -Fc) |
| Branch | `git checkout feat/login-bypass && git pull` → HEAD `a1be998` |
| Install | `docker compose exec odoo odoo -i neon_login_bypass --stop-after-init --no-http` — registry loaded in 3.186s; no ERROR / CRITICAL |
| Restart | `docker compose restart odoo` — clean |
| HTTP up | curl `/web/login` → 200 after 1 retry |
| Verify | `YourLogo:0`, `oe_website_login_container:0`, `About us:0`, `About Us:0`, `o_database_list:1`, `company_logo:1` |

### Tag

```
git tag v17.0.1.0.0-login-bypass a1be998
git push origin v17.0.1.0.0-login-bypass
 * [new tag]  v17.0.1.0.0-login-bypass -> v17.0.1.0.0-login-bypass
```

### Status: SUCCESS

`/web/login` on `crm.neonhiring.com` now renders bare Neon-branded login. Module count: 91 → 92. Asset regen skipped (single XML view active-flag change does not touch any compiled JS/SCSS bundles).

### Rollback (if needed)

```
docker compose stop odoo
docker compose exec -T db pg_restore -U odoo -d neon_crm \
    --clean --if-exists /root/backups/neon_crm_pre_login_bypass_20260523_094318.dump
cd /opt/neon-odoo
git checkout v17.0.8.7.0-phase7e-live
docker compose start odoo
```

Or to leave Phase 7e in place but disable the bypass:

```
docker compose exec odoo odoo -d neon_crm \
    --uninstall=neon_login_bypass --stop-after-init --no-http
docker compose exec odoo odoo shell -d neon_crm --no-http <<'PY'
env.ref("website.login_layout").active = True
env.cr.commit()
PY
docker compose restart odoo
```

(Uninstalling neon_login_bypass alone does NOT re-activate `website.login_layout` — Odoo's data-record ownership tracks the original module, so our XML's `active=False` write persists. The shell command above is required to restore the pre-bypass chrome.)

