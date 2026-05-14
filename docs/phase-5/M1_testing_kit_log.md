# P5.M1 — Equipment testing kit

A local-only seed for the Phase 5 workshop register. Populates the
neon_crm database with 46 realistic equipment types spanning all 9
categories and ~330 physical units distributed across the 8-state
lifecycle, so the Workshop kanban / tree / form views have something
diverse to render during local browser smoke.

## Files

| File | Purpose |
|---|---|
| `.claude/p5m1_testing_kit.py` | Idempotent seed |
| `.claude/p5m1_testing_kit_teardown.py` | Symmetric removal |
| `docs/phase-5/M1_testing_kit_log.md` | This document |

The seed and teardown scripts are **never** loaded from the addon
manifest — they run only via manual `docker compose exec`.

## Volume + distribution

| Category | Types | Units | Tracking |
|---|---|---|---|
| Sound | 8 | 24 | mixers serial, mics+speakers quantity |
| Visual | 4 | 12 | all serial |
| Lighting | 6 | 48 | all serial |
| Cabling and Accessories | 10 | 120 | all quantity |
| Laptops | 3 | 6 | all serial |
| Staging | 3 | 18 | all quantity |
| Dance Floor | 2 | 30 | all quantity |
| Effects | 4 | 12 | fazer + CO2 jet serial; bubble + confetti quantity |
| Trussing | 6 | 60 | all quantity |
| **TOTAL** | **46** | **330** | mixed |

Volumes are proportional to the PHP-era workshop reality —
Cabling and Accessories was the largest category there too.

### State distribution (across all 330 units)

The locked 9-state contract on `neon.equipment.unit` (2026-05-14)
is exercised by spreading units across every state so the kanban,
tree, and form decorations all render at least once during local
browser smoke.

| State | Target | Approx units |
|---|---|---|
| active | 65% | ~215 |
| draft | 12% | ~40 |
| reserved | 6% | ~20 |
| checked_out | 6% | ~20 |
| returned | 3% | ~10 |
| maintenance | 3% | ~10 |
| transferred | 2% | ~7 |
| damaged | 2% | ~7 |
| decommissioned | 1% | ~3 |

State assignment is deterministic — index-based, not random — so
re-running on a fresh DB always produces the same distribution.

The model's canonical state codes (locked in
`neon_equipment_unit.py`) supersede the early Schema Sketch draft
which used `enrolled` / `in_repair` / `retired` and omitted
`damaged`. The model's choices are clearer on the workshop floor,
and `transferred` was added 2026-05-14 to cover the Q9 cross-job
transfer workflow.

## Naming convention

Every record carries `[TEST-DELETE]` so the teardown can find it
via `ilike` scan:

- `product.template.name` → `[TEST-DELETE] Robe MegaPointe Beam`
- `product.template.workshop_name` → `ROBE MEGAPOINTE BEAM` (PHP
  convention — ALL CAPS, used as the search anchor)
- Serial-tracked units carry `serial_number = workshop_name + ' #N'`
  (e.g. `ROBE MEGAPOINTE BEAM #1`)
- Quantity-tracked units carry `asset_tag = workshop_name + '-N'`
  with spaces converted to underscores (e.g. `XLR_CABLE_5M-1`)

## Usage

### Apply the seed
```bash
docker compose exec -T odoo odoo shell -d neon_crm \
    < .claude/p5m1_testing_kit.py
```

Idempotent. Re-runs on an already-seeded DB report `types created: 0
(skipped 46)` and exit cleanly.

### Remove the seed
```bash
docker compose exec -T odoo odoo shell -d neon_crm \
    < .claude/p5m1_testing_kit_teardown.py
```

Idempotent. Re-runs on a clean DB report zero counts.

### When real CSVs replace this
1. Run the teardown first (above) so the test records don't collide
   with the real data.
2. Apply the real import via the migration script (B6, parked).
3. Confirm the test records are absent — search
   `product.template` for `[TEST-DELETE]` and expect zero rows.

## Production caveat

**Never run the seed on the Hetzner production database.**
Production receives equipment data from real CSV exports of the PHP
workshop system, applied during the P5.M11 cutover. The
`[TEST-DELETE]` marker keeps any accidental run trivially recoverable
via the teardown, but the safest stance is not to run it at all on
`neon_crm` at `188.245.154.84`.
