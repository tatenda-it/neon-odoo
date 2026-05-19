"""P2.M5 smoke tests — Soft Hold lifecycle."""
from datetime import timedelta

from odoo import fields, SUPERUSER_ID
from odoo.exceptions import UserError

print("=" * 72)
print("SETUP")
print("=" * 72)

# Hard cleanup
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["commercial.job.crew"].sudo().search([]).unlink()
env["mail.activity"].sudo().search([("res_model", "=", "commercial.job")]).unlink()
env["res.users"].sudo().search([("login", "like", "p2m5_")]).unlink()
env["venue.room"].sudo().search([("name", "like", "P2M5")]).unlink()
env["res.partner"].sudo().search([("name", "like", "P2M5")]).unlink()
env.cr.commit()

venue = env["res.partner"].create({
    "name": "P2M5 Venue", "is_company": True, "is_venue": True,
})
room = env["venue.room"].create({
    "name": "P2M5 Room", "venue_id": venue.id, "capacity": 100,
})
client = env["res.partner"].create({
    "name": "P2M5 Client", "is_company": True, "is_venue": False,
})
regular = env["res.users"].create({
    "name": "P2M5 Regular", "login": "p2m5_user",
    "email": "p2m5_user@test.local",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
manager = env["res.users"].create({
    "name": "P2M5 Manager", "login": "p2m5_mgr",
    "email": "p2m5_mgr@test.local",
    "groups_id": [(6, 0, [
        env.ref("base.group_user").id,
        env.ref("neon_jobs.group_neon_jobs_manager").id,
    ])],
})
env.cr.commit()

base_date = fields.Date.add(fields.Date.today(), days=21)
today = fields.Date.today()


def mk_job(**kw):
    vals = {
        "partner_id": client.id, "venue_id": venue.id,
        "venue_room_id": room.id, "event_date": base_date,
        "currency_id": env.company.currency_id.id,
    }
    vals.update(kw)
    return env["commercial.job"].create(vals)


results = {}


def force_today(job, soft_hold_until=None):
    """Bypass write override transition guards to mutate dates for testing."""
    # No transition rules on these fields; vanilla write is fine.
    upd = {}
    if soft_hold_until is not None:
        upd["soft_hold_until"] = soft_hold_until
    job.write(upd)
    job.invalidate_recordset(["soft_hold_state"])
    job._compute_soft_hold_state()


# ============================================================
print()
print("=" * 72)
print("T1 - Create pending job -> soft_hold_until=today+7, state=active, count=0")
print("=" * 72)
j = mk_job()
expected = fields.Date.add(today, days=7)
ok = (j.soft_hold_until == expected
      and j.soft_hold_state == "active"
      and j.soft_hold_extension_count == 0)
print("T1: soft_hold_until=", j.soft_hold_until, " expected=", expected)
print("    state=", j.soft_hold_state, " count=", j.soft_hold_extension_count)
print("T1:", "PASS" if ok else "FAIL")
results["T1"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T2 - Cron on job with soft_hold_until=today")
print("=" * 72)
j2 = mk_job()
# Force soft_hold_until to today; assign a real salesperson via lead
lead = env["crm.lead"].create({
    "name": "P2M5 T2 Lead",
    "partner_id": client.id,
    "user_id": regular.id,
})
force_today(j2, soft_hold_until=today)
j2.write({"crm_lead_id": lead.id})
prior_msgs = env["mail.message"].search_count(
    [("model", "=", "commercial.job"), ("res_id", "=", j2.id)])
prior_acts = env["mail.activity"].search_count(
    [("res_model", "=", "commercial.job"), ("res_id", "=", j2.id)])
env["commercial.job"].cron_process_soft_hold_expiry()
j2.invalidate_recordset()
new_msgs = env["mail.message"].search_count(
    [("model", "=", "commercial.job"), ("res_id", "=", j2.id)])
new_acts = env["mail.activity"].search_count(
    [("res_model", "=", "commercial.job"), ("res_id", "=", j2.id)])
act = env["mail.activity"].search(
    [("res_model", "=", "commercial.job"), ("res_id", "=", j2.id)], limit=1)
ok = (new_msgs > prior_msgs and new_acts == prior_acts + 1
      and act.user_id == regular
      and j2.last_expiry_notification_date == today)
print("T2: msgs +", new_msgs - prior_msgs, " acts +", new_acts - prior_acts,
      " activity user=", act.user_id.name,
      " last_notif=", j2.last_expiry_notification_date)
print("T2:", "PASS" if ok else "FAIL")
results["T2"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T3 - Cron on job with soft_hold_until=today-2")
print("=" * 72)
j3 = mk_job()
force_today(j3, soft_hold_until=fields.Date.subtract(today, days=2))
env["commercial.job"].cron_process_soft_hold_expiry()
j3.invalidate_recordset()
# Activity creation auto-posts its own "Dear X, you have a task..." entry
# after the cron's message_post. Search by content rather than recency.
phrase_msg = env["mail.message"].search([
    ("model", "=", "commercial.job"),
    ("res_id", "=", j3.id),
    ("body", "ilike", "2 days ago"),
], limit=1)
ok = (j3.last_expiry_notification_date == today and bool(phrase_msg))
print("T3: last_notif=", j3.last_expiry_notification_date,
      " matched body snippet=", (phrase_msg.body or "")[:120] if phrase_msg else "(none)")
print("T3:", "PASS" if ok else "FAIL")
results["T3"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T4 - Idempotency: run cron twice, no duplicate")
print("=" * 72)
acts_before = env["mail.activity"].search_count(
    [("res_model", "=", "commercial.job"), ("res_id", "=", j3.id)])
msgs_before = env["mail.message"].search_count(
    [("model", "=", "commercial.job"), ("res_id", "=", j3.id)])
env["commercial.job"].cron_process_soft_hold_expiry()
acts_after = env["mail.activity"].search_count(
    [("res_model", "=", "commercial.job"), ("res_id", "=", j3.id)])
msgs_after = env["mail.message"].search_count(
    [("model", "=", "commercial.job"), ("res_id", "=", j3.id)])
ok = (acts_after == acts_before and msgs_after == msgs_before)
print("T4: acts before=", acts_before, " after=", acts_after,
      " msgs before=", msgs_before, " after=", msgs_after)
print("T4:", "PASS" if ok else "FAIL")
results["T4"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T5 - Extension wizard: 7 days, count=1, chatter logged, notif cleared")
print("=" * 72)
j5 = mk_job()
orig_expiry = j5.soft_hold_until
# Simulate an earlier notification so we can verify it gets cleared
j5.write({"last_expiry_notification_date": today})
wiz = env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
    "job_id": j5.id, "extension_days": "7", "reason": "T5 client delay",
})
print("T5 wizard new_expiry=", wiz.new_expiry, "(today=", today, ")")
wiz.action_confirm()
j5.invalidate_recordset()
expected_new = fields.Date.add(orig_expiry, days=7)
last_msg = env["mail.message"].search(
    [("model", "=", "commercial.job"), ("res_id", "=", j5.id)],
    order="id desc", limit=1)
ok = (j5.soft_hold_until == expected_new
      and j5.soft_hold_extension_count == 1
      and not j5.last_expiry_notification_date
      and "extended by 7" in (last_msg.body or "").lower())
print("T5: soft_hold_until=", j5.soft_hold_until, " (expected", expected_new, ")")
print("    count=", j5.soft_hold_extension_count,
      " last_notif=", j5.last_expiry_notification_date)
print("    chatter snippet=", (last_msg.body or "")[:120])
print("T5:", "PASS" if ok else "FAIL")
results["T5"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T6 - 3 extensions consumed -> 4th raises UserError")
print("=" * 72)
j6 = mk_job()
# Extension 1: 7 -> count=1
env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
    "job_id": j6.id, "extension_days": "7",
}).action_confirm()
# Extension 2: 7 -> count=2
env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
    "job_id": j6.id, "extension_days": "7",
}).action_confirm()
# Extension 3: 7 -> count=3 (now at cap)
env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
    "job_id": j6.id, "extension_days": "7",
}).action_confirm()
j6.invalidate_recordset()
print("T6: after 3 extensions, count=", j6.soft_hold_extension_count)
try:
    env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
        "job_id": j6.id, "extension_days": "7",
    }).action_confirm()
    print("T6 FAIL: 4th extension should have raised")
    results["T6"] = False
except UserError as e:
    ok = "3 extensions" in str(e) and "cannot be extended further" in str(e)
    print("T6 raised:", str(e)[:160])
    print("T6:", "PASS" if ok else "FAIL")
    results["T6"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T7 - Manual edit beyond cap -> wizard total-days check")
print("=" * 72)
j7 = mk_job()
# Force soft_hold_until to today+30 manually (bypassing wizard)
far = fields.Date.add(today, days=30)
j7.write({"soft_hold_until": far})
# Now try a 7-day extension; wizard will compute new_expiry=far+7
try:
    env["commercial.job.soft_hold.extend.wizard"].with_user(regular).create({
        "job_id": j7.id, "extension_days": "7",
    }).action_confirm()
    print("T7 FAIL: should have raised on total-days cap")
    results["T7"] = False
except UserError as e:
    ok = "28 days" in str(e) or "soft-hold cap" in str(e).lower()
    print("T7 raised:", str(e)[:160])
    print("T7:", "PASS" if ok else "FAIL")
    results["T7"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T8 - soft_hold_state transitions")
print("=" * 72)
j8 = mk_job()
force_today(j8, soft_hold_until=fields.Date.add(today, days=10))
s_active = j8.soft_hold_state
force_today(j8, soft_hold_until=fields.Date.add(today, days=2))
s_soon = j8.soft_hold_state
force_today(j8, soft_hold_until=fields.Date.subtract(today, days=1))
s_exp = j8.soft_hold_state
# Reset to a healthy hold then move to active state to confirm 'none'.
# Bypass action_activate (gate would reject because prior tests left
# many pending+soft-held jobs at the same venue/room — that's the P2.M5
# gate enhancement working as intended). _do_activate_state just writes
# state + clears soft_hold_until.
force_today(j8, soft_hold_until=fields.Date.add(today, days=15))
j8._do_activate_state()
j8.invalidate_recordset()
s_active_job = j8.soft_hold_state
ok = (s_active == "active"
      and s_soon == "expiring_soon"
      and s_exp == "expired"
      and s_active_job == "none")
print("T8: state=active at +10 ->", s_active,
      " +2 ->", s_soon, " -1 ->", s_exp,
      " then job.state=active ->", s_active_job)
print("T8:", "PASS" if ok else "FAIL")
results["T8"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T9 - Gate: pending+soft-hold conflicts with activating job")
print("=" * 72)
# venue_b/room_b for isolation
venue_b = env["res.partner"].create({
    "name": "P2M5 Venue B", "is_company": True, "is_venue": True,
})
room_b = env["venue.room"].create({
    "name": "P2M5 Room B", "venue_id": venue_b.id, "capacity": 200,
})
gate_date = fields.Date.add(today, days=45)
soft_held = mk_job(venue_id=venue_b.id, venue_room_id=room_b.id,
                   event_date=gate_date)
# soft_held is pending with default soft_hold_until=today+7, > today
activating = mk_job(venue_id=venue_b.id, venue_room_id=room_b.id,
                    event_date=gate_date)
# Activating the second one: same venue + same room → reject citing soft hold
try:
    activating.with_user(manager).action_activate()
    # Manager would get wizard; we just check gate_check_log
    import json as _json
    log = _json.loads(activating.gate_check_log)
    dv = next((c for c in log["checks"] if c["name"] == "date_venue"), None)
    ok = (dv and dv["result"] == "reject"
          and "soft-hold" in dv["message"].lower())
    print("T9: date_venue =", dv["result"] if dv else None,
          " msg=", (dv["message"] if dv else "")[:160])
    print("T9:", "PASS" if ok else "FAIL")
    results["T9"] = ok
except UserError as e:
    # Should not raise as manager (wizard returned)
    print("T9 UNEXPECTED UserError:", str(e)[:120])
    results["T9"] = False
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T10 - User fallback chain")
print("=" * 72)
# Case A: job with crm_lead.user_id set -> activity assigned to that user
case_a = mk_job()
lead_a = env["crm.lead"].create({
    "name": "P2M5 T10A Lead", "partner_id": client.id, "user_id": regular.id,
})
force_today(case_a, soft_hold_until=today)
case_a.write({"crm_lead_id": lead_a.id})
case_a.write({"last_expiry_notification_date": False})
env["commercial.job"].cron_process_soft_hold_expiry()
act_a = env["mail.activity"].search(
    [("res_model", "=", "commercial.job"), ("res_id", "=", case_a.id)],
    order="id desc", limit=1)
print("T10a: activity user=", act_a.user_id.name, "(expected regular)")
a_ok = act_a.user_id == regular

# Case B: job without crm_lead -> create_uid (regular created it)
case_b = env["commercial.job"].with_user(regular).create({
    "partner_id": client.id, "venue_id": venue.id,
    "venue_room_id": room.id, "event_date": base_date,
    "currency_id": env.company.currency_id.id,
})
force_today(case_b, soft_hold_until=today)
env["commercial.job"].cron_process_soft_hold_expiry()
act_b = env["mail.activity"].search(
    [("res_model", "=", "commercial.job"), ("res_id", "=", case_b.id)],
    order="id desc", limit=1)
print("T10b: activity user=", act_b.user_id.name, "(expected regular)")
b_ok = act_b.user_id == regular

# Case C: job created by SUPERUSER, no crm_lead -> first manager
case_c = env["commercial.job"].with_user(SUPERUSER_ID).create({
    "partner_id": client.id, "venue_id": venue.id,
    "venue_room_id": room.id, "event_date": base_date,
    "currency_id": env.company.currency_id.id,
})
force_today(case_c, soft_hold_until=today)
env["commercial.job"].cron_process_soft_hold_expiry()
act_c = env["mail.activity"].search(
    [("res_model", "=", "commercial.job"), ("res_id", "=", case_c.id)],
    order="id desc", limit=1)
# Expected: first user (by id) in group_neon_jobs_manager
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")
expected_mgr = env["res.users"].search(
    [("groups_id", "in", mgr_group.id)], limit=1, order="id")
print("T10c: activity user=", act_c.user_id.name,
      " expected=", expected_mgr.name, "(id=", expected_mgr.id, ")")
c_ok = act_c.user_id == expected_mgr

ok = a_ok and b_ok and c_ok
print("T10:", "PASS" if ok else "FAIL",
      " (A=", a_ok, " B=", b_ok, " C=", c_ok, ")")
results["T10"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
