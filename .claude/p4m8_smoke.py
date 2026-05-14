"""P4.M8 smoke — UI polish: is_due_soon compute + Mark Done audit + chip map.

T230 is_overdue computes correctly across past/future due_date + closed state
T231 is_due_soon respects per-config escalation_minutes window
T232 is_due_soon falls back to 1440-minute default when minutes=0/NULL
T233 action_mark_done happy path: state→done + closure_reason + state_change history
T234 action_mark_done denies a non-assignee non-manager user
T235 action_mark_done allows manager bypass on any item
T236 action_mark_done idempotent / safe on terminal state (raises, doesn't mutate)
T237 SKIPPED — menu needaction badge scoped out per M8 decision M4
T238 SKIPPED — needaction count scoped out per M8 decision M4
T239 PRIORITY_BADGE_MAP module constant present with bootstrap classes
T240 Trigger config escalation_minutes coverage (sla_passed + manual=0 by design)
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login)

# Cleanup prior P4M8 fixtures
Item = env["action.centre.item"].sudo()
Item.search([("title", "like", "P4M8FIX%")]).unlink()
env.cr.commit()


def _make(title, **vals):
    base = {"title": "P4M8FIX " + title, "priority": "medium"}
    base.update(vals)
    return Item.create(base)


results = {}


# ============================================================
print()
print("=" * 72)
print("T230 - is_overdue across past/future/closed states")
print("=" * 72)
past = _make("T230 past", due_date=fields.Datetime.now() - timedelta(hours=2))
future = _make("T230 future", due_date=fields.Datetime.now() + timedelta(hours=2))
closed_past = _make("T230 closed-past",
                    due_date=fields.Datetime.now() - timedelta(hours=2))
closed_past.with_context(_allow_state_write=True).write({"state": "done"})
past.invalidate_recordset()
future.invalidate_recordset()
closed_past.invalidate_recordset()
ok = (
    past.is_overdue is True
    and future.is_overdue is False
    and closed_past.is_overdue is False
)
print("  past (2h ago, open):       is_overdue=", past.is_overdue,
      "(want True)")
print("  future (2h ahead, open):   is_overdue=", future.is_overdue,
      "(want False)")
print("  past (2h ago, done):       is_overdue=", closed_past.is_overdue,
      "(want False)")
print("T230:", "PASS" if ok else "FAIL")
results["T230"] = ok


# ============================================================
print()
print("=" * 72)
print("T231 - is_due_soon respects escalation_minutes window")
print("=" * 72)
# Use the readiness_50 config which has escalation_minutes=240 (4h).
cfg_readiness50 = env.ref(
    "neon_jobs.trigger_config_readiness_50").sudo()
# Pick a config with a wider window for the negative case —
# closeout_overdue at 1440 minutes (24h).
cfg_closeout = env.ref(
    "neon_jobs.trigger_config_closeout_overdue").sudo()

within = _make(
    "T231 within (1h ahead, 4h window)",
    due_date=fields.Datetime.now() + timedelta(hours=1),
    trigger_config_id=cfg_readiness50.id,
    is_manual=False,
)
outside = _make(
    "T231 outside (8h ahead, 4h window)",
    due_date=fields.Datetime.now() + timedelta(hours=8),
    trigger_config_id=cfg_readiness50.id,
    is_manual=False,
)
overdue_already = _make(
    "T231 overdue (2h ago, 4h window)",
    due_date=fields.Datetime.now() - timedelta(hours=2),
    trigger_config_id=cfg_readiness50.id,
    is_manual=False,
)
for r in (within, outside, overdue_already):
    r.invalidate_recordset()
ok = (
    within.is_due_soon is True
    and outside.is_due_soon is False
    and overdue_already.is_due_soon is False  # overdue takes precedence
    and overdue_already.is_overdue is True
)
print("  within window (1h / 4h):  is_due_soon=", within.is_due_soon,
      "(want True)")
print("  outside window (8h / 4h): is_due_soon=", outside.is_due_soon,
      "(want False)")
print("  already overdue:          is_due_soon=", overdue_already.is_due_soon,
      "(want False, overdue precedence)")
print("T231:", "PASS" if ok else "FAIL")
results["T231"] = ok


# ============================================================
print()
print("=" * 72)
print("T232 - is_due_soon falls back to 1440-minute default")
print("=" * 72)
# Manual item — no trigger_config_id, so the 1440-minute fallback
# should kick in. 12h ahead is well inside that window → True.
manual_within = _make(
    "T232 manual 12h ahead",
    due_date=fields.Datetime.now() + timedelta(hours=12),
)
# Also test an item with a config but escalation_minutes=0: sla_passed.
cfg_sla = env.ref("neon_jobs.trigger_config_sla_passed").sudo()
zero_window = _make(
    "T232 sla_passed config (0 minutes) 12h ahead",
    due_date=fields.Datetime.now() + timedelta(hours=12),
    trigger_config_id=cfg_sla.id,
    is_manual=False,
)
for r in (manual_within, zero_window):
    r.invalidate_recordset()
ok = (
    manual_within.is_due_soon is True
    and zero_window.is_due_soon is True
)
print("  manual item 12h ahead:    is_due_soon=", manual_within.is_due_soon,
      "(want True, 1440min fallback)")
print("  sla_passed config 12h ahead: is_due_soon=", zero_window.is_due_soon,
      "(want True, 1440min fallback)")
print("T232:", "PASS" if ok else "FAIL")
results["T232"] = ok


# ============================================================
print()
print("=" * 72)
print("T233 - action_mark_done happy path (closure_reason + audit row)")
print("=" * 72)
i233 = _make("T233", primary_assignee_id=sales.id)
prior_state = i233.state
i233.with_user(sales).action_mark_done()
i233.invalidate_recordset()
state_rows = i233.history_ids.filtered(
    lambda h: h.event_type == "state_change"
    and h.from_value == prior_state
    and h.to_value == "done"
    and h.actor_is_system is False
    and h.actor_id == sales
)
ok = (
    i233.state == "done"
    and (i233.closure_reason or "").startswith("Manually resolved by ")
    and len(state_rows) == 1
)
print("  state:", i233.state, "(want done)")
print("  closure_reason:", repr(i233.closure_reason)[:80])
print("  matching history rows:", len(state_rows), "(want 1)")
print("T233:", "PASS" if ok else "FAIL")
results["T233"] = ok


# ============================================================
print()
print("=" * 72)
print("T234 - action_mark_done denies non-assignee non-manager")
print("=" * 72)
i234 = _make("T234", primary_assignee_id=manager.id)
# crew_leader is not the assignee, not the escalated user, not a
# manager — should be denied.
denied = False
try:
    i234.with_user(crew_leader).action_mark_done()
except UserError as e:
    denied = "permission" in (str(e) or "").lower() or "only" in (str(e) or "").lower()
i234.invalidate_recordset()
ok = denied and i234.state == "open"
print("  raised UserError? ", denied, "(want True)")
print("  state after:        ", i234.state, "(want open)")
print("T234:", "PASS" if ok else "FAIL")
results["T234"] = ok


# ============================================================
print()
print("=" * 72)
print("T235 - action_mark_done allows manager bypass on any item")
print("=" * 72)
i235 = _make("T235", primary_assignee_id=sales.id)
i235.with_user(manager).action_mark_done()
i235.invalidate_recordset()
ok = i235.state == "done"
print("  state:", i235.state, "(want done — manager bypass on any assignee)")
print("T235:", "PASS" if ok else "FAIL")
results["T235"] = ok


# ============================================================
print()
print("=" * 72)
print("T236 - action_mark_done on terminal state raises, no mutation")
print("=" * 72)
# i235 from T235 is already done — try again, expect UserError, state stays.
raised = False
try:
    i235.with_user(manager).action_mark_done()
except UserError:
    raised = True
i235.invalidate_recordset()
ok = raised and i235.state == "done"
print("  raised UserError on terminal? ", raised, "(want True)")
print("  state still done?             ", i235.state == "done", "(want True)")
print("T236:", "PASS" if ok else "FAIL")
results["T236"] = ok


# ============================================================
print()
print("=" * 72)
print("T237 - SKIPPED (menu needaction badge scoped out per M4)")
print("=" * 72)
results["T237"] = None


# ============================================================
print()
print("=" * 72)
print("T238 - SKIPPED (needaction count scoped out per M4)")
print("=" * 72)
results["T238"] = None


# ============================================================
print()
print("=" * 72)
print("T239 - PRIORITY_BADGE_MAP module constant present")
print("=" * 72)
from odoo.addons.neon_jobs.models.action_centre_item import (
    PRIORITY_BADGE_MAP,
)
expected_keys = {"low", "medium", "high", "urgent"}
expected_prefix = "bg-"
ok = (
    set(PRIORITY_BADGE_MAP.keys()) == expected_keys
    and all(v.startswith(expected_prefix)
            for v in PRIORITY_BADGE_MAP.values())
)
print("  keys:", sorted(PRIORITY_BADGE_MAP.keys()))
print("  values:", list(PRIORITY_BADGE_MAP.values()))
print("T239:", "PASS" if ok else "FAIL")
results["T239"] = ok


# ============================================================
print()
print("=" * 72)
print("T240 - Trigger config escalation_minutes coverage")
print("=" * 72)
# Per M8 clarification A: sla_passed and manual both legitimately
# carry escalation_minutes=0 (the alert IS the SLA breach, the
# manual config has no trigger-side timing). All other configs
# must be > 0 and not NULL.
cfgs = env["action.centre.trigger.config"].search([])
zero_allowed = {"sla_passed", "manual"}
problems = []
for c in cfgs:
    if c.escalation_minutes is False or c.escalation_minutes is None:
        problems.append((c.trigger_type, "NULL"))
    elif c.escalation_minutes <= 0 and c.trigger_type not in zero_allowed:
        problems.append((c.trigger_type, c.escalation_minutes))
ok = len(problems) == 0 and len(cfgs) == 10
print("  total configs:", len(cfgs), "(want 10)")
print("  problematic configs:", problems, "(want [])")
print("T240:", "PASS" if ok else "FAIL")
results["T240"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T230", "T231", "T232", "T233", "T234", "T235", "T236",
         "T237", "T238", "T239", "T240"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
skipped = sum(1 for k in order if results.get(k) is None)
print()
print("Total: {}/{} passed ({} skipped per design)".format(
    passed, len(order) - skipped, skipped))

env.cr.commit()
