"""neon_login_bypass smoke (4 tests)

T_LB100 - website.login_layout deactivated (our override applied)
T_LB101 - portal.frontend_layout still active (/my/* chrome intact)
T_LB102 - web.login_layout still active + auth_signup.login still
          active (backend login form still wired)
T_LB103 - rendered /web/login HTML drops the website wrap
          (no oe_website_login_container div; no website.layout
          YourLogo placeholder string)
"""
from odoo.exceptions import AccessError, ValidationError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

View = env["ir.ui.view"]


# ============================================================
print()
print("T_LB100 - website.login_layout deactivated")
print("=" * 72)
v = env.ref("website.login_layout", raise_if_not_found=False)
ok = bool(v) and v.active is False
print(f"  view id={v.id if v else None}")
print(f"  active={v.active if v else None} (expected False)")
print("T_LB100:", "PASS" if ok else "FAIL")
results["T_LB100"] = ok


# ============================================================
print()
print("T_LB101 - portal.frontend_layout still active")
print("=" * 72)
p = env.ref("portal.frontend_layout", raise_if_not_found=False)
ok = bool(p) and p.active is True
print(f"  view id={p.id if p else None}")
print(f"  active={p.active if p else None} (expected True)")
print("T_LB101:", "PASS" if ok else "FAIL")
results["T_LB101"] = ok


# ============================================================
print()
print("T_LB102 - web.login_layout + auth_signup.login still active")
print("=" * 72)
ll = env.ref("web.login_layout", raise_if_not_found=False)
asl = env.ref("auth_signup.login", raise_if_not_found=False)
ok = bool(ll) and ll.active is True and bool(asl) and asl.active is True
print(f"  web.login_layout active={ll.active if ll else None}")
print(f"  auth_signup.login active={asl.active if asl else None}")
print("T_LB102:", "PASS" if ok else "FAIL")
results["T_LB102"] = ok


# ============================================================
print()
print("T_LB103 - web.login_layout combined arch has no website wrap")
print("=" * 72)
# Get the combined (post-inherit) arch of web.login_layout. With our
# fix, website.login_layout (which xpath-replaces the body with
# <t t-call="website.layout">) is inactive, so its xpath does NOT
# apply. The neon_channels.neon_login_footer adjustment (active)
# still applies.
try:
    base = env.ref("web.login_layout")
    combined = base.with_context(
        check_view_ids=base.ids
    ).get_combined_arch()
    arch_s = combined if isinstance(combined, str) else (
        combined.decode("utf-8"))
    has_wrap = 'oe_website_login_container' in arch_s
    has_website_layout_call = (
        't-call="website.layout"' in arch_s
        or "t-call='website.layout'" in arch_s)
    # active inheritor (neon_login_footer) replaces the default footer
    # with empty -- the marker class still in there should be
    # 'o_database_list' from the bare layout body.
    has_db_list = 'o_database_list' in arch_s
    ok = (has_db_list and not has_wrap and not has_website_layout_call)
    print(f"  arch length: {len(arch_s)}")
    print(f"  contains 'o_database_list': {has_db_list}"
          f" (expect True)")
    print(f"  contains 'oe_website_login_container': {has_wrap}"
          f" (expect False)")
    print(f"  contains t-call='website.layout': "
          f"{has_website_layout_call} (expect False)")
except Exception as e:  # noqa: BLE001
    ok = False
    print(f"  inspect err: {e}")
print("T_LB103:", "PASS" if ok else "FAIL")
results["T_LB103"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T_LB100", "T_LB101", "T_LB102", "T_LB103"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
