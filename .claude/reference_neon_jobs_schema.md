# neon_jobs schema reference

Discovered + documented across Phase 7b M5 / M6 / M10.

## Models

- `commercial.job` -- parent record (the contracted gig). NOT `neon.event.job`.
- `commercial.event.job` -- per-day event instance under a commercial.job. Has its own state machine.
- `commercial.job.crew` -- the row capturing a crew assignment (NOT a Many2many on commercial.job).

## Key field name corrections (prompts have used wrong names; these are the real ones)

| Model | Correct field | Notes |
|---|---|---|
| `commercial.job` | `partner_id` | NOT `client_id` |
| `commercial.job` | `crew_assignment_ids` | NOT `crew_ids` |
| `commercial.job` | `event_job_ids` | One2many to `commercial.event.job` |
| `commercial.job` | `venue_id` | Required on create |
| `commercial.job` | `currency_id` | Required on create |
| `commercial.event.job` | `commercial_job_id` | M2O back to parent |
| `commercial.event.job` | `state` | Selection (see below) |
| `commercial.event.job` | `event_date`, `event_end_date` | Two date fields, both used by M10 filter |
| `commercial.job.crew` | `job_id` | M2O to `commercial.job` (NOT to event.job) |
| `commercial.job.crew` | `user_id` | M2O to `res.users` |
| `commercial.job.crew` | `role` | Selection: `lead_tech / tech / runner / driver / other` |

## `commercial.event.job.state` -- 12 values

```
draft, planning, prep, ready_for_dispatch,
dispatched, in_progress, strike,
returned, completed, closed,
cancelled, released
```

## M10 filter buckets (consume these for any portal/dashboard split)

- **upcoming**: `draft, planning, prep, ready_for_dispatch`
- **in_progress**: `dispatched, in_progress, strike`
- **completed**: `returned, completed, closed`
- **excluded** (admin-only states, no crew-facing relevance): `cancelled, released`

## Test escape hatches

- `with_context(_allow_state_write=True)` bypasses Phase 7a's transition-only state write guard. Use ONLY in smoke setup; production state changes must walk through `action_move_to_*` methods.
- `commercial.event.job.state` writes through write() are blocked at `neon_jobs/models/commercial_event_job.py:2350` unless the context flag is set.

## Required fields for `commercial.job.create()`

```python
Job.create({
    "name": ...,
    "partner_id": ...,
    "venue_id": ...,
    "currency_id": ...,
    "event_date": ...,
})
```

Reuse an existing job's partner/venue/currency in smoke setup -- `Job.search([], limit=1)` and copy those refs.

## Reading completed jobs for a user (M5 + M6 amendment pattern)

```python
crew_rows = env["commercial.job.crew"].sudo().search([
    ("user_id", "=", user_id),
])
event_jobs = crew_rows.mapped("job_id.event_job_ids")
completed = event_jobs.filtered(
    lambda ej: ej.state == "completed"
    and ej.event_date >= since_date
)
```

## When the Schema Sketch (or build prompt) uses the wrong name

This is the canonical truth. The Schema Sketch was authored before the M5 recon; M6+ corrections live here.
