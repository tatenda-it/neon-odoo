"""P-HR-R1a smoke — employee foundation (neon_hr).

Runs in `odoo shell -d <db>`. T-HR-R1a-01 .. 39.

Covers acceptance §3:
- all 7 categories exist with DISTINCT default doc-sets
- 3 contract templates load; salary/per-job/commission are per-contract not global
- renewal state machine: valid transitions pass, invalid blocked
- notice period: permanent defaults 30d; others flagged, NOT 3 months
- is_compliant false until mandatory docs present; assignment soft-block + override
- 30-day expiry raises an Action Centre task; expired-but-Active surfaced
- record rules: a non-OD/MD/Admin, non-owner user cannot read salary/personal docs
- manifest version + R1b field-name contract
"""
import base64
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR-R1a — employee foundation (neon_hr)")
print("=" * 72)
results = {}

# Headless-shell mail setup (rolled back at end). Production has a
# configured sender; this shell does not, so explicit message_post
# calls (renewal transitions, Action Centre chatter) would raise
# "configure the sender's email address". Set a sender + force async
# so notifications queue instead of raising. NOT a code change —
# purely a test-environment unblock.
env = env(context=dict(
    env.context,
    mail_notify_force_send=False,
    mail_create_nosubscribe=True,
    tracking_disable=True,
))
env.company.sudo().write({"email": env.company.email or "noreply@neonhiring.com"})
_root = env.ref("base.user_root")
if not _root.email:
    _root.sudo().write({"email": "root@neonhiring.com"})
if not env.user.email:
    env.user.sudo().write({"email": "shell@neonhiring.com"})

HR = env["hr.employee"]
Contract = env["hr.contract"]
Cat = env["neon.hr.category"]
DocType = env["neon.hr.document.type"]
Doc = env["neon.hr.document"]
Tpl = env["neon.hr.contract.template"]
ACItem = env["action.centre.item"]
ACConfig = env["action.centre.trigger.config"]

today = date.today()
cat_by_code = {c.code: c for c in Cat.sudo().search([])}
EXPECTED_CATS = {
    "permanent", "fixed_term", "employed_technician",
    "freelance_technician", "casual_crew", "contractor", "driver",
}


def _attach(doc):
    att = env["ir.attachment"].sudo().create({
        "name": f"probe_{doc.id}.pdf",
        "datas": base64.b64encode(b"probe").decode(),
        "res_model": "neon.hr.document", "res_id": doc.id,
    })
    doc.sudo().write({"attachment_ids": [(4, att.id)]})
    doc.invalidate_recordset(["attachment_ids", "state", "is_expired"])
    return att


# ============================================================
# Categories (7, distinct doc-sets)
# ============================================================
_check("T-HR-R1a-01",
       set(cat_by_code) == EXPECTED_CATS,
       f"7 categories: {sorted(cat_by_code)}")

doc_sets = {}
for code, cat in cat_by_code.items():
    doc_sets[code] = frozenset(
        cat.required_document_type_ids.mapped("code"))
_check("T-HR-R1a-02",
       len(set(doc_sets.values())) == 7,
       f"all 7 doc-sets distinct: sizes={ {k: len(v) for k, v in doc_sets.items()} }")
_check("T-HR-R1a-03",
       all(len(v) > 0 for v in doc_sets.values()),
       "every category has a non-empty required-document set")
_check("T-HR-R1a-04",
       cat_by_code["permanent"].default_pay_type == "salary"
       and cat_by_code["freelance_technician"].default_pay_type == "per_job",
       "default_pay_type drives off category")


# ============================================================
# Document types (Appendix B7)
# ============================================================
dt_codes = set(DocType.sudo().search([]).mapped("code"))
MANDATORY = {
    "signed_contract", "code_of_conduct", "id_passport", "work_permit",
    "emergency_contact", "banking_details", "tax_statutory",
    "conflict_of_interest", "confidentiality_ack", "competency_record",
    "nssa_registration",
}
_check("T-HR-R1a-05",
       MANDATORY.issubset(dt_codes),
       f"mandatory doc types present ({len(dt_codes)} total)")
_check("T-HR-R1a-06",
       DocType.sudo().search(
           [("code", "=", "id_passport")]).requires_expiry
       and not DocType.sudo().search(
           [("code", "=", "banking_details")]).requires_expiry,
       "requires_expiry set correctly (id_passport yes, banking no)")


# ============================================================
# Contract templates + per-contract (not global) pay fields
# ============================================================
tpls = Tpl.sudo().search([])
_check("T-HR-R1a-07", len(tpls) >= 3, f"{len(tpls)} contract templates load")
tpl_types = set(tpls.mapped("neon_contract_type"))
_check("T-HR-R1a-08",
       {"employed_technician", "casual_crew", "freelance_technician"}.issubset(tpl_types),
       f"3 expected template types present: {tpl_types}")

cfields = Contract._fields
_check("T-HR-R1a-09",
       cfields["wage"].store and cfields["per_job_amount"].store
       and cfields["commission_percent"].store,
       "salary(wage)/per_job_amount/commission_percent are stored "
       "hr.contract fields — per-contract, not global constants")
_check("T-HR-R1a-10",
       all(t.default_wage == 0.0 and t.default_per_job_amount == 0.0
           for t in tpls),
       "templates carry NO baked salary/per-job (vary by person, Q5)")


# ============================================================
# Renewal state machine
# ============================================================
emp_r = HR.sudo().create({"name": "PHR Renewal Probe"})
# draft state: the native hr_contract rule forbids >1 non-draft
# contract per employee; the renewal machine is independent of state.
c_r = Contract.sudo().create({
    "name": "PHR renewal contract", "employee_id": emp_r.id,
    "wage": 1000.0, "date_start": today, "state": "draft",
})
_check("T-HR-R1a-11", c_r.renewal_state == "not_reviewed",
       f"renewal_state defaults not_reviewed: {c_r.renewal_state}")

c_r.action_renewal_start_review()
_check("T-HR-R1a-12", c_r.renewal_state == "renewal_under_review",
       "not_reviewed -> renewal_under_review")
c_r.action_renewal_decide_renew()
_check("T-HR-R1a-13", c_r.renewal_state == "renew",
       "renewal_under_review -> renew")
c_r.action_renewal_issue_letter()
c_r.action_renewal_new_contract_signed()
_check("T-HR-R1a-14", c_r.renewal_state == "new_contract_signed",
       "renew -> renewal_letter_issued -> new_contract_signed (full path)")

# Invalid: terminal state cannot move
term_blocked = False
try:
    c_r.action_renewal_start_review()
except UserError:
    term_blocked = True
_check("T-HR-R1a-15", term_blocked,
       "invalid transition from terminal new_contract_signed blocked")

# Invalid: cannot skip stages
c_r2 = Contract.sudo().create({
    "name": "PHR renewal contract 2", "employee_id": emp_r.id,
    "wage": 900.0, "date_start": today, "state": "draft",
})
skip_blocked = False
try:
    c_r2.action_renewal_issue_letter()   # not_reviewed -> letter (skip)
except UserError:
    skip_blocked = True
_check("T-HR-R1a-16", skip_blocked,
       "cannot skip not_reviewed -> renewal_letter_issued")

# Valid do-not-renew path to expired
c_r2.action_renewal_start_review()
c_r2.action_renewal_decide_not_renew()
c_r2.action_renewal_issue_non_renewal()
c_r2.action_renewal_mark_expired()
_check("T-HR-R1a-17", c_r2.renewal_state == "expired",
       "do_not_renew -> non_renewal_notice_issued -> expired")


# ============================================================
# Notice period (permanent 30d; others flagged, not 3 months)
# ============================================================
_check("T-HR-R1a-18",
       cat_by_code["permanent"].notice_period_days == 30
       and not cat_by_code["permanent"].notice_flagged_for_legal,
       "permanent category notice = 30d, not flagged")
non_perm = [c for k, c in cat_by_code.items() if k != "permanent"]
_check("T-HR-R1a-19",
       all(c.notice_flagged_for_legal for c in non_perm)
       and all(c.notice_period_days != 90 for c in non_perm),
       "all non-permanent categories flagged + NOT defaulted to 90 days")

c_n = Contract.sudo().create({
    "name": "PHR notice probe", "employee_id": emp_r.id,
    "wage": 1000.0, "date_start": today, "state": "draft",
})
c_n.neon_contract_type = "permanent"
c_n.trial_date_end = False
c_n._onchange_notice_flag()
_check("T-HR-R1a-20",
       c_n.notice_period_days == 30 and not c_n.notice_period_flagged_for_legal,
       "permanent contract (no trial) -> 30d, not flagged")
c_n.neon_contract_type = "casual_crew"
c_n._onchange_notice_flag()
_check("T-HR-R1a-21",
       c_n.notice_period_flagged_for_legal,
       "casual contract -> notice flagged for legal")
# Probation-on-probation contradiction: trial set -> flagged even if permanent
c_n.neon_contract_type = "permanent"
c_n.trial_date_end = today + timedelta(days=90)
c_n._onchange_notice_flag()
_check("T-HR-R1a-22",
       c_n.notice_period_flagged_for_legal,
       "permanent WITH trial (probation) -> flagged (contradiction surfaced)")


# ============================================================
# Compliance + assignment gate
# ============================================================
emp_c = HR.sudo().create({"name": "PHR Compliance Probe"})
emp_c.write({"neon_category_id": cat_by_code["employed_technician"].id})
emp_c.invalidate_recordset(["document_ids", "is_compliant", "document_count"])
req_n = len(cat_by_code["employed_technician"].required_document_type_ids)
_check("T-HR-R1a-23",
       len(emp_c.document_ids) == req_n and req_n == 10,
       f"category set -> checklist auto-generated ({len(emp_c.document_ids)} rows)")
_check("T-HR-R1a-24",
       not emp_c.is_compliant,
       "is_compliant False while all documents missing")

_attach(emp_c.document_ids[0])
emp_c.invalidate_recordset(["is_compliant"])
_check("T-HR-R1a-25",
       not emp_c.is_compliant,
       "is_compliant still False with only one document provided")

for d in emp_c.document_ids:
    _attach(d)
emp_c.invalidate_recordset(["is_compliant", "compliance_summary"])
_check("T-HR-R1a-26",
       emp_c.is_compliant,
       f"is_compliant True once all provided: {emp_c.compliance_summary}")

# Assignment gate
emp_noc = HR.sudo().create({"name": "PHR No-Contract Probe"})
ok_noc, _r = emp_noc._check_assignable()
_check("T-HR-R1a-27", not ok_noc, f"no contract -> soft block ({_r})")

emp_exp = HR.sudo().create({"name": "PHR Expired-Contract Probe"})
Contract.sudo().create({
    "name": "expired", "employee_id": emp_exp.id, "wage": 800.0,
    "date_start": today - timedelta(days=400),
    "date_end": today - timedelta(days=5), "state": "open",
})
emp_exp.invalidate_recordset(["has_valid_contract"])
ok_exp, _re = emp_exp._check_assignable()
_check("T-HR-R1a-28",
       not emp_exp.has_valid_contract and not ok_exp,
       f"expired contract -> soft block ({_re})")

emp_val = HR.sudo().create({"name": "PHR Valid-Contract Probe"})
Contract.sudo().create({
    "name": "valid", "employee_id": emp_val.id, "wage": 800.0,
    "date_start": today, "date_end": today + timedelta(days=200),
    "state": "open",
})
emp_val.invalidate_recordset(["has_valid_contract"])
ok_val, _rv = emp_val._check_assignable()
_check("T-HR-R1a-29",
       emp_val.has_valid_contract and ok_val,
       "valid open contract -> assignable")

# Override by OD/MD
su_group = env.ref("neon_core.group_neon_superuser")
su_user = env["res.users"].sudo().create({
    "name": "PHR OD/MD Probe", "login": "phr_odmd_probe",
    "email": "phr_odmd_probe@neonhiring.com",
    "groups_id": [(6, 0, [su_group.id])],
})
emp_exp.with_user(su_user).action_override_assignment()
emp_exp.invalidate_recordset(["assignment_override"])
ok_ovr, _ro = emp_exp._check_assignable()
_check("T-HR-R1a-30",
       emp_exp.assignment_override and ok_ovr,
       "OD/MD override flips the soft block to assignable")

# Non-OD/MD cannot override
sales_user = env["res.users"].sudo().search(
    [("login", "=", "p2m75_sales")], limit=1)
if not sales_user:
    sales_user = env["res.users"].sudo().create({
        "name": "PHR Sales Probe", "login": "phr_sales_probe",
        "email": "phr_sales_probe@neonhiring.com",
        "groups_id": [(6, 0, [env.ref("neon_core.group_neon_sales_rep").id])],
    })
emp_val2 = HR.sudo().create({"name": "PHR Override-Auth Probe"})
ovr_blocked = False
try:
    emp_val2.with_user(sales_user).action_override_assignment()
except AccessError:
    ovr_blocked = True
_check("T-HR-R1a-31", ovr_blocked,
       "non-OD/MD user cannot override the assignment gate")


# ============================================================
# Action Centre contract-expiry alert
# ============================================================
cfg = ACConfig.sudo().search(
    [("trigger_type", "=", "contract_expiry_30days")], limit=1)
_check("T-HR-R1a-32",
       bool(cfg) and cfg.is_enabled and cfg.name != "Unknown",
       f"trigger config present, enabled, named: {cfg.name!r}")
_check("T-HR-R1a-33",
       "contract_expiry_30days" in dict(
           ACItem._fields["trigger_type"]._description_selection(env)),
       "contract_expiry_30days added to action.centre.item via selection_add")

emp_e = HR.sudo().create({"name": "PHR Expiry Probe"})
c_e = Contract.sudo().create({
    "name": "expiring soon", "employee_id": emp_e.id, "wage": 1200.0,
    "date_start": today - timedelta(days=300),
    "date_end": today + timedelta(days=25), "state": "open",
})
Contract._cron_contract_expiry_scan()
sm = env["ir.model"].sudo()._get("hr.contract")
items = ACItem.sudo().search([
    ("trigger_type", "=", "contract_expiry_30days"),
    ("source_model_id", "=", sm.id), ("source_id", "=", c_e.id),
    ("state", "in", ("open", "in_progress")),
])
_check("T-HR-R1a-34", len(items) == 1,
       f"30-day expiry raises exactly one Action Centre item ({len(items)})")

# Idempotency: re-run, still one
Contract._cron_contract_expiry_scan()
items2 = ACItem.sudo().search([
    ("trigger_type", "=", "contract_expiry_30days"),
    ("source_model_id", "=", sm.id), ("source_id", "=", c_e.id),
    ("state", "in", ("open", "in_progress")),
])
_check("T-HR-R1a-35", len(items2) == 1,
       "cron is idempotent — no duplicate item on re-scan")

# Expired-but-Active surfaced
emp_ea = HR.sudo().create({"name": "PHR Expired-Active Probe"})
c_ea = Contract.sudo().create({
    "name": "expired active", "employee_id": emp_ea.id, "wage": 1000.0,
    "date_start": today - timedelta(days=400),
    "date_end": today - timedelta(days=10), "state": "open",
})
c_ea.invalidate_recordset(["neon_expiry_state"])
_check("T-HR-R1a-36",
       c_ea.neon_expiry_state == "expired_active",
       f"expired-but-Active classified: {c_ea.neon_expiry_state}")
Contract._cron_contract_expiry_scan()
items_ea = ACItem.sudo().search([
    ("trigger_type", "=", "contract_expiry_30days"),
    ("source_model_id", "=", sm.id), ("source_id", "=", c_ea.id),
])
_check("T-HR-R1a-37",
       len(items_ea) == 1 and items_ea.priority == "urgent",
       f"expired-but-Active raises an urgent item ({items_ea.priority if items_ea else 'none'})")


# ============================================================
# Confidentiality record rules
# ============================================================
# Another employee's personal doc + contract (salary).
emp_other = HR.sudo().create({"name": "PHR Confidential Other"})
emp_other.write({"neon_category_id": cat_by_code["casual_crew"].id})
other_doc = emp_other.document_ids[0]
other_contract = Contract.sudo().create({
    "name": "other salary", "employee_id": emp_other.id, "wage": 5000.0,
    "date_start": today, "state": "open",
})

# Clean bare internal user (ONLY base.group_user, no neon/hr groups):
# the canonical "non-OD/MD/Admin, non-owner" — deterministic regardless
# of fixture-user group drift.
clean_user = env["res.users"].sudo().create({
    "name": "PHR Bare Internal", "login": "phr_bare_probe",
    "email": "phr_bare_probe@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
doc_blocked = False
try:
    Doc.with_user(clean_user).browse(other_doc.id).read(["state"])
except AccessError:
    doc_blocked = True
_check("T-HR-R1a-38", doc_blocked,
       "non-OD/MD/Admin, non-owner CANNOT read another's personal document")

salary_blocked = False
try:
    Contract.with_user(clean_user).browse(
        other_contract.id).read(["wage"])
except AccessError:
    salary_blocked = True
_check("T-HR-R1a-39", salary_blocked,
       "non-OD/MD/Admin, non-owner CANNOT read another's salary (wage)")

# Owner CAN read own document
emp_owned = HR.sudo().create({
    "name": "PHR Owned", "user_id": sales_user.id})
emp_owned.write({"neon_category_id": cat_by_code["casual_crew"].id})
owned_doc = emp_owned.document_ids[0]
owner_ok = False
try:
    val = Doc.with_user(sales_user).browse(owned_doc.id).read(["state"])
    owner_ok = bool(val)
except AccessError:
    owner_ok = False
_check("T-HR-R1a-40", owner_ok,
       "record OWNER can read their own personal document")

# HR Admin CAN read anyone's document
hr_admin_user = env["res.users"].sudo().create({
    "name": "PHR HR Admin Probe", "login": "phr_hr_admin_probe",
    "email": "phr_hr_admin_probe@neonhiring.com",
    "groups_id": [(6, 0, [env.ref("neon_hr.group_neon_hr_admin").id])],
})
admin_ok = False
try:
    val = Doc.with_user(hr_admin_user).browse(other_doc.id).read(["state"])
    admin_ok = bool(val)
except AccessError:
    admin_ok = False
_check("T-HR-R1a-41", admin_ok,
       "HR Admin can read any employee's personal document")

# post_init grant: superuser implies hr.group_hr_manager
hr_mgr = env.ref("hr.group_hr_manager")
_check("T-HR-R1a-42",
       hr_mgr in su_group.implied_ids,
       "post_init granted hr.group_hr_manager to neon_core.group_neon_superuser")

# Q28 enforcement: the hr-install auto-grant must have been stripped
# from non-OD/MD/Admin users. A neon-tier fixture (crew) must NOT hold
# hr_manager, and only OD/MD + HR Admin + admin/root should.
hr_user_g = env.ref("hr.group_hr_user")
crew = env["res.users"].sudo().search([("login", "=", "p2m75_crew")], limit=1)
_check("T-HR-R1a-45",
       (not crew) or (hr_mgr not in crew.groups_id
                      and hr_user_g not in crew.groups_id),
       "neon-tier crew user stripped of auto-granted hr access (Q28)")
holders = env["res.users"].sudo().search([
    ("share", "=", False), ("groups_id", "in", hr_mgr.id)])
allowed = set(su_group.sudo().users.ids)
hadm = env.ref("neon_hr.group_neon_hr_admin")
allowed |= set(hadm.sudo().users.ids)
for x in ("base.user_root", "base.user_admin"):
    uu = env.ref(x, raise_if_not_found=False)
    if uu:
        allowed.add(uu.id)
# probe HR-admin user created above is also a legitimate holder
allowed.add(hr_admin_user.id)
stray = [u.login for u in holders if u.id not in allowed]
_check("T-HR-R1a-46",
       not stray,
       f"only OD/MD + HR Admin + admin hold hr_manager; stray={stray[:5]}")


# ============================================================
# Manifest version + R1b field-name contract
# ============================================================
import os
from odoo.modules.module import get_module_path
with open(os.path.join(get_module_path("neon_hr"), "__manifest__.py"),
          "r", encoding="utf-8") as f:
    manifest_src = f.read()
_check("T-HR-R1a-47", "17.0.1.0.1" in manifest_src,
       "neon_hr manifest version 17.0.1.0.1")

# R1b contract — model + field names R1b will reference.
contract_spec = (
    ("hr.employee", "neon_category_id", "many2one"),
    ("hr.employee", "is_compliant", "boolean"),
    ("hr.employee", "document_ids", "one2many"),
    ("hr.contract", "renewal_state", "selection"),
    ("hr.contract", "neon_contract_type", "selection"),
    ("hr.contract", "per_job_amount", "monetary"),
    ("hr.contract", "commission_percent", "float"),
    ("hr.contract", "notice_period_days", "integer"),
    ("neon.hr.category", "required_document_type_ids", "many2many"),
    ("neon.hr.document", "document_type_id", "many2one"),
    ("neon.hr.document.type", "requires_expiry", "boolean"),
    ("neon.hr.contract.template", "neon_contract_type", "selection"),
)
mismatches = []
for model_name, fname, ftype in contract_spec:
    f = env[model_name]._fields.get(fname)
    if not f:
        mismatches.append(f"{model_name}.{fname} MISSING")
    elif f.type != ftype:
        mismatches.append(f"{model_name}.{fname} type={f.type} != {ftype}")
_check("T-HR-R1a-44", not mismatches,
       "R1b field-name contract intact" if not mismatches else str(mismatches))


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)

env.cr.rollback()
