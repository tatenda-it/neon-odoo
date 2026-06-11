# Phase 11 — Cutover & Training Scope

**Nature (from the code audit):** Phase 11 is an **operational go-live**, not
a new feature milestone. The platform is built and live on prod (Core ERP,
Finance, Workshop/equipment, LMS, Dashboards, HR through R3b, the B11
WhatsApp arm). Phase 11 = load real data, train the team, and switch the
business off the old tools (Zoho CRM / Zoho Books / PHP) onto Odoo.

> **Technical prerequisites: NONE outstanding** (per the 2026-06-11 audit) —
> no missing module, no schema gap. The work is data + people + sequencing.

---

## 1. Cutover sequence

### 1a. Environment & backups (do FIRST)
- [ ] Confirm prod (Hetzner, crm.neonhiring.com, DB `neon_crm`) is the single
      source; reconcile `main` ← `feat/wa6-equipment-face` so the deployed
      code == `main` (see the reconciliation plan — separate gate).
- [ ] Full DB backup + a tested restore BEFORE any bulk load.
- [ ] Backup cadence for go-live week (daily dump off-box).
- [ ] Freeze window: agree a date/time after which new business data goes
      into Odoo only (no more new records in Zoho).

### 1b. Data-load mapping (Zoho → Odoo)
| Source | Odoo target | Notes |
|---|---|---|
| Zoho CRM — contacts/accounts | `res.partner` | Company + contact; phone in E.164 so WA-9 matching works. |
| Zoho CRM — leads/deals | `crm.lead` | Map Zoho stages → Neon CRM stages (New/Qualified/Proposal Sent/Negotiation/Closed Won/Lost). |
| Zoho Books — customers | `res.partner` | Dedup against the CRM contact load (one partner per entity). |
| Zoho Books — products/services | `product.template` | Workshop/equipment items already exist; map the rest. |
| Zoho Books — open invoices/quotes | `account.move` / quote model | Decide: migrate open balances only, or full history. Include ZIMRA reg + 15% VAT. |
| Zoho Books — chart of accounts / opening balances | accounting | Finance-led; reconcile to a cut-off date. |
- [ ] Decide migration depth per stream (open-only vs full history).
- [ ] Phone numbers normalised to E.164 on partner load (WA-9 + WhatsApp).
- [ ] A dry-run load into a staging copy first; reconcile counts before prod.

### 1b-2. Data-load mapping (FamCal → Odoo)

**Source: FamCal portal calendar "Team Neon", 23 members.** This is the
operational events calendar — the third legacy source alongside Zoho CRM and
Zoho Books. Verified (read-only, live) stored fields per event: title (client
names embedded, freeform), start/end epoch + all-day + multi-day flags, venue
`evWhere` (~70% coverage), notes `dataContent` (~88% coverage), participants/
notify-by-email, alarms, rare RRULEs, authorship + update timestamps.

| FamCal source | Odoo target | Notes |
|---|---|---|
| Future events | `commercial.job` + event job | Provisional bookings load as **draft** (not confirmed). |
| Past events | completed-job history import | **Recommend importing** — feeds the WA-11 per-client satisfaction timelines. |
| Event titles (client names) | `res.partner` | Via a **human-reviewed** client-name mapping pass, **joined with the Zoho contact import** (one partner per entity — dedup against §1b). |
| The 23-member roster (names + emails, incl. ~16 freelance crew not yet in Odoo) | `hr.employee` freelancer records + future WA crew mapping | **Fills the crew-pool gap** the event-wage grades need (see §4). |
| Venue `evWhere` | event job venue / `venue` model | ~70% populated; backfill the rest at review. |
| Notes `dataContent` | event job notes | ~88% populated. |
| Tasks (e.g. PRAZ renewal) | `mail.activity` | Hand-migrate as activities. |
| Reminders / colours / unused calendar types | — | **Drop.** |

**Extraction method:** the FamCal API is signed (direct replay fails) → use an
**in-page month-walk capture** → JSON export → transform → the Phase-11 load
ritual with **count verification** (§4d pattern: reconcile counts after each
layer).

**⛔ OPEN DECISIONS for Robin:**
1. **History depth** — recommend **full** (richer WA-11 timelines).
2. **Crew-pool import timing** — recommend **with the HR load** (§4): the ~16
   freelance crew become `hr.employee` freelancer records so the event-wage
   grades + future WA crew mapping have a populated pool.
3. **FamCal retirement** — **read-only archive at cutover** (mirrors the Zoho
   freeze in §1a/§3).

> Cross-refs: the client-name → `res.partner` pass must run jointly with §1b's
> Zoho contact load (shared dedup). The freelancer roster feeds §4's HR load
> (crew pool). Past-event history is what makes the WA-11 insights layer
> non-empty on day one.

### 1b-3. Data-load mapping (Workshop PHP → Odoo)

**Source: the legacy PHP inventory/jobs system at `neonhiring.com/workshop`.**
The third legacy source (alongside Zoho and FamCal) — and the only one with a
real **attendance + reconciliation** record. Verified (read-only, live): **55
jobs** (17 Feb – 8 Jun 2026; **~50 real** after excluding test/QA), **14 user
accounts**. Per job: code, client/title, venue, dates, status (Draft / Scheduled
/ InProgress / Completed), a `Crew:` roster, **per-equipment-line technician
attribution** with checkout/return timestamps, and reconciliation stats (units
out / returned / damaged, % accounted).

| Workshop source | Odoo target | Notes |
|---|---|---|
| Jobs | `commercial.job` + event jobs | Completed → history; Scheduled → live pipeline. **Dedupe against FamCal events** (§1b-2): Reghart / Peech / Prime Agro / Csuite / Oasis appear in BOTH sources. |
| `Crew:` rosters | `commercial.job.crew` rows on the historical jobs | This is the **ACTUAL attendance record** — who really worked each job. |
| Per-person tallies | evidence sheet for **Kudzai's wage-grade assignments** | mutasa 20, tadiwa 14, stanley 11, adam 8, trymore 7, kelvin 3, others ≤2. **These are FLOORS** — a shared `"tech"` account masks **51/55** jobs (real counts are higher). |
| Workspace usernames | identity join table: **workshop username ↔ FamCal email ↔ `hr.employee`** | The join that resolves crew identity across all three sources. Workshop adds **"mutasa"** — absent from FamCal's 23-member roster. |
| Equipment-line history | — | **DO NOT migrate granularly** — Odoo's movement/reservation history starts fresh at cutover. Workshop becomes a **read-only archive** (same as FamCal/Zoho). |

**⚠️ Flag for the team — the shared `"tech"` account anonymises attendance.**
Because 51/55 jobs were logged under one shared login, the per-person tallies
under-count everyone. At cutover **every crew member gets their own identity**
(already the Odoo + WhatsApp design — bot.user → res.users, actor-audited
movements), so this blind spot ends: from go-live, attendance and equipment
attribution are per-person and honest.

> Cross-refs: the **three-source identity join** (Zoho contacts §1b + FamCal
> roster §1b-2 + Workshop usernames here) resolves to one `res.partner` per
> client and one `hr.employee` per crew member — run the dedup pass ONCE across
> all three. Workshop attendance + FamCal freelancer roster together populate
> §4's crew pool with an evidence trail for the wage grades. All three legacy
> systems retire to read-only archive at cutover (§1a/§3).

### 1c. HR data load — **concrete order + templates** (see §4)

---

## 2. Training plan
- [ ] **Order of modules** (suggest): (1) CRM + client lane (Munashe/sales),
      (2) Commercial + event jobs + equipment/Workshop (Lisa/OD + crew leads),
      (3) Finance/quotes/invoices + ZIMRA/VAT (Tatenda), (4) HR/leave/payroll
      (Robin + Tatenda), (5) the WhatsApp surfaces (already in daily use).
- [ ] **Who/when:** per-role 1–2 hr sessions; record short SOP clips into the
      LMS (neon_lms is live) so they're reusable for new staff.
- [ ] **Sandbox:** trainees practise on a staging copy, not prod.
- [ ] **Support runbook:** who fields "how do I…" in week 1; where issues log
      (Action Centre / a shared list).

## 3. Go-live checklist
- [ ] Backups verified (1a).
- [ ] Data loads reconciled (counts + spot-checks) (1b, 4).
- [ ] R3 governance flags signed off (see `R3_Governance_Gates.md`) — required
      before the first real payroll/leave run.
- [ ] PAYE tables + NSSA rate/ceiling current (⚠️ VERIFY ZIMRA/NSSA).
- [ ] User accounts + roles verified (ACL); the Phase-7a base.group_user
      implied-id cleanup confirmed on prod.
- [ ] First real payroll run on a staging copy → reconcile → then prod.
- [ ] Zoho set read-only / archived; team briefed on the freeze.
- [ ] Day-1 support cover assigned.

## 4. HR DATA LOAD — load order, templates, sensitivity

**Why this is its own section:** prod currently has **1 hr.employee and zero
contracts/leave/payslips**. The HR dashboard lens is mechanically correct but
shows little because the data isn't there yet. Load in dependency order;
each layer needs the one above it.

### 4a. Load order (strict — each depends on the prior)
1. **Employees** — the people (master record).
2. **Contracts / wage grades** — employment terms + pay basis (needs the
   employee).
3. **Leave allocations** — opening leave balances (needs employee + the
   accrual policy from `R3_Governance_Gates.md` §5).
4. **Competencies / licences** — skills + driver-licence classes that gate
   crew assignment (needs the employee).

### 4b. Sensitivity — who enters what
- **Non-sensitive (loadable from existing data / a clerk):** name, linked
  Odoo user, work email, work phone, job title, department.
- **SENSITIVE — entered DIRECTLY by Robin/Tatenda, never in a shared CSV:**
  salary / wage rate, bank details, national ID / passport, date of birth,
  next-of-kin, contract value, loan figures. These go straight into the form
  by an authorised user; they are **out of scope** for any bulk template.

### 4c. CSV import templates (non-sensitive columns only)

**(1) employees.csv** → `hr.employee`
```
name,work_email,work_phone,job_title,department,related_user_login
Tatenda Ngairongwe,tatenda@neonhiring.co.zw,,Finance,Finance,tatenda@neonhiring.co.zw
Munashe,munashe@neonhiring.co.zw,,Sales / Client Relations,Sales,munashe@neonhiring.co.zw
...
```
(`related_user_login` maps the employee to their `res.users`. Salary/ID/bank
columns are deliberately ABSENT — entered on the form.)

**(2) contracts.csv** → contract / wage grade  *(SENSITIVE — Robin/Tatenda enter on the form; template shown only for the non-sensitive frame)*
```
employee,wage_grade,start_date,pay_basis        # wage AMOUNT entered on the form, not here
```

**(3) leave_allocations.csv** → opening leave balances
```
employee,leave_type,opening_balance_days,as_of_date
```
(Opening balances per the agreed accrual policy — `R3_Governance_Gates.md` §5.)

**(4) competencies.csv** → competency / licence
```
employee,competency_or_licence,level_or_class,issued_date,expiry_date
```
(Driver-licence class + expiry feeds the R3a crew-assignment gate.)

### 4d. Validation after each layer
- After employees: count == headcount; every employee linked to the right
  user; spot-check 3 records.
- After contracts: every active employee has a contract; pay basis correct.
- After leave: balances reconcile to the manual register.
- After competencies: licence expiries populated for all drivers.

### 4e. Seeded starting point
A non-sensitive **employee seed** for the known staff (name + linked user +
work email + job title only) can be created now so the team sees the HR
surface populated and can start adding the sensitive detail per 4b/4c — see
the seed proposal (held for explicit go; it's a real-data write). It does NOT
load any contract/leave/salary/ID data.

---

### Owner & next step
Robin walkthrough of this skeleton; fill the decision slots (depth of data
migration, training dates, freeze date) and the `R3_Governance_Gates.md`
figures. No code work is implied by Phase 11; it is execution + sign-off.
