"""P7a.M2 smoke -- neon.training.certification record + state machine (34 tests).

T7200 model installs (sanity)
T7201 default state is 'draft'
T7202 date_expires computed from date_obtained + validity_months
T7203 date_expires empty when validity_months = 0
T7204 category_id rolls up from type_id
T7205 action_submit_for_verification: draft -> pending_verification
T7206 action_verify by signoff: pending_verification -> active + verified flags
T7207 action_verify by signoff: draft -> active (one-step path)
T7208 action_suspend by admin requires reason
T7209 action_suspend by admin: active -> suspended + reason captured
T7210 action_reactivate by admin: suspended -> active + reason cleared
T7211 action_mark_expired by signoff: active -> expired
T7212 training_user CANNOT verify (signoff guard fires)
T7213 training_user CANNOT suspend (admin guard fires)
T7214 training_signoff CANNOT suspend (admin guard fires)
T7215 unique active per (user, type) enforced
T7216 unique constraint allows multiple non-active rows
T7217 date_obtained cannot be in the future
T7218 level outside skill_level_mode rejected (binary type, tiered level)
T7219 level inside skill_level_mode accepted (binary type, pass level)
T7220 external_trainer required when category.requires_external_trainer
T7221 external_trainer ok when signed_off_by_id is set instead
T7222 onchange type_id clears stale level
T7223 mail.thread wired (state transition recorded in chatter)
T7224 NO perm_unlink as training_admin (audit-trail)
T7225 NO perm_unlink as training_signoff
T7226 NO perm_unlink as training_user
T7227 ir.rule: training_user sees only own certs
T7228 ir.rule: training_signoff sees all certs
T7229 ir.rule: training_admin sees all certs
T7230 training_user can create OWN cert
T7231 training_user CANNOT create cert for another user (ir.rule blocks)
T7232 res.users.active_certifications_count computes correctly
T7233 res.users.expiring_soon_count computes for 90-day horizon
"""
from datetime import date, datetime, timedelta

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

Cert = env["neon.training.certification"]
Category = env["neon.training.certification.category"]
CertType = env["neon.training.certification.type"]
Users = env["res.users"]

# Reuse the P7a.M1 group bindings for fixture users -- new fixtures
# tagged p7am2_ to keep cycle hygiene with the M1 set.
g_train_user = env.ref("neon_training.group_neon_training_user")
g_train_signoff = env.ref("neon_training.group_neon_training_signoff")
g_train_admin = env.ref("neon_training.group_neon_training_admin")
internal = env.ref("base.group_user")


def _get_or_create(login, *groups):
    user = Users.sudo().search([("login", "=", login)], limit=1)
    gids = [internal.id] + [g.id for g in groups]
    email = f"{login}@neon.local"  # mail.thread requires author email
    if not user:
        user = Users.sudo().create({
            "name": login,
            "login": login,
            "email": email,
            "password": "test123",
            "groups_id": [(6, 0, gids)],
        })
    else:
        user.sudo().write({
            "email": email,
            "groups_id": [(6, 0, gids)],
        })
    return user


u_user = _get_or_create("p7am2_train_user", g_train_user)
u_signoff = _get_or_create("p7am2_train_signoff", g_train_signoff)
u_admin = _get_or_create("p7am2_train_admin", g_train_admin)
# Subject is another crew member -- has training_user (every employee
# with an Odoo login gets training_user per H1/H2 framing); u_user
# cannot create certs for them (ir.rule + method-level check).
u_subject = _get_or_create("p7am2_subject", g_train_user)

# Commit fixtures so they persist for browser smoke (same pattern
# as p7a_m1_smoke).
env.cr.commit()
print("  fixture user ids (committed):",
      u_user.id, u_signoff.id, u_admin.id, u_subject.id)


# Seed types we'll reuse across tests
ma3 = env.ref("neon_training.cert_type_ma3_console")          # equipment, tiered_3
first_aid = env.ref("neon_training.cert_type_first_aid")      # safety, binary, external
work_heights = env.ref("neon_training.cert_type_work_at_heights")  # safety, binary, external, 24mo
lead_tech = env.ref("neon_training.cert_type_lead_tech")      # role, custom
english = env.ref("neon_training.cert_type_lang_english")     # soft, binary


# ============================================================
print()
print("=" * 72)
print("T7200 - model installed")
print("=" * 72)
ok = "neon.training.certification" in env.registry
print("  registry has model:", ok)
print("T7200:", "PASS" if ok else "FAIL")
results["T7200"] = ok


# ============================================================
print()
print("=" * 72)
print("T7201 - default state is draft")
print("=" * 72)
c_t7201 = Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=30),
})
ok = c_t7201.state == "draft"
print("  state:", c_t7201.state)
print("T7201:", "PASS" if ok else "FAIL")
results["T7201"] = ok


# ============================================================
print()
print("=" * 72)
print("T7202 - date_expires = date_obtained + validity_months")
print("=" * 72)
# Use first_aid (24 month validity)
c_t7202 = Cert.create({
    "user_id": u_subject.id,
    "type_id": first_aid.id,
    "date_obtained": date(2026, 1, 15),
    "signed_off_by_id": u_signoff.id,  # satisfy external trainer constraint
})
expected = date(2028, 1, 15)
ok = c_t7202.date_expires == expected
print("  date_obtained:", c_t7202.date_obtained,
      "validity:", first_aid.validity_months,
      "date_expires:", c_t7202.date_expires,
      "expected:", expected)
print("T7202:", "PASS" if ok else "FAIL")
results["T7202"] = ok


# ============================================================
print()
print("=" * 72)
print("T7203 - date_expires empty when validity_months = 0")
print("=" * 72)
# MA3 has validity_months = 0 (or not set -> 0)
c_t7203 = Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date(2026, 1, 15),
})
ok = ma3.validity_months == 0 and not c_t7203.date_expires
print("  validity_months:", ma3.validity_months,
      "date_expires:", c_t7203.date_expires)
print("T7203:", "PASS" if ok else "FAIL")
results["T7203"] = ok


# ============================================================
print()
print("=" * 72)
print("T7204 - category_id rolls up from type_id")
print("=" * 72)
ok = c_t7203.category_id == ma3.category_id
print("  cert.category_id:", c_t7203.category_id.name,
      "type.category_id:", ma3.category_id.name)
print("T7204:", "PASS" if ok else "FAIL")
results["T7204"] = ok


# ============================================================
print()
print("=" * 72)
print("T7205 - action_submit_for_verification: draft -> pending")
print("=" * 72)
c_t7205 = Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=5),
})
# Action methods are user-aware; default smoke runs as superuser
# which does not carry the training_signoff group. Submit via the
# record's owner to exercise the self-upload path.
c_t7205.with_user(u_subject).action_submit_for_verification()
c_t7205.invalidate_recordset()
ok = c_t7205.state == "pending_verification"
print("  state after submit:", c_t7205.state)
print("T7205:", "PASS" if ok else "FAIL")
results["T7205"] = ok


# ============================================================
print()
print("=" * 72)
print("T7206 - action_verify by signoff: pending -> active + flags")
print("=" * 72)
c_t7205.with_user(u_signoff).action_verify()
c_t7205.invalidate_recordset()
ok = (c_t7205.state == "active"
      and c_t7205.verified is True
      and c_t7205.verified_by_id == u_signoff
      and c_t7205.verified_at is not False)
print("  state:", c_t7205.state,
      "verified:", c_t7205.verified,
      "verified_by:", c_t7205.verified_by_id.login,
      "verified_at:", c_t7205.verified_at)
print("T7206:", "PASS" if ok else "FAIL")
results["T7206"] = ok


# ============================================================
print()
print("=" * 72)
print("T7207 - action_verify by signoff: draft -> active (one-step)")
print("=" * 72)
c_t7207 = Cert.create({
    "user_id": u_subject.id,
    "type_id": lead_tech.id,
    "date_obtained": date.today() - timedelta(days=10),
    "level": "lead_tech",
})
c_t7207.with_user(u_signoff).action_verify()
c_t7207.invalidate_recordset()
ok = (c_t7207.state == "active"
      and c_t7207.verified is True)
print("  state:", c_t7207.state, "verified:", c_t7207.verified)
print("T7207:", "PASS" if ok else "FAIL")
results["T7207"] = ok


# ============================================================
print()
print("=" * 72)
print("T7208 - action_suspend by admin requires reason")
print("=" * 72)
err, _r = _try(lambda: c_t7205.with_user(u_admin).action_suspend())
ok = isinstance(err, UserError)
print("  error class:", type(err).__name__ if err else None)
print("T7208:", "PASS" if ok else "FAIL")
results["T7208"] = ok


# ============================================================
print()
print("=" * 72)
print("T7209 - action_suspend by admin: active -> suspended + reason")
print("=" * 72)
c_t7205.with_user(u_admin).with_context(
    suspension_reason="Course discovered to be fraudulent."
).action_suspend()
c_t7205.invalidate_recordset()
ok = (c_t7205.state == "suspended"
      and "fraudulent" in (c_t7205.suspension_reason or ""))
print("  state:", c_t7205.state,
      "reason:", c_t7205.suspension_reason)
print("T7209:", "PASS" if ok else "FAIL")
results["T7209"] = ok


# ============================================================
print()
print("=" * 72)
print("T7210 - action_reactivate by admin: suspended -> active")
print("=" * 72)
c_t7205.with_user(u_admin).action_reactivate()
c_t7205.invalidate_recordset()
ok = (c_t7205.state == "active"
      and not c_t7205.suspension_reason)
print("  state:", c_t7205.state,
      "reason cleared:", not c_t7205.suspension_reason)
print("T7210:", "PASS" if ok else "FAIL")
results["T7210"] = ok


# ============================================================
print()
print("=" * 72)
print("T7211 - action_mark_expired by signoff: active -> expired")
print("=" * 72)
c_t7205.with_user(u_signoff).action_mark_expired()
c_t7205.invalidate_recordset()
ok = c_t7205.state == "expired"
print("  state:", c_t7205.state)
print("T7211:", "PASS" if ok else "FAIL")
results["T7211"] = ok


# ============================================================
print()
print("=" * 72)
print("T7212 - training_user CANNOT verify")
print("=" * 72)
c_t7212 = Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=2),
})
err, _r = _try(lambda: c_t7212.with_user(u_user).action_verify())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7212:", "PASS" if ok else "FAIL")
results["T7212"] = ok


# ============================================================
print()
print("=" * 72)
print("T7213 - training_user CANNOT suspend")
print("=" * 72)
c_t7212.with_user(u_signoff).action_verify()  # promote to active
err, _r = _try(lambda: c_t7212.with_user(u_user).with_context(
    suspension_reason="test").action_suspend())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7213:", "PASS" if ok else "FAIL")
results["T7213"] = ok


# ============================================================
print()
print("=" * 72)
print("T7214 - training_signoff CANNOT suspend")
print("=" * 72)
err, _r = _try(lambda: c_t7212.with_user(u_signoff).with_context(
    suspension_reason="test").action_suspend())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7214:", "PASS" if ok else "FAIL")
results["T7214"] = ok


# ============================================================
print()
print("=" * 72)
print("T7215 - unique active per (user, type)")
print("=" * 72)
# c_t7212 is already active MA3 for u_subject. Try creating another
# MA3 for the same user with verify directly (state=active triggers
# the constraint).
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=1),
    "state": "active",
    "verified": True,
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7215:", "PASS" if ok else "FAIL")
results["T7215"] = ok


# ============================================================
print()
print("=" * 72)
print("T7216 - allow multiple non-active rows per (user, type)")
print("=" * 72)
# Two drafts of MA3 for u_subject should be allowed even though
# active MA3 exists.
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=2),
    # state remains draft (default)
}))
ok = err is None
print("  draft allowed alongside active:", ok)
print("T7216:", "PASS" if ok else "FAIL")
results["T7216"] = ok


# ============================================================
print()
print("=" * 72)
print("T7217 - date_obtained cannot be in the future")
print("=" * 72)
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() + timedelta(days=7),
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7217:", "PASS" if ok else "FAIL")
results["T7217"] = ok


# ============================================================
print()
print("=" * 72)
print("T7218 - level outside skill_level_mode rejected")
print("=" * 72)
# english is binary; reject 'standard' (tiered) on it.
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": english.id,
    "date_obtained": date.today() - timedelta(days=1),
    "level": "standard",
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7218:", "PASS" if ok else "FAIL")
results["T7218"] = ok


# ============================================================
print()
print("=" * 72)
print("T7219 - level inside skill_level_mode accepted")
print("=" * 72)
err, c_t7219 = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": english.id,
    "date_obtained": date.today() - timedelta(days=1),
    "level": "pass",
}))
ok = err is None and c_t7219.level == "pass"
print("  ok:", ok, "level:", c_t7219.level if c_t7219 else None)
print("T7219:", "PASS" if ok else "FAIL")
results["T7219"] = ok


# ============================================================
print()
print("=" * 72)
print("T7220 - external_trainer required for safety category")
print("=" * 72)
# work_heights -- safety category, requires_external_trainer=True
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": work_heights.id,
    "date_obtained": date.today() - timedelta(days=1),
    "state": "pending_verification",  # leaves draft
    # no external_trainer_name + no signed_off_by_id => violation
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7220:", "PASS" if ok else "FAIL")
results["T7220"] = ok


# ============================================================
print()
print("=" * 72)
print("T7221 - external_trainer satisfied via signed_off_by_id")
print("=" * 72)
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": work_heights.id,
    "date_obtained": date.today() - timedelta(days=1),
    "state": "pending_verification",
    "signed_off_by_id": u_signoff.id,
}))
ok = err is None
print("  ok:", ok)
print("T7221:", "PASS" if ok else "FAIL")
results["T7221"] = ok


# ============================================================
print()
print("=" * 72)
print("T7222 - onchange type_id clears stale level")
print("=" * 72)
# Build via NewId so onchange fires (proper API: env['model'].new())
new_record = Cert.new({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "level": "standard",
})
# Switch the type to english (binary) and call onchange.
new_record.type_id = english
new_record._onchange_type_id()
ok = not new_record.level
print("  level after type switch:", new_record.level)
print("T7222:", "PASS" if ok else "FAIL")
results["T7222"] = ok


# ============================================================
print()
print("=" * 72)
print("T7223 - mail.thread records state transition in chatter")
print("=" * 72)
# c_t7212 (MA3 active) -- mark expired and check message_ids grows.
prev_count = len(c_t7212.message_ids)
c_t7212.with_user(u_signoff).action_mark_expired()
c_t7212.invalidate_recordset()
new_count = len(c_t7212.message_ids)
ok = new_count > prev_count
print("  messages before:", prev_count,
      "after:", new_count)
print("T7223:", "PASS" if ok else "FAIL")
results["T7223"] = ok


# ============================================================
print()
print("=" * 72)
print("T7224 - training_admin CANNOT unlink (perm_unlink=0)")
print("=" * 72)
err, _r = _try(lambda: c_t7203.with_user(u_admin).unlink())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7224:", "PASS" if ok else "FAIL")
results["T7224"] = ok


# ============================================================
print()
print("=" * 72)
print("T7225 - training_signoff CANNOT unlink")
print("=" * 72)
err, _r = _try(lambda: c_t7203.with_user(u_signoff).unlink())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7225:", "PASS" if ok else "FAIL")
results["T7225"] = ok


# ============================================================
print()
print("=" * 72)
print("T7226 - training_user CANNOT unlink")
print("=" * 72)
# u_user is not the owner; need to use a cert owned by u_user.
c_t7226_owned = Cert.with_user(u_user).create({
    "user_id": u_user.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=1),
})
err, _r = _try(lambda: c_t7226_owned.with_user(u_user).unlink())
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7226:", "PASS" if ok else "FAIL")
results["T7226"] = ok


# ============================================================
print()
print("=" * 72)
print("T7227 - ir.rule: training_user sees only own certs")
print("=" * 72)
# u_user already has c_t7226_owned (own). Should NOT see u_subject's
# certs. Search as u_user and verify only own ids returned.
seen_ids = Cert.with_user(u_user).search([]).ids
ok = (c_t7226_owned.id in seen_ids
      and c_t7212.id not in seen_ids)
print("  u_user sees own (", c_t7226_owned.id, "):",
      c_t7226_owned.id in seen_ids,
      "; not subject's (", c_t7212.id, "):",
      c_t7212.id not in seen_ids)
print("T7227:", "PASS" if ok else "FAIL")
results["T7227"] = ok


# ============================================================
print()
print("=" * 72)
print("T7228 - ir.rule: training_signoff sees all certs")
print("=" * 72)
seen_ids = Cert.with_user(u_signoff).search([]).ids
ok = (c_t7226_owned.id in seen_ids
      and c_t7212.id in seen_ids)
print("  signoff sees u_user's:", c_t7226_owned.id in seen_ids,
      "; subject's:", c_t7212.id in seen_ids)
print("T7228:", "PASS" if ok else "FAIL")
results["T7228"] = ok


# ============================================================
print()
print("=" * 72)
print("T7229 - ir.rule: training_admin sees all certs")
print("=" * 72)
seen_ids = Cert.with_user(u_admin).search([]).ids
ok = (c_t7226_owned.id in seen_ids
      and c_t7212.id in seen_ids)
print("  admin sees u_user's:", c_t7226_owned.id in seen_ids,
      "; subject's:", c_t7212.id in seen_ids)
print("T7229:", "PASS" if ok else "FAIL")
results["T7229"] = ok


# ============================================================
print()
print("=" * 72)
print("T7230 - training_user can create OWN cert")
print("=" * 72)
err, c_t7230 = _try(lambda: Cert.with_user(u_user).create({
    "user_id": u_user.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=1),
}))
ok = err is None and c_t7230 and c_t7230.user_id == u_user
print("  err:", type(err).__name__ if err else None,
      "user_id:", c_t7230.user_id.login if c_t7230 else None)
print("T7230:", "PASS" if ok else "FAIL")
results["T7230"] = ok


# ============================================================
print()
print("=" * 72)
print("T7231 - training_user CANNOT create cert for ANOTHER user")
print("=" * 72)
err, _r = _try(lambda: Cert.with_user(u_user).create({
    "user_id": u_subject.id,  # not self
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=1),
}))
ok = isinstance(err, AccessError)
print("  error class:", type(err).__name__ if err else None)
print("T7231:", "PASS" if ok else "FAIL")
results["T7231"] = ok


# ============================================================
print()
print("=" * 72)
print("T7232 - res.users.active_certifications_count computes")
print("=" * 72)
u_subject.invalidate_recordset()
count = u_subject.active_certifications_count
# We've activated: c_t7207 (lead_tech active), and several MA3 rows
# in various states. Check at least 1 active.
ok = count >= 1
print("  active_certifications_count for u_subject:", count)
print("T7232:", "PASS" if ok else "FAIL")
results["T7232"] = ok


# ============================================================
print()
print("=" * 72)
print("T7233 - res.users.expiring_soon_count computes for 90d horizon")
print("=" * 72)
# Set up a cert whose expiry falls within 90 days from today.
soon = date.today() - timedelta(days=600)  # 600 days ago
# first_aid is 24 months = ~730 days. 730 - 600 = 130 days remaining
# So pick a date_obtained that puts expiry inside the 90-day horizon.
soon = date.today() - timedelta(days=720)  # 720d ago + 24mo ~= 10d out
expiring_cert = Cert.create({
    "user_id": u_subject.id,
    "type_id": first_aid.id,
    "date_obtained": soon,
    "signed_off_by_id": u_signoff.id,
})
expiring_cert.with_user(u_signoff).action_verify()
u_subject.invalidate_recordset()
count = u_subject.expiring_soon_count
ok = count >= 1
print("  expiring_soon_count for u_subject:", count,
      "(cert expires:", expiring_cert.date_expires, ")")
print("T7233:", "PASS" if ok else "FAIL")
results["T7233"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7200, 7234)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
