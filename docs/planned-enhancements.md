# Planned Enhancements

Deferred chores, refactors, and follow-ups that are too narrow to
warrant a milestone but should not be lost. Add entries with a
clear title, scope, investigation step, functional-impact note,
and priority.

When a chore lands, move the entry to the commit message of the
fix and remove it from here.

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
