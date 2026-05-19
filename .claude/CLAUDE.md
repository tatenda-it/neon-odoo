# Neon-Odoo Project Context

This file is auto-loaded into every Claude Code prompt for the neon-odoo 
repo. It captures invariants that apply across all milestones. For 
milestone-specific procedural steps, see 
`.claude/skills/milestone-pattern/SKILL.md`.

## Project basics

- Repo: neon-odoo (custom Odoo 17 addons for Neon Events Elements)
- Currently in Phase 6 (Finance Module full rebuild)
- Main developer: Tatenda Loyd (Sales Rep + Developer)
- Production server: Hetzner, crm.neonhiring.com
- Phase 5 LIVE; Phase 6 local-only until P6.M12 deploy

## Two-gate approval pattern

Every milestone has exactly two human approval gates:

1. **Design pause** (after discovery, before code)
2. **Commit approval** (after all tests pass)

Between gates: autonomous execution. Mid-build judgment → ⚠️ DECISION 
markers in code + diff summary. No mid-build pauses except hard stops.

**Hard stops**: Python test failure, browser smoke failure, discovery 
reveals invalid design assumption, schema redesign needed. On hard stop: 
STOP → diagnose → report symptom + root cause + 3 fix options → await 
direction.

## Audit-trail discipline

ALL Phase 6 financial models use append-only ACLs: `perm_unlink = 0` 
for every group on every financial model. Corrections via new records 
with later effective_date or cancelled state, never deletion.

Models under this rule: pricing.rule, pricing.bracket, day.multiplier, 
conversion.rate, quote, quote.line, payment.term, cost.line, approval, 
plus future payment + invoice models.

## Browser smoke depth principle

For every menu the smoke verifies as visible: assert visible, click into 
the action, assert at least one piece of content (row count, cell value, 
form opens, badge state). Menu-visibility alone catches ~75% of bugs; 
depth principle catches ~100%.

## Test fixtures

The 8 p2m75_* users are persistent via get-or-create:
- p2m75_sales, p2m75_mgr, p2m75_lead, p2m75_crew, p2m75_other
- p2m75_t20 (throwaway slot from T20 constraint test)
- p2m75_book (Bookkeeper), p2m75_approver (Approver) — added P6.M2/M4

Password `test123` baked into seed. user_ids stable across regression 
cycles. NEVER touch res_users.unlink in setup. Manual UI group grants 
do NOT survive setUp (baseline enforcement). To add a new role for 
testing, ADD a fixture — don't mutate existing ones.

## Manifest versioning

`17.0.<phase>.<minor>.<patch>`

- **Phase era (major)**: new phase OR new central pivot model
- **Minor**: engine wiring, extensions, new layers
- **Patch**: fix rounds within a milestone

## Odoo 17 gotchas

### Routing
`/odoo` and `/odoo/action-...` fall through to website 404. Use `/web` 
and `/web#action=<numeric_id>`.

### Instance methods via RPC
`ir.ui.menu.load_web_menus(self, debug)` is NOT `@api.model`. `call_kw` 
requires `args=[[], False]` (empty recordset + debug flag).

### Security records with `noupdate=1`
Don't propagate `implied_ids` changes on existing installs via `-u` 
alone. Required pattern: migration script with 
`write({'implied_ids': [(4, id)]})` PLUS manifest version bump. Use 
`(4, id)` idempotent add, `(3, id)` defensive remove.

### Odoo account group XML id labels lie
- `account.group_account_invoice` has LABEL "Billing" (basic user)
- `account.group_account_manager` has LABEL "Billing Administrator"
- `account.group_account_user` has LABEL "Accountant"

Never match XML ids by label. Always verify via `res.groups` search.

### Cross-module menu coordination
When module A narrows a shared menu via `(6, 0, [...])` REPLACE, module 
B extending the same menu must use `(4, ref(...))` ADD. Load order must 
respect dependencies (B depends on A).

### Compute chains bypass write()
Stored-computed-field updates do NOT fire `model.write()`. If you need 
behavior on compute update: put it INSIDE the compute method, not in 
write(). Use direct SQL read of prior stored value for change detection 
(avoids ORM cache recursion).

### SQL underscore is a wildcard
`LIKE 'p2m7_'` matches both `'p2m7_'` AND `'p2m75_'`. Use Python 
`startswith()` or Odoo `=like` with escape for prefix cleanup.

### sudo() in computed reads
When a compute on an operational model (event_job, etc.) reads finance-
side models (quote, cost.line, etc.), operational-tier users may lack 
ACL on the finance model. Use `record.sudo()` inside the compute. 
Scopes escalation to that single read; preserves requesting user 
identity.

## Cross-module ACL pattern

When a finance role needs read access on an operational model (e.g. 
Bookkeeper reading event_job for P&L tab), add a row to 
`addons/neon_finance/security/ir.model.access.csv` for the cross-module 
model. `perm_unlink=0` always.

## When the spec is wrong

If the Schema Sketch or design pause spec contains an assumption about 
Odoo that turns out to be wrong (write() firing on stored-compute, etc.), 
THE IMPLEMENTATION TAKES PRECEDENCE. Document with ⚠️ marker:
- What the spec said
- What Odoo actually does
- The corrected mechanism

Don't bend the implementation to match a wrong spec. Bend the spec.

## Anti-patterns (do NOT do)

- Auto-approve action stubs without ⚠️ marker
- Skipping the design pause to "save time"
- Modifying res.users records on every smoke run
- Granting permissions via implied_ids without migration script
- Using `(6, 0, [...])` REPLACE on shared menus that other modules extend
- Reading finance-side models from operational paths without sudo()
- Tests asserting against implementation output (must assert against spec)
- Force-recreating containers without `-u <module>` first
- Committing without browser smoke verification

## Polish backlog discipline

When a real issue surfaces that's not blocking the current milestone:
1. Mark with ⚠️ in the diff summary
2. Add to `project_phase6_status.md` polish backlog with severity 
   (LOW/MEDIUM/HIGH), milestone that surfaced it, fix description, 
   and target timing

No hidden technical debt — every "I'll fix that later" becomes a named 
backlog item.
