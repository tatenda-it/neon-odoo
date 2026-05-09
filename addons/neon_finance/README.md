# Neon Finance

Zimbabwe-specific finance configuration for Neon Events Elements:
ZWG currency ownership, ZIMRA VAT tax records (15.5% standard,
0% zero-rated), tax groups, and supporting structure for the
Phase 1 Finance build.

This module pairs with `neon_crm_extensions` but is functionally
independent — it depends only on the upstream `account` module.

## Invoice numbering anchor

The customer invoice journal (`id=1`, `code=INV`) is configured
with `sequence_override_regex` to produce names of the form
`INV-NNNNNN` (six-digit zero-padded sequence after `INV-`).

The first invoice posted in this database must have its `name`
manually set to **`INV-000299`** to continue the numbering
sequence from Zoho Books (Zoho is currently at next=000299
as of 8 May 2026).

Subsequent invoices will auto-increment from there.

To set the name on the first invoice:

1. Create a draft customer invoice
2. Before posting, edit the **Number** field directly
3. Set name to `INV-000299`
4. Post the invoice
5. All subsequent invoices will derive `INV-000300`,
   `INV-000301`, etc.

The sale order (quote) sequence is configured via
`ir_sequence` `id=1` with prefix `QT-`, padding `6`, starting
at `1975` — no anchor needed.

## Operational data note

Sequences and journal regex are operational data (mutable by
Munashe via the UI without module upgrade overhead). They are
applied via direct SQL during P1.M2.C and are NOT shipped in
this module's data files. This README is the authoritative
record of the configured values.

### Gotcha: backing PostgreSQL sequence

`ir.sequence` records with `implementation='standard'` are backed
by a real PostgreSQL `SEQUENCE` object named `ir_sequence_NNN`
(NNN = zero-padded id). Updating the `number_next` column on
`ir_sequence` alone does **not** change the next value — the
backing PG sequence drives `nextval()`. To realign, also run:

```sql
SELECT setval('ir_sequence_001', <next_value> - 1, true);
```

For id=1 / quote sequence, this was set to `setval(..., 1974, true)`
during P1.M2.C so the first `nextval()` returns 1975.

## Hetzner deployment requirement

When deploying this module to a fresh Odoo instance, the
company's fiscal country MUST be set to Zimbabwe before
or immediately after install:

```sql
UPDATE res_company
SET account_fiscal_country_id = (
  SELECT id FROM res_country WHERE code = 'ZW')
WHERE id = 1;
```

Without this, the VAT 15.5% and VAT 0% Zero-Rated tax
records (which are country-scoped to ZW) will not appear
in tax dropdowns on invoice line items, even though they
exist in the database.

## Invoice numbering implementation

The customer invoice journal (id=1) uses two layered
mechanisms to produce INV-NNNNNN format:

1. Journal code is set to `INV-` (with trailing dash).
   This becomes the prefix on auto-derived names.

2. `sequence_override_regex` matches the format INV-NNNNNN
   with optional suffix:

   ```
   ^(?P<prefix1>INV-)(?P<seq>\d{6})(?P<suffix>.*)$
   ```

   The suffix capture group exists specifically to allow
   draft invoices (which use placeholder names like
   `INV-000299/` or just `/`) to pass regex validation.

The first invoice posted in this database was manually
named `INV-000299` to anchor continuity from Zoho Books.
All subsequent invoices auto-derive from there.

## Company logo

The Neon Events Elements logo lives at
`static/src/img/neon_logo.png` (800×228, RGBA PNG) and is wired
to `res.company.logo` via `data/res_company_logo.xml`, which in
turn flows through to `res_partner.image_1920` (attachment-backed)
on the company partner record.

### Fresh-install path (Hetzner)

`odoo -i neon_finance -d <db>` loads the data file in init mode;
`base.main_company`'s `noupdate=true` flag is bypassed during
init, and the logo is set automatically. No manual step needed.

### Existing-install path (already-installed local DBs)

`odoo -u neon_finance` runs in update mode and respects the
`noupdate=true` flag on `base.main_company` — the data file's
logo write is silently skipped. To apply or refresh the logo
on an existing install, run an imperative ORM write:

```python
# docker exec ... odoo shell -d <db> --no-http
import base64
with open('/mnt/extra-addons/neon_finance/static/src/img/neon_logo.png', 'rb') as f:
    logo_b64 = base64.b64encode(f.read())
env['res.company'].browse(1).write({'logo': logo_b64})
env.cr.commit()
```

This was used to set the logo on the local development DB on
2026-05-08 (file size 74,960 bytes; auto-derived thumbnails
filled image_1024 / 512 / 256 / 128 on the partner).

| Item | Value |
|------|-------|
| Quote prefix | `QT-` |
| Quote padding | `6` |
| Quote next | `1975` (as of 8 May 2026) |
| Invoice journal regex | `^(?P<prefix1>INV-)(?P<seq>\d{6})$` |
| Invoice anchor name | `INV-000299` (manual on first post) |
| Bill journal | default Odoo naming (revisit P1.M6) |
| Credit notes | revisit P1.M4.5 — refund regex on journals |

## VAT Rate History

P1.M2.B initially configured Zimbabwe VAT at 15% per the
pre-2026 ZIMRA rate. Effective 1 January 2026 the standard
VAT rate increased to 15.5% (Zimbabwe Finance Act No. 7 of
2025). The active sale/purchase taxes in this module now
reflect the current 15.5% rate; the original 15% records
(auto-seeded by Odoo's account chart-of-accounts) are
archived and preserved for audit.

Reference: https://www.zimra.co.zw — Public Notice 07 of
2026.

## Company contact information

Per Neon Events Elements Pvt Ltd standard:
- Website: `https://neonhiring.com` (.com — primary domain)
- Team emails: `@neonhiring.co.zw` (.co.zw — operational)
- Company general email: `admin@neonhiring.co.zw`
- Company main phone: `+263775672250`

This split is deliberate. Do NOT consolidate to a single
domain without explicit approval from Robin.

### report_footer drift

`res.company.report_footer` is **independent** of `email` /
`phone` / `website`. The Document Layout wizard writes a
snapshot HTML string to `report_footer`, and that snapshot
does NOT auto-update when the scalar contact fields change.
Anyone changing `email` / `phone` / `website` on `res.company`
must also update `report_footer` (either via this module's
data file or manually via Settings → General Settings →
Configure Document Layout). Otherwise PDFs render stale
contact info even after the underlying fields are fixed.

VAT / TIN / BPN are intentionally excluded from the footer —
they are already prominent in the ZIMRA strip on the document
body (P1.M3.C). Duplicating them in the footer adds clutter.

### Existing-install fix-up: contact fields + footer

`res.company` `email`, `phone`, `website`, and `report_footer`
are all written via `data/res_company_profile.xml`. Same
`base.main_company` `noupdate=true` gotcha — `odoo -u neon_finance`
will silently skip the writes on existing installs. Apply
imperatively:

```python
# docker exec ... odoo shell -d <db> --no-http
env['res.company'].browse(1).write({
    'email': 'admin@neonhiring.co.zw',
    'phone': '+263775672250',
    'website': 'https://neonhiring.com',
    'report_footer': '<p>admin@neonhiring.co.zw • '
                     'https://neonhiring.com • '
                     '+263775672250</p>',
})
env.cr.commit()
```

### Existing-install fix-up: re-point company default taxes

`res_company.account_sale_tax_id` / `account_purchase_tax_id`
are written via `data/res_company_profile.xml`. Same
`base.main_company` `noupdate=true` gotcha as the logo and
legal name — `odoo -u neon_finance` will silently skip the
write on existing installs. Apply imperatively via shell:

```python
# docker exec ... odoo shell -d <db> --no-http
env['res.company'].browse(1).write({
    'account_sale_tax_id': env.ref('neon_finance.tax_vat_15_5_sale').id,
    'account_purchase_tax_id': env.ref('neon_finance.tax_vat_15_5_purchase').id,
})
env.cr.commit()
```
