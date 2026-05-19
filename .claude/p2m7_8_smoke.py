"""P2.M7.8 smoke — crew-specific list and form views.

T42 crew tree view shows only event info (no lifecycle/status/finance/gate).
T43 crew form header carries no action buttons.
T44 crew form populates My Assignment computed fields for the calling user.
T45 crew form embeds a Crew notebook tab listing all assignments on the job.
T46 action_open_my_upcoming routes crew-only users to the crew views.
T47 action_open_my_upcoming for sales/manager keeps default views.
T48 default commercial_job_action remains closed to crew (deep-link defense).
T49 Sales rep sees Invoicing menu (P2.M7.8.1 reversal of M7.7 D4).
T50 Sales rep has account.group_account_invoice via implication.
T51 Crew Leader still does NOT see Invoicing menu.
T62 Default view picker returns STANDARD form for every role
    (P2.M7.8.2 regression guard — groups_id on primary ir.ui.view
    does NOT filter default-view selection in Odoo 17).
T64 menu_my_schedule visible only to crew tier (P2.M9.4 scope fix).
T65 commercial.job.dashboard.name resolves to "Operations Dashboard".
T66 commercial.job.crew.schedule.name resolves to "My Schedule".
"""
import re

from odoo import fields

print("=" * 72)
print("SETUP")
print("=" * 72)

crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
print("crew:", crew_only.login, " sales:", sales.login, " manager:", manager.login)

CREW_TREE = env.ref("neon_jobs.commercial_job_view_tree_for_crew")
CREW_FORM = env.ref("neon_jobs.commercial_job_view_form_for_crew")
print("crew tree view id:", CREW_TREE.id, " form view id:", CREW_FORM.id)

# Fixture: a job the crew member is assigned to, in the upcoming window.
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)
env["commercial.job.crew"].sudo().search(
    [("user_id", "=", crew_only.id)]).unlink()
base_date = fields.Date.add(fields.Date.today(), days=30)
J = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": base_date,
    "currency_id": env.company.currency_id.id,
})
J.write({"state": "active", "soft_hold_until": False})
my_assignment = env["commercial.job.crew"].create({
    "job_id": J.id, "user_id": crew_only.id,
    "role": "tech", "state": "pending",
})
env.cr.commit()
print("Fixture: job", J.name, "with pending assignment for", crew_only.login)

results = {}


def _field_names(arch_xml, in_tag=None):
    """Return ordered list of <field name="..."> values that appear in
    the arch. If in_tag is set, restrict to <field>s inside that tag."""
    if in_tag:
        m = re.search(rf"<{in_tag}\b[^>]*>(.*?)</{in_tag}>", arch_xml, re.S)
        if not m:
            return []
        scope = m.group(1)
    else:
        scope = arch_xml
    return re.findall(r'<field\s+name="([^"]+)"', scope)


# ============================================================
print()
print("=" * 72)
print("T42 - Crew tree shows only event info (no job-management columns)")
print("=" * 72)
arch = CREW_TREE.arch
fields_in_tree = _field_names(arch)
allowed = {
    "name", "event_date", "event_end_date", "partner_id",
    "venue_id", "venue_room_id", "sub_hire_required", "logistics_flag",
}
forbidden = {
    "state", "soft_hold_state", "soft_hold_until",
    "commercial_status", "finance_status", "operational_status",
    "gate_result", "needs_attention", "quoted_value", "currency_id",
    "master_contract_id",
}
actual = set(fields_in_tree)
missing_allowed = allowed - actual
extra = actual - allowed
forbidden_seen = actual & forbidden
ok = not missing_allowed and not extra and not forbidden_seen
print("T42: fields present =", sorted(actual))
print("     missing required:", sorted(missing_allowed) or "none")
print("     unexpected extras:", sorted(extra) or "none")
print("     forbidden seen:  ", sorted(forbidden_seen) or "none")
print("T42:", "PASS" if ok else "FAIL")
results["T42"] = ok


# ============================================================
print()
print("=" * 72)
print("T43 - Crew form <header> has no <button> elements")
print("=" * 72)
form_arch = CREW_FORM.arch
m = re.search(r"<header\b[^>]*>(.*?)</header>", form_arch, re.S)
if m is None:
    self_closed = re.search(r"<header\s*/>", form_arch)
    header_inner = "" if self_closed else None
else:
    header_inner = m.group(1)
if header_inner is None:
    print("T43: no <header> element found at all")
    ok = False
else:
    btns = re.findall(r"<button\b", header_inner)
    ok = len(btns) == 0
    print("T43: <header> button count =", len(btns), "(want 0)")
print("T43:", "PASS" if ok else "FAIL")
results["T43"] = ok


# ============================================================
print()
print("=" * 72)
print("T44 - Crew form populates my_assignment_* for the calling user")
print("=" * 72)
j_as_crew = env["commercial.job"].with_user(crew_only).browse(J.id)
ma_id = j_as_crew.my_assignment_id
ma_role = j_as_crew.my_assignment_role
ma_state = j_as_crew.my_assignment_state
ok = (
    ma_id.id == my_assignment.id
    and ma_role == "tech"
    and ma_state == "pending"
)
print("T44: my_assignment_id    =", ma_id.id, "(want", my_assignment.id, ")")
print("     my_assignment_role  =", ma_role, "(want tech)")
print("     my_assignment_state =", ma_state, "(want pending)")
print("T44:", "PASS" if ok else "FAIL")
results["T44"] = ok


# ============================================================
print()
print("=" * 72)
print("T45 - Crew form embeds crew_assignment_ids in a notebook page")
print("=" * 72)
has_notebook = "<notebook" in form_arch
nb_field = re.search(
    r'<field\s+name="crew_assignment_ids"[^>]*>',
    form_arch,
)
ok = has_notebook and bool(nb_field)
print("T45: has <notebook>?            ", has_notebook)
print("     crew_assignment_ids field? ", bool(nb_field))
print("T45:", "PASS" if ok else "FAIL")
results["T45"] = ok


# ============================================================
print()
print("=" * 72)
print("T46 - Crew users get the crew views from action_open_my_upcoming")
print("=" * 72)
schedule = env["commercial.job.crew.schedule"].with_user(crew_only).create({})
action = schedule.action_open_my_upcoming()
views = action.get("views") or []
view_ids = [v[0] for v in views]
expected = [CREW_TREE.id, CREW_FORM.id]
ok = (
    view_ids == expected
    and action.get("context", {}).get("force_crew_view") == 1
)
print("T46: action.views     =", views, "(want", expected, ")")
print("     force_crew_view? ", action.get("context", {}).get("force_crew_view"))
print("T46:", "PASS" if ok else "FAIL")
results["T46"] = ok


# ============================================================
print()
print("=" * 72)
print("T47 - Sales/Manager get default views (no crew-view override)")
print("=" * 72)
sales_schedule = env["commercial.job.crew.schedule"].with_user(sales).create({})
sales_action = sales_schedule.action_open_my_upcoming()
mgr_schedule = env["commercial.job.crew.schedule"].with_user(manager).create({})
mgr_action = mgr_schedule.action_open_my_upcoming()
ok = (
    "views" not in sales_action
    and sales_action.get("context", {}).get("force_crew_view") is None
    and "views" not in mgr_action
)
print("T47: sales 'views' present?", "views" in sales_action, "(want False)")
print("     manager 'views' present?", "views" in mgr_action, "(want False)")
print("     sales force_crew_view?  ",
      sales_action.get("context", {}).get("force_crew_view"))
print("T47:", "PASS" if ok else "FAIL")
results["T47"] = ok


# ============================================================
print()
print("=" * 72)
print("T48 - Default commercial_job_action remains closed to crew")
print("=" * 72)
default_action = env.ref("neon_jobs.commercial_job_action").sudo()
crew_grp = env.ref("neon_jobs.group_neon_jobs_crew")
allowed_groups = default_action.groups_id
ok = (
    crew_grp not in allowed_groups
    and bool(allowed_groups)
)
print("T48: default action.groups_id =",
      [g.name for g in allowed_groups])
print("     crew_grp in allowed?      ", crew_grp in allowed_groups,
      "(want False)")
print("T48:", "PASS" if ok else "FAIL")
results["T48"] = ok


# ============================================================
print()
print("=" * 72)
print("T49 - Sales rep sees Invoicing menu (P2.M7.8.1 reversal of M7.7 D4)")
print("=" * 72)
invoicing = env.ref("account.menu_finance")
sales_sees = env["ir.ui.menu"].with_user(sales).search([("id", "=", invoicing.id)])
ok = bool(sales_sees)
print("T49: sales sees Invoicing? ", bool(sales_sees), "(want True)")
print("T49:", "PASS" if ok else "FAIL")
results["T49"] = ok


# ============================================================
print()
print("=" * 72)
print("T50 - Sales rep has account.group_account_invoice via implication")
print("=" * 72)
billing = env.ref("account.group_account_invoice")
user_grp = env.ref("neon_jobs.group_neon_jobs_user")
edge_in_place = billing in user_grp.implied_ids
sales_has_billing = billing in sales.groups_id
ok = edge_in_place and sales_has_billing
print("T50: neon_jobs_user → billing edge present? ", edge_in_place,
      "(want True)")
print("     sales user has Billing group?          ", sales_has_billing,
      "(want True)")
print("T50:", "PASS" if ok else "FAIL")
results["T50"] = ok


# ============================================================
print()
print("=" * 72)
print("T51 - Crew Leader sees Invoicing menu (P6.M5: needed for Cost Lines reach)")
print("=" * 72)
# P6.M5 extended account.menu_finance's groups_id to include
# group_neon_jobs_crew_leader so Ranganai can reach the Cost Lines
# submenu under Customers. Pre-P6.M5 this test asserted the OPPOSITE
# (crew_leader hidden from Invoicing); the spec changed in M5 and so
# does this assertion. Analogous to the M3 T509 / M4 M2-test refactors:
# the test still validates a Phase 6 Schema Sketch contract, just an
# updated one.
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
lead_sees = env["ir.ui.menu"].with_user(crew_leader).search([("id", "=", invoicing.id)])
ok = bool(lead_sees)
print("T51: crew leader sees Invoicing? ", bool(lead_sees), "(want True per P6.M5)")
print("T51:", "PASS" if ok else "FAIL")
results["T51"] = ok


# ============================================================
print()
print("=" * 72)
print("T62 - Default view picker resolves to STANDARD form for every role")
print("=" * 72)
# P2.M7.8.2 regression guard. groups_id on a primary ir.ui.view does
# NOT filter default-view selection in Odoo 17 — BaseModel._get_view_id
# is purely priority-ordered. If anyone resolves to the crew form by
# default again, the priority/groups assumption is broken.
STD_FORM = env.ref("neon_jobs.commercial_job_view_form")
STD_TREE = env.ref("neon_jobs.commercial_job_view_tree")
robin = env["res.users"].search(
    [("login", "=", "robin@neonhiring.co.zw")], limit=1)
candidates = [
    ("robin", robin), ("sales", sales), ("manager", manager),
    ("crew_leader",
     env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)),
    ("crew_only", crew_only),
]
failures = []
print("  Expected: form id =", STD_FORM.id, " tree id =", STD_TREE.id)
for label, user in candidates:
    if not user:
        print("  skipped (user missing):", label)
        continue
    try:
        f_id = env["commercial.job"].with_user(user).get_view(view_type="form")["id"]
        t_id = env["commercial.job"].with_user(user).get_view(view_type="tree")["id"]
    except Exception as e:
        failures.append((label, "ERR " + type(e).__name__))
        continue
    ok_form = f_id == STD_FORM.id
    ok_tree = t_id == STD_TREE.id
    print("  {:<12} form_id={} ({}) tree_id={} ({})".format(
        label, f_id, "OK" if ok_form else "WRONG",
        t_id, "OK" if ok_tree else "WRONG",
    ))
    if not (ok_form and ok_tree):
        failures.append((label, "form=%s tree=%s" % (f_id, t_id)))
ok = not failures
print("  failures:", failures or "none")
print("T62:", "PASS" if ok else "FAIL")
results["T62"] = ok


# ============================================================
print()
print("=" * 72)
print("T64 - menu_my_schedule visible only to crew tier (P2.M9.4 scope fix)")
print("=" * 72)
my_sched = env.ref("neon_jobs.menu_my_schedule")
candidates = [
    ("sales", sales),
    ("manager", manager),
    ("crew_leader",
     env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)),
    ("crew_only", crew_only),
]
fails = []
for label, user in candidates:
    if not user:
        continue
    visible = env["ir.ui.menu"].with_user(user).search(
        [("id", "=", my_sched.id)])
    sees = bool(visible)
    expected = (label == "crew_only")
    print("  {:<12} sees My Schedule? {} (want {})".format(
        label, sees, expected))
    if sees != expected:
        fails.append(label)
ok = not fails
print("  failures:", fails or "none")
print("T64:", "PASS" if ok else "FAIL")
results["T64"] = ok


# ============================================================
print()
print("=" * 72)
print("T65 - commercial.job.dashboard.name == 'Operations Dashboard'")
print("=" * 72)
rec = env["commercial.job.dashboard"].create({})
ok = rec.name == "Operations Dashboard"
print("  name =", repr(rec.name), "(want 'Operations Dashboard')")
print("T65:", "PASS" if ok else "FAIL")
results["T65"] = ok


# ============================================================
print()
print("=" * 72)
print("T66 - commercial.job.crew.schedule.name == 'My Schedule'")
print("=" * 72)
rec = env["commercial.job.crew.schedule"].create({})
ok = rec.name == "My Schedule"
print("  name =", repr(rec.name), "(want 'My Schedule')")
print("T66:", "PASS" if ok else "FAIL")
results["T66"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T42", "T43", "T44", "T45", "T46", "T47", "T48", "T49", "T50",
         "T51", "T62", "T64", "T65", "T66"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
