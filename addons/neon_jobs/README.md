# Neon Jobs — Phase 2 — P2.M1

**Status:** P2.M1 Schema (models + base form views).
**Version:** 17.0.1.0.0
**Depends on:** base, mail, sale, crm, contacts.

## Scope

This module implements the central operational record for Neon Events Elements'
event production work — the **Commercial Job** — together with its supporting
models per the v4.1 master roadmap and the Phase 2 Open Questions answers from
Robin (10 May 2026).

### Models in this milestone

| Model | Purpose |
|-------|---------|
| `commercial.job.master` | Optional parent for multi-event corporate contracts (C Suite, Kuyana, Boxing, Lusitania). |
| `commercial.job` | Central event record. Two-state lifecycle (pending → active), three parallel status tracks. |
| `commercial.job.crew` | Crew assignment with confirm/decline state. |
| `venue.room` | Rooms within a venue for calendar conflict detection. |
| `res.partner` (extended) | Adds `is_venue` flag and `room_ids`. |
| `crm.lead` (extended) | Reverse pointer to commercial jobs + smart button. |
| `sale.order` (extended) | Reverse pointer to commercial jobs + smart button. |

## What this milestone does NOT do

These come in subsequent Phase 2 milestones — the hooks are present but the
logic is intentionally not wired:

- **P2.M2** — State machine transitions and security groups for the three status tracks.
- **P2.M3** — CRM stage triggers (Proposal Sent → create Pending Job; Closed Won → Active; Closed Lost → Archived).
- **P2.M4** — Capacity Acceptance Gate: 8-check matrix and override flow.
- **P2.M5** — Soft Hold lifecycle: 7-day default already wired in `create()`, but expiry processing and capacity warnings come here.
- **P2.M6** — Calendar visualisation (replaces FamCal): venue/room conflict, crew double-booking.
- **P2.M7** — Capacity warnings (active monitoring, dashboard).
- **P2.M8** — Rapid Ops Override (trusted-client fast path).
- **P2.M9** — Hetzner production deploy.

## Install

Drop into `addons/neon_jobs/` and:

```bash
docker compose exec -T odoo odoo -i neon_jobs -d neon_crm --stop-after-init
```

After install, restart Odoo so HTTP workers pick up the new menus:

```bash
docker compose up -d --force-recreate odoo
```

## Smoke test

After install, verify:

1. **Menu structure**: top-level "Operations" menu visible with sub-items
   Commercial Jobs / Master Contracts / Crew Assignments / Configuration → Venues / Venue Rooms.
2. **Sequences**: `JOB-` and `MC-` prefixes configured. First Commercial Job → JOB-000001. First Master Contract → MC-00001.
3. **Create a Master Contract** end-to-end: name, partner, period, target value.
4. **Create a Commercial Job** for that partner: confirm `master_contract_id` auto-suggests when partner has an active master.
5. **Mark a partner as `is_venue`** and add a Venue Room.
6. **Verify form constraints** (event_date and venue required at pending; loss_reason required at archived).
7. **Verify smart buttons**: from a CRM lead and from a sale order, the Commercial Jobs smart button shows and links correctly.

## Known limitations of P2.M1

- `state` is a plain Selection field. State transitions happen via direct
  edit. Buttons and workflow guards are P2.M2 work.
- `gate_result` defaults to `not_run` and stays there. The 8-check evaluator
  is P2.M4.
- `commercial_job_crew.notification_sent` is currently always `False`. The
  Odoo + WhatsApp dispatch logic is P2.M2.
- Master Contract auto-suggestion (3+ events in 12 months) is documented in
  the schema but the scheduled action is P2.M3.

## Calendar (P2.M6)

Two calendar views replace the prior FamCal workflow. Both live under
**Operations** and share the same form/popover.

| Menu | Domain | Default filters |
|------|--------|-----------------|
| Calendar — Live Pipeline | `state in (pending, active)` | Pending + Active |
| Calendar — All Events | no filter | none |

### Tile colour (operational_status)

The tile background is the Odoo palette index of `operational_status_color`:

| operational_status | Colour index |
|---|---|
| planning | 5 (light blue) |
| soft_hold | 2 (orange) |
| confirmed | 10 (light green) |
| pre_event | 3 (yellow) |
| live | 11 (purple) |
| wrapped | 4 (teal) |
| done | 7 (grey) |

### Tile label prefixes (gate_result)

The tile title is `calendar_display_name` — the client partner name with a
prefix derived from the Capacity Gate result:

| gate_result | Prefix |
|---|---|
| reject | ⚠ |
| warning | ▷ |
| overridden | ✓ |
| pass / not_run | (none) |

### Popover fields

Clicking a tile opens the standard Odoo popover with venue, room,
operational status, gate result, crew totals, equipment count, sub-hire,
logistics, and soft hold state. The "Open" button links to the full form.
Quick-create is disabled (required fields can't be filled in a popover).

## Author

Neon Events Elements
https://neonhiring.com

## Licence

LGPL-3
