# Kanban drag-drop respecting state-machine guards

Established in Phase 7c M5 (May 23 2026). Stock Odoo kanban
with `default_group_by="state"` fires
`write({"state": new_state})` when an admin drags a card
between columns. This bypasses any action methods that
enforce the state-transition graph — invalid transitions
land silently in the DB.

## The problem

Phase 7c's `neon.external.training.booking` has an 8-state
machine (draft → pending_approval → booked → attended →
completed → cert_issued, plus cancelled / no_show terminal
branches). Transitions are normally invoked via header
buttons (`action_submit_for_approval`, `action_approve`,
etc.) that route through `_transition_to`, which validates
the move against `_ALLOWED_TRANSITIONS` and raises
`UserError` on invalid jumps.

But kanban drag-drop calls `write` directly:

```python
# Kanban drag from 'draft' column to 'completed' column
booking.write({"state": "completed"})  # bypasses guard!
```

Without intervention, this would let an admin click-drag
draft → completed without ever submitting for approval or
recording attendance, breaking the audit trail.

## The pattern

Two pieces:

1. **`write()` override** intercepts state changes and
   routes them through `_transition_to`.
2. **Context flag** lets `_transition_to`'s own write land
   without re-entering the override.

```python
def _transition_to(self, new_state, extra_vals=None):
    """Move self to new_state, enforcing the
    _ALLOWED_TRANSITIONS graph."""
    self.ensure_one()
    vals = dict(extra_vals or {})
    allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
    if new_state not in allowed:
        raise UserError(_(
            "Cannot transition from '%s' to '%s'. "
            "Allowed: %s."
        ) % (self.state, new_state,
             ", ".join(sorted(allowed)) or "(none)"))
    vals["state"] = new_state
    # Context flag prevents the write() override from
    # re-entering the guard for this internal write.
    self.sudo().with_context(
        neon_p7c_internal_transition=True
    ).write(vals)


def write(self, vals):
    """When a write changes state, route through the
    transition guard. _transition_to sets the context
    flag so its own write lands cleanly."""
    if (
        "state" in vals
        and not self.env.context.get(
            "neon_p7c_internal_transition")
    ):
        new_state = vals["state"]
        for rec in self:
            if rec.state != new_state:
                rec._transition_to(new_state)
        # Strip state from the batch write -- _transition_to
        # has already handled it per record.
        vals = {k: v for k, v in vals.items()
                if k != "state"}
        if not vals:
            return True
    return super().write(vals)
```

## Why the context flag

`_transition_to` MUST write the state field itself (that's
how the value actually flips in the DB). Without the flag,
that write would re-enter `write()` → either infinite
recursion or duplicate guard firing.

The flag is namespaced to the module
(`neon_p7c_internal_transition`) so it doesn't collide
with other state-machine modules that might use the same
pattern.

## Result

Drag-drop with invalid target column:

- `write({"state": "completed"})` fires from kanban
- `write()` override sees state change, no context flag
- Calls `_transition_to("completed")`
- `_ALLOWED_TRANSITIONS["draft"]` does NOT include
  `"completed"` → `UserError` raised
- Kanban catches the exception, surfaces it as a toast, and
  bounces the card back to its origin column

Drag-drop with valid target column:

- Same path, but `_transition_to` validates OK
- It calls `self.sudo().with_context(neon_p7c_internal_transition=True).write({"state": "attended"})`
- Recursive write() sees the context flag → skips the
  guard, calls super().write() directly
- Side effects fire (notifications, audit chatter, etc.)
- Card lands in the new column

## Action methods still own the security boundary

The `write()` override only handles the state-machine
validation. ACL + sudo() boundaries are still enforced by
the action methods:

- `action_approve` calls `_m3_assert_superuser` BEFORE
  `_transition_to` — non-superusers can't approve, even
  via drag-drop.
- `_transition_to` itself uses `self.sudo()` on the inner
  write, which lets crew (read-only ACL via own-row record
  rule) submit their own bookings without crashing on
  write permission. The rule + the action methods together
  scope which records crew can submit; the state machine
  scopes which transitions are valid.

Drag-drop inherits all of that — a crew member dragging
their own booking to "submit for approval" works (rule
allows read, sudo bypasses write ACL, transition is
valid). A crew member trying to drag SOMEONE ELSE's
booking fails at the record-rule layer (they don't even
see it). A crew member trying to drag their own booking to
`booked` (approval-bypass) fails at the action-method
layer because crew isn't superuser.

## Side effects in `_transition_to` vs after

Notifications and audit posts can live either inside
`_transition_to` (fires on every transition path including
drag) or in the action methods (fires only on explicit
button click). Phase 7c chose the action-method placement
because:

1. Drag-drop is a power-user shortcut; the explicit button
   path is the canonical flow that documents what should
   happen.
2. Some side effects (e.g., creating a cert in
   `action_mark_cert_issued`) involve cross-module writes
   that benefit from clearer error reporting than a kanban
   drop-back gives.

If you put side effects in `_transition_to`, drag-drop
gets parity with buttons "for free" but you lose the
ability to do button-only steps (e.g., a confirmation
dialog before destructive transitions).

## Phase 11 candidate — confirmation dialog

For terminal or destructive transitions (`cert_issued`,
`cancelled`), an Owl popup before commit would prevent
fat-finger drags. Pattern:

```javascript
// In a custom kanban controller subclass:
async _onRecordDragDrop(record, newColumn) {
    if (DESTRUCTIVE_TRANSITIONS.includes(newColumn)) {
        const confirmed = await this.dialog.confirm({
            title: _t("Confirm transition"),
            body: _t("Moving to %s will create downstream " +
                     "records and cannot be undone.").format(
                     newColumn),
        });
        if (!confirmed) return;
    }
    return super._onRecordDragDrop(record, newColumn);
}
```

Useful for transitions that create cert records, send
external notifications, or commit financial state.

## When NOT to use this pattern

- Models without a state field don't need it.
- Models where the state field is purely derived (computed,
  no manual writes) don't need it.
- Models where kanban is read-only (`records_draggable="0"`
  in the arch) don't need it — drag is disabled at the
  view layer.

For everything else with `default_group_by="state"` on a
Selection field that has a transition graph, this pattern
gives you cheap drag-drop with full safety.
