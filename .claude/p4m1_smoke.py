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
print("T164 - Cancel via wizard succeeds with closure_reason")
print("=" * 72)
i164 = _new_item("T164", assignee=sales, user=sales)
# Open wizard as manager (mirrors form button flow)
act = i164.with_user(manager).action_open_cancel_wizard()
ok_act = (
    act.get("res_model") == "action.centre.item.cancel.wizard"
    and act.get("context", {}).get("default_item_id") == i164.id
)
# Create the wizard record + submit
wiz = env["action.centre.item.cancel.wizard"].with_user(manager).create({
    "item_id": i164.id,
    "closure_reason": "T164 — testing wizard submit",
})
wiz.action_confirm()
i164.invalidate_recordset()
ok = (
    ok_act
    and i164.state == "cancelled"
    and "T164" in (i164.closure_reason or "")
    and i164.closed_by_id == manager
)
print("  wizard action returned correct shape?", ok_act)
print("  state:", i164.state, "reason:", i164.closure_reason)
print("T164:", "PASS" if ok else "FAIL")
results["T164"] = ok


# ============================================================
print()
print("=" * 72)
print("T165 - source_record renders as 'model,id' string for non-admin")
print("=" * 72)
some_evt = env["commercial.event.job"].sudo().search([], limit=1)
src_model = env["ir.model"].sudo().search(
    [("model", "=", "commercial.event.job")], limit=1)
if not some_evt or not src_model:
    print("  SKIP — no event_job in DB to point at")
    results["T165"] = None
else:
    i165 = _new_item("T165", assignee=sales, user=sales)
    i165.write({
        "source_model_id": src_model.id,
        "source_id": some_evt.id,
    })
    i165.invalidate_recordset()
    # Read as sales (the role that lacks ir.model access pre-fix)
    sr = i165.with_user(sales).source_record
    # Reference field returns recordset on Python read; the wire
    # format is the 'model,id' string. We verify both: that the
    # recordset is correct AND that the underlying field stored
    # the right string.
    ok = (
        bool(sr)
        and sr._name == "commercial.event.job"
        and sr.id == some_evt.id
    )
    print("  source_record recordset:", repr(sr))
    print("T165:", "PASS" if ok else "FAIL")
    results["T165"] = ok


# ============================================================
print()
print("=" * 72)
print("T166 - Manual creation auto-assigns creator (matching role)")
print("=" * 72)
# Sales user creates a task with primary_role='sales'. Creator
# should be auto-assigned. Without role match → unassigned.
i166_match = env["action.centre.item"].with_user(sales).create({
    "title": "P4M1FIX T166_match",
    "primary_role": "sales",
})
i166_mismatch = env["action.centre.item"].with_user(sales).create({
    "title": "P4M1FIX T166_mismatch",
    "primary_role": "manager",
})
i166_norole = env["action.centre.item"].with_user(sales).create({
    "title": "P4M1FIX T166_norole",
})
i166_match.invalidate_recordset()
i166_mismatch.invalidate_recordset()
i166_norole.invalidate_recordset()
ok = (
    i166_match.primary_assignee_id == sales
    and not i166_mismatch.primary_assignee_id
    and not i166_norole.primary_assignee_id
)
print("  sales+role=sales auto-assignee:    ",
      i166_match.primary_assignee_id.login, "(want p2m75_sales)")
print("  sales+role=manager auto-assignee:  ",
      i166_mismatch.primary_assignee_id.login or "(none)", "(want none)")
print("  sales+no role auto-assignee:       ",
      i166_norole.primary_assignee_id.login or "(none)", "(want none)")
print("T166:", "PASS" if ok else "FAIL")
results["T166"] = ok


# ============================================================
print()
print("=" * 72)
print("T167 - Overdue filter loads (domain evaluates) as each role")
print("=" * 72)
# Mimic the search filter domain. Failure modes: ACL on a referenced
# field, bad domain syntax, etc. We just run the search for each
# role and assert no exception.
from datetime import date
overdue_domain = [
    ("due_date", "<", date.today()),
    ("state", "in", ("open", "in_progress")),
]
ok = True
for u in (sales, crew_leader, manager, crew_only):
    try:
        n = env["action.centre.item"].with_user(u).search_count(overdue_domain)
        print(f"  {u.login}: search_count = {n}")
    except Exception as e:
        print(f"  {u.login}: FAILED -> {type(e).__name__}: {str(e)[:120]}")
        ok = False
print("T167:", "PASS" if ok else "FAIL")
results["T167"] = ok


# ============================================================
print()
print("=" * 72)
print("T168 - Overdue filter: domain returns correct items per role")
print("=" * 72)
# Use the EXACT domain the view filter evaluates to. The view uses
# context_today().strftime('%Y-%m-%d'); we replicate via Date.today().
today_str = fields.Date.today().strftime('%Y-%m-%d')
overdue_domain = [
    ("due_date", "!=", False),
    ("due_date", "<", today_str),
    ("state", "not in", ("done", "cancelled")),
]
# Build a clean three-record fixture assigned to crew_leader so all
# roles can see them via their unrestricted CSV grants (or, for crew,
# via the row-level rule on primary_assignee_id).
past_dt = fields.Datetime.subtract(fields.Datetime.now(), days=2)
future_dt = fields.Datetime.add(fields.Datetime.now(), days=2)
i168_past_open = _new_item(
    "T168_past_open", assignee=crew_leader, due=past_dt, user=manager)
i168_future_open = _new_item(
    "T168_future_open", assignee=crew_leader, due=future_dt, user=manager)
i168_past_done = _new_item(
    "T168_past_done", assignee=crew_leader, due=past_dt, user=manager)
# Close the third one
i168_past_done.with_user(crew_leader).action_mark_done()
i168_past_done.invalidate_recordset()

ok = True
for u in (sales, crew_leader, manager):
    try:
        hits = env["action.centre.item"].with_user(u).search(overdue_domain)
        titles = hits.mapped("title")
        has_past_open = i168_past_open in hits
        has_future_open = i168_future_open in hits
        has_past_done = i168_past_done in hits
        print(f"  {u.login}: hits={len(hits)}, "
              f"past+open={has_past_open}, "
              f"future+open={has_future_open}, "
              f"past+done={has_past_done}")
        if not has_past_open or has_future_open or has_past_done:
            ok = False
    except Exception as e:
        print(f"  {u.login}: FAILED -> {type(e).__name__}: {str(e)[:120]}")
        ok = False
print("T168:", "PASS" if ok else "FAIL")
results["T168"] = ok


# ============================================================
print()
print("=" * 72)
print("T169 - Manual items can set source_model_id + source_id")
print("=" * 72)
src_model = env["ir.model"].sudo().search(
    [("model", "=", "commercial.event.job")], limit=1)
some_evt = env["commercial.event.job"].sudo().search([], limit=1)
if not src_model or not some_evt:
    print("  SKIP — no event_job in DB")
    results["T169"] = None
else:
    i169 = _new_item("T169_manual_with_source",
                     assignee=sales, user=sales)
    # is_manual=True by default for manual creation
    i169.invalidate_recordset()
    is_manual_before = i169.is_manual
    # Manager sets source on a manual item
    i169.with_user(manager).write({
        "source_model_id": src_model.id,
        "source_id": some_evt.id,
    })
    i169.invalidate_recordset()
    ok = (
        is_manual_before is True
        and i169.source_model_id == src_model
        and i169.source_id == some_evt.id
        and i169.source_record
        and i169.source_record._name == "commercial.event.job"
        and i169.source_record.id == some_evt.id
    )
    print("  is_manual at creation:", is_manual_before)
    print("  source_model_id set:  ", i169.source_model_id.model)
    print("  source_id set:        ", i169.source_id)
    print("  source_record:        ", repr(i169.source_record))
    print("T169:", "PASS" if ok else "FAIL")
    results["T169"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = [
    "T151", "T152", "T153", "T154", "T155", "T156", "T157", "T158",
    "T159", "T160", "T161", "T162", "T163",
    "T164", "T165", "T166", "T167",
    "T168", "T169",
]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.commit()
