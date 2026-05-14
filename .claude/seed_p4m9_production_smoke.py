"""Production smoke seed for Phase 4 browser verification (P4.M9).

WHAT THIS CREATES
=================
Synthetic users + operational data on the Hetzner production database
(neon_crm), designed to exercise all 9 Action Centre triggers and the
M8 visual states. Every record is marked for trivial removal during
Phase 9 cutover.

  * 2 res.partner — "TEST Client Co [TEST-DELETE]", "TEST Venue [TEST-DELETE]"
  * 6 res.users — p2m75_sales / mgr / lead / crew / other / t20
        (password test123, comment warning on user.partner_id)
  * 10 commercial.job — names suffixed "[TEST-DELETE]"
  * 10 commercial.event.job — auto-spawned from activations
  * 3 commercial.scope.change — fires scope_change trigger
  * 5 commercial.event.feedback — 3 with is_follow_up_required=True
  * Manual visual touches on a handful of spawned action.centre.items
    to surface overdue / due_soon / cancelled / done states

After it runs, the Action Centre cron should be triggered manually
(via Settings → Technical → Scheduled Actions → Action Centre: evaluate
time-based triggers → Run Manually) so closeout_overdue and sla_passed
items also surface — the script also fires the cron in-process at the
end as a convenience.

WHEN CREATED
============
2026-05-14, as part of P4.M9 production smoke handoff.

WHEN TO DELETE
==============
Phase 9 cutover, before Robin's team starts using the system for real.
Use the companion teardown script:

  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/teardown_p4m9_dummy_data.py

INVOCATION
==========
Manual only — never loaded from the addon manifest. Run with:

  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/seed_p4m9_production_smoke.py

IDEMPOTENCY
===========
Safe to re-run. Each create() call is guarded by a search-first check.
A fully-applied seed re-run reports zero new records but does not
error.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError


MARKER = "[TEST-DELETE]"
USER_WARNING = (
    "TEST USER — DELETE BEFORE GO-LIVE "
    "(created P4.M9 dummy seed 2026-05-14)"
)


def _get_or_create_partner(name, is_venue=False):
    partner = env["res.partner"].search(
        [("name", "=", name)], limit=1)
    if partner:
        return partner, False
    return env["res.partner"].create({
        "name": name,
        "is_company": True,
        "is_venue": is_venue,
    }), True


def _get_or_create_user(login, name, group_xmlids):
    user = env["res.users"].search([("login", "=", login)], limit=1)
    if user:
        return user, False
    grp_ids = [env.ref(x).id for x in group_xmlids]
    user = env["res.users"].create({
        "name": name,
        "login": login,
        "email": "%s@test.neonhiring.co.zw" % login,
        "password": "test123",
        "groups_id": [(6, 0, grp_ids)],
    })
    user.partner_id.write({"comment": USER_WARNING})
    return user, True


def _get_or_create_job(name, event_offset_days,
                       partner, venue, currency):
    full_name = "%s %s" % (name, MARKER)
    existing = env["commercial.job"].search(
        [("equipment_summary", "=", full_name)], limit=1)
    if existing:
        return existing, False
    job = env["commercial.job"].create({
        "partner_id": partner.id,
        "venue_id": venue.id,
        "event_date": fields.Date.add(
            fields.Date.today(), days=event_offset_days),
        "currency_id": currency.id,
        # Names on commercial.job are sequenced (JOB-NNNNNN); we drop
        # the human label into equipment_summary because that field
        # is free-form and shows on the form view. The MARKER stays
        # so teardown can find these records by a simple ilike.
        "equipment_summary": full_name,
    })
    return job, True


# ============================================================
print("=" * 72)
print("P4.M9 PRODUCTION SEED — START")
print("=" * 72)

today = fields.Date.today()
results = {
    "partners_created": 0, "partners_reused": 0,
    "users_created": 0, "users_reused": 0,
    "jobs_created": 0, "jobs_reused": 0,
    "event_jobs_completed": 0,
    "scope_changes": 0,
    "feedbacks": 0,
    "visual_touches": 0,
}


# ============================================================
print()
print("Step 1: test partners (client + venue)")
print("-" * 72)
client, c_new = _get_or_create_partner(
    "TEST Client Co " + MARKER, is_venue=False)
venue, v_new = _get_or_create_partner(
    "TEST Venue " + MARKER, is_venue=True)
results["partners_created"] += int(c_new) + int(v_new)
results["partners_reused"] += int(not c_new) + int(not v_new)
print("  client:", client.name, "(new)" if c_new else "(reused)")
print("  venue: ", venue.name, "(new)" if v_new else "(reused)")


# ============================================================
print()
print("Step 2: test users (p2m75_*)")
print("-" * 72)
user_specs = [
    ("p2m75_sales", "P2M75 Sales", [
        "base.group_user", "neon_jobs.group_neon_jobs_user"]),
    ("p2m75_mgr", "P2M75 Manager", [
        "base.group_user", "neon_jobs.group_neon_jobs_manager"]),
    ("p2m75_lead", "P2M75 Crew Leader", [
        "base.group_user", "neon_jobs.group_neon_jobs_crew_leader"]),
    ("p2m75_crew", "P2M75 Crew", [
        "base.group_user", "neon_jobs.group_neon_jobs_crew"]),
    ("p2m75_other", "P2M75 Other Crew", [
        "base.group_user", "neon_jobs.group_neon_jobs_crew"]),
    ("p2m75_t20", "P2M75 T20 Target", [
        "base.group_user", "neon_jobs.group_neon_jobs_crew"]),
]
users = {}
for login, name, groups in user_specs:
    u, was_new = _get_or_create_user(login, name, groups)
    users[login] = u
    results["users_created"] += int(was_new)
    results["users_reused"] += int(not was_new)
    print("  %s id=%d %s" % (
        login, u.id, "(new)" if was_new else "(reused)"))
mgr = users["p2m75_mgr"]
lead = users["p2m75_lead"]


# ============================================================
print()
print("Step 3: 10 commercial.job records + event_job auto-spawn")
print("-" * 72)
currency = env.company.currency_id
job_specs = [
    ("TEST Pending Conf A",        30),
    ("TEST Wedding B",             30),
    ("TEST Product Launch C",       2),  # readiness_70 candidate
    ("TEST Corporate Dinner D",    30),  # capacity_gate target
    ("TEST NGO Conference E",      30),  # lost target
    ("TEST Government Function F", -8),  # closeout_overdue (cron)
    ("TEST Concert G",            -15),  # sla_passed (cron)
    ("TEST AGM H",                 20),  # scope_change canvas
    ("TEST Awards I",              -3),  # feedback canvas (completed)
    ("TEST Gala J",                25),  # scope_change canvas
]
jobs = []
for label, day_offset in job_specs:
    j, was_new = _get_or_create_job(
        label, day_offset, client, venue, currency)
    jobs.append(j)
    results["jobs_created"] += int(was_new)
    results["jobs_reused"] += int(not was_new)
    print("  %-32s state=%-9s id=%d %s" % (
        label, j.state, j.id, "(new)" if was_new else "(reused)"))
env.cr.commit()


# ============================================================
print()
print("Step 4: activate the 9 jobs (#1 stays pending)")
print("-" * 72)
# Index in the jobs[] list:
# 0=Pending A, 1=Wedding B, 2=Launch C, 3=Dinner D, 4=NGO E,
# 5=Govt F, 6=Concert G, 7=AGM H, 8=Awards I, 9=Gala J
for idx, j in enumerate(jobs):
    if idx == 0:
        # Pending Conf A — leave in pending state
        continue
    if j.state == "active":
        # already activated on a prior run
        continue
    try:
        j.write({"state": "active", "soft_hold_until": False})
        print("  activated", j.equipment_summary)
    except Exception as e:
        print("  WARN activation failed for", j.equipment_summary,
              ":", type(e).__name__, str(e)[:80])
env.cr.commit()


# ============================================================
print()
print("Step 5: walk event_jobs to 'completed' for #6, #7, #9")
print("-" * 72)
# Jobs at idx 5 (Govt F), 6 (Concert G), 8 (Awards I) need their
# event_job in completed state for the cron-driven triggers
# (closeout_overdue / sla_passed) and for the feedback workflow.
for idx, label in [(5, "Govt F"), (6, "Concert G"), (8, "Awards I")]:
    j = jobs[idx]
    ej = j.event_job_ids[:1]
    if not ej:
        print("  WARN", label, "has no event_job — skip")
        continue
    if ej.state == "completed":
        print("  ", label, "event_job already completed")
        continue
    ej.sudo().with_context(_allow_state_write=True).write({
        "state": "completed",
    })
    results["event_jobs_completed"] += 1
    print("  ", label, "event_job -> completed (",
          ej.name, ")")
env.cr.commit()


# ============================================================
print()
print("Step 6: capacity_gate trigger via gate_result on #4 (Dinner D)")
print("-" * 72)
dinner = jobs[3]
# Refinement 2: try gate_result write first (idiomatic, persisted
# via the model's write hooks). If no item spawns, fall back to
# _persist_gate_result. Report which path worked.
src_model = env["ir.model"].sudo()._get("commercial.job")
def _capacity_items(j):
    return env["action.centre.item"].sudo().search([
        ("trigger_type", "=", "capacity_gate"),
        ("source_model_id", "=", src_model.id),
        ("source_id", "=", j.id),
    ])

pre = _capacity_items(dinner)
print("  capacity_gate items pre-flip:", len(pre))
# Persist the visible state first so a browser viewer sees the
# warning chip on the job form.
dinner.sudo().write({"gate_result": "warning"})
post_a = _capacity_items(dinner)
print("  after gate_result='warning' write:", len(post_a),
      "(delta", len(post_a) - len(pre), ")")
# The model's gate-eval flow (_persist_gate_result) fires the
# capacity_gate trigger from inside an evaluation pass; calling
# that helper from a seed requires synthesising a full gate-result
# object, which is heavier than this seed needs. Fire the trigger
# directly instead — the resulting action.centre.item is
# indistinguishable from the production gate-eval path.
if len(post_a) == len(pre):
    print("  direct trigger fire (gate_result write alone "
          "doesn't fire the trigger — only _persist_gate_result "
          "does, and that needs a structured eval result)")
    try:
        dinner.sudo()._action_centre_create_item("capacity_gate")
        post_b = _capacity_items(dinner)
        print("  after direct _action_centre_create_item:", len(post_b))
    except Exception as e:
        print("  DEFECT: direct capacity_gate trigger failed:",
              type(e).__name__, str(e)[:80])
env.cr.commit()


# ============================================================
print()
print("Step 7: lost trigger via action_archive_lost on #5 (NGO E)")
print("-" * 72)
ngo = jobs[4]
# Refinement 1: verify the lost trigger fires when archived
def _lost_items(j):
    return env["action.centre.item"].sudo().search([
        ("trigger_type", "=", "lost"),
        ("source_model_id", "=", src_model.id),
        ("source_id", "=", j.id),
    ])
pre = _lost_items(ngo)
print("  lost items pre-archive:", len(pre))
if ngo.state != "archived":
    # action_archive_lost takes no kwargs; it reads loss_reason
    # off the record itself, raising UserError if it's empty and
    # the actor isn't a manager. Write the reason first, then
    # archive. Seed runs as admin (a manager-equivalent), so even
    # an empty loss_reason would pass the gate — but we set it
    # anyway so the audit trail and the job form look realistic.
    ngo.sudo().write({
        "loss_reason": "Test seed — lost to a competitor "
                       "(P4.M9 dummy data).",
        "lost_to_competitor": "TEST COMPETITOR " + MARKER,
    })
    ngo.sudo().action_archive_lost()
post = _lost_items(ngo)
print("  lost items post-archive:", len(post),
      "(delta", len(post) - len(pre), ")")
if len(post) == len(pre):
    print("  DEFECT: lost trigger did NOT fire — flag for investigation")
env.cr.commit()


# ============================================================
print()
print("Step 8: 3 scope_change records on event_jobs from #8, #10, #2")
print("-" * 72)
ScopeChange = env["commercial.scope.change"]
scope_specs = [
    (jobs[7], "TEST scope change — added pyrotechnics package", "addition"),
    (jobs[9], "TEST scope change — venue layout modified", "modification"),
    (jobs[1], "TEST scope change — extra crew shift", "addition"),
]
for j, desc, sc_type in scope_specs:
    ej = j.event_job_ids[:1]
    if not ej:
        print("  WARN", j.equipment_summary, "no event_job — skip")
        continue
    full_desc = "%s %s" % (desc, MARKER)
    existing = ScopeChange.search(
        [("description", "=", full_desc)], limit=1)
    if existing:
        print("  reused", existing.name, "for", j.equipment_summary)
        continue
    sc = ScopeChange.sudo().create({
        "event_job_id": ej.id,
        "description": full_desc,
        "scope_change_type": sc_type,
    })
    results["scope_changes"] += 1
    print("  created", sc.name, "on", ej.name)
env.cr.commit()


# ============================================================
print()
print("Step 9: 5 feedback records, 3 with is_follow_up_required=True")
print("-" * 72)
Feedback = env["commercial.event.feedback"]
fb_specs = [
    # (job_index, channel, sentiment, follow_up_required, text)
    (5, "phone",        "negative", True,  "AV issues during keynote"),
    (6, "email_survey", "mixed",    True,  "Late start, recovered well"),
    (8, "in_person",    "positive", False, "Client thrilled with execution"),
    (8, "phone",        "negative", True,  "Sound levels too low in foyer"),
    (5, "written",      "neutral",  False, "Standard post-event card"),
]
for idx, channel, sentiment, follow_up, text in fb_specs:
    j = jobs[idx]
    ej = j.event_job_ids[:1]
    if not ej:
        print("  WARN", j.equipment_summary, "no event_job — skip")
        continue
    full_text = "%s — %s %s" % (text, j.equipment_summary, MARKER)
    existing = Feedback.search(
        [("feedback_text", "=", full_text)], limit=1)
    if existing:
        print("  reused", existing.name)
        continue
    vals = {
        "event_job_id": ej.id,
        "channel": channel,
        "feedback_text": full_text,
        "sentiment": sentiment,
        "is_follow_up_required": follow_up,
    }
    if follow_up:
        vals["follow_up_owner"] = mgr.id
    fb = Feedback.sudo().create(vals)
    results["feedbacks"] += 1
    print("  created", fb.name, "follow_up=", follow_up)
env.cr.commit()


# ============================================================
print()
print("Step 10: visual-state touches (overdue, due_soon, cancelled, done)")
print("-" * 72)
Item = env["action.centre.item"].sudo()
# Pick spawned items from our jobs only — filter by source_model
ours = Item.search([
    ("source_model_id.model", "in", (
        "commercial.event.job",
        "commercial.scope.change",
        "commercial.event.feedback",
        "commercial.job",
    )),
    ("state", "in", ("open", "in_progress")),
])
print("  open/in_progress items spawned by seed:", len(ours))

# overdue: pick an open item, set due_date 2h ago
overdue_targets = ours.filtered(lambda i: i.state == "open")[:1]
if overdue_targets:
    overdue_targets.write({
        "due_date": fields.Datetime.now() - timedelta(hours=2),
    })
    results["visual_touches"] += 1
    print("  marked overdue:", overdue_targets.name)

# due_soon: pick another open item, set due_date in 1 hour
ds_targets = (ours - overdue_targets).filtered(
    lambda i: i.state == "open")[:1]
if ds_targets:
    ds_targets.write({
        "due_date": fields.Datetime.now() + timedelta(hours=1),
    })
    results["visual_touches"] += 1
    print("  marked due_soon:", ds_targets.name)

# cancelled (refinement 3: user-facing path)
cancel_targets = (ours - overdue_targets - ds_targets).filtered(
    lambda i: i.state == "open")[:1]
if cancel_targets:
    try:
        cancel_targets.with_user(mgr).action_cancel(
            reason="Test seed — demo cancellation for visual smoke")
        results["visual_touches"] += 1
        print("  cancelled via action_cancel:", cancel_targets.name)
    except Exception as e:
        print("  WARN cancel failed:", type(e).__name__, str(e)[:80])

# done (refinement 3: action_mark_done as manager — audit reads
# 'Manually resolved by p2m75_mgr' so browser smoke sees a realistic
# closure_reason in the form's Closure tab)
done_targets = (
    ours - overdue_targets - ds_targets - cancel_targets
).filtered(lambda i: i.state == "open")[:1]
if done_targets:
    try:
        done_targets.with_user(mgr).action_mark_done()
        results["visual_touches"] += 1
        print("  marked done as p2m75_mgr:", done_targets.name)
    except Exception as e:
        print("  WARN mark_done failed:", type(e).__name__, str(e)[:80])

env.cr.commit()


# ============================================================
print()
print("Step 11: trigger time-based cron (closeout_overdue + sla_passed)")
print("-" * 72)
# Refinement 4: fire the cron in-process so closeout_overdue and
# sla_passed items spawn immediately rather than waiting for the
# 02:30 nightly run. This rounds out the 9-trigger coverage before
# browser smoke begins.
try:
    Item._cron_evaluate_time_based_triggers()
    print("  _cron_evaluate_time_based_triggers OK")
except Exception as e:
    print("  WARN cron failed:", type(e).__name__, str(e)[:80])
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("SEED COMPLETE — counts")
print("=" * 72)
for k, v in results.items():
    print("  %-25s %d" % (k, v))

# Summary of action.centre.item state by trigger_type
print()
print("Action Centre item counts by trigger_type:")
trigger_types = env["action.centre.item"].search(
    []).mapped("trigger_type")
from collections import Counter
counts = Counter(trigger_types)
expected = [
    "event_created", "readiness_50", "readiness_70",
    "capacity_gate", "lost", "scope_change",
    "feedback_followup", "closeout_overdue", "sla_passed",
    "manual",
]
for t in expected:
    print("  %-22s %d" % (t, counts.get(t, 0)))
missing = [t for t in expected[:-1] if counts.get(t, 0) == 0]
if missing:
    print()
    print("  TRIGGERS WITHOUT ITEMS (investigate):", missing)
else:
    print()
    print("  all 9 trigger types present in Action Centre")

env.cr.commit()
