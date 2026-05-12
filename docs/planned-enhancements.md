# Planned Enhancements

Deferred chores, refactors, and follow-ups that are too narrow to
warrant a milestone but should not be lost. Add entries with a
clear title, scope, investigation step, functional-impact note,
and priority.

When a chore lands, move the entry to the commit message of the
fix and remove it from here.

---

## CHORE — wizards full-width text rendering refactor

**Filed:** 2026-05-12 (during P3.M4 close-out)

**Scope.** All 5 wizards in `addons/neon_jobs/wizards/` ship with
cramped text-field rendering (~290px column on a ~950px wizard
dialog). Section headers (`<separator>`) stretch full-width but
text inputs underneath occupy only the left ~⅓ of the dialog body
with empty whitespace to the right.

**Affected wizards:**
- `commercial_job_loss_wizard`
- `commercial_job_crew_decline_wizard`
- `commercial_job_gate_override_wizard`
- `commercial_job_soft_hold_extend_wizard`
- `commercial_event_job_readiness_override_wizard` (current state
  at 17.0.2.2.2 — already mildly improved with `<group col="1">`,
  but not edge-to-edge)

**Investigation step.** Open one of the wizards in browser dev
tools (F12) and capture the CSS rules applied to
`.o_inner_group > .o_field_widget` and the text input element
itself. Identify which rule is enforcing the ~290px width. The
pattern that actually fills width is not yet known from the
codebase side — three attempts on the readiness override wizard
without dev-tools access made it progressively better but not
edge-to-edge.

**Speculative fix options (pending the dev-tools finding):**
- Drop `<sheet>` from the wizard entirely (Odoo core wizard
  precedent — dialog provides chrome, sheet adds width constraint)
- Wrap text fields in `<div class="row"><div class="col-12">`
  Bootstrap escape
- Add `class="oe_inline"` or `class="o_field_widget oe_inline"`
  to the field element
- Try `widget="text"` with explicit `options="{'rows': 8}"` to
  hint at multi-line layout

**Functional impact.** Zero. All wizards work correctly today,
audit trails persist, validations fire. This is cosmetic only.

**Approach when fixing.** Identify the pattern that actually
fills width on ONE wizard in browser, verify with dev tools, then
propagate the same idiom to all 5 wizards in a single commit:
`chore(neon_jobs/wizards): full-width text-field rendering`.
Do not patch one wizard at a time — keeps the codebase
consistent and avoids the partial-progress trap that 17.0.2.2.1
and 17.0.2.2.2 fell into.

**Priority.** Low. Schedule after Phase 3 wraps OR after first
user feedback on the wizard UX, whichever comes first.

**Origin commits (so the fix history is recoverable):**
- `c0ac21b` 17.0.2.2.1 — first wizard fix attempt (separator +
  bare colspan="2"; landed in DB but did not help rendering)
- `5e1af2f` 17.0.2.2.2 — second attempt (`<group col="1">`;
  improved from ~110px to ~290px but still not edge-to-edge)

---

## CHORE — UI feedback for model-level write() validations

**Filed:** 2026-05-12 (during P3.M5 browser smoke)

**Scope.** When a user toggles a Done switch on a
`commercial.event.job.checklist.item` from the embedded checklist
view inside the Event Job form, model-level `write()` correctly
raises `UserError` (authority gating) or `ValidationError` (missing
`na_reason`, missing required photo). The block fires — data
integrity holds — but the inline form dialog closes silently. The
user sees "nothing changed" without an explanation of why.

**Affected paths:**
- Sales / unauthorised role toggling `is_checked` on items in
  lead_tech / lead_tech_finance / crew_chief-owned checklists
- Any role marking `is_na=True` without `na_reason`
- Any role marking `is_checked=True` on an item with
  `photo_required=True` but no attached photo

**Root cause.** Odoo's inline form dialog (One2many embedded edit)
doesn't reliably surface `UserError` / `ValidationError` from
`write()` as a toast / notification. The exception is raised on
the RPC channel but the dialog UI handles it by closing without
re-rendering the failure.

**Investigation step.** Reproduce by toggling Done as
`p2m75_sales` on a gear_prep checklist item. Open the browser
network panel + console: the RPC response shows the UserError
payload, but no toast / notification surfaces. Confirm whether
the inline-edit pathway in `web/static/src/views/form/` swallows
the error or whether it's a missing notification dispatch.

**Speculative fix options:**
- Convert authority + N/A reason checks from `write()` overrides
  to `@api.onchange` handlers that set a warning on the field
  (Odoo's onchange-warning idiom surfaces as a toast)
- Add an explicit Save button on the embedded item form that
  triggers `display_notification` on error via `action` return
  value (more invasive — changes UX shape)
- Wrap the checklist item `write()` in a `try/except` that returns
  a notification action when called from a UI context (smells)
- Investigate whether Odoo 17.x has a fix or different default
  behavior for inline-form-dialog error rendering

**Functional impact.** Zero on data integrity — writes correctly
block. Medium on UX — users can't tell why a toggle "didn't
work." Currently mitigated by the (read-only) `state` and
completed_at fields surfacing the absence of the change, but a
fresh user wouldn't know to look.

**Priority.** Medium — affects user experience but data
integrity holds (writes correctly block). Schedule alongside the
wizards full-width chore so all UI polish lands in one pass.

**Origin commit:** `587a24b` 17.0.2.3.0 — P3.M5 introduces the
authority gates that surface this gap; pre-P3.M5 the codebase
had no comparable model-level validation on inline-edited items.
