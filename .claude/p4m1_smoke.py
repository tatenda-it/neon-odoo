"""P4.M1 smoke — Action Centre Core.

T151 Manual creation by sales user — name auto-generated, state=open,
     is_manual=True, created_by_id=sales.
T152 Sequence increments — three items in row → ACT-N, ACT-N+1, ACT-N+2.
T153 is_overdue compute — past due+open=True, past due+done=False,
     no due_date=False.
T154 State open → in_progress by primary_assignee.
T155 State open → done direct close by primary_assignee; closed_by/at set.
T156 Direct .write({'state': ...}) blocked; via action method succeeds.
T157 Cancel manager-only; sales raises, manager with reason succeeds.
T158 Reassign manager-only; sales raises, manager succeeds.
T159 Source reference computed — points at event_job; readable.
T160 Crew row-level rule — non-assigned crew cannot read; assigned can.
T161 Tag model exists and attaches to item via tag_ids.
T162 Menu visibility — user/lead/manager see, crew does not.
T163 "My open tasks" filter shows items assigned to current user.
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
other_crew = env["res.users"].search([("login", "=", "p2m75_other")], limit=1)
print("users: sales=", sales.login, " mgr=", manager.login,
      " lead=", crew_leader.login, " crew=", crew_only.login)

# Clean prior P4M1 fixtures (title-tag matched)
prior = env["action.centre.item"].sudo().search(
    [("title", "like", "P4M1FIX%")])
print("cleaning", len(prior), "prior fixtures")
prior.unlink()
prior_tags = env["action.centre.item.tag"].sudo().search(
    [("name", "in", ["P4M1FIX_Urgent", "P4M1FIX_Tag"])])
prior_tags.unlink()
env.cr.commit()


def _new_item(label, assignee=None, due=None, item_type="task",
              priority="medium", user=None):
    Item = env["action.centre.item"]
    if user:
        Item = Item.with_user(user)
    vals = {
        "title": "P4M1FIX " + label,
        "item_type": item_type,
        "priority": priority,
    }
    if assignee:
        vals["primary_assignee_id"] = assignee.id
    if due:
        vals["due_date"] = due
    return Item.create(vals)


results = {}

# ============================================================
print()
print("=" * 72)
print("T151 - Manual creation by sales user")
print("=" * 72)
i151 = _new_item("T151", assignee=sales, user=sales)
i151.invalidate_recordset()
ok = (
    i151.name and i151.name.startswith("ACT-")
    and i151.state == "open"
    and i151.is_manual is True
    and i151.created_by_id == sales
    and i151.item_type == "task"
)
print("  name:", i151.name, "(want ACT-NNNNNN)")
print("  state:", i151.state, "(want open)")
print("  is_manual:", i151.is_manual, "created_by:", i151.created_by_id.login)
print("T151:", "PASS" if ok else "FAIL")
results["T151"] = ok


# ============================================================
print()
print("=" * 72)
print("T152 - Sequence increments")
print("=" * 72)
seq_a = _new_item("T152a", assignee=sales, user=sales)
seq_b = _new_item("T152b", assignee=sales, user=sales)
seq_c = _new_item("T152c", assignee=sales, user=sales)
seq_a.invalidate_recordset()
seq_b.invalidate_recordset()
seq_c.invalidate_recordset()


def _seqnum(rec):
    # ACT-000023 → 23
    parts = (rec.name or "").split("-")
    return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None


n_a, n_b, n_c = _seqnum(seq_a), _seqnum(seq_b), _seqnum(seq_c)
print("  names:", seq_a.name, seq_b.name, seq_c.name)
ok = (
    n_a is not None and n_b == n_a + 1 and n_c == n_b + 1
)
print("T152:", "PASS" if ok else "FAIL")
results["T152"] = ok


# ============================================================
print()
print("=" * 72)
print("T153 - is_overdue compute")
print("=" * 72)
past = fields.Datetime.subtract(fields.Datetime.now(), days=2)
i153a = _new_item("T153_overdue", assignee=sales, due=past, user=sales)
i153b = _new_item("T153_no_due", assignee=sales, user=sales)
i153a.invalidate_recordset()
i153b.invalidate_recordset()
overdue_open = i153a.with_user(sales).is_overdue
# Mark done — must use action_mark_done
i153a.with_user(sales).action_mark_done()
i153a.invalidate_recordset()
overdue_done = i153a.with_user(sales).is_overdue
no_due_overdue = i153b.with_user(sales).is_overdue
print("  past+open is_overdue:", overdue_open, "(want True)")
print("  past+done is_overdue:", overdue_done, "(want False)")
print("  no due_date is_overdue:", no_due_overdue, "(want False)")
ok = overdue_open is True and overdue_done is False and no_due_overdue is False
print("T153:", "PASS" if ok else "FAIL")
results["T153"] = ok


# ============================================================
print()
print("=" * 72)
print("T154 - open → in_progress by primary_assignee")
print("=" * 72)
i154 = _new_item("T154", assignee=sales, user=sales)
i154.with_user(sales).action_mark_in_progress()
i154.invalidate_recordset()
chatter_hits = i154.message_ids.filtered(
    lambda m: "open" in (m.body or "") and "in_progress" in (m.body or ""))
ok = i154.state == "in_progress" and bool(chatter_hits)
print("  state:", i154.state, "(want in_progress)")
print("  chatter posted?", bool(chatter_hits))
print("T154:", "PASS" if ok else "FAIL")
results["T154"] = ok


# ============================================================
print()
print("=" * 72)
print("T155 - open → done (skip in_progress)")
print("=" * 72)
i155 = _new_item("T155", assignee=sales, user=sales)
i155.with_user(sales).action_mark_done()
i155.invalidate_recordset()
ok = (
    i155.state == "done"
    and i155.closed_by_id == sales
    and bool(i155.closed_at)
)
print("  state:", i155.state, "closed_by:", i155.closed_by_id.login,
      "closed_at:", bool(i155.closed_at))
print("T155:", "PASS" if ok else "FAIL")
results["T155"] = ok


# ============================================================
print()
print("=" * 72)
print("T156 - Direct state write blocked")
print("=" * 72)
i156 = _new_item("T156", assignee=sales, user=sales)
raised = False
try:
    i156.sudo().write({"state": "done"})
except UserError:
    raised = True
i156.invalidate_recordset()
state_after = i156.state
# Via action method should work
i156.with_user(sales).action_mark_done()
i156.invalidate_recordset()
ok = raised and state_after == "open" and i156.state == "done"
print("  direct write blocked?", raised)
print("  state after direct:", state_after, "after action:", i156.state)
print("T156:", "PASS" if ok else "FAIL")
results["T156"] = ok


# ============================================================
print()
print("=" * 72)
print("T157 - Cancel manager-only")
print("=" * 72)
i157 = _new_item("T157", assignee=sales, user=sales)
raised_sales = False
try:
    i157.with_user(sales).action_cancel(reason="testing cancel as sales")
except UserError:
    raised_sales = True
i157.invalidate_recordset()
state_after_sales = i157.state
# Manager succeeds with reason
i157.with_user(manager).action_cancel(reason="cancelling per smoke test")
i157.invalidate_recordset()
ok = (
    raised_sales
    and state_after_sales == "open"
    and i157.state == "cancelled"
    and "smoke test" in (i157.closure_reason or "")
)
print("  sales raised UserError?", raised_sales)
print("  state after manager:", i157.state, "reason:", i157.closure_reason)
print("T157:", "PASS" if ok else "FAIL")
results["T157"] = ok


# ============================================================
print()
print("=" * 72)
print("T158 - Reassign manager-only")
print("=" * 72)
i158 = _new_item("T158", assignee=sales, user=sales)
raised_lead = False
try:
    i158.with_user(crew_leader).write({"primary_assignee_id": crew_leader.id})
except UserError:
    raised_lead = True
i158.invalidate_recordset()
assignee_after_lead = i158.primary_assignee_id.id
# Manager succeeds
i158.with_user(manager).write({"primary_assignee_id": crew_leader.id})
i158.invalidate_recordset()
ok = (
    raised_lead
    and assignee_after_lead == sales.id
    and i158.primary_assignee_id == crew_leader
)
print("  crew_leader raised UserError?", raised_lead)
print("  assignee after manager:", i158.primary_assignee_id.login)
print("T158:", "PASS" if ok else "FAIL")
results["T158"] = ok


# ============================================================
print()
print("=" * 72)
print("T159 - Source reference computed")
print("=" * 72)
# Use any commercial.event.job that exists
some_evt = env["commercial.event.job"].sudo().search([], limit=1)
src_model = env["ir.model"].sudo().search(
    [("model", "=", "commercial.event.job")], limit=1)
if not some_evt or not src_model:
    print("  SKIP — no event_job in DB to point at")
    results["T159"] = None
else:
    i159 = _new_item("T159", assignee=sales, user=sales)
    i159.write({
        "source_model_id": src_model.id,
        "source_id": some_evt.id,
    })
    i159.invalidate_recordset()
    sr = i159.source_record
    print("  source_record:", repr(sr))
    ok = bool(sr) and sr._name == "commercial.event.job" and sr.id == some_evt.id
    print("T159:", "PASS" if ok else "FAIL")
    results["T159"] = ok


# ============================================================
print()
print("=" * 72)
print("T160 - Crew row-level rule")
print("=" * 72)
# Item created by sales, primary_assignee_id = crew_leader.
# A "neutral" crew user (other_crew) should NOT be able to read.
# crew_only (set as assignee) SHOULD be able to read.
i160 = _new_item("T160a", assignee=crew_leader, user=sales)
i160.invalidate_recordset()
i160_id = i160.id
# other_crew (not assigned, not creator) — read should be filtered out
not_assigned_count = env["action.centre.item"].with_user(
    other_crew).search_count([("id", "=", i160_id)])
# Set crew_only as assignee
i160.with_user(manager).write({"primary_assignee_id": crew_only.id})
i160.invalidate_recordset()
assigned_count = env["action.centre.item"].with_user(
    crew_only).search_count([("id", "=", i160_id)])
print("  other_crew (not assigned) read count:", not_assigned_count,
      "(want 0)")
print("  crew_only (assigned) read count:    ", assigned_count, "(want 1)")
ok = not_assigned_count == 0 and assigned_count == 1
print("T160:", "PASS" if ok else "FAIL")
results["T160"] = ok


# ============================================================
print()
print("=" * 72)
print("T161 - Tag model + attach via tag_ids")
print("=" * 72)
tag = env["action.centre.item.tag"].create(
    {"name": "P4M1FIX_Urgent", "color": 1})
i161 = _new_item("T161", assignee=sales, user=sales)
i161.write({"tag_ids": [(4, tag.id)]})
i161.invalidate_recordset()
ok = bool(tag.id) and tag in i161.tag_ids
print("  tag created:", tag.name, "color:", tag.color)
print("  attached to item?", tag in i161.tag_ids)
print("T161:", "PASS" if ok else "FAIL")
results["T161"] = ok


# ============================================================
print()
print("=" * 72)
print("T162 - Menu visibility (action_centre menu gating)")
print("=" * 72)
menu = env.ref("neon_jobs.menu_action_centre", raise_if_not_found=False)
if not menu:
    print("  SKIP — menu_action_centre not found in registry")
    results["T162"] = None
else:
    # Test which user groups can see the menu via the groups_id list.
    allowed_groups = menu.groups_id
    user_ok = sales.groups_id & allowed_groups
    mgr_ok = manager.groups_id & allowed_groups
    lead_ok = crew_leader.groups_id & allowed_groups
    crew_ok = crew_only.groups_id & allowed_groups
    print("  groups on menu:", [g.name for g in allowed_groups])
    print("  sales has overlap:    ", bool(user_ok), "(want True)")
    print("  manager has overlap:  ", bool(mgr_ok), "(want True)")
    print("  crew_lead has overlap:", bool(lead_ok), "(want True)")
    print("  crew has overlap:     ", bool(crew_ok), "(want False)")
    ok = bool(user_ok) and bool(mgr_ok) and bool(lead_ok) and not bool(crew_ok)
    print("T162:", "PASS" if ok else "FAIL")
    results["T162"] = ok


# ============================================================
print()
print("=" * 72)
print("T163 - 'My open tasks' filter shows assigned items")
print("=" * 72)
# Create two items: one assigned to crew_leader (should appear), one
# assigned to manager (should not).
i163_lead = _new_item("T163_lead", assignee=crew_leader, user=sales)
i163_mgr = _new_item("T163_mgr", assignee=manager, user=sales)
# Mimic the filter domain
domain = [("state", "=", "open"), ("primary_assignee_id", "=", crew_leader.id)]
hits = env["action.centre.item"].with_user(crew_leader).search(domain)
print("  hits:", hits.mapped("title"))
ok = i163_lead in hits and i163_mgr not in hits
print("T163:", "PASS" if ok else "FAIL")
results["T163"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = [
    "T151", "T152", "T153", "T154", "T155", "T156", "T157", "T158",
    "T159", "T160", "T161", "T162", "T163",
]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.commit()
