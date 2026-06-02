"""P-HR-R3b C3 smoke -- licence-class matching on the crew gate."""
from datetime import date, timedelta

from odoo.exceptions import UserError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R3b C3 -- licence-class matching")
print("=" * 72)
results = {}

Crew = env["commercial.job.crew"]
Job = env["commercial.job"]
Employee = env["hr.employee"]
Licence = env["neon.hr.licence"]
Partner = env["res.partner"]
Users = env["res.users"]
today = date.today()


# Cleanup
for login in ("phr_r3b_c3_driver_c2",
                "phr_r3b_c3_driver_c4",
                "phr_r3b_c3_no_licence"):
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"login": login + "_OLD_" + str(u.id),
                  "active": False})

Crew.sudo().search(
    [("partner_id.name", "=like", "PHR-R3b C3%")]).unlink()
job_existing = Job.sudo().search(
    [("name", "=like", "PHR-R3B C3%")])
job_existing.unlink()
Employee.sudo().search(
    [("name", "=like", "PHR-R3b C3%")]).unlink()
# Don't unlink partners -- they're FK'd by res_users for prior
# test users; leftover partners are harmless.


# Make N parent jobs so each crew assignment can reuse the same
# user without hitting unique(job_id, partner_id)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)
customer = Partner.sudo().search([], limit=1)


def _mk_job(label):
    return Job.sudo().create({
        "name": "PHR-R3B C3 " + label,
        "partner_id": customer.id,
        "state": "active",
        "event_date": today,
        **({"venue_id": venue.id} if venue else {}),
    })


job = _mk_job("MainJob")

# Create users + employees + licences
def _mk_emp_with_licence(login, name, licence_class):
    u = Users.sudo().with_context(no_reset_password=True).create({
        "name": name, "login": login,
        "password": "test123",
        "groups_id": [(4, env.ref("base.group_user").id)],
    })
    emp = Employee.sudo().create({
        "name": name, "user_id": u.id})
    if licence_class:
        Licence.sudo().create({
            "employee_id": emp.id,
            "licence_class": licence_class,
            "licence_number": "PHR-R3b-" + login,
            "expiry_date": today + timedelta(days=365),
        })
    return u, emp


u_c2, emp_c2 = _mk_emp_with_licence(
    "phr_r3b_c3_driver_c2", "PHR-R3b C3 Driver C2", "class_2")
u_c4, emp_c4 = _mk_emp_with_licence(
    "phr_r3b_c3_driver_c4", "PHR-R3b C3 Driver C4", "class_4")
u_nl, emp_nl = _mk_emp_with_licence(
    "phr_r3b_c3_no_licence", "PHR-R3b C3 No Licence", None)
env.cr.commit()


# ============================================================
# T-R3b-C3-01 -- field exists on commercial.job.crew
# ============================================================
_check("T-R3b-C3-01",
       "neon_required_licence_class" in Crew._fields
       and Crew._fields["neon_required_licence_class"].type == "selection",
       "neon_required_licence_class field exists + is Selection")


# ============================================================
# T-R3b-C3-02 -- required Class 4 + driver has Class 4 → OK
# ============================================================
crew_ok_c4 = Crew.sudo().create({
    "job_id": _mk_job("Test%d" % len(results)).id,
    "user_id": u_c4.id, "role": "driver",
    "neon_required_licence_class": "class_4",
})
_check("T-R3b-C3-02",
       crew_ok_c4 and crew_ok_c4.neon_gate_state == "ok",
       f"Class 4 required, driver has Class 4 -> ok; state="
       f"{crew_ok_c4.neon_gate_state}")


# ============================================================
# T-R3b-C3-03 -- required Class 4 + driver has Class 2 → BLOCK
# ============================================================
blocked_wrong_class = False
reason = ""
try:
    with env.cr.savepoint():
        Crew.sudo().create({
            "job_id": _mk_job("Test%d" % len(results)).id,
            "user_id": u_c2.id, "role": "driver",
            "neon_required_licence_class": "class_4",
        })
except UserError as exc:
    blocked_wrong_class = True
    reason = str(exc)
_check("T-R3b-C3-03",
       blocked_wrong_class and "Class 4" in reason,
       f"Class 4 required, driver has Class 2 -> blocked; "
       f"reason={reason[:80]!r}")


# ============================================================
# T-R3b-C3-04 -- required Class 2 + driver has Class 2 → OK
# ============================================================
crew_ok_c2 = Crew.sudo().create({
    "job_id": _mk_job("Test%d" % len(results)).id,
    "user_id": u_c2.id, "role": "driver",
    "neon_required_licence_class": "class_2",
})
_check("T-R3b-C3-04",
       crew_ok_c2 and crew_ok_c2.neon_gate_state == "ok",
       f"Class 2 required, driver has Class 2 -> ok; state="
       f"{crew_ok_c2.neon_gate_state}")


# ============================================================
# T-R3b-C3-05 -- required Class 2 + driver has Class 4 → BLOCK
# ============================================================
blocked_swap = False
reason = ""
try:
    with env.cr.savepoint():
        Crew.sudo().create({
            "job_id": _mk_job("Test%d" % len(results)).id,
            "user_id": u_c4.id, "role": "driver",
            "neon_required_licence_class": "class_2",
        })
except UserError as exc:
    blocked_swap = True
    reason = str(exc)
_check("T-R3b-C3-05",
       blocked_swap and "Class 2" in reason,
       f"Class 2 required, driver has Class 4 -> blocked; "
       f"reason={reason[:80]!r}")


# ============================================================
# T-R3b-C3-06 -- required Class 4 + driver has NO licence → BLOCK
# ============================================================
blocked_no_lic = False
reason = ""
try:
    with env.cr.savepoint():
        Crew.sudo().create({
            "job_id": _mk_job("Test%d" % len(results)).id,
            "user_id": u_nl.id, "role": "driver",
            "neon_required_licence_class": "class_4",
        })
except UserError as exc:
    blocked_no_lic = True
    reason = str(exc)
_check("T-R3b-C3-06",
       blocked_no_lic,
       f"Class 4 required, no licence -> blocked; "
       f"reason={reason[:80]!r}")


# ============================================================
# T-R3b-C3-07 -- NO class set (fallback to R3a) + driver has
# Class 2 → OK (any valid licence qualifies)
# ============================================================
crew_fallback = Crew.sudo().create({
    "job_id": _mk_job("Test%d" % len(results)).id,
    "user_id": u_c2.id, "role": "driver",
    # no neon_required_licence_class
})
_check("T-R3b-C3-07",
       crew_fallback and crew_fallback.neon_gate_state == "ok",
       f"No class required, driver has any valid licence -> ok; "
       f"state={crew_fallback.neon_gate_state}")


# ============================================================
# T-R3b-C3-08 -- NO class set + driver has NO licence → BLOCK
# (R3a behaviour preserved)
# ============================================================
blocked_r3a = False
try:
    with env.cr.savepoint():
        Crew.sudo().create({
            "job_id": _mk_job("Test%d" % len(results)).id,
            "user_id": u_nl.id, "role": "driver",
        })
except UserError:
    blocked_r3a = True
_check("T-R3b-C3-08", blocked_r3a,
       "R3a fallback: no class + no licence -> blocked")


# ============================================================
# T-R3b-C3-09 -- non-driver role bypasses the licence gate entirely
# ============================================================
crew_nondriver = Crew.sudo().create({
    "job_id": _mk_job("Test%d" % len(results)).id,
    "user_id": u_nl.id, "role": "tech",
    "neon_required_licence_class": "class_4",
})
# The licence-class gate only fires for role='driver'. A non-
# driver row may still surface R3a's competency_warning (separate
# rail, not R3b's concern). We assert the gate did NOT licence-
# block, not that everything is 'ok'.
_check("T-R3b-C3-09",
       (crew_nondriver
        and crew_nondriver.neon_gate_state != "licence_block"),
       f"non-driver role bypasses LICENCE gate (state="
       f"{crew_nondriver.neon_gate_state}; not 'licence_block')")


# ============================================================
# T-R3b-C3-10 -- licence-block is NON-override-able even with
# competency override flag set (legal/safety rail held)
# ============================================================
unbreakable = False
reason = ""
try:
    with env.cr.savepoint():
        Crew.sudo().create({
            "job_id": _mk_job("Test%d" % len(results)).id,
            "user_id": u_c4.id, "role": "driver",
            "neon_required_licence_class": "class_2",
            "neon_competency_override": True,
        })
except UserError as exc:
    unbreakable = True
    reason = str(exc)
_check("T-R3b-C3-10",
       unbreakable and "Class 2" in reason,
       f"licence-block stays NON-override-able even with "
       f"competency_override=True; reason={reason[:60]!r}")


# Cleanup
all_jobs = Job.sudo().search(
    [("name", "=like", "PHR-R3B C3%")])
Crew.sudo().search(
    [("job_id", "in", all_jobs.ids)]).unlink()
all_jobs.unlink()
for emp in (emp_c2, emp_c4, emp_nl):
    Licence.sudo().search(
        [("employee_id", "=", emp.id)]).unlink()
    emp.unlink()
for u in (u_c2, u_c4, u_nl):
    u.sudo().write({"active": False})
env.cr.commit()


print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
