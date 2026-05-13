"""P4.M4 smoke — escalation logic + cron + history audit.

T192 history row on state change (mark in progress)
T193 history row on cancel (via wizard)
T194 history row on manager reassignment
T195 cron escalation fires and writes history
T196 cron escalation idempotent (twice in sequence → one increment)
T197 escalation cap (level=3 → no further escalation)
T198 escalation failure logged when no user in role
T199 history append-only — write/unlink raise even for admin
T200 time-based cron stub runs without error
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError


print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login)

# Clean prior P4M4 fixtures
prior = env["action.centre.item"].sudo().search(
    [("title", "like", "P4M4FIX%")])
print("cleaning", len(prior), "prior items (+ cascade their history)")
prior.unlink()
env.cr.commit()


def _make(title, assignee=None, priority="medium", trigger_type=None,
          trigger_config_xmlid=None, user=None):
    Item = env["action.centre.item"]
    if user:
        Item = Item.with_user(user)
    vals = {
        "title": "P4M4FIX " + title,
        "priority": priority,
    }
    if assignee:
        vals["primary_assignee_id"] = assignee.id
    if trigger_type:
        vals["trigger_type"] = trigger_type
    if trigger_config_xmlid:
        cfg = env.ref(trigger_config_xmlid)
        vals["trigger_config_id"] = cfg.id
        vals["is_manual"] = False
    return Item.create(vals)


results = {}

# ============================================================
print()
print("=" * 72)
print("T192 - History row on state change (created + state_change)")
print("=" * 72)
i192 = _make("T192", assignee=sales, user=sales)
# Should already have 1 'created' row from the create() hook
i192.invalidate_recordset()
created_rows = i192.history_ids.filtered(lambda h: h.event_type == "created")
i192.with_user(sales).action_mark_in_progress()
i192.invalidate_recordset()
state_rows = i192.history_ids.filtered(
    lambda h: h.event_type == "state_change"
    and h.from_value == "open"
    and h.to_value == "in_progress"
)
ok = (
    len(created_rows) == 1
    and len(state_rows) == 1
    and state_rows.actor_id == sales
    and not state_rows.actor_is_system
)
print("  created rows:    ", len(created_rows), "(want 1)")
print("  state_change rows: ", len(state_rows), "(want 1)")
if state_rows:
    print("  state row actor: ", state_rows.actor_id.login,
          "is_system:", state_rows.actor_is_system)
print("T192:", "PASS" if ok else "FAIL")
results["T192"] = ok


# ============================================================
print()
print("=" * 72)
print("T193 - History row on cancel (via wizard)")
print("=" * 72)
i193 = _make("T193", assignee=sales, user=sales)
i193.invalidate_recordset()
prior_state = i193.state
wiz = env["action.centre.item.cancel.wizard"].with_user(manager).create({
    "item_id": i193.id,
    "closure_reason": "T193 — testing cancel history hook",
})
wiz.action_confirm()
i193.invalidate_recordset()
cancel_rows = i193.history_ids.filtered(
    lambda h: h.event_type == "state_change"
    and h.from_value == prior_state
    and h.to_value == "cancelled"
)
ok = (
    i193.state == "cancelled"
    and len(cancel_rows) == 1
    and cancel_rows.actor_id == manager
    and not cancel_rows.actor_is_system
)
print("  state:", i193.state, "(want cancelled)")
print("  cancel history rows:", len(cancel_rows), "(want 1)")
if cancel_rows:
    print("  actor:", cancel_rows.actor_id.login,
          "from:", cancel_rows.from_value, "to:", cancel_rows.to_value)
print("T193:", "PASS" if ok else "FAIL")
results["T193"] = ok


# ============================================================
print()
print("=" * 72)
print("T194 - History row on manager reassignment")
print("=" * 72)
i194 = _make("T194", assignee=sales, user=sales)
i194.invalidate_recordset()
i194.with_user(manager).write({"primary_assignee_id": crew_leader.id})
i194.invalidate_recordset()
reassign_rows = i194.history_ids.filtered(
    lambda h: h.event_type == "reassigned"
)
ok = (
    len(reassign_rows) == 1
    and reassign_rows.actor_id == manager
    and not reassign_rows.actor_is_system
    and sales.name in (reassign_rows.from_value or "")
    and crew_leader.name in (reassign_rows.to_value or "")
)
print("  reassigned rows:", len(reassign_rows), "(want 1)")
if reassign_rows:
    print("  from:", reassign_rows.from_value,
          "to:", reassign_rows.to_value,
          "actor:", reassign_rows.actor_id.login,
          "is_system:", reassign_rows.actor_is_system)
print("T194:", "PASS" if ok else "FAIL")
results["T194"] = ok


# ============================================================
print()
print("=" * 72)
print("T195 - Cron escalation fires")
print("=" * 72)
# capacity_gate has primary_role='manager' and escalation_minutes=240
# (4h), escalated_to_role='manager'. Build an item with this trigger
# and backdate it 5h so the escalation window has elapsed.
i195 = _make("T195", assignee=manager, priority="high",
              trigger_type="capacity_gate",
              trigger_config_xmlid="neon_jobs.trigger_config_capacity_gate")
i195.invalidate_recordset()
# Backdate create_date via direct SQL (ORM doesn't allow create_date writes)
env.cr.execute(
    "UPDATE action_centre_item SET create_date = %s WHERE id = %s",
    (fields.Datetime.subtract(fields.Datetime.now(), hours=5), i195.id),
)
env.cr.commit()
i195.invalidate_recordset()
pre_level = i195.escalation_level
pre_assignee = i195.primary_assignee_id
# Run the cron
env["action.centre.item"]._cron_check_escalations()
i195.invalidate_recordset()
escalated_rows = i195.history_ids.filtered(
    lambda h: h.event_type == "escalated"
)
ok = (
    pre_level == 0
    and i195.escalation_level == 1
    and bool(i195.escalated_at)
    and bool(i195.escalated_to_id)
    and i195.primary_assignee_id != pre_assignee
    and len(escalated_rows) == 1
    and escalated_rows.actor_is_system is True
)
print("  pre-level:", pre_level, "→ post:", i195.escalation_level)
print("  pre-assignee:", pre_assignee.login if pre_assignee else "(none)",
      "→ post:", i195.primary_assignee_id.login if i195.primary_assignee_id else "(none)")
print("  escalated_at:", bool(i195.escalated_at),
      "escalated_to:", i195.escalated_to_id.login if i195.escalated_to_id else "(none)")
print("  escalated history rows:", len(escalated_rows),
      "is_system:", escalated_rows.actor_is_system if escalated_rows else "(n/a)")
print("T195:", "PASS" if ok else "FAIL")
results["T195"] = ok


# ============================================================
print()
print("=" * 72)
print("T196 - Cron escalation idempotent (twice in sequence)")
print("=" * 72)
# i195 was just escalated. Re-run cron immediately — escalated_at is
# now() so the window hasn't elapsed; should NOT escalate again.
level_before_2nd_cron = i195.escalation_level
env["action.centre.item"]._cron_check_escalations()
i195.invalidate_recordset()
ok = i195.escalation_level == level_before_2nd_cron
print("  level before 2nd cron:", level_before_2nd_cron,
      "→ after:", i195.escalation_level, "(should be unchanged)")
print("T196:", "PASS" if ok else "FAIL")
results["T196"] = ok


# ============================================================
print()
print("=" * 72)
print("T197 - Escalation cap respected (level=3 → no further)")
print("=" * 72)
i197 = _make("T197", assignee=sales, priority="high",
              trigger_type="capacity_gate",
              trigger_config_xmlid="neon_jobs.trigger_config_capacity_gate")
# Force escalation_level to 3 via sudo write (bypass the ORM gate;
# the _allow_state_write context is irrelevant here since we're
# only touching escalation_level)
i197.sudo().write({"escalation_level": 3})
# Also backdate so the window has elapsed
env.cr.execute(
    "UPDATE action_centre_item SET create_date = %s WHERE id = %s",
    (fields.Datetime.subtract(fields.Datetime.now(), hours=10), i197.id),
)
env.cr.commit()
i197.invalidate_recordset()
escalated_rows_pre = len(i197.history_ids.filtered(
    lambda h: h.event_type == "escalated"))
env["action.centre.item"]._cron_check_escalations()
i197.invalidate_recordset()
escalated_rows_post = len(i197.history_ids.filtered(
    lambda h: h.event_type == "escalated"))
ok = (
    i197.escalation_level == 3
    and escalated_rows_post == escalated_rows_pre
)
print("  level: 3 → ", i197.escalation_level, "(should stay 3)")
print("  escalated rows: ", escalated_rows_pre, "→",
      escalated_rows_post, "(should be unchanged)")
print("T197:", "PASS" if ok else "FAIL")
results["T197"] = ok


# ============================================================
print()
print("=" * 72)
print("T198 - Escalation failure logged when no user in role")
print("=" * 72)
# Use the readiness_50 config which has escalated_to_role=manager,
# but for the FAILURE case we need a role with NO users. Patch the
# trigger config to escalated_to_role='crew_chief' (which has no
# Neon group at all), so _resolve_escalation_user returns empty.
cfg_198 = env.ref("neon_jobs.trigger_config_readiness_50").sudo()
prior_role_198 = cfg_198.escalated_to_role
cfg_198.write({"escalated_to_role": "crew_chief"})
i198 = _make("T198", assignee=sales, priority="high",
              trigger_type="readiness_50",
              trigger_config_xmlid="neon_jobs.trigger_config_readiness_50")
env.cr.execute(
    "UPDATE action_centre_item SET create_date = %s WHERE id = %s",
    (fields.Datetime.subtract(fields.Datetime.now(), hours=10), i198.id),
)
env.cr.commit()
i198.invalidate_recordset()
pre_assignee_198 = i198.primary_assignee_id
env["action.centre.item"]._cron_check_escalations()
i198.invalidate_recordset()
fail_rows = i198.history_ids.filtered(
    lambda h: h.event_type == "escalation_failed"
)
ok = (
    len(fail_rows) == 1
    and i198.primary_assignee_id == pre_assignee_198
    and fail_rows.actor_is_system is True
)
print("  escalation_failed rows:", len(fail_rows), "(want 1)")
print("  primary_assignee unchanged?",
      i198.primary_assignee_id == pre_assignee_198)
if fail_rows:
    print("  fail row to_value:", fail_rows.to_value,
          "actor_is_system:", fail_rows.actor_is_system)
# Restore config
cfg_198.write({"escalated_to_role": prior_role_198})
env.cr.commit()
print("T198:", "PASS" if ok else "FAIL")
results["T198"] = ok


# ============================================================
print()
print("=" * 72)
print("T199 - History append-only (write/unlink raise)")
print("=" * 72)
i199 = _make("T199", assignee=sales, user=sales)
i199.invalidate_recordset()
hist_row = i199.history_ids[:1]
if not hist_row:
    print("  SKIP — no history row to test against")
    results["T199"] = None
else:
    # Try to write (should raise UserError, even as admin)
    write_blocked = False
    try:
        hist_row.sudo().write({"to_value": "tampered"})
    except UserError:
        write_blocked = True
    # Try to unlink (should raise UserError)
    unlink_blocked = False
    try:
        hist_row.sudo().unlink()
    except UserError:
        unlink_blocked = True
    ok = write_blocked and unlink_blocked
    print("  write blocked? ", write_blocked, "(want True)")
    print("  unlink blocked?", unlink_blocked, "(want True)")
    print("T199:", "PASS" if ok else "FAIL")
    results["T199"] = ok


# ============================================================
print()
print("=" * 72)
print("T200 - Time-based cron stub runs without error")
print("=" * 72)
try:
    rv = env["action.centre.item"]._cron_evaluate_time_based_triggers()
    ok = rv is True
    print("  cron returned:", rv, "(want True)")
except Exception as e:
    print(f"  cron raised {type(e).__name__}: {str(e)[:120]}")
    ok = False
print("T200:", "PASS" if ok else "FAIL")
results["T200"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T192", "T193", "T194", "T195", "T196", "T197", "T198",
         "T199", "T200"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.commit()
