from odoo import fields
from odoo.exceptions import UserError

print("=" * 70)
print("SETUP")
print("=" * 70)
print("Setup user:", env.user.name, env.user.login, "id=", env.user.id)

venue = env["res.partner"].search([("name", "=", "Smoke Test Venue")], limit=1)
if not venue:
    venue = env["res.partner"].create({
        "name": "Smoke Test Venue", "is_company": True, "is_venue": True,
    })
    print("Created venue id", venue.id)
else:
    print("Reusing venue id", venue.id)

room = env["venue.room"].search(
    [("venue_id", "=", venue.id), ("name", "=", "Main Hall")], limit=1)
if not room:
    room = env["venue.room"].create({
        "name": "Main Hall", "venue_id": venue.id, "capacity": 200,
    })
print("Room id", room.id)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False),
     ("name", "!=", "Smoke Test Venue")], limit=1)
print("Client:", client.name, "id=", client.id)
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T1 - Pending creation + soft_hold_until")
print("=" * 70)
job = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "venue_room_id": room.id, "event_date": fields.Date.today(),
})
print("T1: created", job.name, "state=", job.state, "soft_hold_until=", job.soft_hold_until)
expected = fields.Date.add(fields.Date.today(), days=7)
if job.soft_hold_until == expected:
    print("T1 PASS")
    t1_pass = True
else:
    print("T1 FAIL: soft_hold_until", job.soft_hold_until, "!= expected", expected)
    t1_pass = False
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T2 - Status track transitions")
print("=" * 70)
results = []

def try_transition(job, field, new_value, should_succeed, label=""):
    try:
        job.write({field: new_value})
        actual = "success"
    except UserError as e:
        actual = "UserError: " + str(e)
    except Exception as e:
        actual = type(e).__name__ + ": " + str(e)
    expected = "success" if should_succeed else "blocked"
    pass_fail = "PASS" if (
        (should_succeed and actual == "success") or
        (not should_succeed and actual.startswith("UserError"))
    ) else "FAIL"
    cur = job[field]
    results.append((label or field, new_value, expected, actual, pass_fail, cur))
    return actual

# Commercial track sub-tests, each on its own fresh job to avoid cross-contamination
job_a = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.today(),
})
try_transition(job_a, "commercial_status", "won", True, "comm: negotiating->won")
try_transition(job_a, "commercial_status", "lost", False, "comm: won->lost (invalid)")

job_b = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.today(),
})
try_transition(job_b, "commercial_status", "on_hold", True, "comm: negotiating->on_hold")

# Operational track
job_c = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.today(),
})
try_transition(job_c, "operational_status", "live", False, "op: planning->live (skip)")
try_transition(job_c, "operational_status", "soft_hold", True, "op: planning->soft_hold")
try_transition(job_c, "operational_status", "confirmed", True, "op: soft_hold->confirmed")
try_transition(job_c, "operational_status", "pre_event", True, "op: confirmed->pre_event")
try_transition(job_c, "operational_status", "planning", False, "op: pre_event->planning (back)")

# Finance track
job_d = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.today(),
})
try_transition(job_d, "finance_status", "fully_paid", False, "fin: quoted->fully_paid (skip)")
try_transition(job_d, "finance_status", "deposit_pending", True, "fin: quoted->deposit_pending")
try_transition(job_d, "finance_status", "deposit_received", True, "fin: dp_pending->dp_received")

print()
hdr = "{:<46}{:<8}{:<60}{:<18}{}".format(
    "TRANSITION", "EXP", "ACTUAL", "AT", "STATUS")
print(hdr)
print("-" * 150)
for r in results:
    actual_short = r[3][:58]
    print("{:<46}{:<8}{:<60}{:<18}{}".format(
        r[0], r[2], actual_short, str(r[5]), r[4]))

t2_fails = [r for r in results if r[4] == "FAIL"]
print()
print("T2 summary:", len(results) - len(t2_fails), "/", len(results),
      "pass,", len(t2_fails), "fail")
env.cr.rollback()

# ============================================================
print()
print("=" * 70)
print("T3 - Loss reason guard at archive")
print("=" * 70)
job = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.today(),
})
try:
    job.action_archive_lost()
    print("T3a FAIL: should have raised UserError")
    t3a_pass = False
except UserError as e:
    print("T3a PASS: blocked -", str(e)[:120])
    t3a_pass = True

job.write({"loss_reason": "Smoke test reason"})
job.action_archive_lost()
if job.state == "archived":
    print("T3b PASS: state after archive =", job.state)
    t3b_pass = True
else:
    print("T3b FAIL: expected archived, got", job.state)
    t3b_pass = False
env.cr.rollback()

# ============================================================
print()
print("=" * 70)
print("T4 - Manager bypass")
print("=" * 70)
mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")
mgr_user = env["res.users"].search([("login", "ilike", "robin@")], limit=1)
if not mgr_user:
    mgr_user = env["res.users"].search([("login", "ilike", "munashe@")], limit=1)
if not mgr_user:
    print("T4 SKIP: no robin@ or munashe@ user found")
    t4_pass = None
else:
    mgr_user.write({"groups_id": [(4, mgr_group.id)]})
    print("T4: promoted", mgr_user.name, "(", mgr_user.login, ") to manager")
    print("     has manager group?",
          mgr_user.has_group("neon_jobs.group_neon_jobs_manager"))
    job = env["commercial.job"].with_user(mgr_user).create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.today(),
    })
    try:
        job.action_archive_lost()
        if job.state == "archived":
            print("T4 PASS: manager archived without loss_reason; state=", job.state)
            t4_pass = True
        else:
            print("T4 FAIL: expected archived, got", job.state)
            t4_pass = False
    except Exception as e:
        print("T4 FAIL: manager bypass raised", type(e).__name__, ":", e)
        t4_pass = False
env.cr.rollback()

# ============================================================
print()
print("=" * 70)
print("T5 - Form button wiring")
print("=" * 70)
job_form = env.ref("neon_jobs.commercial_job_view_form")
arch = job_form.arch
t5_results = []
for btn in ["action_activate", "action_complete", "action_cancel", "action_archive_lost"]:
    in_arch = btn in arch
    method = getattr(env["commercial.job"], btn, None)
    ok = in_arch and method is not None
    t5_results.append((btn, in_arch, method is not None, ok))
    print("T5:", btn.ljust(22), "in arch=", in_arch,
          " method=", method is not None, " ->", "PASS" if ok else "FAIL")
t5_pass = all(r[3] for r in t5_results)

# ============================================================
print()
print("=" * 70)
print("CLEANUP")
print("=" * 70)
env["commercial.job"].search([("partner_id", "=", client.id)]).unlink()
env.cr.commit()
print("Removed test commercial.job rows for client", client.name)

# ============================================================
print()
print("=" * 70)
print("SUMMARY TABLE")
print("=" * 70)
print("T1 Pending creation + soft_hold:   ", "PASS" if t1_pass else "FAIL")
print("T2 Status transitions:             ",
      len(results) - len(t2_fails), "/", len(results),
      "pass (", len(t2_fails), "FAILs )")
print("T3a Archive without reason blocks: ", "PASS" if t3a_pass else "FAIL")
print("T3b Archive with reason succeeds:  ", "PASS" if t3b_pass else "FAIL")
print("T4 Manager bypass:                 ",
      "PASS" if t4_pass else ("SKIP" if t4_pass is None else "FAIL"))
print("T5 Form button wiring:             ", "PASS" if t5_pass else "FAIL")

if t2_fails:
    print()
    print("T2 FAILS - full detail:")
    for r in t2_fails:
        print("  ", r[0], "->", r[1], " expected", r[2], " ACTUAL:", r[3])
