"""P5.M2 smoke — state machine enforcement on neon.equipment.unit.

T260 ALLOWED_TRANSITIONS dict shape
T261 _do_transition — valid (draft -> active)
T262 _do_transition — illegal (draft -> checked_out) raises
T263 _do_transition — unknown state code raises
T264 _do_transition — same-state no-op
T265 Manager bypass — valid (decommissioned -> active)
T266 Manager bypass — missing reason raises
T267 Manager bypass — non-manager raises
T268 Manager bypass — beyond bypass list raises
T269 action_* methods route to correct transitions
T270 can_<verb> compute matrix per state
T271 Form view header has the 11 action buttons + recommission
T272 Recommission wizard end-to-end (decommissioned -> active)
"""
from odoo.exceptions import UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
print("users: mgr=", manager.login, " sales=", sales.login)

Unit = env["neon.equipment.unit"]
Product = env["product.template"]

# Build a dedicated test product so we don't disturb the testing-kit
# seed. Idempotent via workshop_name search.
TEST_WORKSHOP_NAME = "P5M2_TEST_PRODUCT"
test_product = Product.sudo().search(
    [("workshop_name", "=", TEST_WORKSHOP_NAME)], limit=1)
if not test_product:
    sound_cat = env.ref("neon_jobs.equipment_category_sound")
    test_product = Product.sudo().create({
        "name": "[P5M2-SMOKE] Test Product",
        "is_workshop_item": True,
        "equipment_category_id": sound_cat.id,
        "workshop_name": TEST_WORKSHOP_NAME,
    })

# Clean prior P5M2 test units
Unit.sudo().search([
    ("product_template_id", "=", test_product.id),
    ("serial_number", "like", "P5M2_%"),
]).unlink()
env.cr.commit()


def _new_unit(label, state="draft"):
    """Create a fresh unit in the given state via direct write
    (fixtures don't go through _do_transition — see milestone note)."""
    return Unit.sudo().create({
        "product_template_id": test_product.id,
        "serial_number": "P5M2_%s" % label,
        "state": state,
    })


# ============================================================
print()
print("=" * 72)
print("T260 - ALLOWED_TRANSITIONS dict shape")
print("=" * 72)
from odoo.addons.neon_jobs.models.neon_equipment_unit import (
    ALLOWED_TRANSITIONS, MANAGER_BYPASS_TRANSITIONS,
)
expected_keys = {
    "draft", "active", "reserved", "checked_out", "transferred",
    "returned", "maintenance", "damaged", "decommissioned",
}
ok = (
    set(ALLOWED_TRANSITIONS.keys()) == expected_keys
    and all(isinstance(v, list) for v in ALLOWED_TRANSITIONS.values())
    and ALLOWED_TRANSITIONS["decommissioned"] == []
)
print("  keys:", sorted(ALLOWED_TRANSITIONS.keys()))
print("  decommissioned terminal (empty list)?",
      ALLOWED_TRANSITIONS["decommissioned"] == [])
print("T260:", "PASS" if ok else "FAIL")
results["T260"] = ok


# ============================================================
print()
print("=" * 72)
print("T261 - valid transition (draft -> active)")
print("=" * 72)
u261 = _new_unit("T261", "draft")
msg_count_pre = len(u261.message_ids)
u261._do_transition("active")
u261.invalidate_recordset()
matching = u261.message_ids.filtered(
    lambda m: "draft" in (m.body or "") and "active" in (m.body or ""))
ok = (
    u261.state == "active"
    and len(matching) >= 1
    and len(u261.message_ids) > msg_count_pre
)
print("  state:", u261.state, "(want active)")
print("  chatter rows added:", len(u261.message_ids) - msg_count_pre)
print("T261:", "PASS" if ok else "FAIL")
results["T261"] = ok


# ============================================================
print()
print("=" * 72)
print("T262 - illegal transition (draft -> checked_out) raises")
print("=" * 72)
u262 = _new_unit("T262", "draft")
raised = False
try:
    u262._do_transition("checked_out")
except UserError as e:
    raised = "Illegal state transition" in str(e)
u262.invalidate_recordset()
ok = raised and u262.state == "draft"
print("  raised UserError?", raised, "(want True)")
print("  state after:", u262.state, "(want draft)")
print("T262:", "PASS" if ok else "FAIL")
results["T262"] = ok


# ============================================================
print()
print("=" * 72)
print("T263 - unknown state code raises")
print("=" * 72)
u263 = _new_unit("T263", "draft")
raised = False
try:
    u263._do_transition("teleported")
except UserError as e:
    raised = "Unknown state" in str(e)
ok = raised and u263.state == "draft"
print("  raised UserError?", raised, "(want True)")
print("T263:", "PASS" if ok else "FAIL")
results["T263"] = ok


# ============================================================
print()
print("=" * 72)
print("T264 - same-state no-op")
print("=" * 72)
u264 = _new_unit("T264", "active")
msg_count_pre = len(u264.message_ids)
rv = u264._do_transition("active")
u264.invalidate_recordset()
ok = (
    rv is True
    and u264.state == "active"
    and len(u264.message_ids) == msg_count_pre
)
print("  return value:", rv, "(want True)")
print("  chatter unchanged?",
      len(u264.message_ids) == msg_count_pre)
print("T264:", "PASS" if ok else "FAIL")
results["T264"] = ok


# ============================================================
print()
print("=" * 72)
print("T265 - manager bypass: decommissioned -> active (valid)")
print("=" * 72)
u265 = _new_unit("T265", "decommissioned")
u265.with_user(manager)._do_transition(
    "active",
    manager_override=True,
    override_reason="Found fixable on re-inspection — keep in service",
)
u265.invalidate_recordset()
override_msgs = u265.message_ids.filtered(
    lambda m: "Manager override" in (m.body or ""))
ok = (
    u265.state == "active"
    and len(override_msgs) >= 1
)
print("  state:", u265.state, "(want active)")
print("  override chatter posts:", len(override_msgs), "(want >=1)")
print("T265:", "PASS" if ok else "FAIL")
results["T265"] = ok


# ============================================================
print()
print("=" * 72)
print("T266 - manager bypass: missing reason raises")
print("=" * 72)
u266 = _new_unit("T266", "decommissioned")
raised = False
try:
    u266.with_user(manager)._do_transition(
        "active", manager_override=True)  # no reason
except UserError as e:
    raised = "reason" in str(e).lower()
ok = raised and u266.state == "decommissioned"
print("  raised UserError mentioning reason?", raised, "(want True)")
print("T266:", "PASS" if ok else "FAIL")
results["T266"] = ok


# ============================================================
print()
print("=" * 72)
print("T267 - manager bypass: non-manager user raises")
print("=" * 72)
u267 = _new_unit("T267", "decommissioned")
raised = False
try:
    u267.with_user(sales)._do_transition(
        "active",
        manager_override=True,
        override_reason="testing",
    )
except UserError as e:
    raised = "manager group" in str(e).lower()
ok = raised and u267.state == "decommissioned"
print("  raised UserError mentioning manager group?",
      raised, "(want True)")
print("T267:", "PASS" if ok else "FAIL")
results["T267"] = ok


# ============================================================
print()
print("=" * 72)
print("T268 - manager bypass: beyond bypass list raises")
print("=" * 72)
u268 = _new_unit("T268", "decommissioned")
raised = False
try:
    u268.with_user(manager)._do_transition(
        "reserved",  # not in MANAGER_BYPASS_TRANSITIONS['decommissioned']
        manager_override=True,
        override_reason="trying to bypass beyond bypass",
    )
except UserError as e:
    raised = "not allowed" in str(e).lower() or "bypass" in str(e).lower()
ok = raised and u268.state == "decommissioned"
print("  raised UserError?", raised, "(want True)")
print("T268:", "PASS" if ok else "FAIL")
results["T268"] = ok


# ============================================================
print()
print("=" * 72)
print("T269 - action_* methods route correctly")
print("=" * 72)
# action_enroll: draft -> active
ua = _new_unit("T269a", "draft")
ua.action_enroll()
ua.invalidate_recordset()
enroll_ok = ua.state == "active"

# action_reserve: active -> reserved
ub = _new_unit("T269b", "active")
ub.action_reserve()
ub.invalidate_recordset()
reserve_ok = ub.state == "reserved"

# action_check_out on reserved -> checked_out
uc = _new_unit("T269c", "reserved")
uc.action_check_out()
uc.invalidate_recordset()
checkout_reserved_ok = uc.state == "checked_out"

# action_check_out on active -> UserError (must reserve first)
ud = _new_unit("T269d", "active")
checkout_active_blocked = False
try:
    ud.action_check_out()
except UserError as e:
    checkout_active_blocked = "must be reserved" in str(e).lower()
ud.invalidate_recordset()

# action_return on transferred -> returned
ue = _new_unit("T269e", "transferred")
ue.action_return()
ue.invalidate_recordset()
return_ok = ue.state == "returned"

# action_send_to_maintenance from active
uf = _new_unit("T269f", "active")
uf.action_send_to_maintenance()
uf.invalidate_recordset()
maint_ok = uf.state == "maintenance"

# action_complete_maintenance from maintenance
ug = _new_unit("T269g", "maintenance")
ug.action_complete_maintenance()
ug.invalidate_recordset()
complete_maint_ok = ug.state == "active"

ok = all([
    enroll_ok, reserve_ok, checkout_reserved_ok,
    checkout_active_blocked, return_ok, maint_ok,
    complete_maint_ok,
])
print("  enroll draft->active:    ", enroll_ok)
print("  reserve active->reserved:", reserve_ok)
print("  checkout reserved->co:   ", checkout_reserved_ok)
print("  checkout active blocked: ", checkout_active_blocked)
print("  return transferred->ret: ", return_ok)
print("  active->maintenance:     ", maint_ok)
print("  maintenance->active:     ", complete_maint_ok)
print("T269:", "PASS" if ok else "FAIL")
results["T269"] = ok


# ============================================================
print()
print("=" * 72)
print("T270 - can_<verb> compute matrix per state")
print("=" * 72)
# draft: only can_enroll + can_decommission
udraft = _new_unit("T270_draft", "draft")
draft_caps = {
    "enroll": udraft.can_enroll, "reserve": udraft.can_reserve,
    "check_out": udraft.can_check_out,
    "decommission": udraft.can_decommission,
}
draft_ok = (
    udraft.can_enroll is True
    and udraft.can_decommission is True
    and udraft.can_reserve is False
    and udraft.can_check_out is False
)

# active: can_reserve + can_send_to_maintenance + can_flag_damaged + can_decommission
uactive = _new_unit("T270_active", "active")
active_ok = (
    uactive.can_reserve is True
    and uactive.can_send_to_maintenance is True
    and uactive.can_flag_damaged is True
    and uactive.can_decommission is True
    and uactive.can_enroll is False
)

# decommissioned: ALL can_* should be False (terminal)
udecom = _new_unit("T270_decom", "decommissioned")
decom_caps = [
    udecom.can_enroll, udecom.can_reserve, udecom.can_check_out,
    udecom.can_transfer, udecom.can_receive_transfer,
    udecom.can_return, udecom.can_complete_check_in,
    udecom.can_send_to_maintenance, udecom.can_complete_maintenance,
    udecom.can_flag_damaged, udecom.can_decommission,
]
decom_ok = not any(decom_caps)

# reserved: can_check_out + can_send_to_maintenance + can_reserve(self-loop? no — 'reserved' not in active list... wait)
# Let's check: ALLOWED_TRANSITIONS['reserved'] = ['active', 'checked_out', 'maintenance']
# so can_reserve = False (no 'reserved' target from reserved), can_check_out = True
ureserved = _new_unit("T270_reserved", "reserved")
reserved_ok = (
    ureserved.can_check_out is True
    and ureserved.can_send_to_maintenance is True
    and ureserved.can_reserve is False  # 'reserved' not in target list from 'reserved'
    and ureserved.can_decommission is False  # blocked from reserved
)

ok = draft_ok and active_ok and decom_ok and reserved_ok
print("  draft caps OK:        ", draft_ok)
print("  active caps OK:       ", active_ok)
print("  decommissioned terminal:", decom_ok)
print("  reserved caps OK:     ", reserved_ok)
print("T270:", "PASS" if ok else "FAIL")
results["T270"] = ok


# ============================================================
print()
print("=" * 72)
print("T271 - Form view header has all action buttons")
print("=" * 72)
view = env.ref("neon_jobs.neon_equipment_unit_view_form")
arch = view.arch_db or ""
expected_buttons = [
    "action_enroll", "action_reserve", "action_check_out",
    "action_transfer", "action_receive_transfer", "action_return",
    "action_complete_check_in", "action_send_to_maintenance",
    "action_complete_maintenance", "action_flag_damaged",
    "action_decommission", "action_open_recommission_wizard",
]
missing = [b for b in expected_buttons if 'name="%s"' % b not in arch]
header_present = "<header>" in arch
statusbar_present = 'widget="statusbar"' in arch
ok = (
    not missing
    and header_present
    and statusbar_present
)
print("  <header> in arch:    ", header_present)
print("  statusbar widget:    ", statusbar_present)
print("  missing buttons:     ", missing or "(none)")
print("T271:", "PASS" if ok else "FAIL")
results["T271"] = ok


# ============================================================
print()
print("=" * 72)
print("T272 - Recommission wizard end-to-end")
print("=" * 72)
u272 = _new_unit("T272", "decommissioned")
Wizard = env["neon.equipment.recommission.wizard"]
w = Wizard.with_user(manager).create({
    "equipment_unit_id": u272.id,
    "reason": "Found a replacement part — repair viable",
    "target_state": "active",
})
w.action_confirm()
u272.invalidate_recordset()
override_msg = u272.message_ids.filtered(
    lambda m: "Manager override" in (m.body or ""))
ok = (
    u272.state == "active"
    and len(override_msg) >= 1
    and "replacement part" in (override_msg[0].body or "")
)
print("  state after wizard:", u272.state, "(want active)")
print("  override chatter present:", len(override_msg) >= 1)
print("T272:", "PASS" if ok else "FAIL")
results["T272"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T260", "T261", "T262", "T263", "T264", "T265", "T266",
         "T267", "T268", "T269", "T270", "T271", "T272"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()  # don't persist the test fixtures
