"""P4.M7 smoke — final 3 triggers + Bug A + Bug B + D5 chatter.

T216 scope_change fires on commercial.scope.change create
T217 scope_change idempotency (re-trigger → still 1 item)
T218 feedback_followup fires on create with is_follow_up_required=True
T219 feedback_followup does NOT fire when is_follow_up_required=False
T220 feedback_followup fires on write() flip False→True
T221 feedback_followup auto-closes on follow_up_completed=True
T222 sla_passed cron fires for 14+ day completed event_jobs
T223 sla_passed cron is idempotent
T224 feedback_followup cron backfill catches missed records
T225 Bug A — auto-assignment from event_job.lead_tech_id
T226 Bug B — auto-close writes auto_closed history row
T227 D5 — chatter on readiness_70 condition cleared (task stays open)
T228 TRIGGER_REGISTRY has all 10 entries with renderable templates
"""
from datetime import timedelta

from odoo import fields


print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
print("client:", client.name, "venue:", venue.name)

# Cleanup prior P4M7 fixtures (items, feedback, scope_change, jobs)
ItemModel = env["action.centre.item"].sudo()
ItemModel.search([("title", "like", "%P4M7FIX%")]).unlink()
env["commercial.scope.change"].sudo().search(
    [("description", "like", "P4M7FIX%")]).unlink()
env["commercial.event.feedback"].sudo().search(
    [("feedback_text", "like", "P4M7FIX%")]).unlink()
prior_jobs = env["commercial.job"].sudo().search(
    [("equipment_summary", "like", "P4M7FIX%")])
env["commercial.event.job"].sudo().search(
    [("commercial_job_id", "in", prior_jobs.ids)]).unlink()
prior_jobs.unlink()
env.cr.commit()


def _new_job_with_event(label, day_offset=60, lead_tech=None):
    """Create commercial.job, activate it, optionally set lead tech."""
    J = env["commercial.job"].sudo().create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.add(fields.Date.today(),
                                       days=day_offset),
        "currency_id": env.company.currency_id.id,
        "equipment_summary": "P4M7FIX " + label,
    })
    J.write({"state": "active", "soft_hold_until": False})
    EJ = J.event_job_ids[:1]
    if lead_tech and EJ:
        EJ.lead_tech_id = lead_tech.id
    return J, EJ


def _items_for(record, trigger_type):
    src_model = env["ir.model"].sudo().search(
        [("model", "=", record._name)], limit=1)
    return env["action.centre.item"].sudo().search([
        ("source_model_id", "=", src_model.id),
        ("source_id", "=", record.id),
        ("trigger_type", "=", trigger_type),
    ])


results = {}


# ============================================================
print()
print("=" * 72)
print("T216 - scope_change fires on commercial.scope.change create")
print("=" * 72)
J216, EJ216 = _new_job_with_event("T216", 30, lead_tech=crew_leader)
sc216 = env["commercial.scope.change"].sudo().create({
    "event_job_id": EJ216.id,
    "description": "P4M7FIX T216 — added pyrotechnics package on-site",
    "scope_change_type": "addition",
})
items = _items_for(sc216, "scope_change")
ok = (
    len(items) == 1
    and items.item_type == "task"
    and items.primary_role == "lead_tech"
    and EJ216.name in items.title
    and items.primary_assignee_id == crew_leader
)
print("  scope_change items:", len(items), "(want 1)")
if items:
    print("  item_type:", items.item_type,
          "primary_role:", items.primary_role)
    print("  title:", items.title)
    print("  primary_assignee:", items.primary_assignee_id.login,
          "(want", crew_leader.login + ")")
print("T216:", "PASS" if ok else "FAIL")
results["T216"] = ok


# ============================================================
print()
print("=" * 72)
print("T217 - scope_change idempotency")
print("=" * 72)
# Re-trigger explicitly — should not duplicate
sc216.sudo()._action_centre_create_item("scope_change")
items_after = _items_for(sc216, "scope_change")
ok = len(items_after) == 1
print("  items after re-trigger:", len(items_after), "(want 1)")
print("T217:", "PASS" if ok else "FAIL")
results["T217"] = ok


# ============================================================
print()
print("=" * 72)
print("T218 - feedback_followup fires on create (is_follow_up_required=True)")
print("=" * 72)
J218, EJ218 = _new_job_with_event("T218", 30, lead_tech=crew_leader)
fb218 = env["commercial.event.feedback"].sudo().create({
    "event_job_id": EJ218.id,
    "channel": "phone",
    "feedback_text": "P4M7FIX T218 — client unhappy with AV setup",
    "sentiment": "negative",
    "is_follow_up_required": True,
    "follow_up_owner": manager.id,
})
items = _items_for(fb218, "feedback_followup")
ok = (
    len(items) == 1
    and items.item_type == "task"
    and items.primary_role == "manager"
    and items.primary_assignee_id == manager
)
print("  feedback_followup items:", len(items), "(want 1)")
if items:
    print("  item_type:", items.item_type,
          "primary_role:", items.primary_role)
    print("  primary_assignee:", items.primary_assignee_id.login,
          "(want", manager.login + ")")
print("T218:", "PASS" if ok else "FAIL")
results["T218"] = ok


# ============================================================
print()
print("=" * 72)
print("T219 - feedback_followup does NOT fire when is_follow_up_required=False")
print("=" * 72)
J219, EJ219 = _new_job_with_event("T219", 30, lead_tech=crew_leader)
fb219 = env["commercial.event.feedback"].sudo().create({
    "event_job_id": EJ219.id,
    "channel": "email_survey",
    "feedback_text": "P4M7FIX T219 — client happy",
    "sentiment": "positive",
    "is_follow_up_required": False,
})
items = _items_for(fb219, "feedback_followup")
ok = len(items) == 0
print("  feedback_followup items:", len(items), "(want 0)")
print("T219:", "PASS" if ok else "FAIL")
results["T219"] = ok


# ============================================================
print()
print("=" * 72)
print("T220 - feedback_followup fires on write() flip False→True")
print("=" * 72)
J220, EJ220 = _new_job_with_event("T220", 30, lead_tech=crew_leader)
fb220 = env["commercial.event.feedback"].sudo().create({
    "event_job_id": EJ220.id,
    "channel": "phone",
    "feedback_text": "P4M7FIX T220 — neutral, no follow-up flagged",
    "sentiment": "neutral",
    "is_follow_up_required": False,
})
items_pre = _items_for(fb220, "feedback_followup")
fb220.sudo().write({
    "is_follow_up_required": True,
    "follow_up_owner": manager.id,
})
items_post = _items_for(fb220, "feedback_followup")
ok = len(items_pre) == 0 and len(items_post) == 1
print("  items pre-flip:", len(items_pre), "(want 0)",
      "post-flip:", len(items_post), "(want 1)")
print("T220:", "PASS" if ok else "FAIL")
results["T220"] = ok


# ============================================================
print()
print("=" * 72)
print("T221 - feedback_followup auto-closes on follow_up_completed=True")
print("=" * 72)
# Reuse fb218 from T218 which has an open feedback_followup item
items_open = _items_for(fb218, "feedback_followup").filtered(
    lambda i: i.state in ("open", "in_progress"))
print("  items open pre-complete:", len(items_open), "(want 1)")
fb218.sudo().write({
    "follow_up_completed": True,
    "follow_up_completed_at": fields.Datetime.now(),
    "follow_up_completed_by": manager.id,
})
items_after = _items_for(fb218, "feedback_followup")
ok = (
    len(items_open) == 1
    and len(items_after) == 1
    and items_after.state == "cancelled"
)
print("  item state after complete:", items_after.state,
      "(want cancelled)")
print("T221:", "PASS" if ok else "FAIL")
results["T221"] = ok


# ============================================================
print()
print("=" * 72)
print("T222 - sla_passed cron fires for 14+ day completed events")
print("=" * 72)
J222, EJ222 = _new_job_with_event("T222", -15, lead_tech=crew_leader)
EJ222.sudo().with_context(_allow_state_write=True).write({
    "state": "completed",
})
EJ222.invalidate_recordset()
env["commercial.event.job"].sudo()._evaluate_sla_passed_trigger()
items = _items_for(EJ222, "sla_passed")
ok = (
    len(items) == 1
    and items.item_type == "alert"
    and items.primary_role == "manager"
)
print("  sla_passed items:", len(items), "(want 1)")
if items:
    print("  item_type:", items.item_type,
          "primary_role:", items.primary_role)
print("T222:", "PASS" if ok else "FAIL")
results["T222"] = ok


# ============================================================
print()
print("=" * 72)
print("T223 - sla_passed cron idempotency")
print("=" * 72)
env["commercial.event.job"].sudo()._evaluate_sla_passed_trigger()
items_after = _items_for(EJ222, "sla_passed")
ok = len(items_after) == 1
print("  sla_passed items after 2nd run:", len(items_after),
      "(want 1)")
print("T223:", "PASS" if ok else "FAIL")
results["T223"] = ok


# ============================================================
print()
print("=" * 72)
print("T224 - feedback_followup cron backfill")
print("=" * 72)
# Create a feedback record then manually delete the spawned item to
# simulate "record loaded without firing the real-time trigger".
J224, EJ224 = _new_job_with_event("T224", 30, lead_tech=crew_leader)
fb224 = env["commercial.event.feedback"].sudo().create({
    "event_job_id": EJ224.id,
    "channel": "phone",
    "feedback_text": "P4M7FIX T224 — backfill scenario",
    "sentiment": "negative",
    "is_follow_up_required": True,
    "follow_up_owner": manager.id,
})
_items_for(fb224, "feedback_followup").unlink()
items_pre_cron = _items_for(fb224, "feedback_followup")
env["commercial.event.feedback"].sudo()._evaluate_feedback_followup_backfill()
items_post_cron = _items_for(fb224, "feedback_followup")
ok = len(items_pre_cron) == 0 and len(items_post_cron) == 1
print("  items pre-cron:", len(items_pre_cron), "(want 0)",
      "post-cron:", len(items_post_cron), "(want 1)")
print("T224:", "PASS" if ok else "FAIL")
results["T224"] = ok


# ============================================================
print()
print("=" * 72)
print("T225 - Bug A: auto-assignment from event_job.lead_tech_id")
print("=" * 72)
# Create event_job with lead_tech set, delete the auto-spawned
# event_created item (which fired before our timing window), then
# re-trigger via the mixin on the fully populated source. The
# PREFERRED_ASSIGNEE_FIELDS lookup should now find lead_tech_id and
# auto-fill primary_assignee_id without any explicit kwarg.
J225, EJ225 = _new_job_with_event("T225", 30, lead_tech=crew_leader)
_items_for(EJ225, "event_created").unlink()
EJ225.invalidate_recordset()
new_item = EJ225.sudo()._action_centre_create_item("event_created")
ok = (
    new_item
    and new_item.primary_role == "lead_tech"
    and new_item.primary_assignee_id == crew_leader
)
print("  new item primary_assignee:",
      new_item.primary_assignee_id.login if new_item else "(none)",
      "(want", crew_leader.login + ")")
print("T225:", "PASS" if ok else "FAIL")
results["T225"] = ok


# ============================================================
print()
print("=" * 72)
print("T226 - Bug B: auto-close writes auto_closed history row")
print("=" * 72)
# Drive an event_job into a low-readiness state to spawn readiness_50,
# then recover to trigger the auto-close path. The auto_closed history
# row must land.
J226, EJ226 = _new_job_with_event("T226", 30, lead_tech=crew_leader)
# Force readiness_50 via direct compute-trigger eval — readiness_50
# fires on scores below 50. The empty-event default already lands
# well below 50, so trigger evaluation alone should spawn it.
EJ226._evaluate_readiness_triggers()
items_open = _items_for(EJ226, "readiness_50").filtered(
    lambda i: i.state in ("open", "in_progress"))
print("  readiness_50 items open:", len(items_open), "(want >= 1)")
if items_open:
    target = items_open[0]
    pre_close_state = target.state
    # Trigger the auto-close path. _action_centre_close_items only
    # closes auto-eligible items; readiness_50 (alert with
    # auto_close=True) is eligible.
    EJ226._action_centre_close_items("readiness_50")
    target.invalidate_recordset()
    auto_closed_rows = target.history_ids.filtered(
        lambda h: h.event_type == "auto_closed"
    )
    ok = (
        target.state == "cancelled"
        and len(auto_closed_rows) == 1
        and auto_closed_rows.actor_is_system
        and auto_closed_rows.from_value == pre_close_state
        and auto_closed_rows.to_value == "cancelled"
    )
    print("  item state:", target.state, "(want cancelled)")
    print("  auto_closed rows:", len(auto_closed_rows), "(want 1)")
    if auto_closed_rows:
        print("  from_value:", auto_closed_rows.from_value,
              "to_value:", auto_closed_rows.to_value,
              "is_system:", auto_closed_rows.actor_is_system)
else:
    ok = False
    print("  readiness_50 did not spawn — cannot test Bug B")
print("T226:", "PASS" if ok else "FAIL")
results["T226"] = ok


# ============================================================
print()
print("=" * 72)
print("T227 - D5: chatter on readiness_70 condition cleared")
print("=" * 72)
# Spawn a readiness_70 task: event within 3 days, readiness below 70.
J227, EJ227 = _new_job_with_event("T227", 2, lead_tech=crew_leader)
EJ227._evaluate_readiness_triggers()
items_70 = _items_for(EJ227, "readiness_70")
print("  readiness_70 items spawned:", len(items_70), "(want >= 1)")
if items_70:
    target = items_70[0]
    msg_count_pre = len(target.message_ids)
    # Force the "condition cleared" path. Easiest way without
    # touching real readiness fields is to push the event_date out
    # past 3 days, which the helper's `days_to_event >= 3` branch
    # treats as cleared.
    EJ227.sudo().write({
        "event_date": fields.Date.add(fields.Date.today(), days=10),
    })
    EJ227.invalidate_recordset()
    EJ227._evaluate_readiness_triggers()
    target.invalidate_recordset()
    msg_count_post = len(target.message_ids)
    matching = target.message_ids.filtered(
        lambda m: m.body and "Condition cleared" in (m.body or "")
    )
    ok = (
        target.state in ("open", "in_progress")
        and len(matching) >= 1
    )
    print("  task state:", target.state, "(want open/in_progress)")
    print("  chatter messages pre:", msg_count_pre,
          "post:", msg_count_post)
    print("  'Condition cleared' messages:", len(matching),
          "(want >= 1)")
else:
    ok = False
    print("  readiness_70 did not spawn — cannot test D5 chatter")
print("T227:", "PASS" if ok else "FAIL")
results["T227"] = ok


# ============================================================
print()
print("=" * 72)
print("T228 - TRIGGER_REGISTRY has 10 entries with renderable templates")
print("=" * 72)
from odoo.addons.neon_jobs.models.action_centre_mixin import TRIGGER_REGISTRY
keys = list(TRIGGER_REGISTRY.keys())
expected = {
    "capacity_gate", "lost", "event_created", "readiness_50",
    "readiness_70", "scope_change", "closeout_overdue",
    "sla_passed", "feedback_followup", "manual",
}
ok = set(keys) == expected and len(keys) == 10
print("  keys (", len(keys), "):", sorted(keys))
print("  template count:",
      sum(1 for k, v in TRIGGER_REGISTRY.items()
          if v.get("default_title")),
      "(want 10)")
all_have_templates = all(
    bool(v.get("default_title")) for v in TRIGGER_REGISTRY.values()
)
ok = ok and all_have_templates
print("T228:", "PASS" if ok else "FAIL")
results["T228"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T216", "T217", "T218", "T219", "T220", "T221", "T222",
         "T223", "T224", "T225", "T226", "T227", "T228"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.commit()
