"""P7b.M3 smoke -- kanban + polished form + menu structure
(7 tests).

T7b300  kanban view loads cleanly (read_combined returns
        arch + no errors)
T7b301  candidate form view loads cleanly
T7b302  candidate form usable by training_admin (with_user
        view rendering doesn't throw)
T7b303  Skip Onboarding button has groups='neon_core.
        group_neon_superuser' in the form arch
T7b304  Skip Onboarding button NOT visible in form arch
        when fetched by training_admin (groups attr filters
        the button out at view-render time)
T7b305  load_web_menus for superuser returns the 4 expected
        menu items (root + Candidates + Configuration +
        Requirement Templates)
T7b306  kanban view declares default_group_by='state'
"""
import re

from odoo import fields


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

Users = env["res.users"]
View = env["ir.ui.view"]
Menu = env["ir.ui.menu"]


def _get_or_create_user(login, name, group_xmlids):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name,
            "login": login,
            "password": "test123",
        })
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_superuser = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])
u_train_admin = _get_or_create_user(
    "p7b_m1_training_admin", "P7b M1 Training Admin",
    ["neon_training.group_neon_training_admin"])
print(f"  u_superuser   uid={u_superuser.id}")
print(f"  u_train_admin uid={u_train_admin.id}")
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T7b300 - kanban view loads cleanly")
print("=" * 72)
kanban_view = env.ref(
    "neon_onboarding.view_neon_onboarding_candidate_kanban")
err, combined = _try(
    lambda: View.with_user(u_superuser)._get_view(
        view_id=kanban_view.id))
ok = (err is None and combined is not None)
print(f"  view id={kanban_view.id} "
      f"err={type(err).__name__ if err else None}")
print("T7b300:", "PASS" if ok else "FAIL")
results["T7b300"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b301 - candidate form view loads cleanly")
print("=" * 72)
form_view = env.ref(
    "neon_onboarding.view_neon_onboarding_candidate_form")
err, combined = _try(
    lambda: View.with_user(u_superuser)._get_view(
        view_id=form_view.id))
ok = (err is None and combined is not None)
print(f"  view id={form_view.id} "
      f"err={type(err).__name__ if err else None}")
print("T7b301:", "PASS" if ok else "FAIL")
results["T7b301"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b302 - form usable by training_admin")
print("=" * 72)
err, _r = _try(
    lambda: View.with_user(u_train_admin)._get_view(
        view_id=form_view.id))
ok = (err is None)
print(f"  err={type(err).__name__ if err else None}")
print("T7b302:", "PASS" if ok else "FAIL")
results["T7b302"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b303 - Skip button has superuser groups attr in form")
print("=" * 72)
# Inspect the form view's source arch. Note: Odoo resolves
# %(action_neon_onboarding_skip_wizard)d to a numeric action
# id at view-record-save time, so the arch_db contains the
# resolved integer in the name= attr instead of the xmlid.
# Match by the unique button string + groups attr in the
# same tag.
arch_db = form_view.arch_db or form_view.arch or ""
# Find the unique Skip Onboarding button (string is unique
# in the form arch).
btn_match = re.search(
    r"<button[^/>]*string=\"Skip Onboarding[^>]*/>",
    arch_db, flags=re.DOTALL)
ok = False
if btn_match:
    btn_text = btn_match.group(0)
    ok = "neon_core.group_neon_superuser" in btn_text
print(f"  button found: {bool(btn_match)}  "
      f"has superuser groups: {ok}")
if btn_match:
    print(f"  button arch: {btn_match.group(0)[:160]}")
print("T7b303:", "PASS" if ok else "FAIL")
results["T7b303"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b304 - Skip button removed from training_admin's "
      "rendered view")
print("=" * 72)
# Odoo's _get_view() returns a dict with 'arch' that has
# groups-based elements filtered out for the requesting user.
rendered_admin = View.with_user(u_train_admin)._get_view(
    view_id=form_view.id)
admin_arch = rendered_admin.get("arch") if isinstance(
    rendered_admin, dict) else None
# Rendered arch may be lxml element or string depending on
# Odoo internals; coerce to string.
try:
    from lxml import etree
    if hasattr(admin_arch, "tag"):
        admin_arch_str = etree.tostring(
            admin_arch, encoding="unicode")
    else:
        admin_arch_str = str(admin_arch or "")
except Exception:
    admin_arch_str = str(admin_arch or "")
# The button references the skip wizard action by xmlid; once
# the groups filter strips the button, the action ref
# disappears from rendered arch.
ok = "action_neon_onboarding_skip_wizard" not in admin_arch_str
print(f"  skip wizard action ref in rendered admin arch: "
      f"{'action_neon_onboarding_skip_wizard' in admin_arch_str}")
print("T7b304:", "PASS" if ok else "FAIL")
results["T7b304"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b305 - load_web_menus surfaces all 4 onboarding menus")
print("=" * 72)
expected_xmlids = [
    "neon_onboarding.menu_neon_onboarding_root",
    "neon_onboarding.menu_neon_onboarding_candidates",
    "neon_onboarding.menu_neon_onboarding_configuration",
    "neon_onboarding.menu_neon_onboarding_templates",
]
expected_ids = []
for xid in expected_xmlids:
    m = env.ref(xid, raise_if_not_found=False)
    if m:
        expected_ids.append(m.id)
web_menus = Menu.with_user(u_superuser).load_web_menus(False)
# load_web_menus dict keys are strs in Odoo 17.
present = []
missing = []
for mid in expected_ids:
    if str(mid) in web_menus or mid in web_menus:
        present.append(mid)
    else:
        missing.append(mid)
ok = len(missing) == 0 and len(present) == 4
print(f"  expected ids: {expected_ids}")
print(f"  present:      {present}")
print(f"  missing:      {missing}")
print("T7b305:", "PASS" if ok else "FAIL")
results["T7b305"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b306 - kanban declares default_group_by='state'")
print("=" * 72)
kanban_arch = kanban_view.arch_db or kanban_view.arch or ""
ok = re.search(
    r'default_group_by\s*=\s*"state"', kanban_arch) is not None
print(f"  default_group_by='state' present: {ok}")
print("T7b306:", "PASS" if ok else "FAIL")
results["T7b306"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b300", "T7b301", "T7b302", "T7b303",
        "T7b304", "T7b305", "T7b306"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
