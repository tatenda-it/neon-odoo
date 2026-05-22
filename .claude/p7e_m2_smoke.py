"""P7e.M2 smoke -- operating authority model + 6 seeds (7 tests)."""
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

Authority = env["neon.lms.operating.authority"]
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


u_crew = _get_or_create_user(
    "p7e_m1_crew", "P7e M1 Crew",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()


# ============================================================
print()
print("T7e200 - 6 authority records seeded")
print("=" * 72)
auths = Authority.search([])
ok = len(auths) == 6
print(f"  count: {len(auths)} (expected 6)")
print(f"  codes: {sorted(auths.mapped('code'))}")
print("T7e200:", "PASS" if ok else "FAIL")
results["T7e200"] = ok


# ============================================================
print()
print("T7e201 - stop_work requires Foundations only")
print("=" * 72)
stop_work = env.ref(
    "neon_lms.authority_stop_work",
    raise_if_not_found=False)
foundations = env.ref(
    "neon_lms.track_foundations_safety",
    raise_if_not_found=False)
ok = (bool(stop_work) and bool(foundations)
      and len(stop_work.requires_track_ids) == 1
      and stop_work.requires_track_ids == foundations)
print(f"  requires count: {len(stop_work.requires_track_ids) if stop_work else 'N/A'}")
print(f"  has foundations: "
      f"{stop_work.requires_track_ids == foundations if stop_work else False}")
print("T7e201:", "PASS" if ok else "FAIL")
results["T7e201"] = ok


# ============================================================
print()
print("T7e202 - working_at_height.requires_practical_signoff=True")
print("=" * 72)
wah = env.ref(
    "neon_lms.authority_working_at_height",
    raise_if_not_found=False)
ok = bool(wah) and wah.requires_practical_signoff is True
print(f"  practical signoff: "
      f"{wah.requires_practical_signoff if wah else None}")
print("T7e202:", "PASS" if ok else "FAIL")
results["T7e202"] = ok


# ============================================================
print()
print("T7e203 - working_at_height needs Foundations + Rigging")
print("=" * 72)
rigging = env.ref("neon_lms.track_rigging")
ok = bool(wah) and (
    foundations in wah.requires_track_ids
    and rigging in wah.requires_track_ids
    and len(wah.requires_track_ids) == 2)
print(f"  required tracks: "
      f"{wah.requires_track_ids.mapped('code') if wah else 'N/A'}")
print("T7e203:", "PASS" if ok else "FAIL")
results["T7e203"] = ok


# ============================================================
print()
print("T7e204 - track -> authority reverse mapping")
print("=" * 72)
electrical = env.ref("neon_lms.authority_electrical")
foundations_auths = foundations.operating_authority_ids
ok = (stop_work in foundations_auths
      and electrical in foundations_auths
      and len(foundations_auths) == 6)
print(f"  Foundations authorities: "
      f"{foundations_auths.mapped('code')}")
print(f"  count: {len(foundations_auths)} (expected 6)")
print("T7e204:", "PASS" if ok else "FAIL")
results["T7e204"] = ok


# ============================================================
print()
print("T7e205 - authority code uniqueness")
print("=" * 72)
err, _r = _try(lambda: Authority.sudo().create({
    "code": "stop_work",  # collides
    "name": "Dup Authority",
    "requires_track_ids": [(4, foundations.id)],
}))
ok = err is not None and (
    "unique" in (str(err) or "").lower()
    or "duplicate" in (str(err) or "").lower())
print(f"  err class: {type(err).__name__ if err else None}")
print("T7e205:", "PASS" if ok else "FAIL")
results["T7e205"] = ok


# ============================================================
print()
print("T7e206 - crew read-only on authority model")
print("=" * 72)
err_read, _r = _try(
    lambda: Authority.with_user(u_crew).search([]).read(["code"]))
err_create, _r2 = _try(
    lambda: Authority.with_user(u_crew).create({
        "code": "crew_fail",
        "name": "Crew Should Fail",
        "requires_track_ids": [(4, foundations.id)],
    }))
ok = (err_read is None
      and isinstance(err_create, AccessError))
print(f"  read err: {type(err_read).__name__ if err_read else None}")
print(f"  create err: {type(err_create).__name__ if err_create else None}")
print("T7e206:", "PASS" if ok else "FAIL")
results["T7e206"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e200", "T7e201", "T7e202", "T7e203",
         "T7e204", "T7e205", "T7e206"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
