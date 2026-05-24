# Phase 7d Custom Knowledge Base — Sub-phase Close Log

**Sub-phase**: Phase 7d — Custom Knowledge Base
**Build window**: 23 May 2026
**Branch**: `feat/kb-phase-7d`
**Final HEAD pre-deploy**: `b755436` (M7) — M8 commit lands on top
**Module versions at close**:
- `neon_kb` 17.0.1.5.0 (new module)
- `neon_training` 17.0.8.10.0 (Phase 7a extension for M6)
- `neon_lms` 17.0.1.15.0 (Phase 7e extension for M5)

---

## 1. Milestones

| M | Commits | Scope | P7a/P7e touched? |
|---|---|---|---|
| M1 | `901238a` | category + tag models + 5 capability-cluster seed categories + tier ACLs (incl portal) + Configuration submenu | no |
| M2 | `982a20c` | article model + 3-state machine + slug create-time auto-gen + OR-merged record rules + write() override | no |
| M3 | `7dde68d` | kanban grouped by category + 5 filter chips + name_search override across name/summary/keywords | no |
| M4 | `bbb9e80` | portal /my/kb list + /my/kb/article/{code} detail + view_count helper + home card | no |
| M5 | `e4b876f` + `d55c8e0` | 3 cross-link M2M (cert_type / sop / module) + SOP reverse pointer + join-table fixup migration | **yes (P7e)** |
| M6 | `a354b76` + `bea0ec0` | dashboard 2 KB counters + drill-through actions (5th cross-module touch on the dashboard) | **yes (P7a)** |
| M7 | `b755436` | 4 notification stubs on state transitions (published/archived/back_to_draft/republished) | no |
| M8 | (this commit) | integration smoke + ref doc update + this deploy log | no |

Total: 8 milestones, 9 commits (M5 and M6 doubled for cross-module atomic separation per CLAUDE.md M4 amendment).

---

## 2. Smoke progression

| Milestone | Smoke | Cumulative |
|---|---|---|
| M1 | 11/11 | 11/11 |
| M2 | 14/14 | 25/25 |
| M3 | 13/13 | 38/38 |
| M4 | 10/10 | 48/48 |
| M5 | 10/10 | 58/58 |
| M6 | 7/7 | 65/65 |
| M7 | 8/8 | 73/73 |
| M8 integration | 1/1 (12 stages) | **74/74** |

**Cumulative: 74/74 PASS** across the 8 milestones plus integration.

Full `.claude/run_regression.sh` baseline after M8 additions: **1379/1391**. The 12 counted failures are entirely known-noise carried forward; no new regressions introduced by Phase 7d. M8 adds the 8 Phase 7d suites to the canonical list (see § 6 below).

Known-noise carried forward (unchanged):
- `p2m2`, `p2m4`, `p2m5` — pre-existing fixture issues (no summary line; not counted in totals)
- `p2m7_7` — pre-existing test selector drift (6/8 — accounts for 2 failures in the total)
- `p6m3` — calendar-induced fixture collision (18/28 — accounts for 10 failures in the total)

---

## 3. Phase 7a + 7e extensions

| Module | From | To | Driver |
|---|---|---|---|
| `neon_lms` | `17.0.1.14.0` | `17.0.1.15.0` | M5: `kb_article_ids` M2M reverse pointer on `neon.lms.sop` |
| `neon_training` | `17.0.8.9.0` | `17.0.8.10.0` | M6: 2 KB counters + drill-through actions on `neon.training.dashboard` |

Phase 7e files modified: **3** (sop model, manifest, migration).
Phase 7a files modified: **4** (dashboard model, dashboard view, manifest, migration).

`neon_jobs` / `neon_core` / `neon_onboarding` / `neon_external_training` / `neon_finance` modifications: **0**.

---

## 4. Phase 7d module versions

`neon_kb` versions land in order:

```
17.0.1.0.0  (M1)
17.0.1.1.0  (M2)
17.0.1.2.0  (M3)
17.0.1.3.0  (M4)
17.0.1.4.0  (M5; FK fixup migration at the same version)
17.0.1.5.0  (M7)
```

Clean linear progression — no migration-rebump churn this sub-phase (M5's join-table fixup landed in `17.0.1.4.0/post-migrate.py` directly, no need for a `.4.1` retry).

---

## 5. Architectural decisions (chronological)

1. **5 capability-cluster seed categories** (M1). Audio / Lighting / Video / Safety / Admin. `noupdate=0` for now — Phase 11 flip to `noupdate=1` after Tatenda enriches descriptions through the admin form.

2. **`last_updated` tracking only** (M2). No revision history chain (`previous_version_id` deferred to Phase 11). The `last_updated` Datetime field is `@api.depends("write_date", "create_date")` + `store=True`, so it advances on every write but doesn't preserve prior bodies.

3. **Slug auto-gen via `@api.model_create_multi` override, NOT a stored compute** (M2). First built with `@api.depends("name") + store=True + readonly=False`. That interacted badly with Odoo's flush queue under savepoint rollback — UniqueViolation inside a savepoint left the cache + pending-write queue in a state where subsequent `cr.commit()` retried the failed INSERT. Switched to create-only auto-gen. Audit-stable URL behaviour matches the original intent. Phase 11 candidate: investigate the underlying savepoint+cache bug.

4. **OR-merged record rules** (M2). Two rules on `base.group_user`: published-for-all and author-sees-own. Odoo OR-merges rules in the same group; net result: users see published OR own-authored (in any state). Permissive rules on `training_admin` + `superuser` open the full dataset for those tiers. Portal sees published only.

5. **`name_search` override + search view `filter_domain` double-coverage** (M3). Brief asked for `_name_search` override (covers autocomplete / quick-search). M3 additionally added `filter_domain` on the search view's name field — covers full search-bar typing too. Both routes search across `name + summary + keywords`.

6. **State machine via `write()` override + context flag** (M2 + Phase 7c M5 pattern). Drag-drop on a kanban with `default_group_by="state"` would otherwise bypass the transition guard. `_transition_to` raises `UserError` on invalid jumps; `neon_p7d_internal_transition` context flag prevents re-entry.

7. **Server-side author/admin gate in action methods** (M2 + M3). Form view buttons gate with `groups=` for visibility, but `_assert_author_or_admin` is the security boundary — `xmlrpc` / shell calls bypass the view.

8. **`view_count` increments only via portal route** (M4). Admin form-open does NOT bump the counter. Brief documented the design — popularity metric is for the portal audience, not for admin browsing.

9. **Cross-link via M2M with forward-string + join-table fixup migration** (M5). Phase 7c M4 pattern applied to M2M instead of M2O. `addons/neon_kb/migrations/17.0.1.4.0/post-migrate.py` idempotently creates the 3 join tables + FKs if Odoo's table-init pass missed them (only matters on staged-upgrade scenarios; combined `-u neon_lms,neon_kb` creates them correctly during the first install).

10. **5th cross-module touch on the dashboard — fully mechanical** (M6). Same defensive `env.get` pattern as LMS counters (Phase 7e M11) + Onboarding counters (Phase 7b) + External Training counters (Phase 7c M6). Pattern is now ripe for the `register_dashboard_counter` helper Phase 11 candidate.

11. **ASCII hyphen in stub marker, with split-literal grep awareness** (M7). The marker `[Notification stub - Phase 9 will send]` uses U+002D. Smokes verify the marker against the RENDERED chatter body, not via `inspect.getsource()` — when the marker is split across adjacent string literals (Python concat at compile time), source-level grep reports false-negative.

---

## 6. Reference doc updates this sub-phase

| File | Change |
|---|---|
| `.claude/reference_neon_notification_stub_pattern.md` | Appended "Marker greppability — rendered body, not source" section. Captures the M7 finding that smokes must check rendered chatter, not source via `inspect.getsource()`, when the marker is split across adjacent string literals. |

No new reference docs this sub-phase — the patterns this batch exercised (`reference_odoo17_forward_string_m2o_fk.md`, `reference_odoo17_kanban_drag_state_machine.md`, `reference_neon_notification_stub_pattern.md`) are well-established by now. The notification doc update is a clarification, not a new pattern.

The canonical regression `.claude/run_regression.sh` gets the 8 Phase 7d suites added (7 milestones + integration smoke).

---

## 7. Phase 11 amendment candidates queued this sub-phase

1. **Revision history chain** — `previous_version_id` Many2one on article, deferred from M2 per Tatenda's spec.
2. **Slug + savepoint UniqueViolation cache poisoning investigation** — M2 finding. The stored-compute slug pattern interacted badly with Odoo's flush queue under savepoint rollback. Workaround was to switch to create-only auto-gen; underlying bug remains.
3. **Smoke harness run-isolation** — M2 finding. `env.cr.commit()` mid-smoke commits leftover records that subsequent runs collide with. Either each smoke wraps in a single transaction with no internal commit, OR each smoke gets a unique run-id prefix that the cleanup phase strips.
4. **Savepoint + UniqueViolation transaction-abort recovery** — M2 finding. Odoo's `cr.savepoint(flush=True)` doesn't reliably recover; `flush=False` defers the problem. Phase 11 patch on the cursor context manager would unblock generic ORM-triggered constraint testing.
5. **"Popular" threshold via `ir.config_parameter`** — M3. View count threshold for the Popular filter chip is hard-coded at 10.
6. **`view_count` rate-limiting** — M4. Once-per-user-per-hour suppression via sidecar log model.
7. **`register_m2m_join` generic helper** — M5. The 3 M2M join-table fixup blocks in `migrations/17.0.1.4.0/post-migrate.py` are textually identical save for the table/column names; a `register_m2m_join(table, col_a, col_b, ref_a, ref_b)` in `neon_core` collapses them to a one-liner per join.
8. **RequestStub smoke helper for portal renders** — M5. Portal layout templates (`portal.portal_layout`) can't render in shell because they need `request.env.user._is_public()`. A minimal stub would unblock full-template smoke renders.
9. **QWeb `<li t-field=...>` compiler hint** — M5. The assertion error is correct but doesn't point at the fix (`<span t-field="...">` inside the `<li>`).
10. **`register_dashboard_counter` generic helper** — M6 (5x pattern). Five cross-module extensions of `neon.training.dashboard` now share the same defensive-`env.get` + drill-through structure. A helper in `neon_core` would shrink each future extension from ~50 lines to a one-liner per counter.
11. **`action_publish` dual-purpose refactor** — M7. The same method drives "draft → published" AND is a building block for the "archived → published" republish flow. Currently disambiguated via a `prior_state` check before firing the publish notification. Phase 11: explicit notification-routing per state-graph edge, or split `action_publish` into `_publish_from_draft` / `_publish_from_archived`.
12. **Notification source-vs-rendered grep lesson documented** — M7. Filed against `reference_neon_notification_stub_pattern.md` and updated in this sub-phase's docs commit.

---

## 8. Cross-cutting touches summary

| Module | Files modified across Phase 7d |
|---|---|
| `neon_kb` | new module (M1) — manifest, init, models (3), controllers (1), security (2), data (1), views (4), portal templates, migrations (1), smokes (7+1) |
| `neon_training` | 4 (dashboard model + dashboard view + manifest + migration) |
| `neon_lms` | 3 (sop model + manifest + migration) |
| `neon_jobs` | 0 |
| `neon_core` | 0 |
| `neon_onboarding` | 0 |
| `neon_external_training` | 0 |
| `neon_finance` | 0 |

Phase 7d's reach: the new module plus 4 surgical files in Phase 7a and 3 in Phase 7e. Two cross-module touches (M5 + M6) followed the established two-commit atomic pattern.

---

## 9. Module count growth

- Pre-Phase-7d on local: 94 installed modules
- Post-Phase-7d on local: 95 installed modules
- Delta: +1 (`neon_kb`)

(On prod, pre-Phase-7d is 92 — post-Phase-7c-live state. Post-Phase-7d will be 93 once deployed.)

---

## 10. Deferred to admin run / Phase 9

- **WhatsApp + email actual dispatch** — `_notify_send` is a stub. Phase 9 overrides it to wire the dispatch engine (pending Meta business-account approval).
- **Initial content authoring** — M1 ships 5 categories with placeholder descriptions; the article table is empty. Tatenda + content team author the first batch post-deploy.
- **Portal navigation polish** — M5's portal article-detail page shows related items as display-only badges. Phase 11 can wire actual links to `/my/training` and similar once those routes exist for the cross-linked models.

---

## 11. Ready for prod deploy

Tag target: `v17.0.8.10.0-phase7d-live` on the commit including M8.

Deploy operation outline (executed in a separate session per established cadence):

```
# Pre-flight
ssh root@188.245.154.84
cd /opt/neon-odoo
git status
git log --oneline -1   # expect feat/kb-phase-7d HEAD

# Backup
docker exec neon-odoo-db pg_dump -Fc -U odoo -d neon_crm \
    > /root/backups/neon_crm_pre_phase7d_<timestamp>.dump

# Code pull
git fetch origin
git checkout feat/kb-phase-7d
git pull origin feat/kb-phase-7d

# Combined install + upgrade (new module + 2 extended)
docker compose exec odoo odoo -c /etc/odoo/odoo.conf -d neon_crm \
    -i neon_kb -u neon_training,neon_lms \
    --stop-after-init --no-http

# Restart + asset regen
docker compose restart odoo
# (asset regen script per Phase 7e + 7c + 7e deploys)

# Tag
git tag v17.0.8.10.0-phase7d-live
git push origin v17.0.8.10.0-phase7d-live
```

Expected post-deploy verifications:
- `neon_kb` installed at 17.0.1.5.0
- `neon_training` installed at 17.0.8.10.0
- `neon_lms` installed at 17.0.1.15.0
- 5 category seeds present (env.ref on each)
- Knowledge Base menu visible at sequence 83 (after External Training @ 82)
- Dashboard form shows new "Knowledge Base" card group with 2 counters
- 3 M2M join tables exist + FK constraints in `pg_constraint`
- T7dI001 integration smoke runs clean against prod DB

## Total deploy time estimate

~10-15 minutes (matches Phase 7c + 7e cadence; one new module + two upgrades with log-only migrations + idempotent join-table fixup).

---

## 12. Status: ready for deploy

Phase 7d functionally complete. All 8 milestones land on `feat/kb-phase-7d`; integration smoke 12/12 stages; no regression hits on the canonical baseline.
