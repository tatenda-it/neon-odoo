"""P7e.M12 smoke -- LMS notification stubs (7 tests)."""
from datetime import timedelta

from odoo import fields, SUPERUSER_ID


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

Enrollment = env["slide.channel.partner"]
TrackComp = env["neon.lms.track.completion"]
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


u_learner = _get_or_create_user(
    "p7e_m12_learner", "P7e M12 Learner",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

program = env.ref("neon_lms.program_channel")
foundations = env.ref("neon_lms.track_foundations_safety")
audio = env.ref("neon_lms.track_audio")
authority_electrical = env.ref(
    "neon_lms.authority_electrical")


def _has_notify_stub(messages, event):
    return messages.filtered(
        lambda m: ("Notification stub" in (m.body or "")
                   and event in (m.body or "")))


# ============================================================
print()
print("T7e1200 - _notify_track_certified fires on M8 "
      "sub-cert issuance")
print("=" * 72)
enroll = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_learner.partner_id.id,
})
tc = TrackComp.sudo().create({
    "enrollment_id": enroll.id,
    "track_id": foundations.id,
    "state": "completed",
})
# Trigger sub_cert issuance via M8 helper (foundations has
# sub_cert_type_id wired from M9).
tc._issue_sub_cert()
tc.invalidate_recordset()
enroll.invalidate_recordset()
notify_msgs = _has_notify_stub(
    enroll.partner_id.message_ids, "track_certified")
ok = (tc.state == "certified"
      and bool(tc.sub_cert_id)
      and len(notify_msgs) >= 1)
print(f"  track state: {tc.state}")
print(f"  sub_cert: {tc.sub_cert_id.id if tc.sub_cert_id else None}")
print(f"  notify messages: {len(notify_msgs)}")
print("T7e1200:", "PASS" if ok else "FAIL")
results["T7e1200"] = ok


# ============================================================
print()
print("T7e1201 - _notify_capstone_certified on capstone issue")
print("=" * 72)
# Build all 7 track completions certified for a fresh learner
# + trigger capstone check.
u_capstone = _get_or_create_user(
    "p7e_m12_capstone", "P7e M12 Capstone Learner",
    ["neon_jobs.group_neon_jobs_crew"])
enroll_cap = Enrollment.sudo().create({
    "channel_id": program.id,
    "partner_id": u_capstone.partner_id.id,
})
for trk in env["neon.lms.track"].search([]):
    TrackComp.sudo().create({
        "enrollment_id": enroll_cap.id,
        "track_id": trk.id,
        "state": "certified",
    })
enroll_cap._check_and_advance_to_certified()
enroll_cap.invalidate_recordset()
capstone_msgs = _has_notify_stub(
    enroll_cap.partner_id.message_ids, "capstone_certified")
ok = (enroll_cap.neon_state == "certified"
      and bool(enroll_cap.neon_capstone_cert_id)
      and len(capstone_msgs) >= 1)
print(f"  neon_state: {enroll_cap.neon_state}")
print(f"  capstone_cert: "
      f"{enroll_cap.neon_capstone_cert_id.id if enroll_cap.neon_capstone_cert_id else None}")
print(f"  notify messages: {len(capstone_msgs)}")
print("T7e1201:", "PASS" if ok else "FAIL")
results["T7e1201"] = ok


# ============================================================
print()
print("T7e1202 - _notify_authority_granted on track with "
      "operating_authority_ids")
print("=" * 72)
# Foundations track grants 6 authorities. T7e1200 fired
# _issue_sub_cert on enroll/foundations -- check that the
# authority notify fired for each.
authority_msgs = _has_notify_stub(
    enroll.partner_id.message_ids, "authority_granted")
ok = len(authority_msgs) >= 6  # Foundations grants 6 authorities
print(f"  authority notify messages: {len(authority_msgs)} "
      f"(expected >=6 for Foundations)")
print("T7e1202:", "PASS" if ok else "FAIL")
results["T7e1202"] = ok


# ============================================================
print()
print("T7e1203 - _notify_quiz_failed_max_attempts callable "
      "(placeholder)")
print("=" * 72)
m01 = env.ref("neon_lms.module_m01")
err, _r = _try(
    lambda: enroll._notify_quiz_failed_max_attempts(m01))
quiz_msgs = _has_notify_stub(
    enroll.partner_id.message_ids, "quiz_failed_max_attempts")
ok = err is None and len(quiz_msgs) >= 1
print(f"  err: {err}")
print(f"  quiz notify messages: {len(quiz_msgs)}")
print("T7e1203:", "PASS" if ok else "FAIL")
results["T7e1203"] = ok


# ============================================================
print()
print("T7e1204 - stub marker present in all messages")
print("=" * 72)
all_notify = enroll.partner_id.message_ids.filtered(
    lambda m: "Notification stub" in (m.body or ""))
ok = (len(all_notify) >= 2
      and all("Phase 9 will send" in (m.body or "")
              for m in all_notify))
print(f"  notify count: {len(all_notify)}")
print(f"  all have Phase 9 marker: "
      f"{all('Phase 9 will send' in (m.body or '') for m in all_notify)}")
print("T7e1204:", "PASS" if ok else "FAIL")
results["T7e1204"] = ok


# ============================================================
print()
print("T7e1205 - channels recorded in body (email + whatsapp "
      "default)")
print("=" * 72)
track_cert_msg = all_notify.filtered(
    lambda m: "track_certified" in (m.body or ""))[:1]
ok = bool(track_cert_msg) and (
    "email" in (track_cert_msg.body or "")
    and "whatsapp" in (track_cert_msg.body or ""))
print(f"  channels in body: "
      f"email={'email' in (track_cert_msg.body or '') if track_cert_msg else False} "
      f"whatsapp={'whatsapp' in (track_cert_msg.body or '') if track_cert_msg else False}")
print("T7e1205:", "PASS" if ok else "FAIL")
results["T7e1205"] = ok


# ============================================================
print()
print("T7e1206 - dispatcher uses sudo() in source (M12 lesson)")
print("=" * 72)
import inspect
from odoo.addons.neon_lms.models import neon_lms_enrollment
src = inspect.getsource(neon_lms_enrollment)
# Check that message_post is called with sudo() in the
# dispatcher (per Phase 7b M12 reference doc lesson).
src_compact = " ".join(src.split())
has_sudo_message = (
    "self.sudo().message_post(" in src
    or "sudo().message_post(" in src_compact)
ok = has_sudo_message
print(f"  sudo().message_post present: {has_sudo_message}")
print("T7e1206:", "PASS" if ok else "FAIL")
results["T7e1206"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e1200", "T7e1201", "T7e1202", "T7e1203",
         "T7e1204", "T7e1205", "T7e1206"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
