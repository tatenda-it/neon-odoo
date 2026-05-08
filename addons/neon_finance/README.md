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

| Item | Value |
|------|-------|
| Quote prefix | `QT-` |
| Quote padding | `6` |
| Quote next | `1975` (as of 8 May 2026) |
| Invoice journal regex | `^(?P<prefix1>INV-)(?P<seq>\d{6})$` |
| Invoice anchor name | `INV-000299` (manual on first post) |
| Bill journal | default Odoo naming (revisit P1.M6) |
| Credit notes | revisit P1.M4.5 — refund regex on journals |
