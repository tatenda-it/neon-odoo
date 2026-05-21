# Phase 7e PHP Course Audit

## 1. Source

| Field | Value |
|---|---|
| File | `neon_final_publication_master_for_upload.docx` |
| Provided by | Tatenda |
| Date received | 21 May 2026 |
| Catalog type | Master publication pack from legacy PHP system, exported via `html-to-docx` for review |
| File size | 2.2 MB |
| Doc metadata | Author `html-to-docx`, created + modified 2026-04-27 (single revision), no doc title set |
| Structural shape | 1 long-form document — 4,478 non-empty paragraphs + 3 index tables + 17 module bodies + practical-quiz appendix |

The file is NOT a per-course catalog with one entry per row. It is **one consolidated training program** ("Neon Workshop Training — Final Publication Master") containing 17 modules, hundreds of quiz questions, an SOP reference library, and an Operating Authority Boundaries section. Inventory below is therefore at the **module level** rather than course level.

## 2. Summary statistics

| Metric | Value |
|---|---|
| Total modules | **17** (M01–M17) |
| Total written quiz questions | **520** (confirmed in table 2 of the doc: "Overall total confirmed") |
| Total practical quiz questions | **~85** (5 per module × 17, per "Suggested online use" note) |
| Total quiz items combined | **~605** |
| Question-count verification status | M01–M03 confirmed at 30 each; M04–M17 marked "Requires platform export verification" |
| Certification tracks | **1 common standard** for all enrolled technicians (NOT Level 1 / 2 / 3 tracks — explicit publication-pass decision) |
| Lesson structure per module | Module prompt → Recommended links → 5+ Lessons (each with "What this lesson covers" + "Why this matters") → Practical quiz |
| SOP / reference standards | **15** standards in the SOP Library section (Allen & Heath SQ6, QU16/QU24, Midas/Behringer, wireless mic Audio-Technica + Shure, Wireless Workbench, Dante, PowerWorks Zethus, RCF NX/TT+, Avolites Titan Mobile, Capture, Kommander, projector/LED/HDMI, warehouse, outdoor generator, truss/stand) |
| Operating-authority boundary domains | **6** (electrical/power, generator/distro, rigging/truss/stand, working at height, outdoor/public safety, damaged-equipment stop-work rule) |
| Format (legacy delivery) | Mixed — text content + question banks + image/video references (recommended-links sections) |
| Status indicators | All 17 modules marked "Confirmed from source brief" (M01–M03) or "Requires platform export verification" (M04–M17) — none archived, none draft-only |
| Cert linkage (current PHP system) | Single certification — "Neon Events Elements Technical Certification" — earned on completing all 17 modules |
| Completion criteria | Implicit: pass all 17 module quizzes + supervisor-reviewed practical assessments. Not explicitly broken down per-module in the catalog (deferred to "platform export verification"). |

## 3. Field inventory

What metadata exists per module in the source pack:

| Field | Coverage | Type | Sample values | Phase 7e / 7a mapping |
|---|---|---|---|---|
| `module_code` | 17 / 17 (100 %) | enum (M01–M17) | `M01`, `M14` | New `neon.lms.module.code` Char field (unique) |
| `module_title` | 17 / 17 (100 %) | Char | "Safety Foundations", "Avolites Titan Mobile" | `name` on `slide.channel` (Odoo eLearning Course model) OR new `neon.lms.module.name` |
| `lesson_count` | 17 / 17 (sampled — confirmed for M01; presumed identical structure for M02–M17) | Integer (implicit) | M01 = 5 lessons | Compute from `slide.channel.slide_ids` count |
| `module_prompt` | 17 / 17 | Text | (Per-module guidance for the learner) | `description` field on slide.channel |
| `recommended_links` | 17 / 17 | URL list (text) | Replacement safety/PPE videos, ear-training references, Capture lessons | Many2many or Text on the slide.channel description |
| `written_quiz_count` | 3 / 17 confirmed (M01-M03 = 30 each); 14 / 17 pending verification | Integer | 30 / "Requires platform export verification" | survey.survey question count (Odoo eLearning quiz integration) |
| `practical_quiz_count` | 17 / 17 (5 each per "Suggested online use") | Integer | 5 | Separate survey or `neon.lms.practical_test` model |
| `status` | 17 / 17 | enum (3 values used) | "Confirmed", "Pending verification", "Drafted (M03 Q24 gap)" | Maps to slide.channel state |
| `cite/source brief reference` | All rows | reference marker | `[file:1]`, `[cite:2]`, `[cite:119]` | Drop on migration (internal authoring marker, not learner-facing) |
| `lesson_objective` | Per-lesson (every lesson has "What this lesson covers") | Text | "Personal protective equipment fundamentals" | slide.slide.description |
| `lesson_rationale` | Per-lesson (every lesson has "Why this matters") | Text | "Safety is part of the job" | Combine with objective into the slide body |
| `category / department` | **NOT EXPLICIT** in the source | — | (Inferred from titles — see §4) | Need to assign during migration; new field on slide.channel.tag_ids |
| `format (video/PDF/live/mixed)` | **NOT EXPLICIT** in the source | — | (Implicit — "recommended links" sections reference video content but content type isn't formalised) | slide.slide.slide_type — needs assignment on migration |
| `duration (hours/sessions)` | **NOT EXPLICIT** in the source | — | (Not captured anywhere in the doc) | slide.slide.completion_time — needs estimation during migration |
| `instructor / facilitator` | **NOT EXPLICIT** in the source | — | (Single common cert implies institutional, not per-instructor) | Skip — single-track model |
| `prerequisites` | Soft hints only (Audio Advanced after Audio Basics, etc.) | (implicit ordering) | M03 references M02 ear-training | slide.channel prerequisite Many2one or sequence ordering |
| `date_created / last_updated` | **NOT EXPLICIT** (doc-level metadata only; per-module dates absent) | — | — | Capture during migration in `create_date` |
| `archived flag` | **NOT EXPLICIT** | — | (All modules "active" per current publication) | Default active=True on import |

**Coverage summary**: the catalog is rich on **content** (module bodies, lesson objectives, quiz questions) but **sparse on structured metadata** (no per-module duration, no formal category field, no instructor attribution, no creation dates). The PHP system likely tracked some of this in DB tables not exported into this docx. The doc is a publication-ready content pack, not a metadata dump.

## 4. Categorization

The 17 modules don't carry an explicit `category` field. Inferring from titles + lesson topics, the natural groupings are:

| Inferred category | Modules | Count | Likely Phase 7a cert linkage |
|---|---|---|---|
| **Foundations & Safety** | M01 Safety Foundations, M08 Power and Electrical Discipline | 2 | `cert_type_first_aid`, `cert_type_fire_safety_indoor` / `_outdoor`, `cert_type_electrical_live_mains` |
| **Audio** | M02 Audio Basics, M03 Audio Advanced, M15 Allen & Heath SQ6 | 3 | NEW equipment cert types needed (audio consoles — Phase 7a M3 seed has DiGiCo, but not SQ6 / Audio fundamentals) |
| **Lighting** | M04 Lighting Basics, M05 Lighting Advanced, M14 Avolites Titan Mobile | 3 | `cert_type_avolites_tiger_touch` is close (Titan Mobile is the Avolites laptop variant); Lighting fundamentals = NEW cert type |
| **Video / LED** | M06 LED / Video Basics, M07 LED / Video Advanced, M16 Kommander Media Server | 3 | NEW equipment cert types — Phase 7a M3 seed has `cert_type_led_wall` likely (verify); Kommander = NEW |
| **Workflow / Operations** | M09 Event Setup Workflow, M10 Fault Finding and Troubleshooting, M11 Warehouse and Equipment Care | 3 | Role-tier prerequisites — these inform `cert_type_tech` / `cert_type_lead_tech` competency rather than mapping 1:1 |
| **Soft Skills** | M12 Professional Communication and Team Discipline, M13 Leadership, Responsibility and Team Standards | 2 | `cert_type_client_facing_comfort`, `cert_type_leadership` (existing soft-skill seeds in M3) |
| **Rigging** | M17 Truss Systems and Rigging Discipline | 1 | `cert_type_truss_climbing_prolyte` (existing M3 seed; module content reinforces) |

**Most common format inferred**: text + reference video links + multiple-choice quizzes per module. No live-instructor sessions in the catalog scope — designed for self-paced upload by Arnold (per opening sentence: "prepared for Arnold's upload workflow").

**Typical duration**: not captured. Sampling M01 body (paragraphs ~88–~400 range): 5 lessons each with a 2–3 paragraph theory section + practice prompts + supervisor-review note. Estimated **30–45 min reading + ~30 min quiz per module** = ~1 hour per module → ~17 hours total program. Order-of-magnitude only; needs Tatenda + Ranganai confirmation.

## 5. Migration mapping to Phase 7a + 7e

Phase 7a's `neon.training.certification.type` seed (32 types) is the existing cert vocabulary. Phase 7e's LMS will sit on top of Odoo's `slide.channel` (Course) + `slide.slide` (Slide) + `survey.survey` (Quiz) stdlib trio.

Per-module migration target:

| Module | Migration target | Phase 7a cert that's earned (if any) | Notes |
|---|---|---|---|
| **M01 Safety Foundations** | New LMS course; gates completion of **`cert_type_fire_safety_indoor`** (M3 seed exists) | `cert_type_fire_safety_indoor` / `_outdoor` (PHP module is foundations; live external Fire Safety body still does final cert) | Single common cert means completion of THIS module is one of multiple inputs to the Neon Technical cert, not its own cert. Map as "prerequisite" rather than "earns" if Phase 7e supports prerequisite chaining. |
| **M02 Audio Basics** | New LMS course; **NEW cert type needed** — `cert_type_audio_basics` (not in M3 seed) | new | Phase 7a M3 seed has no Audio Basics cert; either add to seed during 7e build OR keep as LMS-only (no cert outcome) |
| **M03 Audio Advanced** | New LMS course; chained after M02 | new | Same as above — Audio Advanced cert |
| **M04 Lighting Basics** | New LMS course | **NEW cert type needed** | `cert_type_lighting_basics` (analog to Audio Basics) |
| **M05 Lighting Advanced** | New LMS course; chained after M04 | new | `cert_type_lighting_advanced` |
| **M06 LED / Video Basics** | New LMS course | **NEW cert type needed** | `cert_type_led_video_basics` (Phase 7a M3 has `cert_type_led_wall` possibly; verify) |
| **M07 LED / Video Advanced** | New LMS course; chained after M06 | new | `cert_type_led_video_advanced` |
| **M08 Power and Electrical Discipline** | New LMS course; **gates completion** of `cert_type_electrical_live_mains` | `cert_type_electrical_live_mains` (M3 seed exists) | Per Phase 7a: external trainer authority. LMS module is internal-prerequisite. |
| **M09 Event Setup Workflow** | New LMS course; **role-tier prerequisite** for `cert_type_tech` and above | informs role-tier cert | No 1:1 cert outcome; competency baseline for techs |
| **M10 Fault Finding and Troubleshooting** | New LMS course | informs role-tier cert | Same as M09 — competency baseline |
| **M11 Warehouse and Equipment Care** | New LMS course | informs role-tier cert | Same — competency baseline for all crew |
| **M12 Professional Communication and Team Discipline** | New LMS course; **earns** `cert_type_client_facing_comfort` (M3 seed exists, soft skill) | `cert_type_client_facing_comfort` | Map content directly; binary or tiered_3 level |
| **M13 Leadership, Responsibility and Team Standards** | New LMS course; **earns** `cert_type_leadership` (M3 seed exists, soft skill) | `cert_type_leadership` | Direct mapping. Renamed from "Level 3" wording in PHP per publication-pass notes — single-cert design alignment confirmed. |
| **M14 Avolites Titan Mobile** | New LMS course; **earns** `cert_type_avolites_tiger_touch` (M3 seed exists) — verify Titan Mobile vs Tiger Touch nomenclature with Ranganai | `cert_type_avolites_tiger_touch` (probable match) | Both are Avolites products; Titan is the software layer running on multiple hardware — may need cert-type rename or new sub-cert |
| **M15 Allen & Heath SQ6** | New LMS course; **NEW cert type needed** | `cert_type_allen_heath_sq6` (new) | M3 seed has audio console certs (DiGiCo, etc.) but not Allen & Heath specifically |
| **M16 Kommander Media Server** | New LMS course; **NEW cert type needed** | `cert_type_kommander_media_server` (new) | Not in M3 seed |
| **M17 Truss Systems and Rigging Discipline** | New LMS course; **earns** `cert_type_truss_climbing_prolyte` (M3 seed exists) | `cert_type_truss_climbing_prolyte` | Direct mapping; verify Prolyte coverage matches PHP module scope |

**Counts**:

- **Direct cert mapping to existing M3 seed**: 7 modules (M01, M08, M12, M13, M14, M17, + partial M06)
- **NEW cert types to add in Phase 7a seed**: 6 modules (M02, M03, M04, M05, M15, M16) — possibly 7 if M06/M07 don't map to `cert_type_led_wall`
- **LMS-only (competency baseline, no cert outcome)**: 3 modules (M09, M10, M11)
- **Skip / archive**: 0 (all 17 active per the publication pack)

**Plus the SOP Library + Operating Authority Boundaries sections**:

- 15 SOPs → migrate as `slide.slide` records of type `document` (PDF / read-only standard reference) under a dedicated "SOP Library" `slide.channel` separate from the 17 courses. Not cert-bearing; reference material the LMS course content links to.
- 6 Operating Authority Boundary domains → migrate as a single "Safety Boundaries" reference slide attached to the M01 Safety Foundations channel (or kept as a standalone reference under SOP Library).

## 6. Data quality findings

### Missing fields that Phase 7e schema will need

- **Per-module duration**: not captured anywhere. Phase 7e schema needs `completion_time_hours` on the LMS course model; Tatenda + Ranganai estimate per module during migration.
- **Category / tag**: implicit but not stored. Phase 7e schema needs `tag_ids` on the LMS course; categorisation per §4 table.
- **Format (video / PDF / live / mixed)**: implicit. Phase 7e schema uses Odoo's `slide.slide.slide_type` (`document`, `video`, `infographic`, `webpage`, `quiz`); per-slide choice during migration.
- **Question difficulty / weight**: 30 questions per module are unweighted in the source. Phase 7e schema needs `question.weight` if differential scoring desired.
- **Pass mark**: not specified. Phase 7e default = Odoo eLearning's stdlib (typically 80 %); confirm with Robin.
- **Re-take policy**: not specified. Default = unlimited retakes; confirm with Robin.

### Inconsistent values

- Module 13 was renamed in the publication pass to remove "Level 3" wording — historical drift before consolidation onto the single-cert model.
- Module status field uses three distinct phrasings: "Confirmed from source brief", "Requires platform export verification", "Drafted (Question 24 gap)". On migration, normalise to a Selection enum.
- M03 has Question 24 freshly drafted in this publication pack — handle as a normal question on import; no special treatment needed.
- `[file:1]` vs `[cite:2]` vs `[cite:119]` markers — internal authoring references. **Strip on migration.**

### Duplicate or near-duplicate content

- **Tables 0 and 2 are near-duplicates** (same 17-module roster, slightly different status text). Both describe the same module set — table 2 has the verified 520 total. Drop table 0 on migration; table 2 is canonical.
- **Three index sections at file start, middle, end** all list the 17 modules. The publication pack repeats the index for navigation; only one is needed in the target system.

### Courses referencing removed equipment / outdated practices

- None obvious from the audit. The Avolites Titan Mobile module is current; SQ6 is current; Kommander is current. The Truss / Prolyte module references current rigging practice.
- **Possible concern**: M14 says "Avolites Titan Mobile" but Phase 7a M3 seed has `cert_type_avolites_tiger_touch`. **Confirm with Ranganai** whether Titan Mobile is a software product running on Tiger Touch hardware (in which case the cert is the same), or whether they're separate products requiring separate certs.

### Authoring-system artefacts to strip

- `html-to-docx` doc-author metadata
- Per-paragraph `[file:1]` / `[cite:N]` citation markers
- Mojibake characters seen in places (`Arnold�s`, `M01�M03`, `function room�`) — character-encoding loss in the html-to-docx conversion. Use UTF-8 sanitisation pass on migration.
- All paragraphs use a single "Normal" style — heading hierarchy was lost in the export. Re-derive structure on migration from leading patterns (Module / Lesson / Sub-section).

## 7. Phase 7e schema implications

### Confirms the scope assumption

Yes: "use Odoo eLearning (`slide.channel` + `slide.slide` + `survey.survey`) + integrate Phase 7a" remains the right design. The PHP content fits Odoo's eLearning data model directly:

- **PHP "Module"** → Odoo `slide.channel` (Course)
- **PHP "Lesson"** → Odoo `slide.slide` (Slide / lesson)
- **PHP "Written quiz"** → Odoo `survey.survey` linked to the course, with `survey.question` records per question
- **PHP "Practical quiz"** → Odoo `survey.survey` (separate from written quiz) OR new `neon.lms.practical_test` model if supervisor-reviewed
- **PHP "SOP Library"** → Odoo `slide.channel` of type "Library" (standards reference)
- **PHP "Single common certification"** → Phase 7a `cert_type_neon_technical` (new aggregate cert type) earned on completion of all 17 modules + practicals

### Fields Phase 7e LMS needs beyond stdlib eLearning

| Field | Where | Purpose |
|---|---|---|
| `cert_type_id` Many2one → `neon.training.certification.type` | `slide.channel` extension (`neon_lms` inherit) | When a course is completed, which cert it earns (if any — M09/M10/M11 have null) |
| `cert_level` Selection | `slide.channel` extension | What level the earned cert is set to (`pass` for binary, `basic`/`standard`/`expert` for tiered_3) |
| `sign_off_authority_required` Boolean | `slide.channel` extension | Whether the cert needs Phase 7a M7 sign-off authority verification BEYOND the LMS quiz score (default True for safety/role-tier; default False for soft skills) |
| `practical_required` Boolean | `slide.channel` extension | Whether the supervisor-reviewed practical assessment is required for course completion (per "Suggested online use" note in the catalog) |
| `practical_test_id` Many2one → `survey.survey` | `slide.channel` extension | The practical-quiz survey paired with the written quiz |
| `prerequisite_channel_ids` Many2many → `slide.channel` | `slide.channel` extension | M03 requires M02 done first; M07 requires M06; etc. — explicit prerequisite chain |
| `module_code` Char | `slide.channel` extension | The PHP M01–M17 code, preserved for migration traceability and learner reference |

### Does Phase 7e ALSO need to add new cert types in Phase 7a?

**Yes — 6 to 7 new `neon.training.certification.type` records** (per §5 mapping):

- `cert_type_audio_basics`
- `cert_type_audio_advanced`
- `cert_type_lighting_basics`
- `cert_type_lighting_advanced`
- `cert_type_allen_heath_sq6` (or generic `cert_type_audio_console_sq6`)
- `cert_type_kommander_media_server`
- Possibly `cert_type_led_video_basics` / `_advanced` if existing `cert_type_led_wall` doesn't cover

Plus one **aggregate cert type** for the single common Neon Technical certification — `cert_type_neon_technical` — earned only when all 17 modules + their practicals are passed. This needs special handling: it's "auto-issued by the LMS engine when prerequisites met" rather than verified by a human signoff authority.

**Decision deferred to Robin walkthrough**: should the new cert types live in Phase 7e's migration (i.e., the LMS module adds them as part of its install), or in a Phase 7a M13+ data extension (i.e., the cert type list grows independently of LMS)?

Lean: **Phase 7e migration** — keeps the cert-types-driven-by-content coupling intact and matches the institutional reality (these certs exist because the PHP courses exist).

## 8. Open questions for Tatenda + Robin

1. **Migrate vs. rebuild**: copy the PHP content paragraph-by-paragraph into Odoo slides (preserves authoring), OR re-record in Odoo's native format (cleaner UX but slower)? **Default: migrate the text + recommended-links as-is, defer video re-recording to Phase 7e M9+.**

2. **Question count verification**: M04–M17 marked "Requires platform export verification" — total of 520 is doc-confirmed but per-module counts beyond M03 are not. **Required: get a platform export from the PHP system or have Arnold confirm counts module-by-module before migration begins.**

3. **Preserve PHP learner records**: any existing PHP students with completion history (Ranganai, possibly Arnold himself, others) — migrate their completions into Odoo eLearning so they don't need to re-take, OR start fresh on cutover? **Likely: migrate completions** but needs Tatenda + Robin sign-off.

4. **Practical quiz format**: 5 practical scenarios per module — "supervisor-reviewed OR auto-marked" per the catalog. **Decide**: build all 85 as auto-marked multiple-choice (faster, less Ranganai time) OR as supervisor-reviewed scenarios (richer, slower)? Hybrid is possible.

5. **Single-cert vs. modular certs**: the PHP catalog explicitly says "one common standard, not Level 1/2/3 tracks". Phase 7a's data model supports both per-module sub-certs AND an aggregate cert. **Confirm with Robin**: should the LMS issue 7 sub-certs as content is completed (matches Phase 7a's tier model), OR only issue the aggregate `cert_type_neon_technical` on full-program completion (matches PHP's single-cert promise)?

6. **New cert types — Phase 7a extension or Phase 7e addition**: see §7.3.

7. **M14 cert ambiguity**: Avolites Titan Mobile vs. Tiger Touch — Ranganai input needed.

8. **Pass mark + retake policy**: not in source. Need Robin's call.

9. **SOP Library access**: 15 SOPs as reference material — should crew need to "complete" them (acknowledge read) before being marked as having passed the relevant module, or are they pure reference (no completion tracking)? **Default: reference-only**, but Robin may want acknowledgement tracking for legal-coverage reasons (Operating Authority Boundaries section specifically).

10. **Content owner during/after migration**: Arnold authored the publication pack. Phase 7e ongoing — who owns updates to course content? Likely Ranganai post-onboarding (per Phase 7b plan). Confirm.

---

## Appendix A — Catalog structural map (paragraph indices)

For migration scripting reference. Non-empty paragraph indices (0-indexed across the 4478 non-empty paragraphs):

| Section | Paragraph range | Notes |
|---|---|---|
| Title + publication-pass notes | 0 – 6 | Header + single-cert policy + Module 13 rename |
| Neon Equipment Standards and SOP Library | 7 – 32 | 15 SOPs + "how to apply" |
| Neon Safety and Operating Authority Boundaries | 33 – 55 | 6 boundary domains |
| Quiz-count verification status | 56 – 66 | Verification table preamble |
| Curriculum master (overview) | 67 – 87 | "How to use this document" |
| Module 01: Safety Foundations | 88 – ~400 | Lessons + practice prompts |
| Modules M02–M17 (bodies) | ~400 – ~4246 | Same Module / Lessons / Practice structure repeated; full extraction is mechanical, not interpretive |
| Publishing-index references | 4247 – 4263 | 17 short paragraphs, one per module with publish notes |
| (Misc transitional content) | 4264 – 4371 | Suggested-use notes |
| Practical-quiz appendix (one per module) | 4372 – 4473 | M01–M17 practical quizzes, ~5 questions each = ~85 practical questions |
| Closing notes | 4474 – 4477 | "Suggested online use", "Set as supervisor-reviewed", "Pair with practical test form" |

## Appendix B — Sampled content for "what does a module body look like"

From M01 Safety Foundations (paragraphs 88–105):

> Module 01: Safety Foundations
>
> Module prompt
>
> Recommended links
>
> Lesson 1: Introduction to Workplace Safety in Event Production
>
> What this lesson covers
>
> Why this matters
>
> Safety is part of the job

Pattern: short headings, longer descriptive paragraphs after each heading (omitted from this sample). Each lesson contains "What this lesson covers" (objective) + "Why this matters" (rationale) + the body content.

This structure maps cleanly onto Odoo `slide.slide` with `description` (combining objective + rationale) and `slide_category` (groups slides within a channel).

## Next deliverable in Phase 7e pre-build sequence

The schema sketch for Phase 7e LMS (analogous to `docs/phase-7b/schema-sketch.md`). It will define:

- `slide.channel` extension fields (per §7.2 table)
- `slide.channel` ↔ `neon.training.certification.type` integration
- Per-module migration script outline (the 17 → 17 mapping)
- New cert type seed records (6–7 new types per §7.3)
- Pre-migration data prep (platform export request to PHP system for M04–M17 quiz counts + learner records)
- Milestone breakdown for the Phase 7e build (~10–12 milestones estimated)

Phase 7e schema sketch is **NOT in this commit**; it's the follow-on deliverable after this audit is reviewed by Tatenda + Robin.
