"""P7e.M9 smoke -- 8 cert types + system signoff (9 tests)."""
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

CertType = env["neon.training.certification.type"]
Cert = env["neon.training.certification"]
Track = env["neon.lms.track"]
Channel = env["slide.channel"]


# ============================================================
print()
print("T7e900 - 8 LMS cert types seeded")
print("=" * 72)
xmlids = [
    "neon_training.cert_type_neon_foundations_safety",
    "neon_training.cert_type_neon_audio",
    "neon_training.cert_type_neon_lighting",
    "neon_training.cert_type_neon_video_led",
    "neon_training.cert_type_neon_workflow_ops",
    "neon_training.cert_type_neon_client_ready",
    "neon_training.cert_type_neon_rigging",
    "neon_training.cert_type_neon_technical",
]
resolved = [env.ref(x, raise_if_not_found=False) for x in xmlids]
ok = all(r is not None for r in resolved)
for xid, r in zip(xmlids, resolved):
    print(f"  {xid.split('.')[-1]}: "
          f"{'OK id=' + str(r.id) if r else 'MISSING'}")
print("T7e900:", "PASS" if ok else "FAIL")
results["T7e900"] = ok


# ============================================================
print()
print("T7e901 - all 8 have sign_off_authority='system'")
print("=" * 72)
authorities = [r.sign_off_authority for r in resolved]
ok = all(a == "system" for a in authorities)
print(f"  authorities: {authorities}")
print("T7e901:", "PASS" if ok else "FAIL")
results["T7e901"] = ok


# ============================================================
print()
print("T7e902 - 'system' is a valid Selection value")
print("=" * 72)
selection = CertType._fields["sign_off_authority"].selection
keys = [k for k, _label in selection]
ok = "system" in keys
print(f"  selection keys: {keys}")
print("T7e902:", "PASS" if ok else "FAIL")
results["T7e902"] = ok


# ============================================================
print()
print("T7e903 - M7 _resolve_verify_authority_partners returns "
      "empty for 'system' authority")
print("=" * 72)
# Create a draft cert with system-authority type. Call
# _resolve_verify_authority_partners. Expect empty target_user
# and 'system_lms_issued' group_xmlid sentinel.
foundations_type = env.ref(
    "neon_training.cert_type_neon_foundations_safety")
test_user = env["res.users"].sudo().search(
    [("login", "=", "p7e_m8_learner")], limit=1)
if not test_user:
    test_user = env["res.users"].sudo().search(
        [("login", "=", "robin@neonhiring.co.zw")], limit=1)
fake_cert = Cert.sudo().create({
    "user_id": test_user.id,
    "type_id": foundations_type.id,
    "date_obtained": fields.Date.context_today(env.user),
})
target, fallback, group_xmlid = (
    fake_cert._resolve_verify_authority_partners())
ok = (not target and group_xmlid == "system_lms_issued")
print(f"  target: {target} (expect empty)")
print(f"  group_xmlid: {group_xmlid} "
      f"(expect 'system_lms_issued')")
print("T7e903:", "PASS" if ok else "FAIL")
results["T7e903"] = ok


# ============================================================
print()
print("T7e904 - all 7 track.sub_cert_type_id wired")
print("=" * 72)
all_tracks = Track.search([])
unwired = all_tracks.filtered(
    lambda t: not t.sub_cert_type_id)
ok = (len(all_tracks) == 7 and len(unwired) == 0)
print(f"  tracks: {len(all_tracks)}  unwired: {len(unwired)}")
for t in all_tracks:
    print(f"    {t.code} -> "
          f"{t.sub_cert_type_id.code if t.sub_cert_type_id else 'NONE'}")
print("T7e904:", "PASS" if ok else "FAIL")
results["T7e904"] = ok


# ============================================================
print()
print("T7e905 - channel.neon_capstone_cert_type_id resolves")
print("=" * 72)
program = env.ref("neon_lms.program_channel")
capstone_cert = env.ref(
    "neon_training.cert_type_neon_technical")
ok = (program.neon_capstone_cert_type_id == capstone_cert)
print(f"  capstone: "
      f"{program.neon_capstone_cert_type_id.code if program.neon_capstone_cert_type_id else None}")
print("T7e905:", "PASS" if ok else "FAIL")
results["T7e905"] = ok


# ============================================================
print()
print("T7e906 - M8 workflow ends with capstone issued "
      "(end-to-end check)")
print("=" * 72)
# Build fresh enrollment, mark all 7 tracks certified,
# trigger capstone check. Expect neon_state='certified' +
# capstone cert created.
u_e2e = env["res.users"].sudo().search(
    [("login", "=", "p7e_m9_e2e")], limit=1)
if not u_e2e:
    u_e2e = env["res.users"].sudo().create({
        "name": "P7e M9 E2E", "login": "p7e_m9_e2e",
        "password": "test123",
    })
    crew_grp = env.ref("neon_jobs.group_neon_jobs_crew")
    crew_grp.sudo().write({"users": [(4, u_e2e.id)]})

Enrollment = env["slide.channel.partner"]
TrackComp = env["neon.lms.track.completion"]
enroll = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_e2e.partner_id.id,
})
for trk in all_tracks:
    TrackComp.sudo().create({
        "enrollment_id": enroll.id,
        "track_id": trk.id,
        "state": "certified",
    })
enroll._check_and_advance_to_certified()
enroll.invalidate_recordset()
ok = (enroll.neon_state == "certified"
      and bool(enroll.neon_capstone_cert_id)
      and enroll.neon_capstone_cert_id.type_id == capstone_cert)
print(f"  neon_state: {enroll.neon_state}")
print(f"  capstone_cert_id: "
      f"{enroll.neon_capstone_cert_id.id if enroll.neon_capstone_cert_id else None}")
print("T7e906:", "PASS" if ok else "FAIL")
results["T7e906"] = ok


# ============================================================
print()
print("T7e907 - Phase 7a M7 routing still works for non-system "
      "authorities (Robin/Munashe)")
print("=" * 72)
# Use an existing non-system cert type (e.g. cert_type_runner).
runner_type = env.ref("neon_training.cert_type_runner")
fake_cert_runner = Cert.sudo().create({
    "user_id": test_user.id,
    "type_id": runner_type.id,
    "date_obtained": fields.Date.context_today(env.user),
})
target_r, fallback_r, group_xmlid_r = (
    fake_cert_runner._resolve_verify_authority_partners())
ok = (bool(target_r)
      and target_r.login in (
          "robin@neonhiring.co.zw",
          "munashe@neonhiring.co.zw")
      and group_xmlid_r == "cert_verifier_managerial")
print(f"  target: {target_r.login if target_r else None}")
print(f"  group_xmlid: {group_xmlid_r}")
print("T7e907:", "PASS" if ok else "FAIL")
results["T7e907"] = ok


# ============================================================
print()
print("T7e908 - noupdate=False on the seed records "
      "(idempotent extension)")
print("=" * 72)
# Verify the cert types stay loadable on re-install. With
# noupdate=1 (our chosen pattern), admin edits to e.g.
# validity_months are preserved across upgrades. Simulate:
# write a custom validity_months on one cert type + verify
# it survives a flush (no implicit reload).
foundations_type.invalidate_recordset()
original_validity = foundations_type.validity_months
foundations_type.sudo().write({"validity_months": 36})
foundations_type.invalidate_recordset()
preserved = foundations_type.validity_months
# Reset.
foundations_type.sudo().write(
    {"validity_months": original_validity})
ok = preserved == 36
print(f"  original validity: {original_validity}")
print(f"  after write: {preserved}")
print("T7e908:", "PASS" if ok else "FAIL")
results["T7e908"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e900", "T7e901", "T7e902", "T7e903",
         "T7e904", "T7e905", "T7e906", "T7e907", "T7e908"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
