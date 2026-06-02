"""P-HR-R3b C2 smoke -- neon.hr.review model + lifecycle + ACL."""
from odoo.exceptions import AccessError, UserError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R3b C2 -- performance reviews")
print("=" * 72)
results = {}

Review = env["neon.hr.review"]
Employee = env["hr.employee"]
Users = env["res.users"]


# Cleanup
for login in ("phr_r3b_c2_reviewee", "phr_r3b_c2_reviewer",
               "phr_r3b_c2_admin", "phr_r3b_c2_sales"):
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"login": login + "_OLD_" + str(u.id),
                  "active": False})
Review.sudo().search(
    [("review_period", "=", "PHR-R3B-C2-TEST")]).with_context(
    _allow_review_unlink=True).unlink() if False else None

g_super = env.ref("neon_core.group_neon_superuser")
g_sales = env.ref("neon_core.group_neon_sales_rep")
g_hr_admin = env.ref("neon_hr.group_neon_hr_admin")

# Reviewee (portal-ish: base.group_user only)
u_reviewee = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C2 Reviewee",
    "login": "phr_r3b_c2_reviewee",
    "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id)],
})
u_reviewer = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C2 Reviewer",
    "login": "phr_r3b_c2_reviewer",
    "password": "test123",
    "groups_id": [
        (4, env.ref("base.group_user").id),
        (4, g_super.id),
    ],
})
u_admin = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C2 Admin",
    "login": "phr_r3b_c2_admin",
    "password": "test123",
    "groups_id": [
        (4, env.ref("base.group_user").id),
        (4, g_hr_admin.id),
    ],
})
u_sales = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-R3b C2 Sales",
    "login": "phr_r3b_c2_sales",
    "password": "test123",
    "groups_id": [
        (4, env.ref("base.group_user").id),
        (4, g_sales.id),
    ],
})

# Employee linked to the reviewee user
emp = Employee.sudo().create({
    "name": "PHR-R3b C2 Reviewee Employee",
    "user_id": u_reviewee.id,
})
env.cr.commit()


# ============================================================
# T-R3b-C2-01 -- model + perm_unlink=0
# ============================================================
_check("T-R3b-C2-01",
       "neon.hr.review" in env,
       "neon.hr.review model registered")

unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.hr.review"),
    ("perm_unlink", "=", True),
])
_check("T-R3b-C2-02", not unlinkable,
       f"perm_unlink=0 on all review ACL rows; got "
       f"violations={unlinkable.mapped('group_id.name')}")


# ============================================================
# T-R3b-C2-03 -- create as HR Admin succeeds
# ============================================================
rev_admin = Review.with_user(u_admin).create({
    "employee_id": emp.id,
    "review_period": "PHR-R3B-C2-TEST",
    "reviewer_id": u_reviewer.id,
})
_check("T-R3b-C2-03",
       rev_admin and rev_admin.state == "draft",
       f"create as HR Admin: id={rev_admin.id} state="
       f"{rev_admin.state}")


# ============================================================
# T-R3b-C2-04 -- submit refused without rating + comments
# ============================================================
refused = False
try:
    rev_admin.with_user(u_admin).action_submit()
except UserError:
    refused = True
_check("T-R3b-C2-04", refused,
       "submit refused when ratings + comments missing")


# ============================================================
# T-R3b-C2-05 -- submit succeeds with ratings + comments
# ============================================================
rev_admin.with_user(u_admin).write({
    "rating_overall": 4,
    "rating_technical": 4,
    "rating_conduct": 5,
    "reviewer_comments": "Strong technical contribution; safety-first conduct.",
})
rev_admin.with_user(u_admin).action_submit()
rev_admin.invalidate_recordset(
    ["state", "submitted_at", "submitted_by_id"])
_check("T-R3b-C2-05",
       rev_admin.state == "submitted"
       and bool(rev_admin.submitted_at)
       and rev_admin.submitted_by_id.id == u_admin.id,
       f"submitted: state={rev_admin.state} by="
       f"{rev_admin.submitted_by_id.id} (expected {u_admin.id})")


# ============================================================
# T-R3b-C2-06 -- SQL CHECK on rating range. Wrap in a savepoint
# so the constraint failure rolls back cleanly without poisoning
# subsequent tests.
# ============================================================
range_blocked = False
try:
    with env.cr.savepoint():
        rev_admin.with_user(u_admin).write(
            {"rating_overall": 99})
        rev_admin.flush_recordset(["rating_overall"])
except Exception:
    range_blocked = True
_check("T-R3b-C2-06", range_blocked,
       "SQL CHECK rejects out-of-range rating")


# ============================================================
# T-R3b-C2-07 -- acknowledge by employee OWNER succeeds
# ============================================================
rev_admin.with_user(u_reviewee).action_acknowledge()
rev_admin.invalidate_recordset(
    ["state", "acknowledged_at", "acknowledged_by_id"])
_check("T-R3b-C2-07",
       rev_admin.state == "acknowledged"
       and bool(rev_admin.acknowledged_at)
       and rev_admin.acknowledged_by_id.id == u_reviewee.id,
       f"acknowledged: state={rev_admin.state} by="
       f"{rev_admin.acknowledged_by_id.id} (expected reviewee "
       f"{u_reviewee.id})")


# ============================================================
# T-R3b-C2-08 -- acknowledged is append-only (back_to_draft refused)
# ============================================================
walked_back = False
try:
    rev_admin.with_user(u_admin).action_back_to_draft()
except UserError:
    walked_back = False
else:
    walked_back = True
_check("T-R3b-C2-08", not walked_back,
       "acknowledged review cannot be reverted to draft")


# ============================================================
# T-R3b-C2-09 -- Sales (non-HR) cannot READ another's review
# ============================================================
sales_read = []
try:
    sales_read = Review.with_user(u_sales).search(
        [("id", "=", rev_admin.id)])
except AccessError:
    pass
_check("T-R3b-C2-09",
       len(sales_read) == 0,
       f"Sales sees 0 reviews (record rule); got len={len(sales_read)}")


# ============================================================
# T-R3b-C2-10 -- Owner CAN read their own (record rule)
# ============================================================
owner_read = Review.with_user(u_reviewee).search(
    [("id", "=", rev_admin.id)])
_check("T-R3b-C2-10",
       len(owner_read) == 1,
       f"owner reads own review; got len={len(owner_read)}")


# ============================================================
# T-R3b-C2-11 -- Reviewer CAN read assigned review
# ============================================================
reviewer_read = Review.with_user(u_reviewer).search(
    [("id", "=", rev_admin.id)])
_check("T-R3b-C2-11",
       len(reviewer_read) == 1,
       f"reviewer reads assigned review; got "
       f"len={len(reviewer_read)}")


# ============================================================
# T-R3b-C2-12 -- HR Admin sees all (test by another review)
# ============================================================
rev2 = Review.with_user(u_admin).create({
    "employee_id": emp.id,
    "review_period": "PHR-R3B-C2-TEST-2",
    "reviewer_id": u_reviewer.id,
})
admin_all = Review.with_user(u_admin).search([
    ("review_period", "like", "PHR-R3B-C2-TEST")])
_check("T-R3b-C2-12",
       len(admin_all) >= 2,
       f"HR Admin sees all reviews; got len={len(admin_all)}")


# ============================================================
# T-R3b-C2-13 -- Sales cannot CREATE a review
# ============================================================
sales_create_blocked = False
try:
    Review.with_user(u_sales).create({
        "employee_id": emp.id,
        "review_period": "PHR-R3B-C2-SALES",
        "reviewer_id": u_reviewer.id,
    })
except AccessError:
    sales_create_blocked = True
_check("T-R3b-C2-13", sales_create_blocked,
       "Sales user blocked from creating a review")


# Cleanup
for u in (u_reviewee, u_reviewer, u_admin, u_sales):
    u.sudo().write({"active": False})
emp.sudo().write({"active": False})
env.cr.commit()


print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
