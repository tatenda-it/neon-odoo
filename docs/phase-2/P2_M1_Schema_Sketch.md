# P2.M1 — Commercial Job Record Schema Sketch

**Purpose:** Translates Robin's Phase 2 Open Questions answers into a concrete data model.
**Audience:** Tatenda (developer) — review with Munashe & Robin before code.
**Status:** v1.0 — All open questions resolved by Robin. Ready for stakeholder sign-off, then code.
**Date:** 10 May 2026
**Related:** Phase 2 Open Questions (answered 10 May), v4.1 master roadmap §5–§10

---

## 1. Why this document exists

Phase 2's central feature is a record that travels from "client enquired" to "event delivered" — the **Commercial Job**. The schema must support:

- A two-state lifecycle (Pending → Active) confirmed by Robin
- One-to-many relationships (a master contract can spawn multiple events)
- Three parallel status tracks (Commercial / Finance / Operational) per v4.1 §7
- Capacity Acceptance Gate per v4.1 §8 (8 checks, MD/OD override)
- Soft Hold mechanism per v4.1 §10 (7-day default)
- Calendar with venue + room granularity (Robin's Q9 answer)
- Crew assignment with confirmation workflow (Robin's Q9 answer)
- Loss reason capture for archived leads (Robin's Q5 answer)

This document defines models, fields, relationships, and state transitions. It does **not** specify UI, controllers, or Python implementation.

---

## 2. Models overview

```
res.partner ─┬── (client) ──> commercial_job_master ──┐
             │                                        │
             └── (client) ──────────> commercial_job ─┤
                                       │              │
                                       │              └── (optional parent)
                                       │
                            ┌──────────┼──────────┬─────────────────┐
                            ↓          ↓          ↓                 ↓
                  commercial_job_crew  venue.room  crm.lead       sale.order
                  (confirmation       (where)     (where it       (the quote)
                   workflow)                       came from)
```

Five new models, plus extensions to `res.partner`, `crm.lead`, and `sale.order`.

---

## 3. Models in detail

### 3.1 `commercial_job_master` — Master Contract (optional parent)

For repeat clients with formal multi-event commitments. Confirmed examples (Robin Q6): **C Suite, Kuyana, Boxing, Lusitania.**

| Field | Type | Notes |
|---|---|---|
| `name` | Char, required | e.g. "C Suite 2026 Events" |
| `code` | Char, sequenced | e.g. `MC-000001` |
| `partner_id` | M2o `res.partner` | The client |
| `start_date` | Date | Contract period start |
| `end_date` | Date | Contract period end |
| `currency_id` | M2o `res.currency` | Master contract currency |
| `value_target` | Monetary | Total committed value if any |
| `value_realised` | Monetary, computed | Sum of completed child jobs |
| `description` | Text | Free notes |
| `state` | Selection | `draft` / `active` / `completed` / `cancelled` |
| `job_ids` | O2m `commercial_job` | Child events |
| `job_count` | Integer, computed | For UI badge |

**Optional**: a Commercial Job can exist without a master.

**Auto-suggestion logic** (Q-S1 resolved → Hybrid): when a partner has 3+ active or completed jobs in any rolling 12-month window without a master contract, system creates a `mail.activity` for MD/OD: *"Suggest creating a Master Contract for [Partner] — N events in last 12 months."* MD/OD confirms or dismisses. No automatic creation without human sign-off.

---

### 3.2 `commercial_job` — Central record

The core of Phase 2. One record per event.

#### Identity

| Field | Type | Notes |
|---|---|---|
| `name` | Char, sequenced | `JOB-000001` |
| `master_contract_id` | M2o `commercial_job_master` | Optional parent |
| `partner_id` | M2o `res.partner`, required | Client |
| `crm_lead_id` | M2o `crm.lead` | Source CRM record |
| `sale_order_id` | M2o `sale.order` | The quote/sale that triggered creation |
| `invoice_ids` | O2m `account.move`, computed | All invoices issued for this job |

#### Two-state primary lifecycle (Robin Q1, Q7)

| Field | Type | Notes |
|---|---|---|
| `state` | Selection | `pending` / `active` / `completed` / `cancelled` / `archived` |

State transitions:

```
[trigger: quote sent] → PENDING
                          │
                          ├─ [trigger: Closed Won, Capacity Gate passes] → ACTIVE
                          ├─ [trigger: Closed Lost] → ARCHIVED (with loss_reason)
                          └─ [trigger: explicit cancel] → CANCELLED
ACTIVE
   │
   ├─ [trigger: event delivered] → COMPLETED
   └─ [trigger: explicit cancel post-Won] → CANCELLED
```

#### Three parallel status tracks (v4.1 §7)

These run in parallel within ACTIVE state. Each tracks one domain.

| Field | Type | Values |
|---|---|---|
| `commercial_status` | Selection | `negotiating` / `won` / `lost` / `on_hold` |
| `finance_status` | Selection | `quoted` / `deposit_pending` / `deposit_received` / `partial_paid` / `fully_paid` / `overdue` |
| `operational_status` | Selection | `planning` / `soft_hold` / `confirmed` / `pre_event` / `live` / `wrapped` / `done` |

Finance status transitions: **hybrid** — system suggests based on payment events, user confirms (Robin Q13).

#### Dates

| Field | Type | Notes |
|---|---|---|
| `event_date` | Date | Required when state=pending or active (Q-S3 resolved). Tentative date OK at pending stage. |
| `event_end_date` | Date | For multi-day events |
| `soft_hold_until` | Date | Auto-set creation+7 days when state=pending; cleared on activation |

#### Venue + Room (Robin Q9)

| Field | Type | Notes |
|---|---|---|
| `venue_id` | M2o `res.partner` | Filtered to `is_venue=True`. Required when state=pending or active (Q-S3 resolved — tentative venue OK at pending). |
| `venue_room_id` | M2o `venue.room` | Specific room within the venue. Optional. |

If `venue_room_id` is set, calendar conflict detection runs at room level. Otherwise at venue level.

#### Equipment summary (high-level, Phase 5 will be deeper)

| Field | Type | Notes |
|---|---|---|
| `equipment_count` | Integer | High-level number, shown on calendar |
| `equipment_summary` | Text | Free text, main items |
| `sub_hire_required` | Boolean | Flag for capacity gate + calendar |
| `logistics_flag` | Boolean | Travel/distance flag |

#### Crew

| Field | Type | Notes |
|---|---|---|
| `crew_assignment_ids` | O2m `commercial_job_crew` | All crew assigned to this job |
| `crew_confirmed_count` | Integer, computed | How many have confirmed |

#### Money

| Field | Type | Notes |
|---|---|---|
| `currency_id` | M2o `res.currency` | Job's primary currency |
| `quoted_value` | Monetary | From sale_order_id |
| `deposit_received` | Monetary, computed | Sum from payments |

#### Loss capture (Robin Q1, Q5)

| Field | Type | Notes |
|---|---|---|
| `loss_reason` | Text | Why was it lost — input when archiving |
| `lost_to_competitor` | Char | Who won it instead, if known |

#### Capacity Gate result (v4.1 §8)

| Field | Type | Notes |
|---|---|---|
| `gate_result` | Selection | `not_run` / `pass` / `warning` / `reject` / `overridden` |
| `gate_run_at` | Datetime | When the gate was last evaluated |
| `gate_override_by` | M2o `res.users` | MD or OD who overrode |
| `gate_override_reason` | Text | Required when overridden |
| `gate_check_log` | Json | The 8 checks and their individual results |

The Gate fires automatically when state moves Pending → Active. Override authority: **either MD or OD individually** (Robin Q3).

---

### 3.3 `commercial_job_crew` — Crew assignment with confirmation (Robin Q9)

| Field | Type | Notes |
|---|---|---|
| `job_id` | M2o `commercial_job`, required | Parent job |
| `user_id` | M2o `res.users`, required | The crew member |
| `role` | Selection | `lead_tech` / `tech` / `runner` / `driver` / `other` |
| `state` | Selection | `pending` / `confirmed` / `declined` |
| `assigned_on` | Datetime | When assignment was made |
| `responded_on` | Datetime | When the crew member responded |
| `decline_reason` | Text | If state=declined |
| `notification_sent` | Boolean | Whether system notified the crew member |

Workflow:

```
[assigned by sales/OD] → state=pending, notification sent
[crew member confirms] → state=confirmed, responded_on set
[crew member declines] → state=declined, decline_reason captured
                         + alert to MD/OD that re-assignment is needed
```

**Notification channel** (Q-S2 resolved → Hybrid): when assigned, system creates an Odoo activity AND sends a WhatsApp message via `neon_channels` to the crew member's stored mobile number. Message contains a confirmation link that opens an Odoo controller to record confirm/decline. Falls back gracefully if WhatsApp fails — Odoo activity remains.

---

### 3.4 `venue.room` — New model for room granularity (Robin Q9)

Robin: *"sometimes venues have multiple rooms so we need specific information."*

| Field | Type | Notes |
|---|---|---|
| `name` | Char, required | e.g. "Sapphire Hall" |
| `venue_id` | M2o `res.partner`, required | Parent venue (filtered `is_venue=True`) |
| `capacity` | Integer | Standing/seated capacity |
| `floor` | Char | Floor name/number |
| `notes` | Text | Free notes (parking, AV, accessibility) |
| `active` | Boolean | For archival without deletion |

`res.partner` extension: add `room_ids` O2m to `venue.room`, plus `is_venue` Boolean for filtering.

---

## 4. Capacity Acceptance Gate — the 8 checks (v4.1 §8)

Each check produces: **pass** / **warning** / **reject**.
Aggregated:
- All pass → gate_result = `pass`
- Any warning, no reject → `warning`
- Any reject → `reject` (override required for state to move to active)

| # | Check | Logic |
|---|---|---|
| 1 | Date availability | Same day, same venue → **warning regardless** (Q-S4 resolved — even with different rooms, logistics implications). Same day, same venue AND same room → **reject**. |
| 2 | Crew availability | Required crew double-booked? |
| 3 | Equipment availability | `equipment_count` vs current commitments (placeholder until Phase 5) |
| 4 | Cash-flow check | Multiple unpaid deposits stacking on adjacent dates? |
| 5 | Sub-hire flag | `sub_hire_required = True` triggers a warning to confirm supplier lined up |
| 6 | Logistics | `logistics_flag = True` triggers warning re: travel/recovery |
| 7 | Strategic value | High-margin/high-prestige clients always pass |
| 8 | Master contract obligation | If part of master, contributes to value_target tracking |

Override authority: MD or OD individually (Robin Q3 — *"either can override, probably OD"*).

---

## 5. Integration points

### 5.1 CRM linkage (Robin Q1, Q7)

| CRM event | Phase 2 effect |
|---|---|
| `crm.lead.stage_id` set to "Proposal Sent" | Create `commercial_job` with state=pending; soft_hold_until = today + 7 |
| `crm.lead.stage_id` set to "Closed Won" | Run Capacity Gate. If pass → state=active. If reject → block until override. |
| `crm.lead.stage_id` set to "Closed Lost" | state=archived; prompt for `loss_reason` |

CRM record retains `commercial_job_id` reverse pointer for traceability.

### 5.2 Phase 1 finance integration

- `commercial_job` references the `sale.order` it came from
- `commercial_job.invoice_ids` computed from sale order's invoices
- Finance status track responds to payment events on those invoices
- **Single currency per invoice** (Robin Q12) — already enforced by Odoo
- **Per-client payment terms** (Robin Q15) — `res.partner.property_payment_term_id` already exists in Odoo, Phase 2 just respects it

### 5.3 ZIMRA touchpoint (Robin Q14)

> *"Alerts and triggers given to finance team however the Zimra connection is separate from Odoo"*

When an invoice is posted on a Commercial Job:
1. Create `mail.activity` of type "ZIMRA fiscalisation"
2. Assigned to finance team user (Munashe)
3. Activity title: "Process ZIMRA fiscalisation for invoice INV-XXX"
4. No automated submission — manual external process

---

## 6. Out of scope (deferred to other phases)

| Item | Phase | Why deferred |
|---|---|---|
| Pre-quote lead enrichment ("never lose them") | CRM extension | Belongs in CRM, not Commercial Job |
| Post-event follow-up sequences (testimonial requests, referral asks, deeper loss analysis) | Phase 4 (Action Centre) | Action Centre is the right home for sequences |
| Detailed equipment booking with serial numbers + availability | Phase 5 (Workshop) | TechOps inventory work |
| Crew skill matrix, certifications | Phase 6 (Training) | Training is its own domain |
| Reporting dashboards (master contract value, win/loss analytics) | Phase 8 (Reporting) | Cross-phase data needed first |

---

## 7. Decisions confirmed (10 May 2026)

All four schema-level questions resolved by Robin. Full answer trail kept here for the record.

### Q-S1. Master Contract — when does a client get one?

**Confirmed: Hybrid — system suggests, MD/OD confirms.**

Trigger: partner has 3+ active or completed jobs in any rolling 12-month window without a master contract → system creates `mail.activity` for MD/OD with suggestion. No automatic creation. Reflected in §3.1.

### Q-S2. Crew confirmation channel

**Confirmed: Hybrid — Odoo + WhatsApp via `neon_channels`.**

On assignment: Odoo activity created AND WhatsApp message sent. WhatsApp message contains a confirmation link to an Odoo controller. Graceful fallback if WhatsApp fails. Reflected in §3.3.

### Q-S3. Pending state — required vs optional?

**Confirmed: partner + sale_order + event_date + venue all required at pending.**

Tentative event_date and venue are acceptable, but must be present. Empty allowed only on initial form before save. Reflected in §3.2.

### Q-S4. Multiple rooms same venue same day?

**Confirmed: warning regardless.**

Even when rooms differ, logistics overlap (parking, loading, sound bleed, shared crew/equipment) makes this worth flagging. Same room same day = hard reject. Reflected in §4 (Check #1).

---

## 8. Build sequence (preview)

Once this schema is approved:

| Milestone | Scope |
|---|---|
| **P2.M1** | Build models above. Migrations. Base form views. |
| **P2.M2** | Three status tracks: state machines, transitions, security |
| **P2.M3** | CRM linkage: stage triggers, automatic Job creation |
| **P2.M4** | Capacity Acceptance Gate: 8 checks, override flow |
| **P2.M5** | Soft Hold lifecycle: 7-day default, expiry, capacity warnings |
| **P2.M6** | Calendar visualisation (replaces FamCal): venue/room conflict, crew double-booking |
| **P2.M7** | Capacity warnings (active monitoring, dashboard) |
| **P2.M8** | Rapid Ops Override (trusted-client fast path) |
| **P2.M9** | Hetzner deploy |

Estimated build time: 2–3 weeks of focused work.

---

## Approval block

| Role | Name | Signature | Date |
|---|---|---|---|
| Managing Director | Munashe Goneso | | |
| Operational Director | Robin Goneso | | |
| Developer | Tatenda | | |

---

*End of P2.M1 Schema Sketch v1.0 — all open questions resolved*
