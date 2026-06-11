# WA-12 — Pricing capture sheet (Robin + Munashe)

> ⛔ **HOLD — granularity under review (GATE-0 finding 2026-06-11).** The quote
> engine prices **per equipment-CATEGORY** (`neon.finance.pricing.rule` =
> `base_rate` per `neon.equipment.category` × currency — only **~9 categories**),
> NOT per-product. The $1 product `list_price` placeholders do **not** drive
> quote pricing. So **Sections A/B below are likely the WRONG shape** (276
> per-product rows). **Do not fill yet** — pending Tatenda/Robin's decision on
> pricing granularity (per-category vs per-product vs hybrid). If per-category,
> this sheet collapses to ~9 category base-rates × {USD, ZiG} + a dimensional
> section, which is far simpler. See the WA-12 memory / the GATE-0 report.

**Purpose:** capture the REAL day-rates that unlock WA-12 (and every quote in
Odoo). Today **275/276 products carry a $1 placeholder** — honest, but unusable
for quoting. Fill the rates here the same way the R3 governance sheet was
signed; the load then runs under the **Phase-11 data-load ritual with count
verification** (§4d). **Prices are commercial policy — this sheet is yours to
fill; nothing is invented on your behalf.**

> How rates are used: a quote line prices as
> **`quantity × DAY RATE × duration_days × bracket_multiplier`**. So the **DAY
> RATE** below is the per-day hire rate; multi-day events multiply automatically.

---

## Section A — Product day-rates (all 276 products)

Populate the rows from prod (recipe below), then fill the **two bold columns**.

| External ID | Product | Category | Current (placeholder) | **DAY RATE (fill)** | **CURRENCY (fill: USD / ZiG)** | Notes |
|---|---|---|---|---|---|---|
| _(populated from the prod export — 276 rows)_ | | | $1.00 | | | |

**To populate the 276 rows** — run on prod (assistant or team; one command),
paste the CSV output into Section A:

```bash
# on the prod box, in /opt/neon-odoo
docker compose exec -T odoo odoo shell -d neon_crm --no-http <<'PY'
import csv, io
PT = env['product.template'].sudo()
prods = PT.search([('sale_ok','=',True)], order='categ_id, name')
buf = io.StringIO(); w = csv.writer(buf)
w.writerow(['external_id','product','category','current_price','DAY_RATE','CURRENCY','notes'])
xmlids = prods.get_external_id()
for p in prods:
    w.writerow([xmlids.get(p.id,''), p.name, p.categ_id.display_name or '',
                p.list_price, '', '', ''])
print('=== PRICING-CSV (paste into Section A) ===')
print(buf.getvalue())
print('=== %d products ===' % len(prods))
PY
```

Confirm the count == **276** (the count-verification gate). If it differs,
reconcile before the load (some products may be `sale_ok=False` / archived).

---

## Section B — Dimensional rules (so "3×2m" resolves to a price)

Some products price by **size**, not a flat day-rate (the parse lane must turn a
dimension like `3×2m` into a number). For each dimensional product, fill **one**
rate basis:

| Product | Basis (m² OR panel) | **Per-m² DAY RATE** | **Per-panel DAY RATE** | Panel size (m, if per-panel) | CURRENCY | Notes |
|---|---|---|---|---|---|---|
| LED wall (e.g. Absen A3) | per-m² _or_ per-panel | | | e.g. 0.5×0.5 | | "3×2m" → 6 m² × per-m², OR panels = (3/0.5)×(2/0.5) × per-panel |
| LED dance floor | per-m² | | | | | |
| _(add any other size-priced product)_ | | | | | | |

> The build reads these as per-product dimensional fields (Gate-1 open
> decision 2). "3×2m" = 3 m wide × 2 m high = **6 m²**; per-panel needs the
> panel size to compute the panel count.

---

## Section C — Labour / service line rates (when a quote includes crew)

Quote lines support `line_type` = equipment / **labour** / **service**. If WA-12
quotes are to include crew/labour, fill the day-rates per role:

| Role / service | **DAY RATE (fill)** | **CURRENCY** | Notes |
|---|---|---|---|
| Crew chief | | | per person per day |
| Lead technician | | | |
| General crew | | | |
| Rigging / specialist | | | |
| Delivery / transport | | | flat or per-trip — note which |
| _(add roles as needed)_ | | | |

Leave blank if WA-12 v1 quotes equipment-only — confirm with the team.

---

## Section D — Currency + compliance (house rule)

- **CURRENCY column is mandatory** per the house rule — every rate is **USD**
  or **ZiG (Zimbabwe Gold)**; never ambiguous. If a product is quoted in both,
  add a second row.
- ZiG rates: the dashboard's manual ZiG↔USD rate
  (`neon_dashboard.zig_usd_rate_manual`) governs any conversion; rate unset →
  ZiG excluded (don't guess a rate).
- **VAT:** Zimbabwe VAT is **15%**; quotes/invoices must carry **ZIMRA
  registration**. The quote/invoice templates handle VAT — the DAY RATE you
  enter is the **ex-VAT** hire rate unless you note otherwise.
- Payment terms default to **7 days** unless agreed (set per-quote in Odoo).

---

## Load procedure (after the sheet is filled)

1. Reconcile the Section-A row count to the prod product count (expect 276).
2. Dry-run the rate write on a staging copy; print the changed-row list.
3. ⛔ Human gate on the row list (it modifies live `list_price` / the rate
   fields — a money-adjacent write).
4. Apply under the data-load ritual; re-verify counts + spot-check rates.
5. Only then does WA-12 quote against real prices (never the $1 placeholders).
