# Equipment Inventory Loader (P-B14)

Loads workshop equipment units from a CSV source file into
`neon.equipment.unit` + `neon.equipment.category` (auto-creating
subcategories + workshop products as needed).

## Invariants

- Standalone — NOT in the manifest's `data` block, NOT imported by
  `addons/neon_jobs/__init__.py`, no cron, no auto-trigger.
- Idempotent — natural key is `asset_tag`; re-running on the same
  CSV produces zero duplicates.
- Non-destructive — never deletes units; updates only the mapped
  fields; `perm_unlink=0` on the unit model is preserved.
- Dry-run by default — `execute=False` is the safe default.

## Procedure (for the real prod load)

The B14 milestone ships the loader + a 12-row sample fixture.
The real prod load is a separate, human-triggered step:

1. The team supplies the real CSV via Drive / email. Place it at
   `/tmp/inventory.csv` on the Hetzner host (or anywhere the
   `odoo` container can read).

2. Copy it into the container if needed:
   ```
   ssh root@188.245.154.84
   docker cp /tmp/inventory.csv neon-odoo-app:/tmp/inventory.csv
   ```

3. Run a DRY-RUN first:
   ```
   docker compose exec -T odoo odoo shell -d neon_crm --no-http <<'EOF'
   exec(open('/mnt/extra-addons/neon_jobs/scripts/load_inventory.py').read())
   r = main('/tmp/inventory.csv', execute=False, env=env)
   print('ok:', r['ok'], 'total:', r['rows_total'])
   print('create:', r['rows_create'], 'update:', r['rows_update'],
         'reject:', r['rows_reject'])
   for entry in r['report']:
       if entry['action'] == 'REJECT':
           print(entry['row'], entry['asset_tag'], entry['reason'])
   EOF
   ```

4. Review the dry-run report. Fix REJECT rows in the CSV.

5. Run a second DRY-RUN to confirm zero rejects.

6. Run for real:
   ```
   docker compose exec -T odoo odoo shell -d neon_crm --no-http <<'EOF'
   exec(open('/mnt/extra-addons/neon_jobs/scripts/load_inventory.py').read())
   r = main('/tmp/inventory.csv', execute=True, env=env)
   print('ok:', r['ok'], 'total:', r['rows_total'])
   print('create:', r['rows_create'], 'update:', r['rows_update'],
         'failed:', r['rows_failed'])
   env.cr.commit()
   EOF
   ```

7. SQL verify:
   ```
   docker compose exec -T db psql -U odoo -d neon_crm -c \
       "SELECT count(*), condition_status FROM neon_equipment_unit
        GROUP BY condition_status;"
   ```

## CSV column schema

| Column | Required | Notes |
|---|---|---|
| `asset_tag` | yes | Idempotency key. Must be UNIQUE across all rows. |
| `category_code` | yes | One of the 9 seeded codes: `sound`, `visual`, `lighting`, `cabling`, `laptops`, `staging`, `dance_floor`, `effects`, `trussing`. |
| `subcategory_code` | optional | If set, auto-created as a child of `category_code` (B1 parent_id chain). |
| `workshop_name` | yes | Display name. Lookup key for `product.template`; auto-created if not found. |
| `tracking_mode` | optional | `serial` / `quantity` / `batch`. Defaults to the category's `default_tracking`. |
| `serial_number` | required when `tracking_mode='serial'` | Unique per product. |
| `batch_code` | required when `tracking_mode='batch'` | |
| `workshop_location` | optional | Free-text (shelf/rack/vehicle). |
| `condition_status` | optional | `good` (default) / `needs_repair` / `written_off` (B1). |
| `purchase_date` | optional | ISO `yyyy-mm-dd`. |
| `purchase_price` | optional | Numeric. |
| `currency` | optional | ISO 3-letter, defaults to USD. |
| `low_stock_threshold` | optional | Integer, written to the unit's CATEGORY (B1 field). |
| `notes` | optional | Free-text. |

## NOTE TO OPS (Lisa)

The `asset_tag-only` idempotency key (B14 D3, gate-1 (a)) means
**every row** in the source CSV needs a non-empty `asset_tag`,
**including bulk quantity-tracked stock** (cabling drums, truss
segments, multi-pack mics). Untagged rows are REJECTED by design.

If tagging every drum of cable or every truss segment isn't
practical, ping Tatenda — the loader can be extended to a three-
tier `asset_tag` → `serial` → `external_ref` fallback as a small
follow-up patch.
