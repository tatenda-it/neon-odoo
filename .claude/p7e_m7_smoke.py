"""P7e.M7 smoke -- enrollment + completion models (11 tests)."""
import os

from odoo.exceptions import AccessError, ValidationError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Enrollment = env["slide.channel.partner"]
TrackComp = env["neon.lms.track.completion"]
ModuleComp = env["neon.lms.module.completion"]
Users = env["res.users"]
Partner = env["res.partner"]


def _get_or_create_user(login, name, group_xmlids):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
        })
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_learner = _get_or_create_user(
    "p7e_m7_learner", "P7e M7 Learner",
    ["neon_jobs.group_neon_jobs_crew"])
u_other = _get_or_create_user(
    "p7e_m7_other", "P7e M7 Other Learner",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

program = env.ref("neon_lms.program_channel")
foundations = env.ref("neon_lms.track_foundations_safety")
m01 = env.ref("neon_lms.module_m01")
m08 = env.ref("neon_lms.module_m08")


# ============================================================
print()
print("T7e700 - enrollment creates with channel + partner")
print("=" * 72)
enroll = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_learner.partner_id.id,
})
ok = bool(enroll) and enroll.channel_id == program
print(f"  id={enroll.id} channel={enroll.channel_id.name}")
print("T7e700:", "PASS" if ok else "FAIL")
results["T7e700"] = ok


# ============================================================
print()
print("T7e701 - neon_state defaults to 'enrolled'")
print("=" * 72)
ok = enroll.neon_state == "enrolled"
print(f"  state: {enroll.neon_state}")
print("T7e701:", "PASS" if ok else "FAIL")
results["T7e701"] = ok


# ============================================================
print()
print("T7e702 - track.completion creates")
print("=" * 72)
tc = TrackComp.sudo().create({
    "enrollment_id": enroll.id,
    "track_id": foundations.id,
})
ok = (bool(tc) and tc.state == "not_started"
      and tc.modules_total == 2)
print(f"  id={tc.id} state={tc.state} "
      f"modules_total={tc.modules_total}")
print("T7e702:", "PASS" if ok else "FAIL")
results["T7e702"] = ok


# ============================================================
print()
print("T7e703 - unique (enrollment, track) enforced")
print("=" * 72)
err, _r = _try(lambda: TrackComp.sudo().create({
    "enrollment_id": enroll.id,
    "track_id": foundations.id,
}))
ok = err is not None and (
    "unique" in (str(err) or "").lower()
    or "duplicate" in (str(err) or "").lower())
print(f"  err: {type(err).__name__ if err else None}")
print("T7e703:", "PASS" if ok else "FAIL")
results["T7e703"] = ok


# ============================================================
print()
print("T7e704 - module.completion creates")
print("=" * 72)
mc01 = ModuleComp.sudo().create({
    "enrollment_id": enroll.id,
    "module_id": m01.id,
})
ok = bool(mc01) and mc01.state == "not_started"
print(f"  id={mc01.id} state={mc01.state}")
print("T7e704:", "PASS" if ok else "FAIL")
results["T7e704"] = ok


# ============================================================
print()
print("T7e705 - unique (enrollment, module) enforced")
print("=" * 72)
err, _r = _try(lambda: ModuleComp.sudo().create({
    "enrollment_id": enroll.id,
    "module_id": m01.id,
}))
ok = err is not None
print(f"  err: {type(err).__name__ if err else None}")
print("T7e705:", "PASS" if ok else "FAIL")
results["T7e705"] = ok


# ============================================================
print()
print("T7e706 - track._can_transition_to_completed flips on "
      "all modules complete")
print("=" * 72)
# Pre: only m01 completion exists (state=not_started).
not_yet = tc._can_transition_to_completed()
# Now set m01 to completed + create m08 completion as
# completed; modules_total=2, completed=2 -> True.
mc01.sudo().write({"state": "completed"})
mc08 = ModuleComp.sudo().create({
    "enrollment_id": enroll.id,
    "module_id": m08.id,
    "state": "completed",
})
tc.invalidate_recordset()
now_yes = tc._can_transition_to_completed()
ok = (not_yet is False and now_yes is True)
print(f"  before all done: {not_yet} "
      f"after all done: {now_yes}")
print("T7e706:", "PASS" if ok else "FAIL")
results["T7e706"] = ok


# ============================================================
print()
print("T7e707 - module._can_transition requires quiz_score "
      ">= min")
print("=" * 72)
# m01 has min_quiz_score=0.8 default. Set 0.7 -> False;
# set 0.9 -> True.
mc01.sudo().write({"quiz_score": 0.7, "state": "in_progress"})
mc01.invalidate_recordset()
below_ok = not mc01._can_transition_to_completed()
mc01.sudo().write({"quiz_score": 0.9})
mc01.invalidate_recordset()
above_ok = mc01._can_transition_to_completed()
ok = below_ok and above_ok
print(f"  below threshold: blocked={below_ok}")
print(f"  above threshold: allowed={above_ok}")
print("T7e707:", "PASS" if ok else "FAIL")
results["T7e707"] = ok


# ============================================================
print()
print("T7e708 - learner reads own enrollment via rule")
print("=" * 72)
err, own = _try(
    lambda: Enrollment.with_user(u_learner).search([
        ("partner_id", "=", u_learner.partner_id.id),
    ]).read(["channel_id"]))
ok = err is None and len(own) >= 1
print(f"  err: {err} read count: {len(own) if own else 0}")
print("T7e708:", "PASS" if ok else "FAIL")
results["T7e708"] = ok


# ============================================================
print()
print("T7e709 - learner sees only own track completion via "
      "Neon-controlled rule")
print("=" * 72)
# Stdlib slide.channel.partner has broader rules that
# OR-combine with ours, so use track.completion (100%
# Neon-controlled) to verify the own-row pattern.
enroll_other = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_other.partner_id.id,
})
tc_other = TrackComp.sudo().create({
    "enrollment_id": enroll_other.id,
    "track_id": foundations.id,
})
visible = TrackComp.with_user(u_learner).search([])
ok = (tc in visible and tc_other not in visible)
print(f"  own visible: {tc in visible}")
print(f"  other visible (expect False): "
      f"{tc_other in visible}")
print("T7e709:", "PASS" if ok else "FAIL")
results["T7e709"] = ok


# ============================================================
print()
print("T7e710 - own-row rules loaded by xmlid")
print("=" * 72)
rule_xmlids = [
    "neon_lms.rule_enrollment_learner_own",
    "neon_lms.rule_track_completion_learner_own",
    "neon_lms.rule_module_completion_learner_own",
]
loaded = []
for xid in rule_xmlids:
    r = env.ref(xid, raise_if_not_found=False)
    if r:
        loaded.append(xid)
ok = len(loaded) == 3
print(f"  rules loaded: {len(loaded)}/3")
for xid in rule_xmlids:
    r = env.ref(xid, raise_if_not_found=False)
    print(f"    {xid}: "
          f"{'OK id=' + str(r.id) if r else 'MISSING'}")
print("T7e710:", "PASS" if ok else "FAIL")
results["T7e710"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e700", "T7e701", "T7e702", "T7e703", "T7e704",
         "T7e705", "T7e706", "T7e707", "T7e708", "T7e709",
         "T7e710"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
