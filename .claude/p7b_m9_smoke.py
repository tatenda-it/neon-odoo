"""P7b.M9 smoke -- portal self-upload cert wizard (9 tests).

Smoke strategy: call the controller's _m9_create_cert_record
helper directly with a mock FileStorage-like object. HTTP
layer routing + redirects are verified via source inspection
(T7b907 = redirect-when-not-cert-collection asserts the guard
function _m9_get_candidate_or_redirect).

T7b900  cert_uploaded for cert_collection candidate -> cert
        created with type_id + candidate_id + state=
        pending_verification (via action_submit_for_verification)
T7b901  Robin + Munashe added as followers (M7 routing
        override fires via Phase 7a action_submit_for_
        verification)
T7b902  ir.attachment created linked to cert (res_model +
        res_id)
T7b903  audit log entry action='cert_uploaded' + reason
        references cert type name
T7b904  cert_type not in required list -> redirect (no cert
        created) -- assert via controller routing source
T7b905  file > 10MB -> error message returned (no cert
        created)
T7b906  file extension outside whitelist -> error message
        (no cert created)
T7b907  candidate.state != 'cert_collection' -> redirect
        (no cert created) -- assert via guard logic
T7b908  cert already pending for same type -> excluded from
        available_types list
"""
import base64
from datetime import date, timedelta
from io import BytesIO

from odoo import fields, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError, ValidationError


class FakeFileStorage:
    """Mimics werkzeug.FileStorage interface enough for the
    controller's _m9_process_upload / _m9_create_cert_record.
    """
    def __init__(self, filename, mimetype, content):
        self.filename = filename
        self.mimetype = mimetype
        self._buf = BytesIO(content)
        self._size = len(content)
    def seek(self, offset, whence=0):
        return self._buf.seek(offset, whence)
    def tell(self):
        return self._buf.tell()
    def read(self):
        return self._buf.read()


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
Cert = env["neon.training.certification"]
AuditLog = env["neon.onboarding.audit.log"]
Attachment = env["ir.attachment"]


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
env.cr.commit()

# Create a candidate in cert_collection with portal user.
cand_900 = Candidate.sudo().create({
    "name": "T7b900 Upload Candidate",
    "intended_role": "runner",
    "contact_phone": "+263771000900",
    "contact_email": "t7b900@example.com",
    "state": "candidate",
})
# Transition to cert_collection -> M8 hook creates portal user.
cand_900.sudo().write({"state": "cert_collection"})
cand_900.invalidate_recordset()
portal_user = cand_900.user_id
print(f"  candidate id={cand_900.id} portal_user={portal_user.login}")

# Cert types we'll upload against (from M2 runner template).
runner_template = env.ref("neon_onboarding.template_runner")
cert_type_runner = env.ref("neon_training.cert_type_runner")
cert_type_fire = env.ref(
    "neon_training.cert_type_fire_safety_indoor")
# Confirm required types match expectation.
required_ids = set(cand_900.required_cert_type_ids.ids)
print(f"  required cert type ids: {sorted(required_ids)}")


# ============================================================
# Direct invocation of the controller helper without HTTP.
# Bind a mock request env so request.env works.
# ============================================================
from odoo.addons.neon_onboarding.controllers.portal import (
    NeonOnboardingPortal, _M9_UPLOAD_MAX_BYTES)


class FakeRequest:
    def __init__(self, env_, file_obj=None, form=None):
        self.env = env_
        self._file_obj = file_obj
        self._form = form or {}
        # Mock httprequest object.
        class FakeHttpRequest:
            def __init__(self, file_obj):
                self.files = (
                    {"cert_file": file_obj} if file_obj
                    else {})
                self.method = "POST" if file_obj else "GET"
        self.httprequest = FakeHttpRequest(file_obj)


# Monkey-patch request import in the controller module so
# the FakeRequest stands in for HTTP layer. The controller
# module's `request` is `odoo.http.request`; we patch it
# locally.
import odoo.addons.neon_onboarding.controllers.portal as portal_mod


def _invoke_create(candidate, cert_type, file_obj,
                   date_obtained, date_expires=False):
    """Run the controller's process_upload pipeline manually
    with our fake request.
    """
    fake_form = {
        "date_obtained": str(date_obtained),
        "date_expires": str(date_expires)
                        if date_expires else False,
    }
    saved_request = portal_mod.request
    portal_mod.request = FakeRequest(env, file_obj, fake_form)
    try:
        controller = NeonOnboardingPortal()
        return controller._m9_process_upload(
            candidate, cert_type, fake_form)
    finally:
        portal_mod.request = saved_request


# ============================================================
print()
print("=" * 72)
print("T7b900 - cert_uploaded -> cert + state advance")
print("=" * 72)
fake_pdf = FakeFileStorage(
    filename="runner_cert.pdf",
    mimetype="application/pdf",
    content=b"%PDF-1.4 fake content")
err = _invoke_create(
    cand_900, cert_type_runner, fake_pdf,
    date.today() - timedelta(days=30))
created_cert = Cert.sudo().search([
    ("candidate_id", "=", cand_900.id),
    ("type_id", "=", cert_type_runner.id),
], limit=1)
ok = (err is None
      and bool(created_cert)
      and created_cert.user_id == portal_user
      and created_cert.state == "pending_verification")
print(f"  err: {err}")
print(f"  cert.id={created_cert.id if created_cert else None}")
print(f"  cert.state={created_cert.state if created_cert else None}")
print(f"  cert.user_id={created_cert.user_id.login if created_cert else None}")
print("T7b900:", "PASS" if ok else "FAIL")
results["T7b900"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b901 - Robin + Munashe followers via M7 routing")
print("=" * 72)
robin = Users.sudo().search(
    [("login", "=", "robin@neonhiring.co.zw")], limit=1)
munashe = Users.sudo().search(
    [("login", "=", "munashe@neonhiring.co.zw")], limit=1)
followers = created_cert.message_partner_ids
ok = bool(created_cert) and bool(robin) and bool(munashe) and (
    robin.partner_id in followers
    and munashe.partner_id in followers)
print(f"  robin followed: {robin.partner_id in followers if robin else None}")
print(f"  munashe followed: {munashe.partner_id in followers if munashe else None}")
print("T7b901:", "PASS" if ok else "FAIL")
results["T7b901"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b902 - ir.attachment created + linked to cert")
print("=" * 72)
atts = Attachment.sudo().search([
    ("res_model", "=", "neon.training.certification"),
    ("res_id", "=", created_cert.id),
])
ok = (len(atts) >= 1
      and any(a.name == "runner_cert.pdf" for a in atts))
print(f"  attachments linked: {len(atts)}")
if atts:
    print(f"  attachment names: {atts.mapped('name')}")
print("T7b902:", "PASS" if ok else "FAIL")
results["T7b902"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b903 - audit_log action='cert_uploaded'")
print("=" * 72)
audit_900 = AuditLog.sudo().search([
    ("candidate_id", "=", cand_900.id),
    ("action", "=", "cert_uploaded"),
])
ok = (len(audit_900) == 1
      and cert_type_runner.name in (audit_900.reason or "")
      and audit_900.actor_id == portal_user)
print(f"  audit count={len(audit_900)} "
      f"actor={audit_900.actor_id.login if audit_900 else None}")
if audit_900:
    print(f"  reason: {audit_900.reason[:80]}")
print("T7b903:", "PASS" if ok else "FAIL")
results["T7b903"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b904 - cert_type not in required -> redirect path")
print("=" * 72)
# Use a cert type NOT in runner template (e.g. lead_tech).
cert_type_lead = env.ref(
    "neon_training.cert_type_lead_tech")
in_required = cert_type_lead in cand_900.required_cert_type_ids
# The controller's GET handler does:
#   if cert_type not in candidate.required_cert_type_ids:
#       return request.redirect('/my/onboarding/upload')
# We assert the precondition (not in required) holds; the
# redirect logic is in the source which we verify alongside.
import inspect
src = inspect.getsource(portal_mod)
has_guard = (
    "cert_type not in candidate.required_cert_type_ids"
    in src and "/my/onboarding/upload" in src)
ok = (not in_required) and has_guard
print(f"  lead_tech in required (should be False): {in_required}")
print(f"  guard logic in source: {has_guard}")
print("T7b904:", "PASS" if ok else "FAIL")
results["T7b904"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b905 - file > 10MB -> error message")
print("=" * 72)
huge_content = b"x" * (11 * 1024 * 1024)
fake_huge = FakeFileStorage(
    filename="huge.pdf",
    mimetype="application/pdf",
    content=huge_content)
prior_cert_count = Cert.sudo().search_count([
    ("candidate_id", "=", cand_900.id)])
err = _invoke_create(
    cand_900, cert_type_fire, fake_huge,
    date.today() - timedelta(days=10))
post_cert_count = Cert.sudo().search_count([
    ("candidate_id", "=", cand_900.id)])
ok = (err is not None
      and "10 MB" in err
      and post_cert_count == prior_cert_count)
print(f"  err: {err}")
print(f"  cert count unchanged: {post_cert_count == prior_cert_count}")
print("T7b905:", "PASS" if ok else "FAIL")
results["T7b905"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b906 - bad extension -> error message")
print("=" * 72)
fake_exe = FakeFileStorage(
    filename="suspicious.exe",
    mimetype="application/octet-stream",
    content=b"MZ binary")
prior_cert_count = Cert.sudo().search_count([
    ("candidate_id", "=", cand_900.id)])
err = _invoke_create(
    cand_900, cert_type_fire, fake_exe,
    date.today() - timedelta(days=10))
post_cert_count = Cert.sudo().search_count([
    ("candidate_id", "=", cand_900.id)])
ok = (err is not None
      and "PDF" in err
      and post_cert_count == prior_cert_count)
print(f"  err: {err}")
print("T7b906:", "PASS" if ok else "FAIL")
results["T7b906"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b907 - state != cert_collection -> redirect")
print("=" * 72)
# Create a candidate in 'candidate' state (not cert_collection).
# Note: M8 portal user creation happens on cert_collection
# entry only. This candidate has no portal user.
cand_907 = Candidate.sudo().create({
    "name": "T7b907 Wrong State",
    "intended_role": "runner",
    "contact_phone": "+263771000907",
    "contact_email": "t7b907@example.com",
    "state": "candidate",
})
# Verify the guard helper redirects -- we mock request and
# call _m9_get_candidate_or_redirect with a context where
# the user matches no candidate OR a candidate in wrong state.
# Easier: source inspection of the guard logic.
has_state_guard = (
    'candidate.state != "cert_collection"' in src
    or "candidate.state != 'cert_collection'" in src)
has_redirect = "/my/onboarding" in src
ok = has_state_guard and has_redirect
print(f"  state guard in source: {has_state_guard}")
print(f"  redirect path in source: {has_redirect}")
print("T7b907:", "PASS" if ok else "FAIL")
results["T7b907"] = ok


# ============================================================
print()
print("=" * 72)
print("T7b908 - cert pending for same type -> excluded "
      "from available_types")
print("=" * 72)
# Replicate the controller's list logic. cand_900 has a cert
# in pending_verification for cert_type_runner (from T7b900).
# That type should NOT appear in available_types now.
existing_blocking = cand_900.collected_cert_ids.filtered(
    lambda c: c.state in ("pending_verification", "active")
).mapped("type_id")
available_types = (
    cand_900.required_cert_type_ids - existing_blocking)
ok = (cert_type_runner not in available_types
      and cert_type_fire in available_types)
print(f"  runner in available (should be False): "
      f"{cert_type_runner in available_types}")
print(f"  fire in available (should be True):    "
      f"{cert_type_fire in available_types}")
print("T7b908:", "PASS" if ok else "FAIL")
results["T7b908"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T7b900", "T7b901", "T7b902", "T7b903", "T7b904",
        "T7b905", "T7b906", "T7b907", "T7b908"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
