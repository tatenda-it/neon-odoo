# Phase 7e Schema Sketch — Internal LMS (Neon Workshop Training)

**Status:** Pre-build design. Built on audit findings (`docs/phase-7e/php-course-audit.md`, commit `f36a82b`) + Tatenda's Coursera-style design decision (21 May 2026).
**Branch:** `feat/training-phase-7a` (Phase 7e branch cuts after 7a + 7b deploy)
**Target manifest range:** new `neon_lms` module 17.0.1.0.0 → 17.0.1.14.0 (14–16 milestones); also extends `neon_training` (8 new cert types + 1 new sign-off authority value)
**Date:** 21 May 2026

---

## 1. Executive Summary

Phase 7e is the Internal LMS sub-phase, between **Phase 7d Custom KB** and **Phase 8 Reports & Analytics**.

**Reframe vs initial scope:** the legacy PHP catalog audit (`php-course-audit.md`) revealed the source is NOT a course library but a **single structured training program** ("Neon Workshop Training") with 17 fixed modules, 520 written quiz questions, 85 practical scenarios, 15 SOPs, and 6 operating-authority domains. The original "use Odoo eLearning + integrate Phase 7a" scope holds, but the structural shape pivots from "many courses, each cert-bearing" to **"one specialization container with 7 cert-bearing sub-courses + 1 capstone."**

**Coursera-style sub-cert architecture** (Tatenda's design decision, 21 May 2026):

- **7 sub-courses** (called "tracks" in the model) grouped by domain: Foundations & Safety, Audio, Lighting, Video & LED, Workflow & Operations, Soft Skills, Rigging
- **Each sub-course earns its own sub-cert** on completion (1 cert per track)
- **Completing all 7 sub-courses earns a capstone cert** (`cert_type_neon_technical`)
- **Foundations & Safety strict gate** — must be completed first; other 6 tracks then in any order
- **Compatible with audit's "no levels" decision** — sub-certs are domain-distinct (Audio ≠ Lighting), not level-tiered (no Level 1 / 2 / 3)

**Estimated effort:** 14–16 milestones, ~3–4 weeks build + ~1 week test + deploy. Slightly larger than 7b due to the track architecture + 8-cert-type Phase 7a M3 seed extension + 5th gate condition in M9–M11.

**Integration with Phase 7a:** 8 new cert types added to M3 seed (7 sub-certs + 1 capstone). One new sign-off authority enum value (`system`) added to M7 routing for LMS-auto-issued certs (no human verifier).

**Integration with Phase 7b:** requirement templates can reference sub-certs for nuanced role onboarding — e.g., an audio crew member needs `cert_type_neon_foundations_safety` + `cert_type_neon_audio` (not the full capstone). This is the **biggest pedagogical win** of the Coursera-style structure: role requirements become precise rather than all-or-nothing.

---

## 2. Audit-Driven Reframe + Coursera-Style Decision

Two reframes captured in one table:

| Aspect | Pre-Audit Assumption | Post-Audit Reality | + Coursera Design Decision |
|---|---|---|---|
| Scope | Course library | One program, 17 modules | Structured as 7 sub-courses + 1 capstone |
| Course count | 30–50 separate courses | 17 fixed modules under one program | 17 modules grouped into 7 tracks |
| Cert design | Per-course cert | Single common standard | 7 sub-certs (by domain) + 1 capstone (Coursera-style) |
| Format | Mixed (some video, some PDF, some live) | Standardized within modules (text + recommended-links + quiz) | Same as audit |
| Sequencing | TBD per course | Implicit linear (M01 → M17) | Foundations strict; others free order post-Foundations |
| Cert level | Tiered Level 1 / 2 / 3 in PHP | Single common cert (PHP renamed M13 to remove "Level 3") | No level tiering — sub-certs are domain-distinct, not level-tiered |

**What this means for the build:**

1. **Architecture**: single program with track-based structuring (closer to Coursera Specialization than to LMS catalog or Udemy-style separate-courses model).
2. **Migration**: content-driven import (17 modules → 17 `neon.lms.module` records), with track assignment as part of import.
3. **Phase 7a impact**: 8 new cert types in M3 seed + 1 new sign-off authority enum value.
4. **Phase 7b impact**: requirement templates gain expressive power (can require sub-certs instead of full capstone).

---

## 3. Default Assumptions for Robin's 10 + 4 Open Questions

Audit's 10 questions (§8 of `php-course-audit.md`) + 4 new from sketch design. Each tagged "(Robin to confirm at walkthrough)":

| # | Question | Default | Rationale |
|---|---|---|---|
| 1 | Single cert vs sub-certs | **7 sub-certs (by domain) + 1 capstone; coexist with existing equipment certs** | Tatenda's design call 21 May; compatible with audit's "no levels" decision. Robin to confirm at walkthrough. |
| 2 | New cert types for Phase 7a M3 seed | **8 new types**: `foundations_safety`, `audio`, `lighting`, `video_led`, `workflow_ops`, `client_ready`, `rigging`, `technical` (capstone) | Sub-cert per track + 1 capstone. Robin to confirm at walkthrough. |
| 3 | Migrate PHP learner records | **Skip — start fresh on 7e deploy** | PHP system was content-only per audit; learner records (if any) not in the docx export. Robin to confirm at walkthrough. |
| 4 | Course content format | **Migrate content as-is (HTML-extracted text + recommended-links), upgrade in-place over time** | Avoids re-recording; gets system live fast. Phase 12+ polish for video re-records. Robin to confirm at walkthrough. |
| 5 | Avolites Titan vs Tiger Touch ambiguity | **Treat as separate concerns**: Tiger Touch is existing equipment cert (Phase 7a M3); Titan is the software workflow covered in the Lighting track | Ranganai interview to confirm. Robin to confirm at walkthrough. |
| 6 | LED/Video basics + advanced | **Both covered in Video & LED sub-cert; existing `cert_type_led_wall` remains for specific equipment competency** | Sub-cert is broad (domain), equipment cert is specific (gear). Robin to confirm at walkthrough. |
| 7 | Operating authorities | **Implement as separate `neon.lms.operating.authority` model; integrate with M9–M11 gate engine; granted on specific track completions (sometimes with practical signoff)** | Procedural authority distinct from skill recognition. Robin to confirm at walkthrough. |
| 8 | Practical scenarios | **Implement as `neon.lms.practical.scenario`; admin/lead-tech signoff required, NOT auto-scored** | 85 scenarios are real-world judgement calls; signoff workflow per M7 authority routing. Robin to confirm at walkthrough. |
| 9 | SOPs | **Implement as `neon.lms.sop`; reference material attached to modules, NOT progression-gating** | SOPs aren't learning content; learners reference them but don't have to "complete" them. Robin to confirm at walkthrough. |
| 10 | Odoo eLearning integration depth | **Extend stdlib** — use `slide.channel` + `slide.slide` + `survey.survey` as the spine; add Neon track / scenario / authority / completion models | Lighter than full custom build; mirrors Phase 6 OWL pattern (extend stdlib, don't fork). Robin to confirm at walkthrough. |
| 11 (NEW) | Track sequencing | **Foundations strict (must complete first), other 6 free order** | Tatenda's design call 21 May. Safety-first pedagogy. Robin to confirm at walkthrough. |
| 12 (NEW) | Quiz retry policy | **Max 3 attempts per quiz, then admin unlock required** | Industry standard pedagogy; prevents brute-force pass. Robin to confirm at walkthrough. |
| 13 (NEW) | Sub-cert expiry independence | **Sub-certs expire independently; capstone expires when ANY sub-cert expires** | Forces refresher engagement; matches Phase 7a M2 expiry pattern. Robin to confirm at walkthrough. |
| 14 (NEW) | Authority revocation workflow | **Manager + admin tier can revoke; logs to audit; auto-revoke on relevant sub-cert expiry** | Safety-critical authorities need active management — can't have expired Foundations holder retaining stop-work authority. Robin to confirm at walkthrough. |

---

## 4. Architecture Decision: Single Channel + Tracks (Coursera Specialization Model)

**Approach:** ONE `slide.channel` record (the Neon Workshop Training Program), with a NEW `neon.lms.track` model grouping modules into 7 sub-courses.

This is the **Coursera Specialization pattern**: a container of related courses (tracks), each separately certifiable, with one aggregate recognition for completing all.

### The data spine

```
slide.channel               (1 record: "Neon Workshop Training Program")
  └── neon.lms.track        (7 records: the sub-courses)
        └── neon.lms.module (17 records: modules grouped under tracks)
              └── slide.slide                (content slides — text, video links)
              ├── neon.lms.quiz.question     (~520 records total across all modules)
              ├── neon.lms.practical.scenario (~85 records across all modules)
              └── neon.lms.sop M2M           (15 SOPs referenced by modules)
```

### Per-learner spine

```
slide.channel.partner       (extended via inherit — the "enrollment")
  └── neon.lms.track.completion   (7 per learner, one per track)
        └── neon.lms.module.completion (17 per learner, one per module)

Issued certs (Phase 7a model):
neon.training.certification (7 sub-certs + 1 capstone per learner once earned)
```

### Why single channel (not 7 separate channels)

- **One enrollment per learner** — less admin overhead; a learner can't be partially enrolled
- **Tracks are progress states, not separate registrations** — moving from Foundations → Audio doesn't require re-enrollment
- **Capstone logic is centralised** — "all 7 tracks certified" is a single condition on one enrollment record, not a cross-channel join
- **Aligns with Coursera's Specialization UX** — learners see one program with sub-progress, not a fragmented "you've enrolled in 3 of 7 courses"

### Why tracks (not just module grouping)

- **Track has its own state machine** (`not_started → in_progress → completed → certified`) — module-level grouping wouldn't expose track-level completion state cleanly
- **Track-level certs need a clean model layer** — `track_completion.sub_cert_id` is direct; deriving track completion from module aggregation would be a fragile compute
- **Operating authorities tied to track completions** — not individual modules; the track is the granularity
- **Track sequencing rules** (Foundations strict) belong on the track model, not scattered across modules

### Trade-offs accepted

- **Cross-track navigation requires manual sequencing logic** — Odoo stdlib's `slide.channel` doesn't natively support sub-channels. M3 (Foundations gate) and M8 (completion workflow) carry the sequencing rules.
- **Migration from PHP is one-shot** — content is structured per the new track grouping, not preserved as PHP's flat 17-module order. The 17 modules survive; their grouping is a 7e addition.
- **Odoo's `slide.channel.completion` doesn't know about tracks** — overlay layer (`neon.lms.track.completion` + `neon.lms.module.completion`) does. Smoke must verify the two stay in sync.

---

## 5. Models

For each model: name, purpose, key fields, ACLs, inherits.

### 5.1 `slide.channel` (Odoo eLearning extension via `_inherit`)

Single channel record: "Neon Workshop Training Program."

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `neon_program_state` | Selection | yes | `draft` | `draft / active / archived` |
| `neon_track_ids` | One2many → `neon.lms.track` | — | — | The 7 tracks under this channel |
| `neon_total_tracks` | Integer | computed | 7 | `len(neon_track_ids)` |
| `neon_capstone_cert_type_id` | Many2one → `neon.training.certification.type` | no | `cert_type_neon_technical` xmlid | The capstone cert |
| `neon_capstone_authority_domain_ids` | Many2many → `neon.lms.operating.authority` | — | — | Authorities granted on capstone completion (in addition to per-track grants) |

**ACLs:**

| Group | Read | Write | Create | Unlink |
|---|---|---|---|---|
| `group_neon_training_admin` | ✓ | ✓ | ✓ | ✗ |
| `group_neon_jobs_manager` | ✓ | ✗ | ✗ | ✗ |
| `group_neon_jobs_crew` | ✓ | ✗ | ✗ | ✗ |

`perm_unlink=0` consistent with Phase 7a H3=A discipline.

### 5.2 `neon.lms.track` (NEW — the sub-course)

The 7 sub-courses. Each is a domain grouping of modules + a sub-cert outcome.

**`_order`:** `sequence asc, id asc`

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `code` | Char | yes (unique) | — | e.g., `TRK_FOUND_SAFETY` |
| `name` | Char | yes | — | e.g., "Foundations & Safety" |
| `description` | Text | no | — | |
| `channel_id` | Many2one → `slide.channel` | yes | — | The single Neon program channel |
| `module_ids` | One2many → `neon.lms.module` | — | — | Modules grouped under this track |
| `sequence` | Integer | — | 10 | Sort order |
| `is_foundation_gate` | Boolean | — | False | True for Foundations track only — drives strict sequencing rule |
| `prerequisite_track_ids` | Many2many → self | — | — | Empty for Foundations; contains Foundations for the other 6 |
| `sub_cert_type_id` | Many2one → `neon.training.certification.type` | yes | — | The cert auto-issued on track completion |
| `operating_authority_ids` | Many2many → `neon.lms.operating.authority` | — | — | Authorities granted on track completion |
| `min_overall_score` | Float | — | 0.8 | 80 % across quizzes + scenarios |

**ACLs:** admin full; manager read; learner read.

### 5.3 `neon.lms.module` (NEW — one of the 17)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `code` | Char | yes (unique) | — | e.g., `M01` |
| `name` | Char | yes | — | e.g., "Foundations of Workshop Safety" |
| `track_id` | Many2one → `neon.lms.track` | yes | — | Parent track |
| `channel_id` | Many2one → `slide.channel` | computed/related | `track_id.channel_id` | Stored for index efficiency |
| `sequence_in_track` | Integer | — | 10 | Sort order within track |
| `slide_ids` | One2many → `slide.slide` | — | — | Content slides (text, video, attachments) |
| `quiz_question_ids` | One2many → `neon.lms.quiz.question` | — | — | ~30 per module |
| `practical_scenario_ids` | One2many → `neon.lms.practical.scenario` | — | — | ~5 per module |
| `sop_ids` | Many2many → `neon.lms.sop` | — | — | Reference SOPs |
| `prerequisite_module_ids` | Many2many → self | — | — | Intra-track ordering (e.g., M02 before M03) |
| `min_quiz_score` | Float | — | 0.8 | |

**ACLs:** same as track.

### 5.4 `neon.lms.quiz.question` (NEW — the 520 written questions)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `module_id` | Many2one → `neon.lms.module` | yes | — | Parent module |
| `question_text` | Text | yes | — | |
| `question_type` | Selection | yes | `multiple_choice` | `multiple_choice / true_false / fill_in_the_blank` |
| `option_ids` | One2many → `neon.lms.quiz.option` | — | — | For MCQ; one row per option |
| `correct_answer` | Char | yes (one of `option_ids.is_correct=True` OR for fill-in: stored here) | — | |
| `points` | Float | — | 1.0 | Per-question weight |
| `explanation` | Text | no | — | Shown after submission |
| `sequence` | Integer | — | 10 | |

**ACLs:** admin full; learner read (gated to current attempt — `ir.rule` restricts to questions in their active enrollment).

### 5.5 `neon.lms.quiz.option` (NEW — for MCQ choices)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `question_id` | Many2one → `neon.lms.quiz.question` | yes (cascade) | — | |
| `text` | Char | yes | — | |
| `is_correct` | Boolean | — | False | |
| `sequence` | Integer | — | 10 | |

### 5.6 `neon.lms.practical.scenario` (NEW — the 85 scenarios)

Real-world judgement calls; signoff-reviewed, not auto-scored.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `module_id` | Many2one → `neon.lms.module` | yes | — | |
| `scenario_text` | Text | yes | — | The scenario prompt |
| `expected_competencies` | Text | no | — | What the signoff should look for |
| `signoff_authority` | Selection | yes | per Phase 7a M7 enum + `system` | Resolves verifier — typically `lead_tech` for safety + ops scenarios, `od_md` for soft-skill ones |

### 5.7 `neon.lms.scenario.completion` (NEW — per-learner per-scenario signoff record)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `enrollment_id` | Many2one → `neon.lms.enrollment` (the slide.channel.partner inherit) | yes (cascade) | — | |
| `scenario_id` | Many2one → `neon.lms.practical.scenario` | yes (restrict) | — | |
| `state` | Selection | yes | `pending` | `pending / passed / failed` |
| `signed_off_by_id` | Many2one → `res.users` | no | — | Sign-off authority who reviewed |
| `signoff_date` | Datetime | no | — | |
| `notes` | Text | no | — | Signoff context |

**Constraints:** unique `(enrollment_id, scenario_id)`; `perm_unlink=0` (audit-immutable per H3=A).

### 5.8 `neon.lms.sop` (NEW — the 15 SOPs as reference content)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | Char | yes | — | e.g., "Allen & Heath SQ6 Conference Setup" |
| `code` | Char | yes (unique) | — | e.g., `SOP_AH_SQ6_CONF` |
| `description` | Text | no | — | |
| `attachment_ids` | Many2many → `ir.attachment` | — | — | PDFs / reference docs |
| `module_ids` | Many2many → `neon.lms.module` | — | — | Reverse from `module.sop_ids` |

**ACLs:** admin full; learner read.

### 5.9 `neon.lms.operating.authority` (NEW — the 6 authority domains)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | Char | yes | — | e.g., "Generator Setup Authority" |
| `code` | Char | yes (unique) | — | e.g., `AUTH_GENERATOR` |
| `description` | Text | no | — | |
| `requires_track_ids` | Many2many → `neon.lms.track` | yes (non-empty) | — | Must complete ALL these tracks |
| `requires_practical_signoff` | Boolean | — | False | Whether extra practical evaluation is needed beyond track completion |
| `granted_to_user_ids` | Many2many → `res.users` | computed (store=False) | — | Computed from enrollment completion + signoff records |

**Authority-to-track mapping** (see §7 for full table):

- `stop_work`: Foundations only
- `electrical`: Foundations only
- `generator`: Foundations + Workflow & Ops
- `rigging`: Foundations + Rigging
- `working_at_height`: Foundations + Rigging + practical signoff
- `outdoor_public`: Foundations + Workflow & Ops

### 5.10 `neon.lms.enrollment` (NEW — extends `slide.channel.partner`)

One record per learner. **Inherits `slide.channel.partner`** (Odoo's enrollment model) and adds Neon fields.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `partner_id`, `channel_id` | (inherited from `slide.channel.partner`) | yes | — | Standard Odoo |
| `neon_overall_state` | Selection | computed | `enrolled` | `enrolled / in_progress / completed / certified` |
| `neon_track_completion_ids` | One2many → `neon.lms.track.completion` | — | — | 7 records (one per track) materialised on enrollment |
| `neon_modules_completed` | Integer | computed | 0 | |
| `neon_modules_total` | Integer | computed | 17 | |
| `neon_overall_progress` | Float | computed | 0.0 | 0–100 % |
| `neon_capstone_cert_id` | Many2one → `neon.training.certification` | no | — | Set when all 7 tracks certified |
| `neon_capstone_completion_date` | Datetime | no | — | |
| `neon_granted_authority_ids` | Many2many → `neon.lms.operating.authority` | computed | — | From track_completion + signoff records |

### 5.11 `neon.lms.track.completion` (NEW — per-learner per-track state)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `enrollment_id` | Many2one → `neon.lms.enrollment` | yes (cascade) | — | |
| `track_id` | Many2one → `neon.lms.track` | yes (restrict) | — | |
| `state` | Selection | yes | `not_started` | `not_started / in_progress / completed / certified` |
| `modules_completed` | Integer | computed | 0 | |
| `modules_total` | Integer | related from `track_id.module_ids` count | — | |
| `overall_score` | Float | computed | 0.0 | Weighted average of module quiz scores |
| `sub_cert_id` | Many2one → `neon.training.certification` | no | — | Set on `certified` transition |
| `completion_date` | Datetime | no | — | When `state` became `completed` |
| `certification_date` | Datetime | no | — | When `state` became `certified` (sub-cert issued) |

**Constraint:** unique `(enrollment_id, track_id)`. `perm_unlink=0`.

### 5.12 `neon.lms.module.completion` (NEW — per-learner per-module state)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `enrollment_id` | Many2one → `neon.lms.enrollment` | yes (cascade) | — | |
| `module_id` | Many2one → `neon.lms.module` | yes (restrict) | — | |
| `state` | Selection | yes | `not_started` | `not_started / in_progress / completed` |
| `quiz_score` | Float | — | 0.0 | Best score across attempts |
| `quiz_attempts` | Integer | — | 0 | Capped at 3 per DP12; admin unlock resets |
| `scenarios_completed` | Integer | computed | 0 | |
| `scenarios_total` | Integer | related from `module_id.practical_scenario_ids` count | — | |
| `last_activity` | Datetime | — | — | |

**Constraint:** unique `(enrollment_id, module_id)`. `perm_unlink=0`.

### 5.13 `neon.lms.completion.workflow` (Service / helper — not stored)

No database backing. Pure orchestration logic. Methods:

- `check_module_completion(module_completion)` — called on quiz pass or scenario signoff; flips module state, triggers track check
- `check_track_completion(track_completion)` — if all modules in track completed, issues sub-cert via Phase 7a `neon.training.certification.create()` with `state='active'`, sets `track_completion.sub_cert_id`, transitions track to `certified`, triggers capstone check, recomputes authorities
- `check_capstone_completion(enrollment)` — if all 7 tracks certified, issues capstone cert (`cert_type_neon_technical`), sets `enrollment.neon_capstone_cert_id`, transitions enrollment to `certified`
- `grant_authorities(user)` — recomputes the M2M for authorities based on the user's current sub-certs + signoff records; called on cert issuance + cert state changes

**Why a service, not a model:** these are pure functions on existing data. Persisting workflow state would duplicate `track_completion.state`. Following Odoo idiom for orchestration helpers (no `_name`, called via `env['neon.lms.completion.workflow']` or as static module functions).

### 5.14 `neon.training.certification` (Phase 7a extension — single new field)

Per the audit's "M_N owns the fix" pattern, 7e adds a reverse pointer:

| Field | Type | Required | Notes |
|---|---|---|---|
| `lms_track_completion_id` | Many2one → `neon.lms.track.completion` | no | `ondelete='set null'` — cert outlives the LMS completion record |

For sub-certs + capstone issued by the LMS workflow, this links back. Manual certs (existing Phase 7a flow) leave it null. Searchable: "which certs came from the LMS?"

---

## 6. State Machines

### 6.1 Module-level

```
not_started ──[first slide viewed OR first quiz attempt]──▶ in_progress
                                                              │
                            [quiz_score >= min_quiz_score      │
                             AND all scenarios signed off]     │
                                                               ▼
                                                          completed
```

### 6.2 Track-level

```
not_started ──[any module in track started]──▶ in_progress
                                                  │
                          [all modules in track   │
                           completed]             │
                                                  ▼
                                             completed
                                                  │
                          [completion workflow    │
                           issues sub-cert]       │
                                                  ▼
                                             certified
```

**Special**: Foundations track blocks other tracks from entering `in_progress` until Foundations is `certified` (strict sequencing — DP11).

### 6.3 Overall enrollment

```
enrolled ──[any track in_progress]──▶ in_progress
                                          │
                       [all 7 tracks      │
                        at min 'completed']│
                                          ▼
                                     completed
                                          │
                       [all 7 tracks      │
                        'certified']      │
                                          ▼
                                     certified
                                  (capstone issued)
```

---

## 7. Track Structure + Module Grouping

### Track 1: Foundations & Safety **[FOUNDATION GATE]**

- **Modules:** M01 Safety Foundations, M08 Power and Electrical Discipline
- **Sub-cert:** `cert_type_neon_foundations_safety`
- **Authorities granted on completion:** `stop_work` (always), `electrical` (always)
- **Special:** **STRICT prerequisite** — all other 6 tracks gate on this track being `certified`

### Track 2: Audio Technical

- **Modules:** M02 Audio Basics, M03 Audio Advanced, M15 Allen & Heath SQ6
- **Sub-cert:** `cert_type_neon_audio`
- **Authorities granted:** none directly (audio doesn't carry safety authority)

### Track 3: Lighting Technical

- **Modules:** M04 Lighting Basics, M05 Lighting Advanced, M14 Avolites Titan Mobile
- **Sub-cert:** `cert_type_neon_lighting`
- **Authorities granted:** none directly

### Track 4: Video & LED Technical

- **Modules:** M06 LED / Video Basics, M07 LED / Video Advanced, M16 Kommander Media Server
- **Sub-cert:** `cert_type_neon_video_led`
- **Authorities granted:** none directly

### Track 5: Workflow & Operations

- **Modules:** M09 Event Setup Workflow, M10 Fault Finding and Troubleshooting, M11 Warehouse and Equipment Care
- **Sub-cert:** `cert_type_neon_workflow_ops`
- **Authorities granted on completion (combined with Foundations):** `generator`, `outdoor_public`

### Track 6: Soft Skills

- **Modules:** M12 Professional Communication and Team Discipline, M13 Leadership, Responsibility and Team Standards
- **Sub-cert:** `cert_type_neon_client_ready`
- **Authorities granted:** none

### Track 7: Rigging

- **Modules:** M17 Truss Systems and Rigging Discipline
- **Sub-cert:** `cert_type_neon_rigging`
- **Authorities granted on completion (combined with Foundations):** `rigging`; `working_at_height` (with practical signoff)

### Capstone

- **Requirement:** All 7 tracks certified
- **Cert:** `cert_type_neon_technical`
- **Recognition:** "Neon Workshop Training Program — Full Completion"
- **Symbolic value:** marks the learner as fully trained across all Neon technical domains. Phase 7b requirement templates can use this as a shorthand for "all certs" instead of listing 7 sub-certs.

---

## 8. Operating Authority Gates (integration with M9–M11)

Phase 7a's three-tier gate engine evaluates assignments against required certs. Phase 7e extends with a **5th gate condition**: "required operating authority."

### Example scenarios

- **Outdoor generator setup** → `required_authority = generator`. Learners without Foundations + Workflow & Ops blocked at tier 3 (block + override).
- **Truss rigging** → `required_authority = rigging` AND `working_at_height`. Both required.
- **High-voltage cabling** → `required_authority = electrical` (Foundations grants this).
- **Stop-work on damaged equipment** → `required_authority = stop_work` (Foundations grants this — every trained crew member can call stop-work).

### Implementation

- **Extend gate evaluation** in M9–M11 engine: add a 5th condition type `required_authority`
- **Add `commercial.event.job.required_authority_ids`** Many2many → `neon.lms.operating.authority`
- **Compute event-job authorities** from task descriptions or manager-set tags (M10 + M11 of 7e)
- **Authority check happens alongside cert check** — gate engine evaluates BOTH; failing either fires the appropriate tier wizard

**Phase 7a code change scope:** M9–M11's gate engine function gains one more condition branch. Smoke test extended with authority-gate scenarios. No other Phase 7a code touched.

---

## 9. Phase 7a M3 Seed Extension (8 new cert types + 1 new sign-off authority enum value)

Modify `addons/neon_training/data/neon_training_data.xml` to add:

| Cert Type | XMLID | Category | Sign-off Authority | Level Mode |
|---|---|---|---|---|
| Neon Foundations & Safety | `cert_type_neon_foundations_safety` | role_tier | `system` | binary |
| Neon Audio Technical | `cert_type_neon_audio` | role_tier | `system` | binary |
| Neon Lighting Technical | `cert_type_neon_lighting` | role_tier | `system` | binary |
| Neon Video & LED Technical | `cert_type_neon_video_led` | role_tier | `system` | binary |
| Neon Workflow & Operations | `cert_type_neon_workflow_ops` | role_tier | `system` | binary |
| Neon Client-Ready Skills | `cert_type_neon_client_ready` | role_tier | `system` | binary |
| Neon Rigging Technical | `cert_type_neon_rigging` | role_tier | `system` | binary |
| Neon Technical (Capstone) | `cert_type_neon_technical` | role_tier | `system` | binary |

### New sign-off authority value: `system`

Phase 7a M7 currently has 4 sign-off authority values: `self_with_peer`, `lead_tech`, `od_md`, `external_trainer`. **Add a 5th: `system`** — for certs auto-issued by the LMS workflow without human verification.

**Behaviour:**

- State transitions from `draft → active` automatically when LMS workflow reports track completion
- No human verifier needed
- M7's `_SIGN_OFF_AUTHORITY_GROUP` dict gets a new key: `"system": None` (or a synthetic xmlid pointing at a system-services group)
- TODO routing skipped for `system` authority — no human to notify
- Audit trail records the LMS workflow as the "verifier" via `verified_by_id = SUPERUSER_ID` + chatter note indicating system issuance

This is a **single one-line addition to the `_SIGN_OFF_AUTHORITY_GROUP` dict and the cert type Selection enum** in Phase 7a. Smoke test extended: `_resolve_verify_authority_partners` returns empty recordset when authority is `system`, and the issuance path is via `record.sudo().write({'state': 'active'})` in the LMS workflow.

---

## 10. Phase 7a Integration

| 7a Artifact | 7e Usage |
|---|---|
| `neon.training.certification` (M2) | 7 sub-certs + 1 capstone created via LMS workflow; new `lms_track_completion_id` reverse pointer (§5.14) |
| `neon.training.certification.type` (M3) | 8 new types added (§9); 7 sub + 1 capstone |
| Cert state machine (M2) | LMS-issued certs start at `state='active'` (system-verified); admin can suspend later |
| Sign-off authority routing (M7) | Add `system` enum value (§9); routing skipped for system-issued |
| 3-tier gate engine (M9–M11) | Extended with 5th condition type: `required_authority` (§8) |
| Compliance Dashboard (M12) | Add 4 LMS counters: Active Enrollments, Pending Capstone Cert, Authorities Granted (30 d), Track Certification Distribution |

---

## 11. Phase 7b Integration (Onboarding)

| 7b Artifact | 7e Usage |
|---|---|
| `neon.onboarding.candidate` | A candidate enrolling in 7e contributes to `cert_collection` state advancement once their first sub-cert is earned |
| `neon.onboarding.requirement.template` | `required_cert_type_ids` can now include sub-certs (audio crew needs `cert_type_neon_foundations_safety` + `cert_type_neon_audio`, not full capstone) |
| Admin override (Skip Onboarding) | Does NOT affect 7e enrollment — Skip is workflow-level (skip the entire onboarding); 7e enrollment is content-level (skip Skip wizard requires manual sub-cert grants outside the LMS) |

**Sub-cert benefit for 7b:** requirement templates become more nuanced. Instead of "must hold full Neon Technical capstone," roles can be specified as "must hold Foundations + their domain sub-cert."

Suggested updates to 7b requirement templates (§7 of `phase-7b/schema-sketch.md`):

- **Driver**: existing certs + `cert_type_neon_foundations_safety` sub-cert
- **Lead Tech**: existing certs + `cert_type_neon_foundations_safety` + (`cert_type_neon_lighting` OR `cert_type_neon_audio` OR `cert_type_neon_video_led`) — matches their domain
- **Tech**: existing certs + `cert_type_neon_foundations_safety` + at least one technical sub-cert
- **Runner**: existing certs + `cert_type_neon_foundations_safety` only (lightest requirement)

These are flexible — Robin's call at the Phase 7b walkthrough.

---

## 12. Test Data Plan

**SECOND populated instance** of `docs/_templates/test-data-plan-template.md`. Apply the 3 template-fit refinements logged from 7b sketch:

- **Refinement 1 (§C ACL boundary):** Phase 7e has a natural read-only tier — `p7e_m1_observer` (no enrollment, can browse program structure). The forced-fit issue in 7b (where every tier could create) is resolved cleanly here.
- **Refinement 2 (§D commit exception):** Get-or-create fixture-setup block exception language. Applied verbatim from 7b.
- **Refinement 3 (§D cross-milestone drift):** Generalised "dashboard counter drift" to "user-visible state drift." Phase 7e instance: drift between M8 (track completion workflow) and M2/M9 (cert issuance).

### §A — Seed data

| Record set | Model | Count | Source XML file | Variability |
|---|---|---|---|---|
| Program channel | `slide.channel` | 1 | `addons/neon_lms/data/neon_lms_program.xml` | low |
| 7 tracks | `neon.lms.track` | 7 | `addons/neon_lms/data/neon_lms_tracks.xml` | medium |
| 17 modules | `neon.lms.module` | 17 | `addons/neon_lms/data/neon_lms_modules.xml` | medium |
| 6 operating authorities | `neon.lms.operating.authority` | 6 | `addons/neon_lms/data/neon_lms_authorities.xml` | low |
| 8 NEW cert types (M3 extension) | `neon.training.certification.type` | 8 | `addons/neon_training/data/neon_training_data.xml` (extension in 7e M9) | medium |
| Track-to-authority mapping | `neon.lms.track.operating_authority_ids` M2M | rows per §7 | `addons/neon_lms/data/neon_lms_authority_mapping.xml` | medium |
| 15 SOPs | `neon.lms.sop` | 15 | `addons/neon_lms/data/neon_lms_sops.xml` | low |

**Not seed; migrated:** 520 quiz questions + 85 practical scenarios come from the M12 migration script (one-shot content import from the PHP docx + adjacent attachments). They are content, not seed — `noupdate=True` is wrong here (they evolve as the curriculum evolves) but they also don't fit `data/*.xml` (too large; ~600 records). Migration script handles them directly.

**Cross-module dependency:** `neon_lms.__manifest__.py` declares `depends=['neon_training']`. The 8 new cert types land in `neon_training` (Phase 7a M3 extension), not in `neon_lms`. The track XML references those cert type xmlids; the dependency ensures they resolve at install time.

### §B — Test fixtures

All passwords = `test123`. All logins prefixed `p7e_m1_*`.

| Tier | Fixture login | Groups | Records owned / seen | Smoke ref |
|---|---|---|---|---|
| LMS Admin | `p7e_m1_lms_admin` | `base.group_user` + `neon_training.group_neon_training_admin` + `website.group_website_publisher` | Full CRUD across LMS models | `.claude/p7e_m1_smoke.py` |
| Lead Tech (scenario signoff) | `p7e_m1_lead_tech` | `base.group_user` + `neon_jobs.group_neon_jobs_crew_leader` + `neon_training.group_neon_training_signoff` | Signs off scenarios on assigned learners | `.claude/p7e_m1_smoke.py` |
| Learner — fresh enrollment | `p7e_m1_learner_new` | `base.group_user` + `neon_jobs.group_neon_jobs_crew` + `neon_training.group_neon_training_user` | `enrollment.neon_overall_state = 'enrolled'`, no progress | `.claude/p7e_m1_smoke.py` |
| Learner — Foundations done | `p7e_m1_learner_foundation_only` | same groups | Foundations track certified; can start other tracks | `.claude/p7e_m1_smoke.py` |
| Learner — multi-track in progress | `p7e_m1_learner_specializing` | same groups | Foundations + Audio certified; Lighting in progress | `.claude/p7e_m1_smoke.py` |
| Learner — capstone-ready | `p7e_m1_learner_capstone_ready` | same groups | All 7 sub-certs earned; capstone trigger pending | `.claude/p7e_m1_smoke.py` |
| Read-only observer | `p7e_m1_observer` | `base.group_user` only | NO enrollment, sees program structure but no module / quiz / scenario content | `.claude/p7e_m1_smoke.py` |

**(Refinement 1 applied:** `p7e_m1_observer` is the natural read-only tier — no enrollment record, can browse program metadata via `slide.channel` public-read but cannot access `slide.slide` content or quiz / scenario records. Resolves the "is there a read-only tier for ACL boundary tests?" template-pre-flight question cleanly.**)**

**Get-or-create discipline + commit gate** per template §D refinement 2: smoke setup top-of-file uses `_get_or_create_user(login, name, groups_xmlids)` helper + `env.cr.commit()` for fixture persistence across regression cycles. Explicitly labelled in the smoke as an idempotency-gated exception to the "no mid-test commit" rule.

### §C — Test scenario coverage

15 scenarios — broader coverage than 7b's 15 because 7e exercises more state-machine transitions (3 levels: module → track → enrollment).

| # | Workflow | Scenario | Fixture | Expected outcome |
|---|---|---|---|---|
| 1 | Foundations gate enforcement | New learner tries to start Audio track before Foundations | `p7e_m1_learner_new` | Blocked at `slide.channel` access guard; UI message "Complete Foundations & Safety first" |
| 2 | Foundations completion unlocks others | Learner completes Foundations track (all modules + scenarios) | `p7e_m1_learner_foundation_only` (set up at this state via fixture create) | All other 6 tracks become startable; Foundations sub-cert auto-issued; authorities `stop_work` + `electrical` granted |
| 3 | Track completion → sub-cert issuance | Learner completes Audio track (3 modules) | `p7e_m1_learner_specializing` | `cert_type_neon_audio` auto-issued; `track_completion.state='certified'`; `track_completion.sub_cert_id` set; `track_completion.certification_date` populated |
| 4 | Free order after Foundations | Specializing learner starts Lighting before completing Audio | `p7e_m1_learner_specializing` | Allowed; no gate on Lighting given Foundations certified |
| 5 | Capstone auto-issuance | Learner finishes 7th sub-cert (any order) | `p7e_m1_learner_capstone_ready` (fixture: 6 sub-certs, 1 module left in 7th track) | `cert_type_neon_technical` auto-issued; `enrollment.neon_overall_state='certified'`; `enrollment.neon_capstone_cert_id` set |
| 6 | Quiz retry policy (3 attempts) | Learner scores 50 % on M01 quiz, retries twice, passes on 3rd at 85 % | `p7e_m1_learner_new` | First 2 attempts logged; 3rd attempt at 85 % passes; module marked complete; `quiz_attempts=3` |
| 7 | Quiz retry exhaustion | Learner fails all 3 quiz attempts on M01 | `p7e_m1_learner_new` | Quiz locked (`quiz_attempts=3, state=in_progress`); admin must unlock manually; `_unlock_quiz` admin action exists |
| 8 | Scenario signoff | Lead Tech signs off learner's M17 rigging scenario | `p7e_m1_lead_tech` | `scenario_completion.state='passed'`, `signed_off_by_id` set; track progression updates via workflow.check_module_completion |
| 9 | Authority grant on track completion | Learner completes Foundations + Workflow & Ops | `p7e_m1_learner_specializing` (post-Audio fixture extended) | `generator` + `outdoor_public` authorities granted (combined from both track completions); `granted_to_user_ids` recomputes |
| 10 | Authority grant with practical signoff | Learner completes Foundations + Rigging + practical at-height scenario signed off | `p7e_m1_learner_specializing` extended | `working_at_height` authority granted only AFTER the practical signoff; `rigging` granted without it |
| 11 | ACL boundary — observer | Observer tries to access quiz content via direct URL | `p7e_m1_observer` | `AccessError` via enrollment-scoped `ir.rule` on `neon.lms.quiz.question` |
| 12 | Sub-cert expiry triggers capstone expiry | Capstone-certified learner has one sub-cert auto-expire via cron | (synthetic — modify cert `date_expires` to past via sudo) | Capstone cert state flips to `expired`; enrollment.neon_overall_state recomputes back to `completed` (not certified); authorities recompute (revoke those tied to expired sub-cert) |
| 13 | Authority revocation | Admin manually revokes generator authority from a learner | `p7e_m1_lms_admin` | Authority M2M updated; audit log entry; if a job currently requires this authority and learner is assigned, gate fire surfaces |
| 14 | 5th gate condition fires | Manager assigns crew to event_job requiring `rigging` + `working_at_height`; crew has rigging only | `p7e_m1_lms_admin` + Phase 7a fixtures | Tier-3 block wizard fires (per M9–M11 engine); override path available; gate_log entry shows `required_authority` was the failing condition |
| 15 | Cross-milestone drift catch (Refinement 3) | Learner marked `completed` by M8 workflow but capstone cert not issued (simulated bug — comment out the `check_capstone_completion` call) | (synthetic — M14 smoke includes this regression test) | Test FAILS — drift between M8 workflow + M9 cert issuance surfaces before deploy; deliberate negative test |

**(Refinement 3 applied:** Scenario 15 generalises the cross-milestone drift catch beyond 7b's dashboard-counter-specific version. The pattern is: "do a thing in milestone X that should propagate to milestone Y; verify it actually propagates." For 7b this was dashboard counters; for 7e it's capstone issuance. Future sub-phases instantiate the same pattern with their own X→Y pair.**)**

### §D — Cleanup + drift detection

| Concern | Mitigation for 7e |
|---|---|
| 520 quiz questions seeded as test fixtures (would bloat `data/`) | Migration script imports as content, not data XML; smoke fixtures use 1–2 question sets per module, not the full 30 |
| 85 practical scenarios — same risk | Same mitigation — migration script handles bulk; smoke uses 1 scenario per module |
| Mid-test commits leaking | NO `env.cr.commit()` in smoke files. **Exception:** get-or-create fixture-setup block at smoke top, gated by idempotency check (per Refinement 2) |
| Cross-milestone drift (M8 → M2 / M9) | Generalized scenario 15 in §C |
| eLearning stdlib upgrade breaks 7e extensions | Pin Odoo minor version per Phase 11 cutover plan; regression runs on pinned version |
| Sub-cert issued but `lms_track_completion_id` reverse pointer null (drift between Phase 7a cert + Phase 7e track completion) | Scenario 3 asserts both directions of the FK are populated |
| Authority M2M stale after sub-cert state change | Scenarios 9 + 12 cover this both ways (grant + revoke) |

### §E — Sub-phase-specific notes

- **Test fixtures depend on Phase 7a + Phase 7b installed.** Cert types from M3 seed (including the 8 new 7e additions) must exist before track records resolve. `__manifest__.py` declares the dependency chain.
- **Quiz attempts require HTTP smoke tests** (eLearning quiz is web-based). Separate `tests/test_quiz_http.py` with `@tagged('-standard')` to skip from default regression runs; included in browser smoke pipeline (`p7e_*_browser_smoke.py`).
- **WhatsApp notification stubs**: Phase 9 territory. M13 of 7e ships trigger points (chatter post + mail.activity per Phase 7b's M12 pattern) but actual WhatsApp send is mocked at `bus.bus._sendone` level in smoke.
- **Foundations gate enforcement test (scenario 1) is the critical architectural verification** — without it, the sub-course sequencing design fails silently. Smoke runs this as the first scenario per regression cycle.
- **Capstone expiry cascade (scenario 12) is subtle** — when ONE sub-cert expires, the capstone should flip back from `certified` to `completed`. Cron-driven; test uses direct ORM trigger rather than waiting on cron.
- **5th gate condition (scenario 14) requires Phase 7a M9–M11 modification** — not a Phase 7e-only test. Listed here because the test is owned by Phase 7e (the gate condition is the new thing); Phase 7a's existing gate smokes don't cover authority requirements.

### Pre-flight checklist before M1 build starts

- [ ] §A: every seed file path declared in `addons/neon_lms/__manifest__.py` data list (8 files)
- [ ] §A: 8 new cert types added to `addons/neon_training/data/neon_training_data.xml` BEFORE neon_lms install (cross-module xmlid resolution)
- [ ] §B: 7 fixture logins unique within `p7e_*` prefix; none collide with `p7a_*`, `p7b_*`, `p2m75_*`
- [ ] §B: each fixture's groups match ACL CSV rows (no fictional groups; `website.group_website_publisher` exists post Odoo stdlib install)
- [ ] §C: all 4 enrollment states + all 4 track states + all 3 module states appear in at least one scenario
- [ ] §C: Foundations gate enforcement (scenario 1) is the first regression assertion per cycle
- [ ] §C: cross-milestone drift (scenario 15) added to M14 smoke explicitly
- [ ] §D: pre-commit grep wired in `.claude/run_regression.sh` for `test123` in `addons/**/data/*.xml`
- [ ] §E: HTTP smoke tagged `@tagged('-standard')` to keep default regression fast

---

## 13. Milestone Breakdown (~14–16)

| # | Scope | LOC est. | Cross-cutting |
|---|---|---|---|
| **M1** | `neon.lms.track` + `neon.lms.module` models + `slide.channel` extension + ACLs + `_post_init_hook` for default tracks | ~700 | 1 NEW addon `neon_lms`; cross-module xmlid refs to Phase 7a |
| **M2** | `neon.lms.operating.authority` model + 6 seed records + track-to-authority M2M | ~400 | Seed XML |
| **M3** | Foundations gate enforcement (track sequencing logic + UI message) | ~500 | Logic on `neon.lms.track.completion` write hook |
| **M4** | `neon.lms.quiz.question` + `neon.lms.quiz.option` + retry policy (3 attempts, admin unlock) | ~700 | 2 new models + admin action |
| **M5** | `neon.lms.practical.scenario` + `neon.lms.scenario.completion` + signoff routing per M7 authority enum | ~700 | 2 new models; M7 authority resolution reuse |
| **M6** | `neon.lms.sop` + module-SOP M2M + attachment handling (PDF upload + reference) | ~500 | 1 model + view |
| **M7** | `neon.lms.enrollment` (extends `slide.channel.partner`) + `neon.lms.track.completion` + `neon.lms.module.completion` + state machines | ~800 | 3 new models + 3 state machines |
| **M8** | `neon.lms.completion.workflow` helper + module → track → capstone auto-issuance + authority recompute | ~700 | Pure logic; hooks on completion model writes |
| **M9** | 8 new cert types in Phase 7a M3 seed + `system` sign-off authority added to M7 routing + reverse `lms_track_completion_id` on `neon.training.certification` | ~500 | **Phase 7a code change** (M3 seed + M7 routing dict + M2 model field) |
| **M10** | Operating authority gate condition (extends M9–M11 engine — 5th condition type) | ~600 | **Phase 7a code change** (gate engine + 1 new M2M on `commercial.event.job`) |
| **M11** | Compliance Dashboard extension (4 LMS counters + drill-throughs) | ~400 | 1 model extension |
| **M12** | PHP migration script (one-shot content import: 17 modules + 520 questions + 85 scenarios + 15 SOPs) | ~900 | Standalone script + idempotent flag |
| **M13** | WhatsApp notification trigger points (scaffolded; sends stubbed for Phase 9) | ~500 | 8 trigger points (enrollment + track + sub-cert + capstone + authority grant + scenario signoff + expiry warning + admin unlock) |
| **M14** | Smoke + integration tests + reference doc updates + `docs/phase-7e/M14_deploy_log.md` | ~700 | Smokes + browser smokes + cross-milestone drift test (scenario 15) |
| **Optional M15** | Learner portal polish (`/learn/...` routes; phone-first responsive layout) | ~600 | Portal templates + controllers |
| **Optional M16** | Admin reporting views (per-learner progress, per-track distribution, authority-grant audit) | ~400 | List + pivot + graph views |

**Subtotal (M1–M14):** ~8700 LOC. With M15 + M16 polish: ~9700 LOC. Both within Phase 7a-calibrated cadence (M1–M12 of 7a was ~9500 LOC).

**Critical sequencing within 7e:**

- M1 → M2 → M3 establishes the structural skeleton + Foundations gate.
- M4 → M5 → M6 → M7 layer content + completion-state models.
- M8 is the workflow keystone — without M8 the auto-issuance logic doesn't exist.
- M9 + M10 are the Phase 7a touchpoints — modifies 7a code (cert types, sign-off enum, gate engine, M12 dashboard).
- M11 dashboard, M12 migration, M13 notifications, M14 smoke wrap the build.

---

## 14. Phase 7a + 7b Reference Docs to Leverage

| Reference Doc | Phase 7e Usage |
|---|---|
| `reference_odoo17_gate_log_fk_lifecycle.md` | M2 audit log on authority grants/revokes; M8 track + module completion FK lifecycle decisions (set null vs cascade) |
| `reference_odoo17_hook_sudo_partner_capture.md` | M8 auto-cert issuance — workflow runs as system, but captures triggering user (= the learner) BEFORE sudo for audit trail |
| `reference_odoo17_menu_visibility_filter.md` | M1 + M11 LMS menu visibility per tier (admin sees Configuration, learner sees only Learn) |
| `reference_odoo17_implied_ids_orm_vs_sql.md` | All group writes via ORM in M1 fixture setup + M9 + M10 |

Plus the `docs/_templates/test-data-plan-template.md` applied as second populated instance (this §12). After 7e ships, the 3 refinements (already applied here) fold back into the template — see §15.

---

## 15. Template Refinement Loop — Reporting Back to the Template

The Test Data Plan template was first populated in 7b. Three template-fit issues surfaced. Phase 7e applies all 3 cleanly and reports back:

| Refinement | 7b Status | 7e Application | Generalize to template? |
|---|---|---|---|
| **R1: ACL-boundary fixture requires a read-only tier** | Forced fit in 7b (signoff tier in 7b actually has create rights; scenario was awkward) | 7e has `p7e_m1_observer` as natural read-only tier (no enrollment, sees structure but not content) | **YES** — generalise: every sub-phase should designate ONE read-only tier in §B, and §C must include an ACL-boundary scenario using it |
| **R2: Mid-test commit exception language** | Added inline in 7b §D | Applied identically in 7e §D | **YES** — fold into template §D's standing language verbatim |
| **R3: Cross-milestone drift scenario generalisation** | 7b was dashboard-specific; 7e generalises to "user-visible state drift between milestone X and milestone Y" | Scenario 15 catches M8 → M9 capstone-issuance drift via deliberate negative test | **YES** — generalise template §C to require: "at least one scenario that exercises a cross-milestone data dependency, designed to fail if either milestone is buggy" |

**All 3 refinements generalise.** After 7e M14 deploys, fold them into `docs/_templates/test-data-plan-template.md` as a template update commit. The doc itself will then be "v2" — 7f / 7g sub-phases use the refined version from the start.

---

## 16. Open Questions Summary for Robin Walkthrough

14 questions total — 10 from audit §8 (with defaults per §3) + 4 new from sketch design (#11–#14). Listed in §3 table; reproduced here as a flat list for the walkthrough script:

1. Single cert vs sub-certs → **7 sub-certs + 1 capstone** (Tatenda's call; Robin to bless)
2. New cert types for Phase 7a M3 seed → **8 added** (7 sub + 1 capstone)
3. Migrate PHP learner records → **skip; start fresh**
4. Course content format → **migrate as-is; upgrade in-place**
5. Avolites Titan vs Tiger Touch → **separate concerns** (Tiger Touch = existing equipment cert; Titan = workflow software in Lighting track)
6. LED / Video basics + advanced → **covered in Video & LED sub-cert; existing `cert_type_led_wall` remains for equipment specificity**
7. Operating authorities → **separate `neon.lms.operating.authority` model; M9–M11 gate integration**
8. Practical scenarios → **`neon.lms.practical.scenario`; admin signoff, not auto-scored**
9. SOPs → **`neon.lms.sop`; reference material, not progression-gating**
10. Odoo eLearning integration → **extend stdlib (`slide.channel` + `slide.slide` + `survey.survey`)**
11. Track sequencing → **Foundations strict, others free order**
12. Quiz retry policy → **3 attempts max, admin unlock thereafter**
13. Sub-cert expiry independence → **sub-certs expire independently; capstone expires when ANY sub-cert expires**
14. Authority revocation → **manager + admin can revoke; logs to audit; auto-revoke on relevant sub-cert expiry**

---

## 17. Build Sequencing Relative to Phase 7a + 7b Deploy

```
Now: Phase 7a feature-complete @ c6326d8 + Pre-deploy session done
     Phase 7b schema sketch @ 0ac85b0
     Phase 7e audit @ f36a82b
     Phase 7e schema sketch @ this commit

Required before Phase 7e build starts:
  1. Phase 7a deployed to prod (v17.0.8.0.0-phase7a-live)
  2. Phase 7b built + deployed (v17.0.9.0.0-phase7b-live)
  3. Robin walkthrough on Phase 7e — confirms 14 open questions
  4. Phase 7e branch cut: feat/training-phase-7e from main

Phase 7e itself:
  5. M1-M14 (or M1-M16 with portal + admin polish) — ~3-4 weeks
  6. Phase 7e pre-deploy Chrome session
  7. Phase 7e deploy (v17.0.10.0.0-phase7e-live)
  8. Phase 7e post-deploy verification

Phase 7e modifies Phase 7a code in M9 + M10:
  - M9: M3 seed (8 cert types), M7 routing (system enum), M2 reverse pointer
  - M10: M9-M11 gate engine (5th condition type), commercial.event.job M2M field

Both must be backwards-compatible with Phase 7a + 7b in production. M9 + M10 deploy as part of neon_lms install AND as a neon_training + neon_jobs upgrade (-u flags both modules). Migration script in neon_training migrations/<version>/post-migrate.py handles the seed extension idempotently.
```

Phase 7e schema sketch is **NOT buildable yet** — design-stage work on the `feat/training-phase-7a` branch per the standing pattern. Build kicks off after Robin's walkthrough confirms the 14 open questions + Phase 7b ships.
