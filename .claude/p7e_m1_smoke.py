"""P7e.M1 smoke -- track + module + slide.channel extension
(9 tests)."""
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

Channel = env["slide.channel"]
Track = env["neon.lms.track"]
Module = env["neon.lms.module"]
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


u_train_admin = _get_or_create_user(
    "p7e_m1_admin", "P7e M1 Train Admin",
    ["neon_training.group_neon_training_admin"])
u_crew = _get_or_create_user(
    "p7e_m1_crew", "P7e M1 Crew",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()


# ============================================================
print()
print("T7e100 - 1 program slide.channel seeded")
print("=" * 72)
program = env.ref(
    "neon_lms.program_channel", raise_if_not_found=False)
ok = (bool(program)
      and "Neon Workshop" in program.name
      and program.neon_program_state == "draft")
print(f"  program id={program.id if program else None}")
print(f"  name={program.name if program else None}")
print(f"  state={program.neon_program_state if program else None}")
print("T7e100:", "PASS" if ok else "FAIL")
results["T7e100"] = ok


# ============================================================
print()
print("T7e101 - 7 tracks seeded")
print("=" * 72)
tracks = Track.search([])
ok = len(tracks) == 7
print(f"  track count: {len(tracks)} (expected 7)")
print(f"  codes: {sorted(tracks.mapped('code'))}")
print("T7e101:", "PASS" if ok else "FAIL")
results["T7e101"] = ok


# ============================================================
print()
print("T7e102 - Foundations has is_foundation_gate=True")
print("=" * 72)
foundations = env.ref(
    "neon_lms.track_foundations_safety",
    raise_if_not_found=False)
ok = bool(foundations) and foundations.is_foundation_gate is True
print(f"  is_foundation_gate: "
      f"{foundations.is_foundation_gate if foundations else None}")
print("T7e102:", "PASS" if ok else "FAIL")
results["T7e102"] = ok


# ============================================================
print()
print("T7e103 - 6 non-foundation tracks prereq foundations")
print("=" * 72)
non_foundation = Track.search(
    [("is_foundation_gate", "=", False)])
all_prereq_ok = all(
    foundations in t.prerequisite_track_ids
    for t in non_foundation)
ok = (len(non_foundation) == 6 and all_prereq_ok)
print(f"  non-foundation count: {len(non_foundation)} (expected 6)")
print(f"  all prereq foundations: {all_prereq_ok}")
print("T7e103:", "PASS" if ok else "FAIL")
results["T7e103"] = ok


# ============================================================
print()
print("T7e104 - 17 modules seeded")
print("=" * 72)
modules = Module.search([])
ok = len(modules) == 17
print(f"  module count: {len(modules)} (expected 17)")
print(f"  codes: {sorted(modules.mapped('code'))}")
print("T7e104:", "PASS" if ok else "FAIL")
results["T7e104"] = ok


# ============================================================
print()
print("T7e105 - each module has track + channel related set")
print("=" * 72)
unlinked = modules.filtered(lambda m: not m.track_id)
channel_mismatch = modules.filtered(
    lambda m: m.channel_id != m.track_id.channel_id)
ok = (not unlinked and not channel_mismatch
      and all(m.channel_id == program for m in modules))
print(f"  unlinked: {len(unlinked)} channel_mismatch: {len(channel_mismatch)}")
print(f"  all on program channel: {all(m.channel_id == program for m in modules)}")
print("T7e105:", "PASS" if ok else "FAIL")
results["T7e105"] = ok


# ============================================================
print()
print("T7e106 - track.code unique enforced")
print("=" * 72)
err, _r = _try(lambda: Track.sudo().create({
    "code": "TRK_FOUND_SAFETY",  # collides
    "name": "Dup Track",
    "channel_id": program.id,
    "is_foundation_gate": False,
    "prerequisite_track_ids": [(4, foundations.id)],
}))
ok = err is not None and (
    "unique" in (str(err) or "").lower()
    or "duplicate" in (str(err) or "").lower())
print(f"  err class: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:80] if err else ''}")
print("T7e106:", "PASS" if ok else "FAIL")
results["T7e106"] = ok


# ============================================================
print()
print("T7e107 - crew can read tracks (cannot create)")
print("=" * 72)
err_read, _r = _try(
    lambda: Track.with_user(u_crew).search([]).read(["name"]))
err_create, _r2 = _try(lambda: Track.with_user(u_crew).create({
    "code": "TRK_CREW_FAIL",
    "name": "Crew Create Fail",
    "channel_id": program.id,
    "is_foundation_gate": False,
    "prerequisite_track_ids": [(4, foundations.id)],
}))
ok = (err_read is None
      and isinstance(err_create, AccessError))
print(f"  read err: {type(err_read).__name__ if err_read else None}")
print(f"  create err: {type(err_create).__name__ if err_create else None}")
print("T7e107:", "PASS" if ok else "FAIL")
results["T7e107"] = ok


# ============================================================
print()
print("T7e108 - training_admin can full CRUD")
print("=" * 72)
new_track_data = {
    "code": "TRK_ADMIN_TEST",
    "name": "Admin Test Track",
    "channel_id": program.id,
    "is_foundation_gate": False,
    "prerequisite_track_ids": [(4, foundations.id)],
}
err, new_track = _try(
    lambda: Track.with_user(u_train_admin).create(new_track_data))
write_ok = False
if new_track:
    err_w, _r = _try(lambda: new_track.with_user(
        u_train_admin).write({"description": "Updated"}))
    write_ok = err_w is None
ok = (err is None and new_track and write_ok)
print(f"  create: {bool(new_track)}")
print(f"  write: {write_ok}")
print("T7e108:", "PASS" if ok else "FAIL")
results["T7e108"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e100", "T7e101", "T7e102", "T7e103", "T7e104",
         "T7e105", "T7e106", "T7e107", "T7e108"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
