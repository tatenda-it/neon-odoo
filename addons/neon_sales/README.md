# Neon Sales

Sales-cycle customisations for Neon Events Elements.

## Scope (current)

- **Covering Letter** — optional introductory paragraph on
  quotes. Salespeople toggle on per quote when a personalised
  preamble is wanted; toggle off for utility quotes.

## Scope (planned)

- P1.M3.C — Branded QWeb quote template (logo, ZIMRA TIN/BPN,
  banking section with currency-matching highlight, T&Cs
  placeholder)
- P1.M3.D — Discount column enablement
- P1.M5 — Quote-to-invoice workflow polish

## Dependencies

- `sale_management` (Odoo standard)
- `neon_finance` (Neon company config + bank accounts)

## Module fields added

| Model | Field | Type | Purpose |
|---|---|---|---|
| sale.order | x_covering_letter_active | Boolean | Toggle visibility of covering letter on quote PDF |
| sale.order | x_covering_letter_text | Html | Rich text content for the covering letter |

## Daily ZWG Rate Update (Operational)

The ZWG pricelist auto-converts USD list prices to ZWG
using `res.currency.rate`. The rate must be updated daily
for accurate quoting:

1. Visit the Reserve Bank of Zimbabwe daily exchange rate
   page (https://www.rbz.co.zw)
2. Note the official ZiG/USD interbank rate for today
3. In Odoo: Accounting → Configuration → Currencies → ZWG
   → Rates tab → Add a new rate row with today's date and
   the noted rate
4. Verify by opening any draft quote, switching to the ZWG
   pricelist, and confirming the displayed prices reflect
   today's conversion

This is a 30-second daily task. Future enhancement:
automated daily import from RBZ (deferred).
