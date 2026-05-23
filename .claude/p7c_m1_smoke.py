"""Phase 7c M1 smoke -- vendor model + 5 seeds + ACLs
(8 tests).

T7c100 - 5 vendor seeds resolve via env.ref
T7c101 - vendor.name unique sql constraint
T7c102 - country_id defaults to Zimbabwe (base.zw)
T7c103 - superuser full CRUD
T7c104 - lead_tech read, no create
T7c105 - bookkeeper read, no create
T7c106 - chatter works (message_post)
T7c107 - manually-created vendors survive module -u
         (record stays after re-load; noupdate=0 only
         touches XML-loaded records, not user-created ones)
"""
from odoo.exceptions import AccessError, ValidationError
from psycopg2.errors import UniqueViolation


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Vendor = env["neon.external.training.vendor"]
Users = env["res.users"]


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
    g = env.ref(group_xmlid, raise_if_not_found=False)
    if g and u not in g.users:
        g.sudo().write({"users": [(4, u.id)]})
    return u


u_super = _get_or_create_user(
    "p7c_m1_super", "P7c M1 Superuser",
    "neon_core.group_neon_superuser")
u_book = _get_or_create_user(
    "p7c_m1_book", "P7c M1 Bookkeeper",
    "neon_core.group_neon_bookkeeper")
u_lead = _get_or_create_user(
    "p7c_m1_lead", "P7c M1 Lead Tech",
    "neon_core.group_neon_lead_tech")
env.cr.commit()


# ============================================================
print()
print("T7c100 - 5 vendor seeds resolve via env.ref")
print("=" * 72)
expected = [
    "neon_external_training.vendor_vid",
    "neon_external_training.vendor_red_cross_zim",
    "neon_external_training.vendor_allen_heath",
    "neon_external_training.vendor_avolites",
    "neon_external_training.vendor_yamaha_pro",
]
resolved = []
for xmlid in expected:
    r = env.ref(xmlid, raise_if_not_found=False)
    resolved.append((xmlid, bool(r), r.name if r else None))
ok = all(found for _x, found, _n in resolved)
for xmlid, found, name in resolved:
    print(f"  {xmlid}: {found} ({name})")
print("T7c100:", "PASS" if ok else "FAIL")
results["T7c100"] = ok


# ============================================================
print()
print("T7c101 - vendor.name unique sql constraint")
print("=" * 72)
seed = env.ref("neon_external_training.vendor_vid")
err, _v = _try(lambda: Vendor.sudo().create({
    "name": seed.name,
}))
# psycopg2 UniqueViolation gets wrapped to IntegrityError
ok = (err is not None
      and ("unique" in str(err).lower()
           or "duplicate" in str(err).lower()))
print(f"  err type: {type(err).__name__ if err else None}")
print(f"  err msg: {str(err)[:140] if err else None}")
print("T7c101:", "PASS" if ok else "FAIL")
results["T7c101"] = ok


# ============================================================
print()
print("T7c102 - country_id defaults to Zimbabwe")
print("=" * 72)
zw = env.ref("base.zw", raise_if_not_found=False)
new_v = Vendor.sudo().create({"name": "T7c102 probe"})
ok = (zw is not None
      and new_v.country_id == zw)
print(f"  base.zw resolved: {bool(zw)}")
print(f"  new vendor country_id: "
      f"{new_v.country_id.code if new_v.country_id else None}"
      f" (expect ZW)")
print("T7c102:", "PASS" if ok else "FAIL")
results["T7c102"] = ok


# ============================================================
print()
print("T7c103 - superuser full CRUD")
print("=" * 72)
err_c, v_super = _try(lambda: Vendor.with_user(u_super).create({
    "name": "T7c103 superuser create"}))
# Write
err_w = None
if v_super:
    try:
        with env.cr.savepoint():
            v_super.with_user(u_super).write(
                {"notes": "edited"})
    except Exception as e:  # noqa: BLE001
        err_w = e
# Unlink
err_u = None
if v_super:
    try:
        with env.cr.savepoint():
            v_super.with_user(u_super).unlink()
    except Exception as e:  # noqa: BLE001
        err_u = e
ok = err_c is None and err_w is None and err_u is None
print(f"  create OK: {err_c is None}")
print(f"  write OK: {err_w is None}")
print(f"  unlink OK: {err_u is None}")
print("T7c103:", "PASS" if ok else "FAIL")
results["T7c103"] = ok


# ============================================================
print()
print("T7c104 - lead_tech read, no create")
print("=" * 72)
# Read
try:
    with env.cr.savepoint():
        _ = Vendor.with_user(u_lead).search(
            [], limit=1).read(["name"])
    read_ok = True
except AccessError:
    read_ok = False
# Create
err_c, _v = _try(lambda: Vendor.with_user(u_lead).create(
    {"name": "T7c104 lead create attempt"}))
ok = read_ok and isinstance(err_c, AccessError)
print(f"  lead can read: {read_ok}")
print(f"  lead create blocked: "
      f"{isinstance(err_c, AccessError)}")
print("T7c104:", "PASS" if ok else "FAIL")
results["T7c104"] = ok


# ============================================================
print()
print("T7c105 - bookkeeper read, no create")
print("=" * 72)
try:
    with env.cr.savepoint():
        _ = Vendor.with_user(u_book).search(
            [], limit=1).read(["name"])
    read_ok = True
except AccessError:
    read_ok = False
err_c, _v = _try(lambda: Vendor.with_user(u_book).create(
    {"name": "T7c105 book create attempt"}))
ok = read_ok and isinstance(err_c, AccessError)
print(f"  book can read: {read_ok}")
print(f"  book create blocked: "
      f"{isinstance(err_c, AccessError)}")
print("T7c105:", "PASS" if ok else "FAIL")
results["T7c105"] = ok


# ============================================================
print()
print("T7c106 - chatter works (message_post)")
print("=" * 72)
v = env.ref("neon_external_training.vendor_vid")
msg = v.with_user(u_super).message_post(
    body="T7c106 chatter probe")
ok = bool(msg) and msg.model == v._name
print(f"  message id: {msg.id if msg else None}")
print(f"  model: {msg.model if msg else None}")
print("T7c106:", "PASS" if ok else "FAIL")
results["T7c106"] = ok


# ============================================================
print()
print("T7c107 - manually-created vendor survives upgrade")
print("=" * 72)
# Simulate the survive-upgrade check by creating a record
# WITHOUT an external id and confirming it persists. The
# real survive-upgrade test runs at deploy time
# (re-running the install loader); here we assert the
# record IS reachable + has no external_id (no ir.model.data
# row pointing at it = no upgrade-driven overwrite).
manual = Vendor.sudo().create({
    "name": "T7c107 manual vendor",
    "notes": "should survive module -u",
})
# Confirm no ir.model.data row points at this record.
IrModelData = env["ir.model.data"]
xid_rows = IrModelData.sudo().search([
    ("model", "=", "neon.external.training.vendor"),
    ("res_id", "=", manual.id),
])
ok = bool(manual) and len(xid_rows) == 0
print(f"  manual vendor created id: {manual.id}")
print(f"  ir.model.data rows targeting it: "
      f"{len(xid_rows)} (expect 0)")
print("T7c107:", "PASS" if ok else "FAIL")
results["T7c107"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7c100", "T7c101", "T7c102", "T7c103",
         "T7c104", "T7c105", "T7c106", "T7c107"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
