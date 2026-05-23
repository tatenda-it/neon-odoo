"""Phase 7d M1 smoke -- category + tag models + 5 seeds +
ACLs (11 tests).

T7d100 - 5 category seeds resolve via env.ref
T7d101 - category.code unique sql constraint
T7d102 - tag.name unique sql constraint
T7d103 - category form view loads
T7d104 - tag form view loads
T7d105 - superuser full CRUD on both models
T7d106 - training_admin full CRUD on both models
T7d107 - base user reads but cannot create
T7d108 - portal user reads categories
T7d109 - chatter works on category (message_post)
T7d110 - manually-created records survive module -u
         (noupdate independence check)
"""
from odoo.exceptions import AccessError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Cat = env["neon.kb.category"]
Tag = env["neon.kb.tag"]
Users = env["res.users"]
View = env["ir.ui.view"]


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


def _get_or_create_user(login, name, group_xmlid):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
            "email": login + "@example.test",
        })
    elif not u.email:
        u.sudo().email = login + "@example.test"
    if group_xmlid:
        g = env.ref(group_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7d_m1_super", "P7d M1 Super",
    "neon_core.group_neon_superuser")
u_admin = _get_or_create_user(
    "p7d_m1_admin", "P7d M1 Train Admin",
    "neon_training.group_neon_training_admin")
u_user = _get_or_create_user(
    "p7d_m1_user", "P7d M1 Internal User",
    "base.group_user")
# Portal user needs special handling: cannot also be
# base.group_user (one user type rule). Create fresh with
# groups_id=portal-only (REPLACE), or look up existing.
u_portal = Users.sudo().search(
    [("login", "=", "p7d_m1_portal")], limit=1)
if not u_portal:
    portal_group = env.ref("base.group_portal")
    u_portal = Users.sudo().with_context(
        no_reset_password=True).create({
        "name": "P7d M1 Portal User",
        "login": "p7d_m1_portal",
        "password": "test123",
        "email": "p7d_m1_portal@example.test",
        "groups_id": [(6, 0, [portal_group.id])],
    })
env.cr.commit()


# ============================================================
print()
print("T7d100 - 5 category seeds resolve via env.ref")
print("=" * 72)
expected = [
    "neon_kb.category_audio",
    "neon_kb.category_lighting",
    "neon_kb.category_video",
    "neon_kb.category_safety",
    "neon_kb.category_admin",
]
resolved = []
for xmlid in expected:
    r = env.ref(xmlid, raise_if_not_found=False)
    resolved.append((xmlid, bool(r),
                     r.name if r else None,
                     r.code if r else None))
ok = all(found for _x, found, _n, _c in resolved)
for xmlid, found, name, code in resolved:
    print(f"  {xmlid}: {found} ({name}, code={code})")
print("T7d100:", "PASS" if ok else "FAIL")
results["T7d100"] = ok


# ============================================================
print()
print("T7d101 - category.code unique constraint")
print("=" * 72)
seed = env.ref("neon_kb.category_audio")
err, _v = _try(lambda: Cat.sudo().create({
    "name": "Audio duplicate probe",
    "code": seed.code,
}))
ok = (err is not None
      and ("unique" in str(err).lower()
           or "duplicate" in str(err).lower()))
print(f"  err type: {type(err).__name__ if err else None}")
print(f"  msg: {str(err)[:120] if err else None}")
print("T7d101:", "PASS" if ok else "FAIL")
results["T7d101"] = ok


# ============================================================
print()
print("T7d102 - tag.name unique constraint")
print("=" * 72)
t1 = Tag.sudo().create({"name": "T7d102 probe"})
err, _v = _try(lambda: Tag.sudo().create(
    {"name": "T7d102 probe"}))
ok = (err is not None
      and ("unique" in str(err).lower()
           or "duplicate" in str(err).lower()))
print(f"  err: {type(err).__name__ if err else None}")
print("T7d102:", "PASS" if ok else "FAIL")
results["T7d102"] = ok


# ============================================================
print()
print("T7d103 - category form view loads")
print("=" * 72)
cat_form = env.ref(
    "neon_kb.view_kb_category_form",
    raise_if_not_found=False)
ok = bool(cat_form)
if cat_form:
    try:
        info = Cat.get_view(
            view_id=cat_form.id, view_type="form")
        ok = ok and bool(info.get("arch"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  view present: {bool(cat_form)}")
print("T7d103:", "PASS" if ok else "FAIL")
results["T7d103"] = ok


# ============================================================
print()
print("T7d104 - tag form view loads")
print("=" * 72)
tag_form = env.ref(
    "neon_kb.view_kb_tag_form",
    raise_if_not_found=False)
ok = bool(tag_form)
if tag_form:
    try:
        info = Tag.get_view(
            view_id=tag_form.id, view_type="form")
        ok = ok and bool(info.get("arch"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  view present: {bool(tag_form)}")
print("T7d104:", "PASS" if ok else "FAIL")
results["T7d104"] = ok


# ============================================================
print()
print("T7d105 - superuser full CRUD")
print("=" * 72)
err_c, v_cat = _try(
    lambda: Cat.with_user(u_super).create({
        "name": "T7d105 super cat",
        "code": "t7d105-super",
    }))
err_w = None
err_u = None
if v_cat:
    try:
        with env.cr.savepoint():
            v_cat.with_user(u_super).write(
                {"description": "edited"})
    except Exception as e:  # noqa: BLE001
        err_w = e
    try:
        with env.cr.savepoint():
            v_cat.with_user(u_super).unlink()
    except Exception as e:  # noqa: BLE001
        err_u = e
ok = err_c is None and err_w is None and err_u is None
print(f"  create OK: {err_c is None}")
print(f"  write OK: {err_w is None}")
print(f"  unlink OK: {err_u is None}")
print("T7d105:", "PASS" if ok else "FAIL")
results["T7d105"] = ok


# ============================================================
print()
print("T7d106 - training_admin full CRUD")
print("=" * 72)
err_c, v_cat = _try(
    lambda: Cat.with_user(u_admin).create({
        "name": "T7d106 admin cat",
        "code": "t7d106-admin",
    }))
err_w = None
err_u = None
err_tag_c = None
if v_cat:
    try:
        with env.cr.savepoint():
            v_cat.with_user(u_admin).write(
                {"description": "edited"})
    except Exception as e:  # noqa: BLE001
        err_w = e
    try:
        with env.cr.savepoint():
            v_cat.with_user(u_admin).unlink()
    except Exception as e:  # noqa: BLE001
        err_u = e
# Also Tag
err_tag_c, v_tag = _try(
    lambda: Tag.with_user(u_admin).create({
        "name": "T7d106 admin tag"}))
ok = (err_c is None and err_w is None and err_u is None
      and err_tag_c is None)
print(f"  cat CRUD: c={err_c is None} w={err_w is None} "
      f"u={err_u is None}")
print(f"  tag create: {err_tag_c is None}")
print("T7d106:", "PASS" if ok else "FAIL")
results["T7d106"] = ok


# ============================================================
print()
print("T7d107 - base user reads but cannot create")
print("=" * 72)
# Read
try:
    with env.cr.savepoint():
        _ = Cat.with_user(u_user).search(
            [], limit=1).read(["name", "code"])
    read_ok = True
except AccessError:
    read_ok = False
# Create
err_c, _v = _try(lambda: Cat.with_user(u_user).create({
    "name": "T7d107 user cat", "code": "t7d107"}))
ok = read_ok and isinstance(err_c, AccessError)
print(f"  user read: {read_ok}")
print(f"  user create blocked: "
      f"{isinstance(err_c, AccessError)}")
print("T7d107:", "PASS" if ok else "FAIL")
results["T7d107"] = ok


# ============================================================
print()
print("T7d108 - portal user reads categories")
print("=" * 72)
try:
    with env.cr.savepoint():
        recs = Cat.with_user(u_portal).search(
            [], limit=5)
        names = recs.read(["name", "code"])
    ok = len(names) >= 5
    print(f"  portal sees {len(names)} categories")
except AccessError as e:
    ok = False
    print(f"  portal blocked: {e}")
print("T7d108:", "PASS" if ok else "FAIL")
results["T7d108"] = ok


# ============================================================
print()
print("T7d109 - chatter works on category")
print("=" * 72)
audio = env.ref("neon_kb.category_audio")
msg = audio.with_user(u_super).message_post(
    body="T7d109 chatter probe")
ok = bool(msg) and msg.model == Cat._name
print(f"  message id: {msg.id if msg else None}, "
      f"model: {msg.model if msg else None}")
print("T7d109:", "PASS" if ok else "FAIL")
results["T7d109"] = ok


# ============================================================
print()
print("T7d110 - manually-created records have no "
      "ir.model.data row")
print("=" * 72)
manual = Cat.sudo().create({
    "name": "T7d110 manual cat",
    "code": "t7d110-manual",
})
IrModelData = env["ir.model.data"]
xid_rows = IrModelData.sudo().search([
    ("model", "=", "neon.kb.category"),
    ("res_id", "=", manual.id),
])
ok = bool(manual) and len(xid_rows) == 0
print(f"  manual cat created: {manual.id}")
print(f"  ir.model.data rows targeting it: "
      f"{len(xid_rows)} (expect 0)")
print("T7d110:", "PASS" if ok else "FAIL")
results["T7d110"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7d100", "T7d101", "T7d102", "T7d103",
         "T7d104", "T7d105", "T7d106", "T7d107",
         "T7d108", "T7d109", "T7d110"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
