"""P7b integration smoke -- full candidate lifecycle (1 test).

T7bI001 threads every Phase 7b code path in one canonical
journey:

  Stage 1: create candidate (state=candidate, intended_role=
    tech, contact_email set)
  Stage 2: assert requirement_template auto-applied via M2
    compute + required_cert_type_ids populated
  Stage 3: transition to cert_collection -> M8 portal user
    created with group_portal only + portal_user_created
    audit entry + notify stub fired
  Stage 4: upload 2 required certs via M9 controller helper
    -> cert.candidate_id set + ir.attachment linked +
    cert_uploaded audit + notify stub + state=
    pending_verification (M7 routing fires)
  Stage 5: verify both certs (sudo write state=active) ->
    M4 cert constrains hook fires -> candidate auto-
    transitions to probationary + cert_verified notify
    stubs fire + promote_probationary audit
  Stage 6: promote via M6 wizard with create_user=True ->
    portal user upgraded (portal removed, base+crew+
    training_user added) + portal_user_upgraded audit +
    promote_active audit + promoted_active notify
  Stage 7: final state assertions (state=active, user
    backend, audit log = 6 entries, chatter has 4+ notify
    stub messages)

This single test exercises ~90% of Phase 7b code paths.
"""
import base64
from datetime import date, timedelta
from io import BytesIO

from odoo import fields, SUPERUSER_ID


class FakeFileStorage:
    """werkzeug.FileStorage mock for M9 controller helper."""
    def __init__(self, filename, mimetype, content):
        self.filename = filename
        self.mimetype = mimetype
        self._buf = BytesIO(content)
    def seek(self, offset, whence=0):
        return self._buf.seek(offset, whence)
    def tell(self):
        return self._buf.tell()
    def read(self):
        return self._buf.read()


class FakeRequest:
    """Mock for M9 controller's request.env + request.httprequest."""
    def __init__(self, env_, user, file_obj=None, form=None):
        self.env = env_(user=user.id)
        class HttpReq:
            def __init__(self, file_obj):
                self.files = ({"cert_file": file_obj}
                              if file_obj else {})
                self.method = "POST" if file_obj else "GET"
        self.httprequest = HttpReq(file_obj)
    def redirect(self, url):
        return ("__REDIRECT__", url)
    def render(self, template, values):
        return ("__RENDER__", template, values)


print("=" * 72)
print("P7b INTEGRATION SMOKE -- full candidate lifecycle")
print("=" * 72)
results = {}

Users = env["res.users"]
Candidate = env["neon.onboarding.candidate"]
PromoteWizard = env["neon.onboarding.promote.wizard"]
Cert = env["neon.training.certification"]
AuditLog = env["neon.onboarding.audit.log"]
Attachment = env["ir.attachment"]


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


u_super = _get_or_create_user(
    "p7b_m1_superuser", "P7b M1 Superuser",
    ["neon_core.group_neon_superuser"])


# Cert types used in this journey (tech template).
tech_template = env.ref("neon_onboarding.template_tech")
cert_type_tech = env.ref("neon_training.cert_type_tech")
cert_type_fire = env.ref(
    "neon_training.cert_type_fire_safety_indoor")


# ============================================================
print()
print("STAGE 1 -- create candidate")
print("=" * 72)
candidate = Candidate.sudo().create({
    "name": "Integration Smoke Crew",
    "intended_role": "tech",
    "contact_phone": "+263771009999",
    "contact_email": "integration@example.com",
    "state": "candidate",
})
stage_1_ok = (candidate.state == "candidate"
              and candidate.intended_role == "tech")
print(f"  state={candidate.state} role={candidate.intended_role}")
print(f"  Stage 1: {'PASS' if stage_1_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 2 -- requirement_template auto-applied")
print("=" * 72)
candidate.invalidate_recordset()
stage_2_ok = (
    candidate.requirement_template_id == tech_template
    and cert_type_tech in candidate.required_cert_type_ids
    and cert_type_fire in candidate.required_cert_type_ids
    and len(candidate.required_cert_type_ids) == 2
)
print(f"  template={candidate.requirement_template_id.name}")
print(f"  required types: {candidate.required_cert_type_ids.mapped('name')}")
print(f"  Stage 2: {'PASS' if stage_2_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 3 -- transition to cert_collection -> portal user")
print("=" * 72)
candidate.sudo().write({"state": "cert_collection"})
candidate.invalidate_recordset()
portal_user = candidate.user_id
g_portal = env.ref("base.group_portal")
g_base = env.ref("base.group_user")
stage_3_ok = (
    bool(portal_user)
    and portal_user.login == "integration@example.com"
    and portal_user in g_portal.users
    and portal_user not in g_base.users
)
audit_portal = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("action", "=", "portal_user_created"),
])
notify_portal = candidate.message_ids.filtered(
    lambda m: ("Notification stub" in (m.body or "")
               and "portal_user_created" in (m.body or "")))
print(f"  portal_user.login={portal_user.login if portal_user else None}")
print(f"  portal-only: {portal_user not in g_base.users if portal_user else False}")
print(f"  audit count: {len(audit_portal)}")
print(f"  notify count: {len(notify_portal)}")
stage_3_full_ok = (stage_3_ok
                   and len(audit_portal) == 1
                   and len(notify_portal) == 1)
print(f"  Stage 3: {'PASS' if stage_3_full_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 4 -- upload 2 required certs via M9 controller")
print("=" * 72)
from odoo.addons.neon_onboarding.controllers.portal import (
    NeonOnboardingPortal)
import odoo.addons.neon_onboarding.controllers.portal as portal_mod

controller = NeonOnboardingPortal()
saved_request = portal_mod.request


def _upload_via_m9(cert_type, filename):
    portal_mod.request = FakeRequest(
        env, portal_user,
        file_obj=FakeFileStorage(
            filename=filename,
            mimetype="application/pdf",
            content=b"%PDF-1.4 integration smoke"),
        form={
            "date_obtained": str(
                date.today() - timedelta(days=14)),
            "date_expires": False,
        })
    try:
        return controller._m9_process_upload(
            candidate, cert_type, portal_mod.request.httprequest.files)
    finally:
        pass


# M9's _m9_process_upload reads form from the request, not
# arg. Inline rebuild matching the controller signature:
def _upload(cert_type, filename):
    file_obj = FakeFileStorage(
        filename=filename,
        mimetype="application/pdf",
        content=b"%PDF-1.4 integration smoke")
    form = {
        "date_obtained": str(
            date.today() - timedelta(days=14)),
        "date_expires": False,
    }
    portal_mod.request = FakeRequest(
        env, portal_user, file_obj=file_obj, form=form)
    try:
        return controller._m9_process_upload(
            candidate, cert_type, form)
    finally:
        pass


err_tech = _upload(cert_type_tech, "tech_cert.pdf")
err_fire = _upload(cert_type_fire, "fire_cert.pdf")
portal_mod.request = saved_request

cert_tech = Cert.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("type_id", "=", cert_type_tech.id),
], limit=1)
cert_fire = Cert.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("type_id", "=", cert_type_fire.id),
], limit=1)
audit_uploads = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("action", "=", "cert_uploaded"),
])
notify_uploads = candidate.message_ids.filtered(
    lambda m: ("Notification stub" in (m.body or "")
               and "cert_uploaded" in (m.body or "")))
stage_4_ok = (
    err_tech is None and err_fire is None
    and bool(cert_tech) and bool(cert_fire)
    and cert_tech.state == "pending_verification"
    and cert_fire.state == "pending_verification"
    and len(audit_uploads) == 2
    and len(notify_uploads) == 2
)
print(f"  cert_tech state: {cert_tech.state if cert_tech else None}")
print(f"  cert_fire state: {cert_fire.state if cert_fire else None}")
print(f"  upload audits: {len(audit_uploads)} (expected 2)")
print(f"  upload notifies: {len(notify_uploads)} (expected 2)")
print(f"  Stage 4: {'PASS' if stage_4_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 5 -- verify both certs -> auto-transition")
print("=" * 72)
cert_tech.sudo().write({"state": "active"})
cert_fire.sudo().write({"state": "active"})
candidate.invalidate_recordset()
audit_promote_prob = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("action", "=", "promote_probationary"),
])
notify_verified = candidate.message_ids.filtered(
    lambda m: ("Notification stub" in (m.body or "")
               and "cert_verified" in (m.body or "")))
stage_5_ok = (
    candidate.state == "probationary"
    and candidate.all_required_certs_satisfied
    and len(audit_promote_prob) == 1
    and len(notify_verified) == 2
)
print(f"  candidate.state: {candidate.state} (expected probationary)")
print(f"  satisfied: {candidate.all_required_certs_satisfied}")
print(f"  promote_probationary audit: {len(audit_promote_prob)}")
print(f"  cert_verified notifies: {len(notify_verified)}")
print(f"  Stage 5: {'PASS' if stage_5_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 6 -- promote via M6 -> user upgraded")
print("=" * 72)
wiz = PromoteWizard.with_user(u_super).create({
    "candidate_id": candidate.id,
    "create_user": True,
})
wiz.action_promote()
candidate.invalidate_recordset()
portal_user.invalidate_recordset()
g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
g_train = env.ref("neon_training.group_neon_training_user")
audit_upgrade = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("action", "=", "portal_user_upgraded"),
])
audit_active = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
    ("action", "=", "promote_active"),
])
notify_active = candidate.message_ids.filtered(
    lambda m: ("Notification stub" in (m.body or "")
               and "promoted_active" in (m.body or "")))
stage_6_ok = (
    candidate.state == "active"
    and portal_user not in g_portal.users
    and portal_user in g_base.users
    and portal_user in g_crew.users
    and portal_user in g_train.users
    and len(audit_upgrade) == 1
    and len(audit_active) == 1
    and len(notify_active) == 1
)
print(f"  candidate.state: {candidate.state} (expected active)")
print(f"  portal stripped: {portal_user not in g_portal.users}")
print(f"  base + crew + training added: "
      f"{all([portal_user in g_base.users, portal_user in g_crew.users, portal_user in g_train.users])}")
print(f"  upgrade audit: {len(audit_upgrade)}")
print(f"  promote_active audit: {len(audit_active)}")
print(f"  promoted_active notify: {len(notify_active)}")
print(f"  Stage 6: {'PASS' if stage_6_ok else 'FAIL'}")


# ============================================================
print()
print("STAGE 7 -- final aggregate assertions")
print("=" * 72)
all_audits = AuditLog.sudo().search([
    ("candidate_id", "=", candidate.id),
])
all_notifies = candidate.message_ids.filtered(
    lambda m: "Notification stub" in (m.body or ""))
# Expected audit log:
#   1 portal_user_created
#   2 cert_uploaded
#   1 promote_probationary
#   1 portal_user_upgraded
#   1 promote_active
# = 6 total
expected_audit_count = 6
# Expected notify count:
#   1 portal_user_created
#   2 cert_uploaded
#   2 cert_verified
#   1 promoted_active
# = 6 total
expected_notify_count = 6
stage_7_ok = (
    len(all_audits) == expected_audit_count
    and len(all_notifies) == expected_notify_count
)
print(f"  audit log entries: {len(all_audits)} "
      f"(expected {expected_audit_count})")
audit_actions = sorted(all_audits.mapped("action"))
print(f"  audit actions: {audit_actions}")
print(f"  notify messages: {len(all_notifies)} "
      f"(expected {expected_notify_count})")
print(f"  Stage 7: {'PASS' if stage_7_ok else 'FAIL'}")


# ============================================================
print()
print("=" * 72)
print("INTEGRATION SMOKE SUMMARY")
print("=" * 72)
all_stages = [
    ("Stage 1 (create)", stage_1_ok),
    ("Stage 2 (template)", stage_2_ok),
    ("Stage 3 (portal user)", stage_3_full_ok),
    ("Stage 4 (uploads)", stage_4_ok),
    ("Stage 5 (auto-advance)", stage_5_ok),
    ("Stage 6 (promote)", stage_6_ok),
    ("Stage 7 (aggregates)", stage_7_ok),
]
for label, ok in all_stages:
    print(f"  {label}: {'PASS' if ok else 'FAIL'}")
passed = sum(1 for _, ok in all_stages if ok)
T7bI001_ok = passed == len(all_stages)
print()
print("T7bI001 (full lifecycle):",
      "PASS" if T7bI001_ok else "FAIL")
print(f"Total: {1 if T7bI001_ok else 0}/1 passed")

env.cr.rollback()
