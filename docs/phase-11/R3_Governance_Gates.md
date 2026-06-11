# HR R3 — Go-Live Governance Decisions (DECIDED 2026-06-11)

Robin sit-down done. Decisions below are FINAL; each notes how it maps to the
built code: **CONFIG** (a value Kudzai sets via the UI — money/leave-adjacent,
not a silent write), **CODE** (a small field/tier = a Gate-1 note, NOT built
yet), or **ALREADY** (the engine already does this). `⚠️ VERIFY` = a statutory
figure to confirm with NSSA / ZIMRA / the Labour Act / the sector NEC before
it's relied on — never guessed.

> No code was built for these and no prod HR/payroll config was silently
> written (money + sensitive). Items needing more than a value are flagged as
> Gate-1 notes for a future neon_hr touch.

---

## 1. NSSA / Accidents — DECIDED
**Decision:** every accident requiring **hospital treatment** must be reported
to NSSA; exposure is a **$20/day fine per day unreported**.
**Maps to code:** `neon.hr.accident` (R2) ALREADY tracks the NSSA submission
(state, `nssa_submission_ref`, `nssa_submitted_date`, proof attachments), a
`reporting_deadline` (= accident_date + a deadline-days constant), a
`days_to_deadline` compute, and a `penalty_risk` ALERT-ONLY flag (the penalty
figure was deliberately left out pending this decision).
- **CODE (Gate-1 note):** add a **hospital-treatment trigger** that marks an
  accident as NSSA-reportable (drives `penalty_risk`/the reportable tier), and
  a **$20/day exposure display** = `max(0, days_unreported) × $20` so the
  running fine is visible. Small (a Boolean/severity input + one computed
  Char/Float + a view line). Hold for a Gate-1 build.
- **⚠️ VERIFY (Kudzai with NSSA):** the **$20/day** figure AND the **reporting
  deadline** (the code currently assumes a 14-day deadline — confirm it's 14,
  and confirm the per-day penalty basis). The exposure display ships only once
  these are confirmed.

## 2. Absence severity ladder — DECIDED (extensible)
**Decision:**
- **SERIOUS:** (a) a crew chief absent from an EVENT without communication;
  (b) **5 days' absence without communication = a dismissible offence.**
- **MEDIUM:** a crew chief gives only day-before notice they won't make an
  upcoming event.
- **MINOR:** absence from WAREHOUSE duties without communication.
**Maps to code:** `neon.hr.case` ALREADY has a `severity` Selection + an
`absence_flow` Selection + `case_type`.
- **CONFIG/DOC:** these three rungs are the policy definitions; logging a case
  at the right severity is operational (Kudzai/OD select the tier when raising
  the case). This doc is the rung reference.
- **CODE (Gate-1 note) IF the `severity` Selection doesn't already carry
  serious/medium/minor values, or if you want the triggers auto-classified:** a
  `selection_add` for the tiers + a short help/mapping. Small; hold for Gate-1.
  More rungs later are an additive `selection_add` (extensible, as decided).
- **⚠️ VERIFY:** the exact **Labour Act** provision wording for (b) the 5-day
  dismissible threshold (so a dismissal on that basis rests on the cited
  section).

## 3. Overtime — DECIDED
**Decision:** OT is **NOT compensated** in this sector — **no OT pay, no TOIL
accrual.** The OT/TOIL machinery is **record-only / off**.
**Maps to code:** `neon.hr.overtime` resolves each OT record case-by-case into
{paid, TOIL, included}; TOIL accrues an `hr.leave.allocation`.
- **POLICY/CONFIG (money-adjacent — Kudzai operates):** the standing policy is
  to record OT and always resolve it as **`included`** (never `paid`, never
  `toil`), so no pay and no TOIL allocation is ever created. No new accrual.
- **CODE (Gate-1 note, OPTIONAL):** if you want the `paid`/`toil` options
  *removed/disabled* in the UI (so they can't be picked by mistake) rather than
  just policy, that's a small field/domain change — hold for Gate-1.
- **⚠️ VERIFY (one-time, labour consultant / sector NEC):** that a
  no-OT-compensation policy is **compliant for our sector** under the Labour
  Act, so the policy rests on confirmed ground.

## 4. Approver bands — DECIDED
**Decision:** **leave AND loans are approved by MD/OD ONLY** (Kudzai
prepares/operates, does NOT approve). **Loan limits: NOT encoded** —
deliberately MD/OD case-by-case discretion (do not scope further).
**Maps to code:** leave approver = each Neon category's `leave_approver_id`
(synced to `hr.employee.leave_manager_id`); `neon.hr.loan.action_approve`
drives state → approved.
- **CONFIG (Kudzai, via the UI — leave/HR policy, not a silent write):** set
  every Neon category's **`leave_approver_id` = Robin (OD) / Munashe (MD)** so
  all leave routes to MD/OD. Confirm the loan-approve action is gated to MD/OD
  (group/owner) — if it's open to Kudzai's tier, tighten to MD/OD.
- **No loan-limit field** (decided): leave the loan model as-is; amount is MD/OD
  discretion at approval.
- ⚠️ no statutory item.

## 5. Leave accrual — DECIDED
**Decision:** **22 days per annum, accrued monthly (22/12 per month)**, with
**MD discretion** to approve days beyond the accrued balance per request.
**Carryover: NO cap** — MD discretion (do not encode a cap).
**Maps to code:** `neon_hr_leave_rules` ALREADY has
`neon_annual_entitlement_days` ("annual 22 … a config value") and
`neon_accrual_cap_days` (was "22 pending legal confirmation").
- **CONFIG (Kudzai, via the UI):** on the **Annual** leave type set
  `neon_annual_entitlement_days = 22`; confirm the accrual engine accrues
  **22/12 per month**. Per the no-cap decision, set **`neon_accrual_cap_days`
  to no-cap (0 / unlimited)** so carryover is NOT auto-dropped — MD discretion.
- **RESOLVES the prior pending note:** the old "22 vs 72-day contradiction /
  pending legal" `⚠️` on `neon_accrual_cap_days` is now DECIDED — **22/yr
  entitlement, no carryover cap.** Over-accrual approvals are MD discretion (the
  leave approval already allows approving beyond balance).
- ⚠️ no further statutory verification required for the 22 (it's a Neon
  entitlement decision; it meets/exceeds the statutory minimum — Kudzai can
  sanity-check the minimum but 22 stands as the policy).

---

## Encode summary (for the record)
| # | Item | How it lands | Outstanding |
|---|---|---|---|
| 1 | NSSA hospital-treatment + $20/day | small **CODE** (Gate-1 note) | ⚠️ VERIFY $20/day + 14-day deadline (NSSA) |
| 2 | Absence ladder S/M/M | `severity` exists; **CONFIG/DOC** (+ small CODE if tiers absent) | ⚠️ VERIFY Labour Act 5-day wording |
| 3 | OT not compensated | **POLICY** (resolve all OT = `included`; no TOIL) | ⚠️ VERIFY no-OT compliance (NEC/consultant); optional CODE to hide paid/TOIL |
| 4 | Approver MD/OD; no loan limit | **CONFIG** (category `leave_approver_id` = MD/OD; confirm loan gate) | — |
| 5 | Leave 22/yr monthly, no carryover cap | **CONFIG** (`neon_annual_entitlement_days=22`, `neon_accrual_cap_days`=no-cap) | resolves prior pending-22 note |

**Next:** Kudzai applies the §4/§5 config via the Odoo UI (leave-type +
category approver). The §1 (+ optional §2/§3) code adds wait for a Gate-1
prompt. The three `⚠️ VERIFY` items (NSSA $20/day+deadline, Labour-Act 5-day,
no-OT compliance) are confirmations to bring back before the related behaviour
is relied on.
