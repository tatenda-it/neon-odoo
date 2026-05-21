# Pre-deploy Chrome Session #1 — Phase 7a

**Date:** 21 May 2026
**Session lead:** Tatenda (driving login + state) + Claude (observing + analysis)
**Branch state at session start:** `feat/training-phase-7a` @ `71dc5d9` (M12.1 commit)
**Branch state at session end:** `feat/training-phase-7a` @ `3258268` (after 4 in-session fix commits)
**Purpose:** Validate Phase 7a feature-complete state before production deploy + Robin walkthrough rehearsal.

This is a repo-side mirror of the canonical session summary in Claude's memory (`project_phase7a_status.md`). Memory file is live working notes; this file is the finalized snapshot at session close. If drift occurs, memory wins for "what's current," this file wins for "what happened then."

---

## Session summary

- Duration: ~2.5 hours of active investigation
- Branch: `feat/training-phase-7a`, advanced from `71dc5d9` to `3258268` (four in-session fix commits)
- 4 deploy fixes shipped during session
- 4 reference docs produced (3 new during session + 1 from M9 already on file)
- Item A elevated to pre-deploy fix; 6 cosmetic items remain for Phase 12 polish
- Session validated the per-sub-phase Chrome cadence -- caught 4 deploy blockers + 6 polish items before Robin's walkthrough

## Deploy fixes shipped during session

| # | Finding | Fix Commit | Manifest |
|---|---------|------------|----------|
| 1 | `neon_training` missing `application=True` in manifest (module installed but invisible in apps switcher) | `33f7b91` | `17.0.7.12.1` |
| 2 | `menu_neon_training_root` restrictive `groups_id` + `base.user_admin` not in any training groups (two-layer fix: menu groups cleared + post-init/post-migrate grant) | `f9c1ea1` | `17.0.7.12.3` |
| 3 | 5 child menus invisible because raw SQL INSERT in post-migrate bypassed `implied_ids` propagation -- admin landed in `training_admin` only, missing implied `signoff` + `user` | `4391cc0` | `17.0.7.12.4` |
| 4 | Dashboard breadcrumb showed debug artifact `neon.training.dashboard,<id>` (TransientModel creates fresh record per load) -- Item A elevated to pre-deploy fix; `_compute_display_name` override returns constant string | `3258268` | `17.0.7.12.5` |

## New reference docs

In `C:/Users/Neon/.claude/projects/C--Users-Neon-neon-odoo/memory/`:

- `reference_odoo17_gate_log_fk_lifecycle.md` (from M9, already on file)
- `reference_odoo17_hook_sudo_partner_capture.md` (from M9, already on file)
- `reference_odoo17_menu_visibility_filter.md` (NEW -- pre-deploy session #2)
- `reference_odoo17_implied_ids_orm_vs_sql.md` (NEW -- pre-deploy session #3)

All indexed in `MEMORY.md`.

## Surfaces verified working

After all four fixes landed and Robin's account reflected the correct group state:

- Neon Training app in apps switcher (after fix #1)
- Training Compliance Dashboard with 13 counters across 4 card groups (after fix #4: clean breadcrumb "Training Compliance Dashboard")
- Find Qualified User wizard with 6 inputs + Search / Reset / Close
- Certifications form with comprehensive structure (state pipeline badge, person/cert metadata, audit chatter)
- M3 dynamic Selection widget verified live with MA3 Console: Category=Equipment, Mode=Tiered (3 levels), Level dropdown shows Basic / Standard / Expert
- Cert type seed data (27+ records visible, 4 categories, sign-off badges + regulatory body fields + validity months)
- Cross-Competencies kanban
- Configuration -> Categories + Certification Types
- Reports submenu with 3 reports (Expiring Soon, Compliance Roster, Cross-Competency Log)
- Gate Log list + kanban (M9 fires)
- State pipeline badge: Draft -> Pending Verification -> Active

## Phase 12 polish backlog (6 items)

Item A was elevated to pre-deploy fix. Items remaining for Phase 12:

- **Item B** -- "1 / 1" pagination on single-record dashboard. May have been partially addressed by display_name fix in commit `3258268`; verify during walkthrough rehearsal. Otherwise needs OWL controller override (custom `js_class` on form view).
- **Item C** -- Drill-through button labels wrap awkwardly (vertical line break). Needs widget/CSS work.
- **Item D** -- Dashboard whitespace between counter rows (visual density).
- **Item E** -- Cert form: "User" field appears twice (header + Person section). Likely view inheritance overlap; deduplicate via xpath.
- **Item F** -- State pipeline shows only Draft -> Pending Verification -> Active; Suspended and Expired absent from the visual statusbar.
- **Item G** -- "Verify" button visible on Draft cert (admin role-based visibility logic -- confirm intent; may be correct UX for admin who can verify before pending_verification transition, but worth a check).
- **Item H** -- Design training-specific icon to replace Odoo default cube placeholder.

## Dashboard singleton optimization (Phase 12)

Dashboard creates a new TransientModel record per visit (record id varies 29/37/41/etc.). display_name now masks the visible symptom. Underlying optimization: switch to a singleton pattern keyed on `env.user.id` (or `env.company.id`) so the dashboard reuses one record per visitor. Auto-vacuum still cleans up after the configured retention; the singleton just avoids per-click churn. Phase 12 performance polish; the cosmetic fix in commit `3258268` is sufficient for deploy.

## Pre-deploy user provisioning checklist

**AUTO-GRANTED** (via `17.0.7.12.4` post-migrate + `_post_init_hook` -- no manual action needed):
- `base.user_admin` (Robin, `robin@neonhiring.co.zw`): `group_neon_training_admin` (propagates to `signoff` + `user` via `implied_ids`)

**MANUAL GRANT REQUIRED** (via Settings -> Users on each environment):
- `munashe@neonhiring.co.zw` (MD): `group_neon_training_admin`
- `ranganai@neonhiring.co.zw` (Lead Tech, when user created): `group_neon_training_signoff`
- `tatenda@neonhiring.co.zw` / `lisar@neonhiring.co.zw` / `evrill@neonhiring.co.zw` (sales / production tier): `group_neon_training_user`
- `admin@neonhiring.co.zw` (Kudzaiishe): `group_neon_training_user` (read-only access for verification workflows)
- Crew accounts (created during Phase 7b onboarding): `group_neon_training_user` via crew onboarding script

## Standing Chrome cadence (locked 21 May 2026)

**Two Chrome sessions per sub-phase boundary**:
1. **Pre-deploy LOCAL session**: after all sub-phase milestones complete on dev branch, before production deploy. Tatenda drives login + state setup; Claude observes + screenshots; no production writes by Claude.
2. **Post-deploy PRODUCTION session**: after sub-phase ships to prod, verify deploy landed.

First execution: 21 May 2026 (Phase 7a pre-deploy). Caught 4 deploy blockers + 6 Phase 12 polish items, validating the per-sub-phase cadence.

## Five-turn session story

- **Turn 1** -- Apps switcher → Training absent → manifest missing `application=True` → Fix #1 (`33f7b91`, 17.0.7.12.1).
- **Turn 2** -- Refresh → Training still absent → backend query revealed restrictive `groups_id` + admin not in training groups → two-layer fix #2 (`f9c1ea1`, 17.0.7.12.3). Hard-stop pause caught raw-SQL `implied_ids` bypass during diagnosis.
- **Turn 3** -- Refresh → Training visible but 5 child menus invisible → ORM vs SQL diagnosis → Fix #3 (`4391cc0`, 17.0.7.12.4) with catch-up migration.
- **Turn 4** -- Refresh → all 7 menus visible. Walked through Dashboard, Find Qualified User, Certifications form (with M3 dynamic widget), Cert Types seed data, Configuration. Surfaced 7 cosmetic items (A-G) + Item H icon.
- **Turn 5** -- Tatenda elevated Item A (dashboard breadcrumb) from Phase 12 polish to pre-deploy fix → Fix #4 (`3258268`, 17.0.7.12.5). Session wrap.

## Phase 11 CLAUDE.md amendment candidates (queued)

1. Gate-1 hook design must explicitly enumerate which lifecycle paths trigger (create / write / unlink / state transition).
2. Reverse o2m enumeration: gate-1 must check whether new o2m fields require reverse-o2m on the comodel; M6 + M8 surfaced this.
3. ORM vs SQL on hook-triggering writes: any migration write touching `res.groups.users` (or other m2m with propagation hooks) must use ORM `(4, id)` over raw SQL. Pre-deploy session #3 surfaced this.
4. Chrome cadence as standing practice: each sub-phase boundary gets two Chrome sessions (pre-deploy local + post-deploy production). Codify in process docs.
5. Manifest hygiene check for new modules: gate-1 for any new top-level Neon module must verify `application=True` is set + root menu has empty `groups_id` (or matches stdlib pattern), avoiding the pre-deploy session #1 + #2 re-discovery.

## Reference cross-links

- `reference_odoo17_menu_visibility_filter.md` -- root visibility two-layer fix
- `reference_odoo17_implied_ids_orm_vs_sql.md` -- the post-migrate ORM bug pattern
- `reference_odoo17_gate_log_fk_lifecycle.md` -- M9 audit FK lessons
- `reference_odoo17_hook_sudo_partner_capture.md` -- M9 sudo escalation pattern
