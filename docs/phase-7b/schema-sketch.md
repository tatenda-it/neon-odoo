# Phase 7b Schema Sketch — Crew Onboarding + Self-service Portal

**Status:** Pre-build design. To be confirmed during Robin's Phase 7a walkthrough.
**Branch:** `feat/training-phase-7a` (Phase 7b branch cuts after 7a deploys)
**Target manifest range:** `neon_training` 17.0.8.1.0 → 17.0.8.13.0 (10–13 milestones)
**Date:** 21 May 2026

---

## 1. Executive Summary

Phase 7b sits between **Phase 7a Core** (cert + gating, feature-complete on `f75082b`) and **Phase 7c External Training Booking** (deferred).

Two parallel work streams in a single sub-phase:

1. **Onboarding workflow** — internal-facing kanban + form for managers (Robin, Munashe) to walk new crew from `candidate` to `active` via a 6-stage state machine, with an admin-only Skip Onboarding override that creates an audit-log entry.
2. **Self-service portal** — public-facing surfaces under `/my/...` for crew to view their own certifications, upload new ones for verification, and see their assigned jobs without needing an internal-user license. Reuses Phase 7a's M2 cert state machine + M7 sign-off routing + M3 dynamic Selection widget.

**Estimated effort:** 10–13 milestones, ~2–3 weeks at proven Phase 7a cadence (~1000–1100 LOC per milestone).

### Key integrations with Phase 7a

- M2 cert state machine → portal upload flow + onboarding cert collection
- M3 cert types + dynamic widget → reused in portal upload wizard for level field
- M7 sign-off authority routing → determines who verifies portal-uploaded certs
- M8 gate inference engine → extended with a 4th gate condition (probationary candidates blocked from non-Runner assignments)
- M9–M11 three-tier gating → unchanged at the engine level; integration point is the 4th condition
- M12 compliance dashboard → +2 counters (Active Candidates, Probationary Crew)

### Bulk-import path for existing crew

The 9 tech crew users currently in production (Arnold M et al., reverted during Phase 7a pre-deploy session and currently NOT on prod — see `project_phase7a_status.md` "Tech crew onboarding — PAUSED") will be created via the **onboarding workflow itself** rather than direct `res.users` writes. Admin uses Skip Onboarding to fast-path each one (~30 seconds per candidate), bypassing the cert-collection phase since their training is already certified out-of-band. Net time: ~5 minutes for all 9.

---

## 2. Default Assumptions for Robin's Open Questions

| # | Question | Default | Rationale |
|---|---|---|---|
| 1 | Probationary period length | **3 jobs** (Robin to confirm at walkthrough) | Aligns with events-production rhythm — by job 4 a new crew member has seen full event flow (load-in, event, strike, return) at least once on different rigs |
| 2 | Admin override authority | **`group_neon_jobs_manager` + `group_neon_training_admin`** (Robin, Munashe, Ranganai when created, Tatenda dev). (Robin to confirm at walkthrough) | Matches existing M7 sign-off routing pattern; both groups already exist + carry the right tier semantics |
| 3 | WhatsApp notification on activation | **Stubbed** — template defined, send deferred to Phase 9. (Robin to confirm at walkthrough) | Avoids Phase 9 dependency blocking 7b ship; same pattern as Phase 7a M5's "TODO surface, dispatch later" choice for cert renewals |
| 4 | Required certs per role (matrix) | **See section 7** for full role → cert mapping. (Robin to confirm at walkthrough) | Sourced from M3 seed data + memory's role-tier definitions + the role-tier-to-cert mapping baked into M8's `_ROLE_TIER_TO_CERT_XMLID` dict |
| 5 | Portal layout direction | **Responsive (mobile-first for crew, desktop for managers)** — single template stack. (Robin to confirm at walkthrough) | Crew use phones; managers use desktops; Odoo's portal templates are responsive by default; no need to fork |
| 6 | Bypass reason field validation | **Required text, no enum** (Robin to confirm at walkthrough) | Free-text justification scales to unknown reasons; an enum would constrain Robin's audit narratives |

---

## 3. Onboarding 6-Stage State Machine

```
                                                ┌──────────────────┐
                                                │ Skip Onboarding  │
                                                │  (admin override │
                                                │  with reason +   │
                                                │  audit log)      │
                                                └──┬───────────────┘
                                                   │
                                                   ▼
  ┌───────────┐    ┌──────────────────┐    ┌──────────────┐    ┌────────┐
  │ candidate │───▶│ cert_collection  │───▶│ probationary │───▶│ active │
  └───────────┘    └──────────────────┘    └──────────────┘    └────────┘
        │                  │                       │                ▲
        │                  │                       │                │
        │           (auto: all required            │      (auto: probationary
        │            certs verified)               │       _jobs_completed >=
        │                                          │       _jobs_target)
        │                                          │
        │           OR manager applies             │      OR manager clicks
        │           template (sets requirement     │      "Promote to Active"
        │           _ids → triggers transition     │      early
        │           to cert_collection)            │
        │                                          │
        └──────────────────────────────────────────┴───────────► active
                                                              (any state →
                                                               admin Skip
                                                               Onboarding)
```

### States (matching `state` Selection on `neon.onboarding.candidate`)

| Value | Label | What's true at this state |
|---|---|---|
| `candidate` | Candidate | Record created, basic personal info captured. No requirement template applied yet. No certs being collected. |
| `cert_collection` | Cert Collection | `intended_role` set; requirement template auto-applied; `required_cert_ids` populated; some/all certs being uploaded + verified. Crew can use the portal in read-only mode here (preview their profile, see what they need). |
| `probationary` | Probationary | All required certs are in state='active' (verified). Candidate can be assigned to jobs but only as Runner / shadow-tier regardless of `intended_role`. Counts toward `probationary_jobs_completed`. |
| `active` | Active | Full crew-tier access per their certified roles. Can be assigned to their `intended_role` and any equipment they hold certs for. |

### Transitions

| From | To | Trigger | Authority |
|---|---|---|---|
| `candidate` | `cert_collection` | Manager sets `intended_role` AND applies a requirement template (typically auto-applied on intended_role change) | manager |
| `cert_collection` | `probationary` | Compute: all `required_cert_ids` have a matching `collected_cert_ids` entry with `state='active'` | automatic |
| `probationary` | `active` | Compute: `probationary_jobs_completed >= probationary_jobs_target` OR manager clicks "Promote to Active" | automatic OR manager |
| any | `active` | Admin clicks Skip Onboarding + provides `bypass_reason` | admin/manager (DP6 confirms) |

**No backward transitions in M1 scope.** Re-cert workflow (active → probationary on cert expiry) deferred to Phase 7b polish (post-M13) or Phase 8.

---

## 4. Models

### 4.1 `neon.onboarding.candidate`

Main onboarding record. Links to `res.users` after activation (M2O nullable until activation moment).

**`_inherit`:** `['mail.thread', 'mail.activity.mixin']` (chatter + activities)
**`_order`:** `state asc, date_started desc, id desc`

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | Char | yes | — | Display name (e.g., "Arnold M") |
| `intended_role` | Selection | yes | — | `driver / lead_tech / tech / runner` — drives requirement template selection |
| `contact_phone` | Char | yes | — | Required for WhatsApp dispatch later (Phase 9) |
| `contact_email` | Char | no | — | Becomes `res.users.login` on activation if set; otherwise generated |
| `emergency_contact_name` | Char | no | — | |
| `emergency_contact_phone` | Char | no | — | |
| `photo` | Binary | no | — | Standard Odoo image field with `image` widget |
| `state` | Selection | yes | `candidate` | See section 3 |
| `requirement_template_id` | Many2one → `neon.onboarding.requirement.template` | no | — | Auto-set when `intended_role` changes |
| `required_cert_ids` | Many2many → `neon.training.certification.type` | computed | — | Mirrors `requirement_template_id.required_cert_type_ids`; recomputed on template change |
| `collected_cert_ids` | One2many → `neon.training.certification` (inverse `candidate_id` — see §4.4 below) | — | — | Certs uploaded for this candidate; reverse relation needs a new field on `neon.training.certification` (M_N owns the fix in M1) |
| `user_id` | Many2one → `res.users` | no | — | Set on activation; null while pre-active. Unique constraint per candidate. |
| `date_started` | Datetime | — | `fields.Datetime.now` | |
| `date_activated` | Datetime | — | — | Set on transition to `active` |
| `probationary_jobs_target` | Integer | — | 3 | DP1 default; manager can override per-candidate |
| `probationary_jobs_completed` | Integer | computed | — | Count of `commercial.job.crew` rows where `user_id == self.user_id AND job_id.state == 'completed'`. Sudo on the read (operational ACL) |
| `bypass_reason` | Char | conditionally required | — | Required if `bypass_actor_id` is set (constraint) |
| `bypass_actor_id` | Many2one → `res.users` | no | — | Populated on Skip Onboarding |

**ACLs (CRUD per tier):**

| Group | Read | Write | Create | Unlink |
|---|---|---|---|---|
| `group_neon_jobs_manager` (Robin/Munashe) | ✓ | ✓ | ✓ | ✗ |
| `group_neon_training_admin` | ✓ | ✓ | ✓ | ✗ |
| `group_neon_training_signoff` | ✓ | ✗ | ✗ | ✗ |
| `group_neon_jobs_crew` | ✓ (own only via ir.rule) | ✓ (limited fields: contact_phone, contact_email, emergency_*, photo) | ✗ | ✗ |
| Portal user (crew via `/my/profile`) | ✓ (own only via ir.rule) | ✓ (same limited fields) | ✗ | ✗ |

**`perm_unlink=0` for ALL tiers** — append-only audit discipline (H3=A from Phase 6). Corrections via state transitions or `bypass_reason` annotation; never via delete.

**Constraints:**

- `_sql_constraints`: `('candidate_user_id_unique', 'unique(user_id)', 'A candidate is linked to at most one user account.')`
- `@api.constrains('bypass_actor_id', 'bypass_reason')`: if either is set, both must be set
- `@api.constrains('state', 'user_id')`: state='active' requires user_id (cannot be active without a backing user)

### 4.2 `neon.onboarding.requirement.template`

Defines required cert types per `intended_role`. Seeded with 4 templates (one per role tier — see seed data below).

**`_order`:** `intended_role, id`

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | Char | yes | — | e.g., "Driver Requirements" |
| `intended_role` | Selection | yes | — | Same enum as `candidate.intended_role` |
| `required_cert_type_ids` | Many2many → `neon.training.certification.type` | yes (non-empty) | — | The cert types a candidate of this role must hold |
| `description` | Text | no | — | Robin's notes; surfaced in candidate form for guidance |
| `active` | Boolean | — | True | Standard archive support |

**ACLs:**

| Group | Read | Write | Create | Unlink |
|---|---|---|---|---|
| `group_neon_jobs_manager` | ✓ | ✓ | ✓ | ✗ |
| `group_neon_training_admin` | ✓ | ✓ | ✓ | ✗ |
| Everyone (`base.group_user`) | ✓ | ✗ | ✗ | ✗ |

**Seed data (`data/neon_onboarding_data.xml`):**

```
template_driver:    intended_role=driver
                    required_cert_type_ids=[
                      cert_type_class_4_driver_licence  (or any of class_2/3/5/PSV — see DP4)
                      cert_type_fire_safety_indoor      (or _outdoor)
                      cert_type_vehicle_safety_briefing (NEW seed in M2 if not in M3 already)
                    ]

template_lead_tech: intended_role=lead_tech
                    required_cert_type_ids=[
                      cert_type_lead_tech               (role-tier)
                      cert_type_electrical_live_mains
                      ≥2 of cert_type_ma2_console / ma3_console / tiger_touch / magicq / digico
                    ]

template_tech:      intended_role=tech
                    required_cert_type_ids=[
                      cert_type_tech                    (role-tier)
                      ≥1 of cert_type_ma2_console / ma3_console / tiger_touch / magicq / digico
                      cert_type_fire_safety_indoor      (or _outdoor)
                    ]

template_runner:    intended_role=runner
                    required_cert_type_ids=[
                      cert_type_runner                  (role-tier)
                      cert_type_fire_safety_indoor      (or _outdoor)
                    ]
```

Note on "any of" quantity logic: M2m can't express "≥2 of these 5"; the requirement template stores a *superset* and the candidate-side `_compute_all_required_held` accepts any subset of the right cardinality. See §6.3 for the helper that implements this.

### 4.3 `neon.onboarding.audit.log`

Separate from chatter for queryable audit trail of override decisions. Same H3=A pattern as M9's `assignment_gate_log`.

**`_inherit`:** `['mail.thread']` (chatter for context messages on each audit entry)
**`_order`:** `timestamp desc, id desc`

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `candidate_id` | Many2one → `neon.onboarding.candidate` | yes | — | `ondelete='restrict'` per FK lifecycle ref doc |
| `action` | Selection | yes | — | `skip_onboarding / promote_probationary / promote_active / template_change` |
| `actor_id` | Many2one → `res.users` | yes | `lambda self: self.env.user.id` | Pre-sudo capture per the hook-sudo-partner-capture ref doc |
| `reason` | Char | yes for override actions | — | Required when action ∈ `{skip_onboarding}`; optional for auto-transitions logged for audit |
| `previous_state` | Char | yes | — | Captured at fire time |
| `new_state` | Char | yes | — | Captured at fire time |
| `timestamp` | Datetime | yes | `fields.Datetime.now` | |

**ACLs:**

| Group | Read | Write | Create | Unlink |
|---|---|---|---|---|
| `group_neon_training_user` (and above) | ✓ | ✗ | ✗ | ✗ |
| `group_neon_training_admin` | ✓ | ✗ | ✓ | ✗ |
| Server-side hooks (sudo) | — | — | ✓ | ✗ |

**`perm_unlink=0` for all groups** — same audit-immutability pattern as M9 `assignment_gate_log`. Override `unlink()` to raise `UserError` (defensive against sudo bypass).

### 4.4 `neon.training.certification` extension

Adds reverse relation for the candidate o2m. Single field, no methods.

| Field | Type | Required | Notes |
|---|---|---|---|
| `candidate_id` | Many2one → `neon.onboarding.candidate` | no | `ondelete='set null'` — cert can outlive the onboarding record (e.g., crew member re-onboards after a break) |

This is **M_N owns the fix** per the M6 enumeration-gap precedent: 7b adds a candidate o2m that requires a reverse field on the 7a model. The reverse Many2one is the smallest valid extension.

---

## 5. Views

### 5.1 Onboarding Kanban (manager view)

Grouped by `state` (4 columns: Candidate / Cert Collection / Probationary / Active). Cards show:

- Photo (cropped, 64px circle)
- Name (bold)
- `intended_role` (badge)
- `date_started` (relative — "3 days ago")
- Progress indicator: "3/5 certs verified" (renders for `cert_collection` only)
- Probationary progress: "Job 2/3" (renders for `probationary` only)

Per-card actions:

- **Open** → form view (default click)
- **Skip Onboarding** → opens override wizard (manager/admin only, visible via `groups_id` on the button)
- **Promote to Active** → visible when `probationary_jobs_completed >= probationary_jobs_target`

### 5.2 Candidate Form

Layout:

```
HEADER
  ├─ Photo (left, 96px)
  ├─ name (h1)
  ├─ intended_role (badge)
  └─ state pipeline indicator (Draft → ... → Active)

ACTION BAR
  ├─ Open Portal Profile (link, opens /my/profile in new tab — visible when user_id set)
  ├─ Skip Onboarding (admin/manager only; opens wizard)
  └─ Promote to Active (visible when probationary + jobs_completed >= target)

PERSON & ROLE TAB
  ├─ name, intended_role, contact_phone, contact_email
  └─ emergency_contact_name, emergency_contact_phone

REQUIREMENTS TAB
  ├─ requirement_template_id (M2O picker)
  └─ required_cert_ids list with status indicators per type:
       ✓ verified  (collected_cert_ids has active match)
       ⏳ pending   (collected_cert_ids has pending_verification match)
       ⚠ missing  (no collected_cert match)

COLLECTED CERTS TAB
  └─ collected_cert_ids one2many (tree + form embedded)

PROBATIONARY TAB (visible only in state in probationary+active)
  ├─ probationary_jobs_target (Integer)
  ├─ probationary_jobs_completed (Integer readonly)
  └─ List of completed jobs (sudo-read)

AUDIT TAB (admin/manager only)
  └─ neon.onboarding.audit.log records filtered to this candidate_id

CHATTER (bottom, full mail.thread)
```

### 5.3 Portal Templates

Three QWeb templates under `addons/neon_training/views/portal/`:

- `portal_my_home.xml` — extends `portal.portal_my_home` adding "My Training" + "My Jobs" sections
- `portal_my_certs.xml` — `/my/certs` route, lists own certs with state badges + upload action
- `portal_my_jobs.xml` — `/my/jobs` route, lightweight read of own `commercial.job.crew` rows

**Routes** (Phase 7b portal controller in `controllers/portal.py`):

| Route | View | Auth |
|---|---|---|
| `/my/profile` | candidate form (read-only display + editable contact fields) | `portal_user` |
| `/my/certs` | own cert list | `portal_user` |
| `/my/certs/upload` | upload wizard (template render + POST handler) | `portal_user` |
| `/my/jobs` | own job assignments | `portal_user` |

Portal user is a crew member with `base.group_portal` only (no `base.group_user`). They consume an Odoo portal license slot, not an internal-user slot — important for cost ceiling.

### 5.4 Self-Upload Wizard (portal-facing)

QWeb form posted to a controller; not a TransientModel modal (portal users can't see internal modals). Fields:

- `cert_type_id` — Selection rendered as searchable dropdown, filtered to types matching `candidate.intended_role` + general role-tier
- `date_obtained` — Date picker
- `date_expires` — Date picker (visible only if selected cert type has `validity_months > 0`)
- `level` — Selection driven by M3 dynamic widget (binary / tiered_3 / custom modes)
- `attachment_ids` — File upload (PDF/JPG/PNG)
- Submit → creates `neon.training.certification` with `state='pending_verification'`, attaches file, fires M7 routing to the appropriate signoff authority

---

## 6. Server Actions / Wizards

### 6.1 Skip Onboarding (admin override)

TransientModel: `neon.onboarding.skip_wizard`

**Fields:**

- `candidate_id` (M2O, required)
- `bypass_reason` (Text, required)
- `create_portal_user` (Boolean, default True) — whether to create a `res.users` record on activation; False for candidates who already have one

**Visibility:**

- Button: visible on candidate form to `group_neon_jobs_manager` + `group_neon_training_admin`

**On Confirm (per the sudo-partner-capture ref doc):**

```python
triggering_user = self.env.user  # capture BEFORE sudo
triggering_partner = triggering_user.partner_id

# Sudo for the writes (manager may lack training_admin)
candidate_su = self.candidate_id.sudo()
previous_state = candidate_su.state

vals = {
    "state": "active",
    "date_activated": fields.Datetime.now(),
    "bypass_actor_id": triggering_user.id,
    "bypass_reason": self.bypass_reason,
}

# Create res.users if needed (ORM (4, id) write for group propagation
# per the implied_ids ORM-vs-SQL ref doc)
if self.create_portal_user and not candidate_su.user_id:
    new_user = self.env["res.users"].sudo().create({
        "name": candidate_su.name,
        "login": (candidate_su.contact_email
                  or f"{candidate_su.name.lower().replace(' ', '.')}"
                     "@neonhiring.co.zw"),
        "password": "Neon2026!",  # temp; user must change on first login
        "groups_id": [(6, 0, [
            self.env.ref("base.group_user").id,
            self.env.ref("neon_jobs.group_neon_jobs_crew").id,
        ])],
    })
    vals["user_id"] = new_user.id

candidate_su.write(vals)

# Audit log entry
self.env["neon.onboarding.audit.log"].sudo().create({
    "candidate_id": candidate_su.id,
    "action": "skip_onboarding",
    "actor_id": triggering_user.id,
    "reason": self.bypass_reason,
    "previous_state": previous_state,
    "new_state": "active",
})

return {"type": "ir.actions.act_window_close"}
```

### 6.2 Apply Requirement Template

Server-side `@api.onchange("intended_role")` on candidate. No user action needed:

```python
@api.onchange("intended_role")
def _onchange_intended_role(self):
    if not self.intended_role:
        return
    template = self.env["neon.onboarding.requirement.template"].search(
        [("intended_role", "=", self.intended_role),
         ("active", "=", True)], limit=1)
    if template:
        self.requirement_template_id = template
```

`required_cert_ids` is then a computed Many2many depending on `requirement_template_id.required_cert_type_ids`.

### 6.3 Promote to Probationary (automatic)

Computed transition. When `required_cert_ids` and `collected_cert_ids` overlap such that every requirement is met (potentially with the "≥N of" quantity logic for templates that need it), state auto-flips from `cert_collection` to `probationary`. Audit log entry written by the compute (sudo path).

Implementation note: a pure `@api.depends` compute would re-fire on every cert change. Use a write-side hook on `neon.training.certification` (when state transitions to active and `candidate_id` is set, call `candidate._maybe_promote_to_probationary()`). Same pattern as M9's crew assignment hook.

### 6.4 Promote to Active (probationary completion)

Two paths:

1. **Automatic** — when `probationary_jobs_completed >= probationary_jobs_target`. Computed via a similar write-side hook on `commercial.event.job` (when state transitions to `completed`, recompute candidates for that job's crew).

2. **Manual button** — manager clicks "Promote to Active" before the threshold is met (e.g., crew member has prior production experience elsewhere). Same audit-log creation pattern as Skip Onboarding but without the wizard (button-confirm dialog only, no required reason since this isn't a bypass).

---

## 7. Required Certs Matrix

**(Robin to confirm at walkthrough.)** Sourced from M3 seed data + M8's `_ROLE_TIER_TO_CERT_XMLID` dict.

| Intended Role | Required Cert Type(s) | Quantity | Notes |
|---|---|---|---|
| Driver | Driver Licence (Class 2 / 3 / 4 / 5 / PSV) | ≥1 | Any one class qualifies; Class 4 is the common case for Neon's fleet |
| Driver | Fire Safety (Indoor OR Outdoor) | 1 | Indoor is sufficient for shed work; outdoor needed for field events |
| Driver | Vehicle Safety Briefing | 1 | Self+Peer sign-off authority; new seed needed (M2 of 7b adds the cert type) |
| Lead Tech | Lead Tech role-tier | 1 | OD/MD sign-off authority |
| Lead Tech | Electrical Live Mains | 1 | External Trainer sign-off authority; 12-month validity per M3 seed |
| Lead Tech | Equipment certs (MA2 / MA3 / Tiger Touch / MagicQ / DiGiCo / LED Wall / Truss / etc.) | ≥2 | Any two qualify; Robin's framing: "no Lead Tech should be one-trick" |
| Tech | Tech role-tier | 1 | OD/MD sign-off authority |
| Tech | Equipment cert (same superset as Lead Tech) | ≥1 | Any one of the equipment certs |
| Tech | Fire Safety (Indoor OR Outdoor) | 1 | Same as Driver |
| Runner | Runner role-tier | 1 | OD/MD sign-off authority |
| Runner | Fire Safety (Indoor OR Outdoor) | 1 | Same as Driver |

**Quantity logic** (`≥N of`): the requirement template stores the full eligible superset; the candidate-side helper counts overlap:

```python
def _is_requirement_met(self, requirement_template):
    """Returns True when the candidate's verified cert types
    satisfy the template, accounting for any-of quantity logic.
    """
    held_types = self.collected_cert_ids.filtered(
        lambda c: c.state == "active").mapped("type_id")
    required = requirement_template.required_cert_type_ids
    # Simple set inclusion for M1; tighten with per-template
    # quantity rules in M4 (e.g. driver requires "any 1 driver
    # licence" but the template lists 5).
    return all(t in held_types for t in required)
```

The "≥N of" tightening (M4) introduces a `min_count_per_subset` field on requirement_template lines (replacing the flat M2M with a one2many of `template_line` records). Deferred to M4 if M1 with strict set-inclusion is workable; will require Robin's confirmation that all-of is too strict.

---

## 8. Integration with Phase 7a

Touchpoints, each with the 7a artifact name + how 7b uses it:

| 7a Artifact | 7b Usage |
|---|---|
| `neon.training.certification` (M2) | New `candidate_id` Many2one (§4.4); `collected_cert_ids` one2many on candidate |
| `neon.training.certification.type` (M3) | `required_cert_type_ids` on requirement template; portal upload wizard's cert-type dropdown filters by role-tier |
| Cert state machine (M2: draft → pending_verification → active → expired/suspended) | Portal upload sets `state='pending_verification'`; M7 signoff routing flips it to `active`; candidate auto-promotes when all required → active |
| M3 dynamic Selection widget | Reused in portal upload wizard for `level` field (binary / tiered_3 / custom) |
| Sign-off authority routing (M7) | `_SIGN_OFF_AUTHORITY_GROUP` resolves the right verifier for each portal-uploaded cert; existing TODO surface handles the verifier notification |
| 3-tier gate engine (M8 inference + M9–M11 enforcement) | Adds a 4th condition to M8's `_compute_gate_status`: when `crew.user_id.partner_id` matches a candidate in state='probationary' AND `crew.role` is anything other than 'runner', set `gate_status='unqualified'`. M11 then blocks event_start as usual. |
| Compliance Dashboard (M12) | Two new counters added to `neon.training.dashboard`: `active_candidates_count`, `probationary_candidates_count`. Single LOC additions to the existing `_compute_counters` method + view extension. |

The **4th gate condition for M8** is the only deep code change; everything else is additive.

---

## 9. Phase 9 WhatsApp Integration Points (stubbed)

For each notification, document trigger / recipient / template variables. Phase 7b builds the trigger points (chatter post, mail.activity, or bus channel toast as placeholder); Phase 9 wires the actual WhatsApp send.

| Trigger | Recipient | Template variables |
|---|---|---|
| Candidate created | `group_neon_jobs_manager` (Robin, Munashe) | `candidate_name, intended_role, contact_phone, started_by_user` |
| Cert uploaded via portal | M7-routed sign-off authority for the cert type | `candidate_name, cert_type_name, cert_level, attachment_url, uploaded_at` |
| All requirements met (state → probationary) | `group_neon_jobs_manager` | `candidate_name, intended_role, days_in_collection, missing_certs (empty)` |
| Probationary jobs completed | `group_neon_jobs_manager` | `candidate_name, intended_role, jobs_completed, jobs_target` |
| State → active | Candidate themselves (via `candidate.contact_phone`) | `candidate_name, intended_role, portal_url, activated_by_user` |
| Skip Onboarding used | `group_neon_jobs_manager` (always, regardless of who triggered) | `candidate_name, intended_role, actor_name, bypass_reason, audit_log_url` |

**Phase 7b ships the trigger code + recipient routing** (resolving the right user/group + getting their `partner_id.phone`); Phase 9 ships the `mail.template` / `whatsapp.template` records and the actual send mechanism. Same separation as M5's notification dispatch built on M4's mail.template stubs.

---

## 10. Milestone Breakdown (target 10–13)

| # | Scope | LOC est. | Cross-cutting |
|---|---|---|---|
| **M1** | `neon.onboarding.candidate` model + state machine + ACLs + `_post_init_hook` for default templates | ~600 | 1 model + 1 reverse o2m on `neon.training.certification` (M_N owns the fix) |
| **M2** | `neon.onboarding.requirement.template` model + 4 seed templates + auto-apply onchange | ~400 | Seed data only |
| **M3** | Onboarding kanban + candidate form view + state pipeline indicator | ~500 | Views only |
| **M4** | Required cert integration: compute `required_cert_ids` from template; `cert_collection → probationary` auto-transition via write-hook on `neon.training.certification`; "≥N of" quantity helper | ~700 | Hook on cert state change |
| **M5** | Probationary period gating: 4th condition on M8's `_compute_gate_status` (probationary candidates blocked from non-Runner roles) | ~400 | 1 modified compute on M8 model |
| **M6** | Activation flow: manual `Promote to Active` button + auto-promote on `probationary_jobs_completed >= target` (write-hook on `commercial.event.job` state='completed') | ~500 | Hook on event_job state change |
| **M7** | Skip Onboarding wizard + audit log model + audit log view + Skip button on candidate form | ~700 | NEW transient model + NEW audit-log model |
| **M8** | Portal stream: `/my/profile` route + portal controller scaffold + read-only candidate view + editable contact fields | ~600 | Portal controller setup |
| **M9** | Portal stream: `/my/certs` + self-upload wizard (controller form) + M7 routing handoff | ~700 | Portal upload flow |
| **M10** | Portal stream: `/my/jobs` lightweight view | ~400 | Portal job-view template |
| **M11** | Dashboard extension: 2 new counters on `neon.training.dashboard` + drill-throughs | ~250 | Single-model extension |
| **M12** | WhatsApp trigger scaffolding (template records + recipient resolver + placeholder chatter posts, actual send deferred to Phase 9) | ~500 | 6 trigger points; recipient resolver helper |
| **M13** | Final smoke pass: T7B-T7B+12 Python smokes + browser smokes for portal flows + integration test that walks candidate→active end-to-end | ~600 | Smokes only |
| **Total** | | **~6850 LOC** | |

Sequencing notes:

- M1–M3 ship the internal-facing skeleton (admin can create candidates, see kanban, edit forms) without portal exposure.
- M4–M6 wire the state-machine automation (auto-transitions + manual overrides on the internal side).
- M7 is the Skip Onboarding flow — useful by itself for the bulk-import path (9 existing crew → ~5 minutes total via Skip).
- M8–M10 are the portal stream; can ship in parallel with M4–M7 if Tatenda wants to swap-task.
- M11–M12 are integrations on top of existing 7a + Phase 9 surfaces — lightest.
- M13 is the regression-suite + walkthrough-ready close.

---

## 11. Phase 7a Reference Docs to Leverage

Each milestone gate-1 should reference the relevant ref doc up front:

| Reference Doc | 7b Milestone Usage |
|---|---|
| `reference_odoo17_gate_log_fk_lifecycle.md` | M7 audit log model — same set null / cascade / restrict decision matrix as M9's gate_log; `candidate_id` ondelete=restrict (audit must outlive crew reorg); `actor_id` ondelete=restrict |
| `reference_odoo17_hook_sudo_partner_capture.md` | M7 Skip Onboarding wizard — capture `triggering_user.partner_id` BEFORE sudo escalation for audit log + any toast notification |
| `reference_odoo17_menu_visibility_filter.md` | M3 onboarding menu — manager-tier visibility; if any child needs broader access, apply two-layer fix |
| `reference_odoo17_implied_ids_orm_vs_sql.md` | M7 Skip Onboarding user creation — `[(4, group_id)]` ORM write to ensure implied_ids propagation; no raw SQL on `res_groups_users_rel` |
| `reference_owl_dashboard_pattern.md` | M11 dashboard counter extension — extend existing form-view virtual model (M12 of 7a), don't fork to OWL |

Plus the CLAUDE.md M4 amendment (enforced gate-1 enumeration of all touched fields/methods/buttons/views) — applies to every milestone.

---

## 12. Open Questions for Robin (Walkthrough Agenda)

Final list of items where the default assumption needs Robin's confirmation. Each tagged with the section number it's specified in.

1. **§2 #1 — Probationary period:** 3 jobs default. Confirm or change.
2. **§2 #2 — Admin override authority:** `group_neon_jobs_manager` + `group_neon_training_admin` (Robin, Munashe, Ranganai when created, Tatenda dev). Confirm the list.
3. **§7 — Required cert matrix:** full role-by-role confirmation, including the "≥N of" quantity logic for Lead Tech equipment certs.
4. **§5.3 — Portal layout direction:** phone-first vs desktop-first. We defaulted to responsive (mobile-first for crew, desktop-only for managers via internal kanban). Confirm.
5. **§9 — WhatsApp notification list:** 6 triggers documented. Add more? Remove any? Confirm recipient routing.
6. **§4.1 — Initial password for portal users:** defaulted to `Neon2026!` shared temp (matches the paused tech-crew onboarding). Robin to confirm; alternative is per-user generated + delivered via WhatsApp on first activation.
7. **§4.3 — Audit log unlink policy:** modeled on M9's H3=A append-only (perm_unlink=0 for ALL groups including admin). Confirm — particularly whether SUPERUSER bypass override should exist for "I made a typo in the audit reason" cases.
8. **§6.4 — Promote to Active manual path:** allow managers to promote early (before probationary jobs target met)? Default yes; confirm.

---

## 13. Build sequencing relative to Phase 7a deploy

```
Now: Phase 7a feature-complete @ f75082b
     + Pre-deploy ACL finding paused at "Robin to advise"

Next:
  1. Robin walkthrough — Phase 7a demo + ACL per-tier mapping + Phase 7b open-Qs
  2. ACL migration drafted per Robin's mapping (memory: project_phase7a_status.md
     "PROD ACL FINDING" section)
  3. Phase 7a + ACL migration deployed together (production tag
     v17.0.8.0.0-phase7a-live)
  4. Tech-crew onboarding RESUMES on prod (9 candidates via Skip Onboarding;
     ~5 min total)
  5. Phase 7b branch cut: feat/training-phase-7b from main post-7a-deploy
  6. Phase 7b M1 gate-1 prompt from Tatenda

Phase 7b SHOULD NOT START until items 1-5 complete. The schema sketch in this
doc is design-stage work that lands on the feat/training-phase-7a branch
(per Tatenda's instruction; 7a branch is the active workbench).
```
