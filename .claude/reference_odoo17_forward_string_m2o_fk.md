# Forward-string Many2one FK creation across modules

Established in Phase 7c M4 (May 23 2026). When an upstream
module defines a `Many2one("downstream.model", ...)` and
gets installed BEFORE the downstream module is loaded into
the registry, Odoo creates the column but silently skips
the SQL-level foreign-key constraint. `ondelete="set null"`
and `ondelete="cascade"` are no-ops in that state.

## The symptom

Phase 7c M4 added `external_booking_id` (M2O to
`neon.external.training.booking`) on
`neon.training.certification`. The atomic two-commit pattern
was followed:

1. Commit B1 (`751803c`) — Phase 7a extension lands: cert
   model + manifest + migration. Upgrade `-u neon_training`
   alone.
2. Commit B2 (`e49781d`) — Phase 7c extension lands: booking
   model write + view + smoke.

On Odoo's upgrade of `neon_training` in step 1, the booking
model wasn't yet in the registry (loaded only when
`neon_external_training` upgrades). Odoo logged a warning:

```
WARNING Field neon.training.certification.external_booking_id
with unknown comodel_name 'neon.external.training.booking'
```

The column was created on `neon_training_certification`,
but the FK constraint was not. T7c407 (delete-cascade test)
caught it: deleting a booking did NOT null the cert's
`external_booking_id`.

## Why `candidate_id` worked but `external_booking_id` did
not

Phase 7b's `neon.training.certification.candidate_id` uses
the same forward-string pattern targeting
`neon.onboarding.candidate`. It DID get the FK constraint
correctly. Difference: in Phase 7b's deploy sequence, both
modules upgraded in the same pass, so when
`neon_training`'s table init ran, `neon_onboarding` was
already registered. Phase 7c's atomic two-commit deploy
sequence broke that.

The forward-string FK creation logic depends on:
> when the table is being initialised, the target comodel is
> registered.

Standalone upstream upgrades that precede the downstream
load violate that assumption.

## The fix — idempotent FK fixup migration

Add a `post-migrate.py` on the DEPENDENT module (Phase 7c
side, not Phase 7a upstream) that creates the FK explicitly
+ idempotently:

```python
# addons/neon_external_training/migrations/17.0.1.3.1/post-migrate.py
import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT 1
          FROM pg_constraint
         WHERE conrelid = 'neon_training_certification'::regclass
           AND contype = 'f'
           AND conname =
               'neon_training_certification_external_booking_id_fkey'
    """)
    if cr.fetchone():
        _logger.info("FK already present; no-op.")
        return
    cr.execute("""
        ALTER TABLE neon_training_certification
          ADD CONSTRAINT
            neon_training_certification_external_booking_id_fkey
          FOREIGN KEY (external_booking_id)
          REFERENCES neon_external_training_booking(id)
          ON DELETE SET NULL
    """)
    _logger.info("FK added with ON DELETE SET NULL.")
```

The migration:

1. Checks `pg_constraint` for the named FK. Skip if
   already exists (idempotent — fresh installs that load
   both modules in the same pass have the FK and this
   migration is a no-op).
2. Otherwise issues `ALTER TABLE ... ADD CONSTRAINT`. The
   constraint name must match Odoo's auto-generated
   convention (`<table>_<column>_fkey`) so subsequent Odoo
   inspections recognize it.

## Where to put it

**On the DEPENDENT module**, not the upstream. The Phase 7c
module owns the model the FK targets, so the migration
lives on the Phase 7c side. Phase 7a's M4 migration stays
log-only.

Rationale: if Phase 7a is installed standalone (without
Phase 7c), there is no `neon_external_training_booking`
table for the FK to reference. The FK creation MUST wait
until Phase 7c is installed. Putting it on the dependent
side guarantees that ordering.

## Phase 11 candidate — `register_forward_fk` helper

Every cross-module Many2one that lands when the dependent
module isn't yet registered needs the same SQL fixup.
Centralize in `neon_core` (or a `phase11_utils` module) so
future sub-phases can call:

```python
from odoo.addons.neon_core.tools.fk_helpers import (
    register_forward_fk)


def migrate(cr, version):
    register_forward_fk(
        cr,
        table="neon_training_certification",
        column="external_booking_id",
        ref_table="neon_external_training_booking",
        on_delete="SET NULL",
    )
```

Avoids the per-field boilerplate above and standardizes
the constraint-naming convention.

## How to detect the issue

Quick check on any cross-module Many2one with `ondelete`:

```sql
SELECT conname, pg_get_constraintdef(oid)
  FROM pg_constraint
 WHERE conrelid = '<table>'::regclass
   AND contype = 'f'
   AND conname LIKE '%<field>%';
```

Empty result on a Many2one with declared `ondelete=` is the
smoking gun. The smoke test that catches this in Phase 7c
M4 (T7c407) is a good template — delete the parent record
and assert the FK back-pointer on a known child was nulled.

## Order-of-install matters

If both upstream and dependent modules are being installed
in the SAME `-i` pass (fresh install of a new env), the FK
creation works correctly because Odoo loads both modules
into the registry before the table-init phase. The fixup
migration is still safe to run (it no-ops on existing FKs),
so ship it unconditionally — it's the live-upgrade case
that needs it.
