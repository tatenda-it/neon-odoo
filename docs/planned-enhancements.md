# Planned Enhancements

Deferred chores, refactors, and follow-ups that are too narrow to
warrant a milestone but should not be lost. Add entries with a
clear title, scope, investigation step, functional-impact note,
and priority.

When a chore lands, move the entry to the commit message of the
fix and remove it from here.

---

## CHORE — Full-width text rendering across `<sheet>`-based forms without `<notebook>`

**Filed:** 2026-05-12 (during P3.M4 close-out); broadened
2026-05-13 (during P3.M6 close-out) to cover standalone sheet
forms in addition to wizards.

**Scope.** Any `<sheet>`-based form that lacks a `<notebook>`
wrapper renders text fields in a cramped ~110–290px column even
when the surrounding section header (`<separator>`) and group
container stretch full-width. The `<page>` context inside a
notebook masks this — that is why `commercial.event.job` (10+
tabs of mixed content) renders cleanly while the same field
markup in a wizard or a single-page form does not.

**Affected surfaces:**
- 5 wizards in `addons/neon_jobs/wizards/`:
  - `commercial_job_loss_wizard`
  - `commercial_job_crew_decline_wizard`
  - `commercial_job_gate_override_wizard`
  - `commercial_job_soft_hold_extend_wizard`
  - `commercial_event_job_readiness_override_wizard` (current
    state at 17.0.2.2.2 — already mildly improved with
    `<group col="1">`, but not edge-to-edge)
- 1 standalone form (added P3.M6):
  - `commercial.scope.change` main form (single-page sheet, no
    notebook — the four `<separator>` + `<group col="1">` text
    sections will likely exhibit the same cramping the moment the
    form is loaded in a browser)
- Future likely-affected (so the sweep doesn't miss them):
  - P3.M7 closeout dialog (forthcoming)
  - Any further single-page sheet forms in P3.M8 onward

**Root cause (working theory).** Bare `<field>` under `<sheet>`
without `<notebook>` falls back to the widget's default render
width. Inside a `<page>` (notebook tab) Odoo applies a different
CSS context that lets the field expand to fill the available
column. The constraint lives in `.o_inner_group >
.o_field_widget` or the field's own input element — exact rule
TBD by dev-tools inspection.

**Investigation step.** F12 the rendered form (pick the scope
change form for richest case — 4 text fields × different
group/separator combinations) and capture the CSS rules applied
to:
- `.o_inner_group > .o_field_widget`
- the bare `<input>` / `<textarea>` element itself
- the surrounding `.o_horizontal_separator` for contrast

Identify which CSS rule constrains width. The pattern that
actually fills edge-to-edge is not yet known from the codebase
side — three attempts on the readiness override wizard without
dev-tools access made it progressively better but not
edge-to-edge.

**Speculative fix options (pending the dev-tools finding):**
- Drop `<sheet>` from wizards entirely (Odoo core wizard
  precedent — dialog provides chrome, sheet adds width
  constraint). Not applicable to standalone forms which need
  `<sheet>` for chatter layout.
- Wrap text fields in `<div class="row"><div class="col-12">`
  Bootstrap escape
- Add `class="oe_inline"` or `class="o_field_widget oe_inline"`
  to the field element
- Try `widget="text"` with explicit `options="{'rows': 8}"` to
  hint at multi-line layout
- For standalone forms: wrap content in a single `<notebook>`
  with one `<page>` (preserves chatter, gains the notebook CSS
  context) — heavy-handed but proven to work.

**Functional impact.** Zero. Everything works today, audit
trails persist, validations fire, data integrity holds. This is
cosmetic only.

**Approach when fixing.** Identify the pattern that actually
fills width on ONE wizard AND ONE standalone form in browser
(verify with dev tools), then propagate the same idiom to all
affected surfaces in a single commit:
`chore(neon_jobs): full-width text-field rendering on sheet forms`.
Do not patch one surface at a time — keeps the codebase
consistent and avoids the partial-progress trap that 17.0.2.2.1
and 17.0.2.2.2 fell into.

**Schedule.** Dedicated milestone before P3.M9 (Hetzner deploy)
— call it **P3.M8.5 — UI layout sweep** (informal numbering,
between functional M8 and deploy M9). Bundling this with deploy
prep means the production rollout ships a polished UI in one
pass.

**Priority.** Medium — affects user experience (notably crew
chiefs filling forms on mobile), data integrity holds.

**Origin commits (so the fix history is recoverable):**
- `c0ac21b` 17.0.2.2.1 — first wizard fix attempt (separator +
  bare colspan="2"; landed in DB but did not help rendering)
- `5e1af2f` 17.0.2.2.2 — second attempt (`<group col="1">`;
  improved from ~110px to ~290px but still not edge-to-edge)
- `5d40bf6` 17.0.2.4.0 — P3.M6 introduces the first standalone
  sheet form (`commercial.scope.change`) likely affected by the
  same rendering quirk

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
