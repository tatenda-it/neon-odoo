"""P7e.M11 smoke -- dashboard 4 LMS counters (8 tests)."""
import inspect

from odoo import fields
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

Dashboard = env["neon.training.dashboard"]
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
    "p7e_m11_admin", "P7e M11 Admin",
    ["neon_training.group_neon_training_admin"])
env.cr.commit()


# ============================================================
print()
print("T7e1100 - dashboard has 4 LMS counter fields")
print("=" * 72)
field_names = set(Dashboard._fields.keys())
expected = {
    "lms_active_enrollments",
    "lms_pending_capstone",
    "lms_authorities_granted_30d",
    "lms_track_cert_distribution",
}
missing = expected - field_names
ok = len(missing) == 0
print(f"  expected fields present: {ok}")
print(f"  missing: {missing or 'none'}")
print("T7e1100:", "PASS" if ok else "FAIL")
results["T7e1100"] = ok


# ============================================================
print()
print("T7e1101 - lms_active_enrollments counter accurate")
print("=" * 72)
dash = Dashboard.sudo().create({})
expected_count = env["slide.channel.partner"].sudo().search_count([
    ("neon_state", "in", ("in_progress", "completed")),
])
ok = dash.lms_active_enrollments == expected_count
print(f"  counter={dash.lms_active_enrollments} "
      f"expected={expected_count}")
print("T7e1101:", "PASS" if ok else "FAIL")
results["T7e1101"] = ok


# ============================================================
print()
print("T7e1102 - lms_pending_capstone counter accurate")
print("=" * 72)
expected_count = env["slide.channel.partner"].sudo().search_count([
    ("neon_state", "=", "completed"),
    ("neon_capstone_cert_id", "=", False),
])
ok = dash.lms_pending_capstone == expected_count
print(f"  counter={dash.lms_pending_capstone} "
      f"expected={expected_count}")
print("T7e1102:", "PASS" if ok else "FAIL")
results["T7e1102"] = ok


# ============================================================
print()
print("T7e1103 - lms_authorities_granted_30d counter "
      "(30-day window arithmetic)")
print("=" * 72)
# Manually verify via search.
from datetime import timedelta
cutoff = fields.Datetime.now() - timedelta(days=30)
TrackComp = env["neon.lms.track.completion"]
recent_certified = TrackComp.sudo().search([
    ("state", "=", "certified"),
    ("certification_date", ">=", cutoff),
])
expected_authorities = sum(
    len(tc.track_id.operating_authority_ids)
    for tc in recent_certified)
ok = dash.lms_authorities_granted_30d == expected_authorities
print(f"  counter={dash.lms_authorities_granted_30d} "
      f"expected={expected_authorities}")
print("T7e1103:", "PASS" if ok else "FAIL")
results["T7e1103"] = ok


# ============================================================
print()
print("T7e1104 - lms_track_cert_distribution returns valid str")
print("=" * 72)
dist = dash.lms_track_cert_distribution
ok = (isinstance(dist, str)
      and (dist == "" or "Foundations" in dist))
print(f"  distribution: {dist[:120] if dist else '(empty)'}")
print("T7e1104:", "PASS" if ok else "FAIL")
results["T7e1104"] = ok


# ============================================================
print()
print("T7e1105 - drill-through actions return action dicts")
print("=" * 72)
actions = {
    "active_enrollments":
        dash.action_view_lms_active_enrollments(),
    "pending_capstone":
        dash.action_view_lms_pending_capstone(),
    "recent_authorities":
        dash.action_view_lms_recent_authorities(),
    "track_distribution":
        dash.action_view_lms_track_distribution(),
}
all_ok = all(
    isinstance(a, dict)
    and a.get("type") == "ir.actions.act_window"
    for a in actions.values())
ok = all_ok
for name, action in actions.items():
    print(f"  {name}: "
          f"res_model={action.get('res_model') if isinstance(action, dict) else 'N/A'}")
print("T7e1105:", "PASS" if ok else "FAIL")
results["T7e1105"] = ok


# ============================================================
print()
print("T7e1106 - defensive env.get pattern in source")
print("=" * 72)
from odoo.addons.neon_training.models import (
    neon_training_dashboard)
src = inspect.getsource(neon_training_dashboard)
src_compact = " ".join(src.split())
checks = {
    "env.get slide.channel.partner": (
        "slide.channel.partner" in src_compact
        and "env.get(" in src_compact),
    "env.get track.completion": (
        "neon.lms.track.completion" in src_compact
        and "env.get(" in src_compact),
    "None-check zeros counters": (
        "Enrollment is None or TrackComp is None" in src
        and "rec.lms_active_enrollments = 0" in src),
    "drill-through returns False": (
        "Enrollment is None:" in src
        and "return False" in src),
}
ok = all(checks.values())
for k, v in checks.items():
    print(f"  {k}: {v}")
print("T7e1106:", "PASS" if ok else "FAIL")
results["T7e1106"] = ok


# ============================================================
print()
print("T7e1107 - regression: existing Phase 7a + 7b counters "
      "unchanged")
print("=" * 72)
existing_fields = {
    "active_certs_total",  # P7a M12
    "expiring_30d",  # P7a M12
    "tier_1_fires_30d",  # P7a M12
    "candidates_in_cert_collection",  # P7b M11
    "candidates_in_probationary",  # P7b M11
}
all_present = all(f in field_names for f in existing_fields)
ok = all_present
for f in existing_fields:
    present = f in field_names
    if not present:
        print(f"  MISSING: {f}")
print(f"  all existing fields present: {all_present}")
print("T7e1107:", "PASS" if ok else "FAIL")
results["T7e1107"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e1100", "T7e1101", "T7e1102", "T7e1103",
         "T7e1104", "T7e1105", "T7e1106", "T7e1107"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
