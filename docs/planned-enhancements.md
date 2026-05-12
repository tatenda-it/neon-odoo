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
