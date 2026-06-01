# -*- coding: utf-8 -*-
"""P-HR-R3a smoke — driver licences (fleet) + competency gating.

Run in an odoo shell:  odoo shell -d neon_crm --no-http < phr_r3a_smoke.py

Covers: licence states + driver definition (any current licence),
configurable expiry lead + Action Centre alert, the SPLIT crew-assignment
gate (driver-licence HARD block non-override-able / competency
warn-vs-block per config / freelancer-no-employee warning), OD/MD
override, confidentiality record rules, crew->employee resolution.
"""
import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


HR = env["hr.employee"].sudo()
Lic = env["neon.hr.licence"].sudo()
Comp = env["neon.hr.competency"].sudo()
EComp = env["neon.hr.employee.competency"].sudo()
RoleComp = env["neon.hr.role.competency"].sudo()
Crew = env["commercial.job.crew"].sudo()
Partner = env["res.partner"].sudo()
Users = env["res.users"].sudo()
ICP = env["ir.config_parameter"].sudo()
today = fields.Date.today()

# ---- clean prior PHR-R3A fixtures (idempotent across cycles) ----
for j in env["commercial.job"].sudo().search([("name", "=like", "PHR-R3A%")]):
    j.crew_ids.unlink()
    j.unlink()
for e in HR.search([("name", "=like", "PHR-R3A%")]):
    Lic.search([("employee_id", "=", e.id)]).unlink()
    EComp.search([("employee_id", "=", e.id)]).unlink()
    e.unlink()
RoleComp.search([]).filtered(lambda r: r.crew_role == "tech").unlink()
Comp.search([("code", "=like", "phr_r3a_%")]).unlink()
Partner.search([("name", "=like", "PHR-R3A%")]).unlink()
# scrub test-only licence_expiry Action Centre items
env["action.centre.item"].sudo().search(
    [("trigger_type", "=", "licence_expiry")]).unlink()
ICP.set_param("neon_hr.competency_gate_mode", "warn")
ICP.set_param("neon_hr.licence_expiry_lead_days", "30")

cat = env["neon.hr.category"].sudo().search(
    [("code", "=", "employed_technician")], limit=1)


def _emp(name, contact=None):
    return HR.create({"name": name, "neon_category_id": cat.id,
                      "work_contact_id": contact.id if contact else False})


# =====================================================================
# 1-10  structure / metadata
# =====================================================================
from odoo.modules.module import get_module_path
with open(get_module_path("neon_hr") + "/__manifest__.py", encoding="utf-8") as f:
    _m = re.search(r'["\']version["\']\s*:\s*["\']([\d.]+)["\']', f.read())
_ver = tuple(int(x) for x in _m.group(1).split(".")) if _m else ()
_check("T-R3A-1", _ver >= (17, 0, 5, 0, 0),
       "neon_hr manifest >= 17.0.5.0.0 (got %s)" % (_m.group(1) if _m else "?"))

models_present = env["ir.model"].sudo().search(
    [("model", "in", ["neon.hr.licence", "neon.hr.competency",
                      "neon.hr.employee.competency",
                      "neon.hr.role.competency"])]).mapped("model")
_check("T-R3A-2", "neon.hr.licence" in models_present, "licence model")
_check("T-R3A-3", "neon.hr.competency" in models_present, "competency model")
_check("T-R3A-4", "neon.hr.employee.competency" in models_present,
       "employee.competency model")
_check("T-R3A-5", "neon.hr.role.competency" in models_present,
       "role.competency model")

r3_models = ["neon.hr.licence", "neon.hr.competency",
             "neon.hr.employee.competency", "neon.hr.role.competency"]
acls = env["ir.model.access"].sudo().search(
    [("model_id.model", "in", r3_models)])
_check("T-R3A-6", acls and set(acls.mapped("perm_unlink")) == {False},
       "all R3a ACL perm_unlink=0 (got %s)" % set(acls.mapped("perm_unlink")))

rules = env["ir.rule"].sudo().search(
    [("model_id.model", "in", ["neon.hr.licence",
                               "neon.hr.employee.competency"])])
_check("T-R3A-7", len(rules) >= 4,
       "licence + emp.competency record rules (got %d)" % len(rules))

labels = dict(env["action.centre.item"]._fields["trigger_type"]
              ._description_selection(env))
_check("T-R3A-8", "licence_expiry" in labels,
       "licence_expiry trigger in selection")

cfg = env["action.centre.trigger.config"].sudo().search(
    [("trigger_type", "=", "licence_expiry")], limit=1)
_check("T-R3A-9", cfg and cfg.is_enabled, "licence_expiry trigger config enabled")

_check("T-R3A-10",
       bool(env.ref("neon_hr.ir_cron_licence_expiry", raise_if_not_found=False)),
       "licence-expiry cron present")

# =====================================================================
# 11-16  licence states + driver definition + expiry alert
# =====================================================================
p_drv = Partner.create({"name": "PHR-R3A Driver contact"})
emp_drv = _emp("PHR-R3A Driver", p_drv)
lic_valid = Lic.create({
    "employee_id": emp_drv.id, "licence_class": "class_3",
    "licence_number": "VALID-1", "expiry_date": today + timedelta(days=200)})
_check("T-R3A-11",
       lic_valid.state == "valid" and emp_drv.is_driver
       and emp_drv.valid_licence_count == 1,
       "valid licence -> state valid + is_driver + count 1 (%s/%s/%s)"
       % (lic_valid.state, emp_drv.is_driver, emp_drv.valid_licence_count))

p_exp = Partner.create({"name": "PHR-R3A Expired contact"})
emp_exp = _emp("PHR-R3A Expired", p_exp)
lic_exp = Lic.create({
    "employee_id": emp_exp.id, "licence_class": "class_3",
    "licence_number": "EXP-1", "expiry_date": today - timedelta(days=10)})
emp_exp.invalidate_recordset(["is_driver"])
_check("T-R3A-12",
       lic_exp.state == "expired" and not emp_exp.is_driver,
       "expired licence -> state expired + NOT driver (%s/%s)"
       % (lic_exp.state, emp_exp.is_driver))

p_soon = Partner.create({"name": "PHR-R3A Soon contact"})
emp_soon = _emp("PHR-R3A Soon", p_soon)
lic_soon = Lic.create({
    "employee_id": emp_soon.id, "licence_class": "class_3",
    "licence_number": "SOON-1", "expiry_date": today + timedelta(days=10)})
_check("T-R3A-13",
       lic_soon.state == "expiring" and emp_soon.is_driver,
       "expiring (<=30d) licence -> state expiring + still driver (%s/%s)"
       % (lic_soon.state, emp_soon.is_driver))

# configurable lead window affects 'expiring' boundary
ICP.set_param("neon_hr.licence_expiry_lead_days", "5")
lic_soon._compute_state()
state_lead5 = lic_soon.state
ICP.set_param("neon_hr.licence_expiry_lead_days", "30")
lic_soon._compute_state()
state_lead30 = lic_soon.state
_check("T-R3A-14",
       state_lead5 == "valid" and state_lead30 == "expiring",
       "lead-days config moves expiring boundary (lead5=%s lead30=%s)"
       % (state_lead5, state_lead30))

# Action Centre alert via cron probe
env["neon.hr.licence"]._cron_licence_expiry_scan()
sm = env["ir.model"].sudo()._get("neon.hr.licence")
item_exp = env["action.centre.item"].sudo().search(
    [("trigger_type", "=", "licence_expiry"),
     ("source_model_id", "=", sm.id), ("source_id", "=", lic_exp.id)])
_check("T-R3A-15", len(item_exp) == 1,
       "cron raises AC item for EXPIRED licence (got %d)" % len(item_exp))
item_soon = env["action.centre.item"].sudo().search(
    [("trigger_type", "=", "licence_expiry"),
     ("source_model_id", "=", sm.id), ("source_id", "=", lic_soon.id)])
_check("T-R3A-16", len(item_soon) == 1,
       "cron raises AC item for EXPIRING licence (got %d)" % len(item_soon))

# =====================================================================
# 17-18  competency catalog + employee competency states + role map
# =====================================================================
comp_height = Comp.create({"name": "PHR-R3A Working at Heights",
                           "code": "phr_r3a_height", "requires_expiry": True})
comp_rig = Comp.create({"name": "PHR-R3A Rigging",
                        "code": "phr_r3a_rig", "requires_expiry": False})
p_comp = Partner.create({"name": "PHR-R3A Comp contact"})
emp_comp = _emp("PHR-R3A Comp", p_comp)
ec_rig = EComp.create({"employee_id": emp_comp.id,
                       "competency_id": comp_rig.id})
ec_height_exp = EComp.create({
    "employee_id": emp_comp.id, "competency_id": comp_height.id,
    "expiry_date": today - timedelta(days=5)})
_check("T-R3A-17",
       ec_rig.state == "valid" and ec_height_exp.state == "expired",
       "competency states: no-expiry valid + past-expiry expired (%s/%s)"
       % (ec_rig.state, ec_height_exp.state))

role_tech = RoleComp.create({
    "crew_role": "tech",
    "competency_ids": [(6, 0, [comp_height.id, comp_rig.id])]})
_check("T-R3A-18", role_tech.competency_ids == (comp_height | comp_rig),
       "role->competency map created for 'tech'")

# =====================================================================
# job + crew gate fixtures
# =====================================================================
venue = Partner.search([("is_venue", "=", True)], limit=1)
if not venue:
    venue = Partner.create({"name": "PHR-R3A Venue", "is_venue": True})
job = env["commercial.job"].sudo().create({
    "name": "PHR-R3A JOB", "partner_id": p_drv.id, "venue_id": venue.id,
    "state": "active", "event_date": today})


def _mk_crew(partner, role, **extra):
    vals = {"job_id": job.id, "partner_id": partner.id, "role": role}
    vals.update(extra)
    return Crew.create(vals)


def _expect_block(partner, role, **extra):
    try:
        with env.cr.savepoint():
            _mk_crew(partner, role, **extra)
        return False
    except UserError:
        return True


# =====================================================================
# 19-22  driver-licence gate (HARD block, not override-able)
# =====================================================================
crew_ok = _mk_crew(p_drv, "driver")
_check("T-R3A-19",
       crew_ok.neon_employee_id == emp_drv and crew_ok.neon_gate_state == "ok",
       "driver + valid licence -> assignment OK (emp=%s state=%s)"
       % (crew_ok.neon_employee_id.id, crew_ok.neon_gate_state))

_check("T-R3A-20", _expect_block(p_exp, "driver"),
       "driver + employee with NO valid licence -> HARD BLOCK")

_check("T-R3A-21", _expect_block(p_exp, "driver", neon_competency_override=True),
       "driver licence block is NOT override-able")

p_free = Partner.create({"name": "PHR-R3A Freelancer"})
crew_free = _mk_crew(p_free, "driver")
_check("T-R3A-22",
       not crew_free.neon_employee_id
       and crew_free.neon_gate_state == "no_employee",
       "driver freelancer (no employee) -> warning, not block (%s/%s)"
       % (crew_free.neon_employee_id.id, crew_free.neon_gate_state))

# =====================================================================
# 23-27  competency gate (warn vs block per config + override)
# =====================================================================
ICP.set_param("neon_hr.competency_gate_mode", "warn")
crew_warn = _mk_crew(p_comp, "tech")
_check("T-R3A-23",
       crew_warn.neon_gate_state == "competency_warning",
       "warn mode: missing competency -> assignment allowed + warning (%s)"
       % crew_warn.neon_gate_state)

ICP.set_param("neon_hr.competency_gate_mode", "block")
p_comp2 = Partner.create({"name": "PHR-R3A Comp2 contact"})
emp_comp2 = _emp("PHR-R3A Comp2", p_comp2)  # holds nothing -> missing both
_check("T-R3A-24", _expect_block(p_comp2, "tech"),
       "block mode: missing competency -> UserError")

crew_ovr = _mk_crew(p_comp2, "tech", neon_competency_override=True)
_check("T-R3A-25",
       crew_ovr.neon_gate_state == "overridden",
       "block mode + OD/MD override -> assignment allowed (%s)"
       % crew_ovr.neon_gate_state)
ICP.set_param("neon_hr.competency_gate_mode", "warn")

# override action is OD/MD-only
bare = Users.search([("login", "=", "phr_r3a_bare")], limit=1)
if not bare:
    bare = Users.with_context(no_reset_password=True).create({
        "name": "PHR-R3A bare", "login": "phr_r3a_bare",
        "email": "phr_r3a_bare@neonhiring.com",
        "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
ovr_denied = False
try:
    crew_warn.with_user(bare).action_neon_override_competency()
except (AccessError, UserError):
    ovr_denied = True
_check("T-R3A-26", ovr_denied, "competency override is OD/MD-only")

missing = emp_comp._missing_competencies(comp_height | comp_rig)
_check("T-R3A-27",
       comp_height in missing and comp_rig not in missing,
       "expired competency counts as missing; valid one does not")

# =====================================================================
# 28-31  helper + confidentiality + resolution
# =====================================================================
_check("T-R3A-28", emp_drv._has_valid_licence() and not emp_exp._has_valid_licence(),
       "_has_valid_licence true for valid, false for expired-only")

lic_blocked = False
try:
    Lic.browse(lic_valid.id).with_user(bare).read(["licence_number"])
except AccessError:
    lic_blocked = True
_check("T-R3A-29", lic_blocked,
       "non-OD/MD/Admin cannot read another's licence (record rule)")

# resolution via user_id
u_crew = Users.search([("login", "=", "phr_r3a_drvuser")], limit=1)
if not u_crew:
    u_crew = Users.with_context(no_reset_password=True).create({
        "name": "PHR-R3A DrvUser", "login": "phr_r3a_drvuser",
        "email": "phr_r3a_drvuser@neonhiring.com",
        "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
emp_u = _emp("PHR-R3A UserDriver")
emp_u.user_id = u_crew.id
Lic.create({"employee_id": emp_u.id, "licence_class": "class_3",
            "licence_number": "UVALID", "expiry_date": today + timedelta(days=99)})
crew_u = _mk_crew(u_crew.partner_id, "driver", user_id=u_crew.id)
_check("T-R3A-30", crew_u.neon_employee_id == emp_u,
       "crew->employee resolves via user_id (%s)" % crew_u.neon_employee_id.id)
_check("T-R3A-31", crew_ok.neon_employee_id == emp_drv,
       "crew->employee resolves via work_contact_id")

# ---- summary ----
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    if not results[k]:
        print(f"  {k}: FAIL")
