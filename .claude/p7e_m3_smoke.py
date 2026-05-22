"""P7e.M3 smoke -- Foundations strict gate enforcement (6 tests).

Helpers (_can_user_start, _reason_user_cannot_start,
@api.constrains _check_foundation_gate_prereqs) shipped with
M1 for cohesion; M3 is the smoke that exercises them.
"""
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

Track = env["neon.lms.track"]
Users = env["res.users"]


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


u_test = _get_or_create_user(
    "p7e_m3_test", "P7e M3 Test User",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()


foundations = env.ref("neon_lms.track_foundations_safety")
audio = env.ref("neon_lms.track_audio")
program = env.ref("neon_lms.program_channel")


# ============================================================
print()
print("T7e300 - Foundations._can_user_start returns True")
print("=" * 72)
result = foundations._can_user_start(u_test)
ok = result is True
print(f"  result: {result} (expected True)")
print("T7e300:", "PASS" if ok else "FAIL")
results["T7e300"] = ok


# ============================================================
print()
print("T7e301 - Audio._can_user_start returns False "
      "(no completion model)")
print("=" * 72)
# neon.lms.track.completion doesn't exist yet (M7 model);
# defensive env.get returns None; _can_user_start returns
# False conservatively.
completion_model = env.get("neon.lms.track.completion")
print(f"  completion model exists: {completion_model is not None}")
result = audio._can_user_start(u_test)
ok = result is False
print(f"  result: {result} (expected False)")
print("T7e301:", "PASS" if ok else "FAIL")
results["T7e301"] = ok


# ============================================================
print()
print("T7e302 - _reason_user_cannot_start returns helpful msg")
print("=" * 72)
reason = audio._reason_user_cannot_start(u_test)
ok = (isinstance(reason, str)
      and len(reason) > 0
      and (foundations.name in reason
           or "Complete these tracks" in reason
           or "not yet active" in reason))
print(f"  reason: {reason[:100]}")
print("T7e302:", "PASS" if ok else "FAIL")
results["T7e302"] = ok


# ============================================================
print()
print("T7e303 - foundation gate cannot have prereqs")
print("=" * 72)
err, _r = _try(lambda: Track.sudo().create({
    "code": "TRK_BAD_FOUND",
    "name": "Bad Foundation Track",
    "channel_id": program.id,
    "is_foundation_gate": True,
    "prerequisite_track_ids": [(4, audio.id)],
}))
ok = isinstance(err, ValidationError) and (
    "foundation" in (str(err) or "").lower()
    and "prerequisite" in (str(err) or "").lower())
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:100] if err else ''}")
print("T7e303:", "PASS" if ok else "FAIL")
results["T7e303"] = ok


# ============================================================
print()
print("T7e304 - non-foundation must include Foundations prereq")
print("=" * 72)
err, _r = _try(lambda: Track.sudo().create({
    "code": "TRK_NO_PREREQ",
    "name": "No Prereq Track",
    "channel_id": program.id,
    "is_foundation_gate": False,
    # Missing foundations in prereqs
}))
ok = isinstance(err, ValidationError) and (
    "foundation" in (str(err) or "").lower()
    and "prerequisite" in (str(err) or "").lower())
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:100] if err else ''}")
print("T7e304:", "PASS" if ok else "FAIL")
results["T7e304"] = ok


# ============================================================
print()
print("T7e305 - existing 7 seeds pass constraint validation")
print("=" * 72)
all_tracks = Track.search([])
err, _r = _try(
    lambda: all_tracks._check_foundation_gate_prereqs())
ok = (len(all_tracks) == 7 and err is None)
print(f"  track count: {len(all_tracks)} "
      f"constraint check err: {type(err).__name__ if err else None}")
print("T7e305:", "PASS" if ok else "FAIL")
results["T7e305"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e300", "T7e301", "T7e302", "T7e303",
         "T7e304", "T7e305"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
