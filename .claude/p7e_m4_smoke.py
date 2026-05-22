"""P7e.M4 smoke -- quiz question + option (8 tests)."""
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

Q = env["neon.lms.quiz.question"]
O = env["neon.lms.quiz.option"]
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


u_admin = _get_or_create_user(
    "p7e_m4_admin", "P7e M4 Train Admin",
    ["neon_training.group_neon_training_admin"])
u_crew = _get_or_create_user(
    "p7e_m1_crew", "P7e M1 Crew",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

m01 = env.ref("neon_lms.module_m01")


# ============================================================
print()
print("T7e400 - question creates with required fields")
print("=" * 72)
q = Q.sudo().create({
    "module_id": m01.id,
    "question_text": "What is the first step before any electrical work?",
    "question_type": "multiple_choice",
    "option_ids": [
        (0, 0, {"option_text": "Power off + lockout/tagout",
                "is_correct": True}),
        (0, 0, {"option_text": "Just be careful",
                "is_correct": False}),
    ],
})
ok = bool(q) and q.module_id == m01
print(f"  id={q.id} module={q.module_id.code}")
print("T7e400:", "PASS" if ok else "FAIL")
results["T7e400"] = ok


# ============================================================
print()
print("T7e401 - MC without is_correct option raises")
print("=" * 72)
err, _r = _try(lambda: Q.sudo().create({
    "module_id": m01.id,
    "question_text": "Bad MC",
    "question_type": "multiple_choice",
    "option_ids": [
        (0, 0, {"option_text": "A", "is_correct": False}),
        (0, 0, {"option_text": "B", "is_correct": False}),
    ],
}))
ok = isinstance(err, ValidationError)
print(f"  err: {type(err).__name__ if err else None}")
print("T7e401:", "PASS" if ok else "FAIL")
results["T7e401"] = ok


# ============================================================
print()
print("T7e402 - short_answer without correct_answer raises")
print("=" * 72)
err, _r = _try(lambda: Q.sudo().create({
    "module_id": m01.id,
    "question_text": "Bad SA",
    "question_type": "short_answer",
}))
ok = isinstance(err, ValidationError)
print(f"  err: {type(err).__name__ if err else None}")
print("T7e402:", "PASS" if ok else "FAIL")
results["T7e402"] = ok


# ============================================================
print()
print("T7e403 - option.question_id required")
print("=" * 72)
err, _r = _try(lambda: O.sudo().create({
    "option_text": "orphan",
    "is_correct": True,
}))
ok = err is not None
print(f"  err: {type(err).__name__ if err else None}")
print("T7e403:", "PASS" if ok else "FAIL")
results["T7e403"] = ok


# ============================================================
print()
print("T7e404 - ondelete cascade removes options")
print("=" * 72)
q2 = Q.sudo().create({
    "module_id": m01.id,
    "question_text": "Cascade test",
    "question_type": "multiple_choice",
    "option_ids": [
        (0, 0, {"option_text": "yes", "is_correct": True}),
    ],
})
opt_id = q2.option_ids[0].id
q2.sudo().unlink()
remaining = O.sudo().search([("id", "=", opt_id)])
ok = not remaining
print(f"  option {opt_id} after unlink: "
      f"{'gone' if not remaining else 'still present'}")
print("T7e404:", "PASS" if ok else "FAIL")
results["T7e404"] = ok


# ============================================================
print()
print("T7e405 - admin CRUD on Q + option")
print("=" * 72)
err_c, q3 = _try(lambda: Q.with_user(u_admin).create({
    "module_id": m01.id,
    "question_text": "Admin write test",
    "question_type": "multiple_choice",
    "option_ids": [
        (0, 0, {"option_text": "a", "is_correct": True}),
    ],
}))
err_w = None
if q3:
    err_w, _r = _try(
        lambda: q3.with_user(u_admin).write(
            {"explanation": "Updated"}))
ok = err_c is None and bool(q3) and err_w is None
print(f"  create: {bool(q3)} write err: {err_w}")
print("T7e405:", "PASS" if ok else "FAIL")
results["T7e405"] = ok


# ============================================================
print()
print("T7e406 - crew read only on questions")
print("=" * 72)
err_r, _r = _try(
    lambda: Q.with_user(u_crew).search([]).read(["question_text"]))
err_c, _r2 = _try(lambda: Q.with_user(u_crew).create({
    "module_id": m01.id,
    "question_text": "Crew should fail",
    "question_type": "multiple_choice",
    "option_ids": [(0, 0, {"option_text": "a",
                            "is_correct": True})],
}))
ok = err_r is None and isinstance(err_c, AccessError)
print(f"  read err: {err_r} create err class: "
      f"{type(err_c).__name__ if err_c else None}")
print("T7e406:", "PASS" if ok else "FAIL")
results["T7e406"] = ok


# ============================================================
print()
print("T7e407 - q.option_ids reverse pointer")
print("=" * 72)
q.invalidate_recordset()
ok = (len(q.option_ids) == 2
      and all(o.question_id == q for o in q.option_ids))
print(f"  option count: {len(q.option_ids)}")
print("T7e407:", "PASS" if ok else "FAIL")
results["T7e407"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e400", "T7e401", "T7e402", "T7e403",
         "T7e404", "T7e405", "T7e406", "T7e407"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
