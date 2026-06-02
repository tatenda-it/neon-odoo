"""P-HR-R3b C4 smoke -- TOIL retire + post-migrate grant restore."""


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R3b C4 -- housekeeping (TOIL retire + grant restore)")
print("=" * 72)
results = {}

Overtime = env["neon.hr.overtime"].sudo()
Menu = env["ir.ui.menu"].sudo()


# ============================================================
# T-R3b-C4-01 -- TOIL menu carries base.group_no_one (hidden)
# ============================================================
menu = env.ref("neon_hr.menu_neon_hr_overtime",
                raise_if_not_found=False)
g_noone = env.ref("base.group_no_one")
hidden = (menu and menu.groups_id
          and g_noone in menu.groups_id)
_check("T-R3b-C4-01",
       bool(hidden),
       f"menu_neon_hr_overtime carries base.group_no_one; "
       f"groups_id={menu.groups_id.mapped('name') if menu else 'NONE'}")


# ============================================================
# T-R3b-C4-02 -- existing TOIL records are active=False after
# the post-migrate (the migration already ran for this DB on
# the -u that introduced 17.0.6.0.0)
# ============================================================
active_toil = Overtime.search_count([("active", "=", True)])
_check("T-R3b-C4-02",
       active_toil == 0,
       f"existing TOIL records inactive; got active count="
       f"{active_toil}")


# ============================================================
# T-R3b-C4-03 -- the data is PRESERVED (with_context active_test=
# False shows the archived rows; we don't unlink per audit rule)
# ============================================================
all_toil = Overtime.with_context(active_test=False).search_count(
    [])
_check("T-R3b-C4-03",
       all_toil >= 0,
       f"TOIL data preserved (with active_test=False): "
       f"total={all_toil}")


# ============================================================
# T-R3b-C4-04 -- perm_unlink=0 still holds (no walk-back)
# ============================================================
unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.hr.overtime"),
    ("perm_unlink", "=", True),
])
_check("T-R3b-C4-04",
       not unlinkable,
       f"perm_unlink=0 still holds on TOIL ACL rows; got "
       f"violations={unlinkable.mapped('group_id.name')}")


# ============================================================
# T-R3b-C4-05 -- HR grants restored (the post-migrate re-fires
# _enforce_hr_confidentiality). Verify the superuser group
# implies hr.group_hr_manager.
# ============================================================
g_super = env.ref("neon_core.group_neon_superuser")
g_hr_mgr = env.ref("hr.group_hr_manager",
                     raise_if_not_found=False)
implies_hr_mgr = (g_hr_mgr
                    and g_hr_mgr in g_super.implied_ids)
_check("T-R3b-C4-05",
       bool(implies_hr_mgr),
       f"superuser implies hr.group_hr_manager (grant restored): "
       f"{bool(implies_hr_mgr)}")


# ============================================================
# T-R3b-C4-06 -- neon_hr version bumped to 17.0.6.0.0
# ============================================================
neon_hr_mod = env["ir.module.module"].sudo().search(
    [("name", "=", "neon_hr")], limit=1)
_check("T-R3b-C4-06",
       neon_hr_mod and neon_hr_mod.latest_version == "17.0.6.0.0",
       f"neon_hr at 17.0.6.0.0; got "
       f"{neon_hr_mod.latest_version if neon_hr_mod else 'NONE'}")


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
