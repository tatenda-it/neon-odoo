"""P7b.M11 smoke -- dashboard onboarding counters (7 tests).

T7b1100  dashboard has both new fields (counters present in
         _fields)
T7b1101  candidates_in_cert_collection counts only state=
         cert_collection (not other states)
T7b1102  candidates_in_probationary counts only state=
         probationary
T7b1103  action_view_candidates_cert_collection returns
         action with state=cert_collection domain
T7b1104  action_view_candidates_probationary returns action
         with state=probationary domain
T7b1105  counter recomputes when candidate state changes
T7b1106  defensive env.get -- source check confirms env.get
         pattern + returns 0 when model absent
"""
import inspect

from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError


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
Candidate = env["neon.onboarding.candidate"]
Dashboard = env["neon.training.dashboard"]


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


u_super = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])

# Pre-existing candidate count -- we'll add deltas + assert
# the count change rather than absolute values.
prior_cert_collection = Candidate.sudo().search_count([
    ("state", "=", "cert_collection")])
prior_probationary = Candidate.sudo().search_count([
    ("state", "=", "probationary")])
print(f"  prior cert_collection count: {prior_cert_collection}")
print(f"  prior probationary count:   {prior_probationary}")
env.cr.commit()


# Seed candidates in each state. Use unique logins so the
# uniqueness constraint on user_id doesn't trip.
u_a = _get_or_create_user(
    "p7b_m11_a", "M11 A", ["neon_jobs.group_neon_jobs_crew"])
u_b = _get_or_create_user(
    "p7b_m11_b", "M11 B", ["neon_jobs.group_neon_jobs_crew"])
u_c = _get_or_create_user(
    "p7b_m11_c", "M11 C", ["neon_jobs.group_neon_jobs_crew"])

cand_cc1 = Candidate.sudo().create({
    "name": "M11 Cert Collection 1",
    "intended_role": "runner",
    "contact_phone": "+263771001101",
    "contact_email": "m11_cc1@example.com",
    "state": "candidate",
})
cand_cc1.sudo().write({"state": "cert_collection"})

cand_cc2 = Candidate.sudo().create({
    "name": "M11 Cert Collection 2",
    "intended_role": "runner",
    "contact_phone": "+263771001102",
    "contact_email": "m11_cc2@example.com",
    "state": "candidate",
})
cand_cc2.sudo().write({"state": "cert_collection"})

cand_prob = Candidate.sudo().create({
    "name": "M11 Probationary",
    "intended_role": "runner",
    "contact_phone": "+263771001103",
    "user_id": u_a.id,
    "state": "probationary",
})

# A candidate NOT in either tracked state (control).
cand_active = Candidate.sudo().create({
    "name": "M11 Active",
    "intended_role": "runner",
    "contact_phone": "+263771001104",
    "user_id": u_b.id,
    "state": "active",
})
print(f"  4 seed candidates created")


# ============================================================
print()
print("=" * 72)
print("T7b1100 - dashboard has both counter fields")
print("=" * 72)
field_names = set(Dashboard._fields.keys())
ok = ("candidates_in_cert_collection" in field_names
      and "candidates_in_probationary" in field_names)
print(f"  candidates_in_cert_collection field: "
      f"{'candidates_in_cert_collection' in field_names}")
print(f"  candidates_in_probationary field:    "
      f"{'candidates_in_probationary' in field_names}")
print("T7b1100:", "PASS" if ok else "FAIL")
results["T7b1100"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1101 - candidates_in_cert_collection counter")
print("=" * 72)
# Render a dashboard record (creates a fresh transient or
# regular record; let's use create + compute).
dash = Dashboard.sudo().create({})
dash.invalidate_recordset()
# Expected count = prior + 2 (cand_cc1 + cand_cc2).
expected_cc = prior_cert_collection + 2
ok = dash.candidates_in_cert_collection == expected_cc
print(f"  counter={dash.candidates_in_cert_collection} "
      f"expected={expected_cc}")
print("T7b1101:", "PASS" if ok else "FAIL")
results["T7b1101"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1102 - candidates_in_probationary counter")
print("=" * 72)
# Expected = prior + 1 (cand_prob).
expected_prob = prior_probationary + 1
ok = dash.candidates_in_probationary == expected_prob
print(f"  counter={dash.candidates_in_probationary} "
      f"expected={expected_prob}")
print("T7b1102:", "PASS" if ok else "FAIL")
results["T7b1102"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1103 - drill-through cert_collection action")
print("=" * 72)
action = dash.action_view_candidates_cert_collection()
ok = (isinstance(action, dict)
      and action.get("res_model") == "neon.onboarding.candidate"
      and ("state", "=", "cert_collection") in action.get("domain", []))
print(f"  action res_model: {action.get('res_model') if isinstance(action, dict) else 'N/A'}")
print(f"  action domain: {action.get('domain') if isinstance(action, dict) else 'N/A'}")
print("T7b1103:", "PASS" if ok else "FAIL")
results["T7b1103"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1104 - drill-through probationary action")
print("=" * 72)
action = dash.action_view_candidates_probationary()
ok = (isinstance(action, dict)
      and action.get("res_model") == "neon.onboarding.candidate"
      and ("state", "=", "probationary") in action.get("domain", []))
print(f"  action res_model: {action.get('res_model') if isinstance(action, dict) else 'N/A'}")
print(f"  action domain: {action.get('domain') if isinstance(action, dict) else 'N/A'}")
print("T7b1104:", "PASS" if ok else "FAIL")
results["T7b1104"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1105 - counter recomputes on state change")
print("=" * 72)
# Change one cand_cc1 to probationary. Counts should shift.
cand_cc1.sudo().write({
    "user_id": u_c.id,  # need user_id for probationary
                         # (no constraint actually, only on
                         # active; but set anyway for clarity)
    "state": "probationary",
})
# Force fresh dashboard (computed non-stored fires on read).
dash_v2 = Dashboard.sudo().create({})
ok = (dash_v2.candidates_in_cert_collection == (
        prior_cert_collection + 1)  # was +2, now +1
      and dash_v2.candidates_in_probationary == (
        prior_probationary + 2))  # was +1, now +2
print(f"  after state move: cc={dash_v2.candidates_in_cert_collection} "
      f"(expected {prior_cert_collection + 1}), "
      f"prob={dash_v2.candidates_in_probationary} "
      f"(expected {prior_probationary + 2})")
print("T7b1105:", "PASS" if ok else "FAIL")
results["T7b1105"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b1106 - defensive env.get pattern in source")
print("=" * 72)
from odoo.addons.neon_training.models import (
    neon_training_dashboard)
src = inspect.getsource(neon_training_dashboard)
has_env_get = 'env.get("neon.onboarding.candidate")' in src
has_none_check = (
    "if Candidate is None:" in src
    and "rec.candidates_in_cert_collection = 0" in src)
ok = has_env_get and has_none_check
print(f"  env.get pattern present: {has_env_get}")
print(f"  None-check zeros counters: {has_none_check}")
print("T7b1106:", "PASS" if ok else "FAIL")
results["T7b1106"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b1100", "T7b1101", "T7b1102", "T7b1103",
        "T7b1104", "T7b1105", "T7b1106"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
