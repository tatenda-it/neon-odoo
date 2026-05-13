"""P4.M2 smoke — trigger registry + mixin abstract.

T170 Trigger config seed records exist — all 10 trigger types.
T171 Mixin creates an item bound to a source (via runtime patch).
T172 Mixin idempotency — second call returns the existing item.
T173 is_auto_close_eligible compute matrix (alert+auto, alert+manual,
     task+auto, no config).
T174 Disabled trigger no-ops — config.is_enabled=False → empty rs.
T175 _action_centre_close_items respects auto_close_eligible — alert
     gets cancelled, task stays open.
T176 Configuration UI access — manager can read + write trigger.config.
T177 Configuration UI access — non-manager read-only on trigger.config.
T178 trigger_type Selection on action.centre.item shows all 10 values.

The mixin is tested by monkey-patching commercial.event.job to
include action.centre.mixin in its _inherit list for the duration
of the test. This avoids polluting the production model and keeps
P4.M2 from prematurely wiring P4.M5+ integration.
"""
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

# Clean prior P4M2 fixtures (items created from this smoke point at
# event_job source rows; their unlink cascades nothing important).
prior_items = env["action.centre.item"].sudo().search(
    [("title", "like", "P4M2FIX%")])
print("cleaning", len(prior_items), "prior items")
prior_items.unlink()
env.cr.commit()

# Snapshot the trigger configs we'll mutate so we can restore.
all_configs = env["action.centre.trigger.config"].sudo().search([])
config_snapshot = {
    c.trigger_type: (c.is_enabled, c.priority)
    for c in all_configs
}


results = {}

# ============================================================
print()
print("=" * 72)
print("T170 - Trigger config seed records exist")
print("=" * 72)
expected = {
    "capacity_gate", "lost", "event_created",
    "readiness_50", "readiness_70", "scope_change",
    "closeout_overdue", "sla_passed", "feedback_followup", "manual",
}
configs = env["action.centre.trigger.config"].sudo().search([])
got = set(configs.mapped("trigger_type"))
print("  total configs:", len(configs), "(want 10)")
print("  trigger types covered:", sorted(got))
ok = len(configs) == 10 and got == expected
print("T170:", "PASS" if ok else "FAIL")
results["T170"] = ok


# ============================================================
print()
print("=" * 72)
print("T173 - is_auto_close_eligible compute matrix")
print("=" * 72)
# Pull three configs that cover the matrix:
cfg_readiness_50 = env.ref("neon_jobs.trigger_config_readiness_50")
cfg_readiness_70 = env.ref("neon_jobs.trigger_config_readiness_70")

# Build four items directly (sudo bypasses authority checks; we're
# isolating compute logic here, not flow). Using is_manual=False so
# the form-level locks would apply in browser; trigger_config_id is
# allowed to be set on creation here because the field is readonly
# in the form only.
item_alert_auto = env["action.centre.item"].sudo().create({
    "title": "P4M2FIX T173_alert_auto",
    "item_type": "alert",
    "trigger_type": "readiness_50",
    "trigger_config_id": cfg_readiness_50.id,
    "is_manual": False,
})
item_alert_manual = env["action.centre.item"].sudo().create({
    "title": "P4M2FIX T173_alert_manual",
    "item_type": "alert",
    "trigger_type": "readiness_70",
    "trigger_config_id": cfg_readiness_70.id,  # auto_close=False
    "is_manual": False,
})
item_task_auto = env["action.centre.item"].sudo().create({
    "title": "P4M2FIX T173_task_auto",
    "item_type": "task",
    "trigger_type": "readiness_50",
    "trigger_config_id": cfg_readiness_50.id,  # cfg auto=True but type=task
    "is_manual": False,
})
item_no_cfg = env["action.centre.item"].sudo().create({
    "title": "P4M2FIX T173_no_cfg",
    "item_type": "alert",
    "trigger_type": "manual",
})
for it in (item_alert_auto, item_alert_manual, item_task_auto, item_no_cfg):
    it.invalidate_recordset()
ok = (
    item_alert_auto.is_auto_close_eligible is True
    and item_alert_manual.is_auto_close_eligible is False
    and item_task_auto.is_auto_close_eligible is False
    and item_no_cfg.is_auto_close_eligible is False
)
print("  alert + auto_close_cfg + cfg.auto=True:  ",
      item_alert_auto.is_auto_close_eligible, "(want True)")
print("  alert + cfg.auto=False:                  ",
      item_alert_manual.is_auto_close_eligible, "(want False)")
print("  task + cfg.auto=True (type wrong):       ",
      item_task_auto.is_auto_close_eligible, "(want False)")
print("  no trigger_config_id:                    ",
      item_no_cfg.is_auto_close_eligible, "(want False)")
print("T173:", "PASS" if ok else "FAIL")
results["T173"] = ok


# ============================================================
print()
print("=" * 72)
print("Patching commercial.event.job with action.centre.mixin")
print("=" * 72)
# Monkey-patch: register the mixin onto commercial.event.job for the
# duration of this smoke. We do this by adding the mixin's methods
# directly to the existing class — _inherit changes need a registry
# rebuild, which we can't do mid-shell. Direct method-attachment is
# safe because the mixin methods don't depend on any class state
# beyond what AbstractModel provides (and Model is-a AbstractModel).
from odoo.addons.neon_jobs.models.action_centre_mixin import ActionCentreMixin
EventJob = env["commercial.event.job"]
EventJob_cls = type(EventJob)
for method_name in (
    "_action_centre_create_item",
    "_action_centre_close_items",
    "_action_centre_get_items",
    "_action_centre_render_title",
):
    method = getattr(ActionCentreMixin, method_name)
    setattr(EventJob_cls, method_name, method)
print("  mixin methods bolted onto commercial.event.job for smoke")

# Fixture: any existing event_job to bind tasks to. We don't mutate
# its state — the items hang off it via source_model_id/source_id.
src_evt = env["commercial.event.job"].sudo().search([], limit=1)
print("  source event_job:", src_evt.name, "id=", src_evt.id)


# ============================================================
print()
print("=" * 72)
print("T171 - Mixin creates an item bound to source")
print("=" * 72)
# Make sure capacity_gate is enabled
cfg_cap = env.ref("neon_jobs.trigger_config_capacity_gate").sudo()
cfg_cap.write({"is_enabled": True})

item = src_evt._action_centre_create_item("capacity_gate")
item.invalidate_recordset()
src_model = env["ir.model"].sudo().search(
    [("model", "=", "commercial.event.job")], limit=1)
ok = (
    bool(item.id)
    and item.trigger_type == "capacity_gate"
    and item.trigger_config_id == cfg_cap
    and item.source_model_id == src_model
    and item.source_id == src_evt.id
    and item.primary_role == cfg_cap.primary_role  # 'manager'
    and item.priority == cfg_cap.priority  # 'high'
    and item.is_manual is False
)
print("  created item:", item.name, "trigger=", item.trigger_type)
print("  source:", item.source_model_id.model, "/", item.source_id)
print("  primary_role:", item.primary_role, "priority:", item.priority,
      "is_manual:", item.is_manual)
print("T171:", "PASS" if ok else "FAIL")
results["T171"] = ok


# ============================================================
print()
print("=" * 72)
print("T172 - Mixin idempotency")
print("=" * 72)
again = src_evt._action_centre_create_item("capacity_gate")
ok = again == item and again.id == item.id
print("  first id:", item.id, "second id:", again.id, "(want equal)")
print("T172:", "PASS" if ok else "FAIL")
results["T172"] = ok


# ============================================================
print()
print("=" * 72)
print("T174 - Disabled trigger no-ops")
print("=" * 72)
cfg_lost = env.ref("neon_jobs.trigger_config_lost").sudo()
cfg_lost.write({"is_enabled": False})
before_count = env["action.centre.item"].sudo().search_count(
    [("trigger_type", "=", "lost")])
result = src_evt._action_centre_create_item("lost")
after_count = env["action.centre.item"].sudo().search_count(
    [("trigger_type", "=", "lost")])
ok = (not result) and before_count == after_count
print("  before:", before_count, "after:", after_count,
      "result truthy?", bool(result))
print("T174:", "PASS" if ok else "FAIL")
results["T174"] = ok
# Restore lost config
cfg_lost.write({"is_enabled": True})


# ============================================================
print()
print("=" * 72)
print("T175 - _action_centre_close_items respects auto_close_eligible")
print("=" * 72)
# Bind one alert + one task to a fresh event_job so they don't
# collide with T171's capacity_gate item.
src_evt_b = env["commercial.event.job"].sudo().search(
    [("id", "!=", src_evt.id)], limit=1)
print("  second source event_job:", src_evt_b.name)
# Use readiness_50 (alert, auto-close=True) and readiness_70
# (task, auto-close=False) so both bind to this source.
alert_item = src_evt_b._action_centre_create_item("readiness_50")
task_item = src_evt_b._action_centre_create_item("readiness_70")
alert_item.invalidate_recordset()
task_item.invalidate_recordset()
print("  pre-close: alert state=", alert_item.state,
      "auto_eligible=", alert_item.is_auto_close_eligible,
      "; task state=", task_item.state,
      "auto_eligible=", task_item.is_auto_close_eligible)
closed = src_evt_b._action_centre_close_items()
alert_item.invalidate_recordset()
task_item.invalidate_recordset()
ok = (
    alert_item.state == "cancelled"
    and task_item.state == "open"
    and alert_item in closed
    and task_item not in closed
)
print("  closed recordset size:", len(closed))
print("  alert state after close:", alert_item.state, "(want cancelled)")
print("  task state after close: ", task_item.state, "(want open)")
print("T175:", "PASS" if ok else "FAIL")
results["T175"] = ok


# ============================================================
print()
print("=" * 72)
print("T176 - Manager can read + write trigger.config")
print("=" * 72)
cfg_cap_mgr = env["action.centre.trigger.config"].with_user(
    manager).search([("trigger_type", "=", "capacity_gate")], limit=1)
ok_read = bool(cfg_cap_mgr.id) and cfg_cap_mgr.priority == "high"
prior_priority = cfg_cap_mgr.priority
try:
    cfg_cap_mgr.write({"priority": "urgent"})
    ok_write = True
except Exception as e:
    print("  write failed:", type(e).__name__, str(e)[:120])
    ok_write = False
# Restore
cfg_cap_mgr.write({"priority": prior_priority})
print("  manager read OK?", ok_read)
print("  manager write OK?", ok_write)
ok = ok_read and ok_write
print("T176:", "PASS" if ok else "FAIL")
results["T176"] = ok


# ============================================================
print()
print("=" * 72)
print("T177 - Non-manager read-only on trigger.config")
print("=" * 72)
# Sales / lead can READ
ok_sales_read = bool(
    env["action.centre.trigger.config"].with_user(sales).search_count([]) >= 10
)
ok_lead_read = bool(
    env["action.centre.trigger.config"].with_user(crew_leader).search_count([]) >= 10
)
# Sales attempting to WRITE should raise AccessError
sales_write_blocked = False
try:
    env["action.centre.trigger.config"].with_user(sales).search(
        [("trigger_type", "=", "capacity_gate")], limit=1
    ).write({"priority": "urgent"})
except AccessError:
    sales_write_blocked = True
lead_write_blocked = False
try:
    env["action.centre.trigger.config"].with_user(crew_leader).search(
        [("trigger_type", "=", "capacity_gate")], limit=1
    ).write({"priority": "urgent"})
except AccessError:
    lead_write_blocked = True
ok = ok_sales_read and ok_lead_read and sales_write_blocked and lead_write_blocked
print("  sales read OK?", ok_sales_read,
      " write blocked?", sales_write_blocked)
print("  lead  read OK?", ok_lead_read,
      " write blocked?", lead_write_blocked)
print("T177:", "PASS" if ok else "FAIL")
results["T177"] = ok


# ============================================================
print()
print("=" * 72)
print("T178 - trigger_type Selection extended to all 10 values")
print("=" * 72)
fdef = env["action.centre.item"].fields_get(
    ["trigger_type"])["trigger_type"]
sel_values = set(v for v, _label in fdef["selection"])
expected_values = {
    "capacity_gate", "lost", "event_created", "readiness_50",
    "readiness_70", "scope_change", "closeout_overdue", "sla_passed",
    "feedback_followup", "manual",
}
ok = sel_values == expected_values
# Also: manual item default still 'manual'
fresh_manual = env["action.centre.item"].with_user(sales).create({
    "title": "P4M2FIX T178_manual_default",
})
ok = ok and fresh_manual.trigger_type == "manual"
print("  selection values:", sorted(sel_values))
print("  default trigger_type on manual create:",
      fresh_manual.trigger_type)
print("T178:", "PASS" if ok else "FAIL")
results["T178"] = ok


# ============================================================
# Restore configs in case smoke ran on a live DB
# ============================================================
for tt, (was_enabled, was_priority) in config_snapshot.items():
    c = env["action.centre.trigger.config"].sudo().search(
        [("trigger_type", "=", tt)], limit=1)
    if c:
        c.write({"is_enabled": was_enabled, "priority": was_priority})
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T170", "T171", "T172", "T173", "T174", "T175", "T176", "T177", "T178"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
