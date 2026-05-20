"""P7a.M1 smoke -- neon_training certification category + type (24 tests).

T7100 4 categories seeded with expected codes
T7101 Equipment category has tiered_3 skill mode + no expiry
T7102 Role category has custom skill mode + no expiry
T7103 Safety category has binary mode + requires_external_trainer + 24-month default
T7104 Soft Skill category has binary mode + audit_track False
T7105 22 certification types seeded total
T7106 Equipment category has 6 types
T7107 Role Tier category has 4 types
T7108 Safety category has 5 types
T7109 Soft Skill category has 7 types
T7110 category code uniqueness enforced (UNIQUE SQL constraint)
T7111 (category, code) tuple uniqueness on type enforced
T7112 category code regex rejects uppercase
T7113 type code regex rejects hyphens
T7114 effective_skill_level_mode falls back to category when type override is null
T7115 effective_skill_level_mode uses type override when set
T7116 training_user can READ category but not CREATE
T7117 training_user can READ type but not CREATE
T7118 training_signoff can CREATE type but NOT category
T7119 training_admin can CREATE both category and type
T7120 training_admin CANNOT unlink category (perm_unlink=0)
T7121 training_admin CANNOT unlink type (perm_unlink=0)
T7122 mail.thread is wired -- message_post works on category
T7123 mail.thread is wired -- message_post works on type
"""
from psycopg2 import IntegrityError

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

Category = env["neon.training.certification.category"]
CertType = env["neon.training.certification.type"]

# Get-or-create test fixture users for the three training groups.
# Pattern matches p2m75_* persistence: stable user_ids across regression
# cycles, baked password=test123, baseline groups_id re-asserted in setUp.
g_train_user = env.ref("neon_training.group_neon_training_user")
g_train_signoff = env.ref("neon_training.group_neon_training_signoff")
g_train_admin = env.ref("neon_training.group_neon_training_admin")
internal = env.ref("base.group_user")


def _get_or_create(login, group):
    user = env["res.users"].sudo().search([("login", "=", login)], limit=1)
    if not user:
        user = env["res.users"].sudo().create({
            "name": login,
            "login": login,
            "password": "test123",
            "groups_id": [(6, 0, [internal.id, group.id])],
        })
    else:
        user.sudo().write({
            "groups_id": [(6, 0, [internal.id, group.id])],
        })
    return user


u_train_user = _get_or_create("p7am1_train_user", g_train_user)
u_train_signoff = _get_or_create("p7am1_train_signoff", g_train_signoff)
u_train_admin = _get_or_create("p7am1_train_admin", g_train_admin)

# Commit the fixture users so they persist across regression cycles
# (browser smoke needs to log them in over HTTP). The final
# env.cr.rollback() at the bottom of this script only undoes work
# performed AFTER this commit -- test artifacts (admin_created cat,
# fallback_probe type, etc.) get cleaned, users + group bindings
# stay. Same intent as the persistent p2m75_* fixtures shared by
# Phase 6 smokes.
env.cr.commit()
print("  fixture user ids (committed):",
      u_train_user.id, u_train_signoff.id, u_train_admin.id)

cat_equipment = env.ref("neon_training.cert_category_equipment")
cat_role = env.ref("neon_training.cert_category_role")
cat_safety = env.ref("neon_training.cert_category_safety")
cat_soft = env.ref("neon_training.cert_category_soft")


# ============================================================
print()
print("=" * 72)
print("T7100 - 4 categories seeded with expected codes")
print("=" * 72)
all_cats = Category.search([])
codes = sorted(all_cats.mapped("code"))
expected = ["equipment", "role", "safety", "soft"]
ok = codes == expected
print("  codes:", codes)
print("T7100:", "PASS" if ok else "FAIL")
results["T7100"] = ok


# ============================================================
print()
print("=" * 72)
print("T7101 - Equipment category: tiered_3, no expiry")
print("=" * 72)
ok = (cat_equipment.skill_level_mode == "tiered_3"
      and cat_equipment.expiry_required is False
      and cat_equipment.audit_track is True)
print("  skill_level_mode:", cat_equipment.skill_level_mode,
      "expiry:", cat_equipment.expiry_required,
      "audit:", cat_equipment.audit_track)
print("T7101:", "PASS" if ok else "FAIL")
results["T7101"] = ok


# ============================================================
print()
print("=" * 72)
print("T7102 - Role category: custom skill mode, no expiry")
print("=" * 72)
ok = (cat_role.skill_level_mode == "custom"
      and cat_role.expiry_required is False)
print("  skill_level_mode:", cat_role.skill_level_mode,
      "expiry:", cat_role.expiry_required)
print("T7102:", "PASS" if ok else "FAIL")
results["T7102"] = ok


# ============================================================
print()
print("=" * 72)
print("T7103 - Safety category: binary + external trainer + 24mo default")
print("=" * 72)
ok = (cat_safety.skill_level_mode == "binary"
      and cat_safety.requires_external_trainer is True
      and cat_safety.expiry_required is True
      and cat_safety.default_validity_months == 24)
print("  binary:", cat_safety.skill_level_mode == "binary",
      "external:", cat_safety.requires_external_trainer,
      "expiry:", cat_safety.expiry_required,
      "validity:", cat_safety.default_validity_months)
print("T7103:", "PASS" if ok else "FAIL")
results["T7103"] = ok


# ============================================================
print()
print("=" * 72)
print("T7104 - Soft Skill category: binary mode, audit_track False")
print("=" * 72)
ok = (cat_soft.skill_level_mode == "binary"
      and cat_soft.audit_track is False
      and cat_soft.expiry_required is False)
print("  binary:", cat_soft.skill_level_mode == "binary",
      "audit:", cat_soft.audit_track,
      "expiry:", cat_soft.expiry_required)
print("T7104:", "PASS" if ok else "FAIL")
results["T7104"] = ok


# ============================================================
# T7105-T7109: M1 seed inventory frozen at xmlid level. Total
# count is growth-tolerant (>=) since future milestones legitimately
# extend the seed (M3 adds 10; later milestones may add more).
# Structural assertion (each xmlid resolves) catches "did a seed
# record disappear" drift cleanly.
# Pattern locked here per Phase 11 polish item (CLAUDE.md amendment
# pending): smoke count assertions default to >= + structural codes.
# ============================================================
M1_TYPE_XMLIDS = {
    "equipment": [
        "neon_training.cert_type_ma3_console",
        "neon_training.cert_type_digico_q5",
        "neon_training.cert_type_chamsys_magicq",
        "neon_training.cert_type_avolites_tiger_touch",
        "neon_training.cert_type_led_wall_absen",
        "neon_training.cert_type_truss_climbing_trilite",
    ],
    "role": [
        "neon_training.cert_type_lead_tech",
        "neon_training.cert_type_tech",
        "neon_training.cert_type_runner",
        "neon_training.cert_type_driver",
    ],
    "safety": [
        "neon_training.cert_type_first_aid",
        "neon_training.cert_type_work_at_heights",
        "neon_training.cert_type_electrical_live_mains",
        "neon_training.cert_type_fire_safety_indoor",
        "neon_training.cert_type_class_4_driver",
    ],
    "soft": [
        "neon_training.cert_type_lang_english",
        "neon_training.cert_type_lang_shona",
        "neon_training.cert_type_lang_ndebele",
        "neon_training.cert_type_mc_presentation",
        "neon_training.cert_type_computer_literacy",
        "neon_training.cert_type_heavy_lift",
        "neon_training.cert_type_venue_knowledge_harare",
    ],
}
M1_TOTAL = sum(len(v) for v in M1_TYPE_XMLIDS.values())  # 22


print()
print("=" * 72)
print("T7105 - >= 22 certification types AND all 22 M1 xmlids resolve")
print("=" * 72)
all_types = CertType.search([])
missing_xmlids = []
for xmlids in M1_TYPE_XMLIDS.values():
    for xid in xmlids:
        try:
            env.ref(xid)
        except ValueError:
            missing_xmlids.append(xid)
ok = len(all_types) >= M1_TOTAL and not missing_xmlids
print("  total types:", len(all_types), "(M1 baseline:", M1_TOTAL, ")")
print("  M1 xmlids missing:", missing_xmlids or "(none)")
print("T7105:", "PASS" if ok else "FAIL")
results["T7105"] = ok


# ============================================================
print()
print("=" * 72)
print("T7106 - Equipment category: >= 6 types AND M1 6 xmlids present")
print("=" * 72)
m1_codes = [x.rsplit(".", 1)[1].replace("cert_type_", "")
            for x in M1_TYPE_XMLIDS["equipment"]]
present_codes = cat_equipment.type_ids.mapped("code")
missing = [c for c in m1_codes if c not in present_codes]
ok = (len(cat_equipment.type_ids) >= 6 and not missing)
print("  equipment type count:", len(cat_equipment.type_ids),
      "M1 missing:", missing or "(none)")
print("T7106:", "PASS" if ok else "FAIL")
results["T7106"] = ok


# ============================================================
print()
print("=" * 72)
print("T7107 - Role Tier category: >= 4 types AND M1 4 xmlids present")
print("=" * 72)
m1_codes = [x.rsplit(".", 1)[1].replace("cert_type_", "")
            for x in M1_TYPE_XMLIDS["role"]]
present_codes = cat_role.type_ids.mapped("code")
missing = [c for c in m1_codes if c not in present_codes]
ok = (len(cat_role.type_ids) >= 4 and not missing)
print("  role type count:", len(cat_role.type_ids),
      "M1 missing:", missing or "(none)")
print("T7107:", "PASS" if ok else "FAIL")
results["T7107"] = ok


# ============================================================
print()
print("=" * 72)
print("T7108 - Safety category: >= 5 types AND M1 5 xmlids present")
print("=" * 72)
m1_codes = [x.rsplit(".", 1)[1].replace("cert_type_", "")
            for x in M1_TYPE_XMLIDS["safety"]]
present_codes = cat_safety.type_ids.mapped("code")
missing = [c for c in m1_codes if c not in present_codes]
ok = (len(cat_safety.type_ids) >= 5 and not missing)
print("  safety type count:", len(cat_safety.type_ids),
      "M1 missing:", missing or "(none)")
print("T7108:", "PASS" if ok else "FAIL")
results["T7108"] = ok


# ============================================================
print()
print("=" * 72)
print("T7109 - Soft Skill category: >= 7 types AND M1 7 xmlids present")
print("=" * 72)
m1_codes = [x.rsplit(".", 1)[1].replace("cert_type_", "")
            for x in M1_TYPE_XMLIDS["soft"]]
present_codes = cat_soft.type_ids.mapped("code")
missing = [c for c in m1_codes if c not in present_codes]
ok = (len(cat_soft.type_ids) >= 7 and not missing)
print("  soft type count:", len(cat_soft.type_ids),
      "M1 missing:", missing or "(none)")
print("T7109:", "PASS" if ok else "FAIL")
results["T7109"] = ok


# ============================================================
print()
print("=" * 72)
print("T7110 - category code uniqueness")
print("=" * 72)
err, _ = _try(lambda: Category.create({
    "name": "Dup",
    "code": "equipment",  # already seeded
    "skill_level_mode": "binary",
}))
ok = isinstance(err, (IntegrityError, ValidationError))
print("  error class:", type(err).__name__ if err else None)
print("T7110:", "PASS" if ok else "FAIL")
results["T7110"] = ok


# ============================================================
print()
print("=" * 72)
print("T7111 - (category, code) tuple uniqueness on type")
print("=" * 72)
err, _ = _try(lambda: CertType.create({
    "name": "Dup MA3",
    "code": "ma3_console",  # already seeded under equipment
    "category_id": cat_equipment.id,
    "sign_off_authority": "lead_tech",
}))
ok = isinstance(err, (IntegrityError, ValidationError))
print("  error class:", type(err).__name__ if err else None)
print("T7111:", "PASS" if ok else "FAIL")
results["T7111"] = ok


# ============================================================
print()
print("=" * 72)
print("T7112 - category code regex rejects uppercase")
print("=" * 72)
err, _ = _try(lambda: Category.create({
    "name": "Bad",
    "code": "BAD_CODE",
    "skill_level_mode": "binary",
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7112:", "PASS" if ok else "FAIL")
results["T7112"] = ok


# ============================================================
print()
print("=" * 72)
print("T7113 - type code regex rejects hyphens")
print("=" * 72)
err, _ = _try(lambda: CertType.create({
    "name": "Hyphen Code",
    "code": "bad-code",  # hyphen invalid
    "category_id": cat_equipment.id,
    "sign_off_authority": "lead_tech",
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7113:", "PASS" if ok else "FAIL")
results["T7113"] = ok


# ============================================================
print()
print("=" * 72)
print("T7114 - effective_skill_level_mode falls back to category")
print("=" * 72)
# All seeded role types have explicit skill_level_mode='custom' (their
# parent category also = 'custom'), so create an override-null type
# to exercise the fall-back.
err, fallback_type = _try(lambda: CertType.create({
    "name": "Fallback Probe",
    "code": "fallback_probe",
    "category_id": cat_safety.id,
    # skill_level_mode left blank -> compute should pull cat_safety's
    # 'binary'.
    "sign_off_authority": "lead_tech",
}))
ok = (err is None
      and fallback_type.skill_level_mode is False
      and fallback_type.effective_skill_level_mode == "binary")
print("  override:", fallback_type.skill_level_mode if fallback_type else None,
      "effective:", fallback_type.effective_skill_level_mode if fallback_type else None)
print("T7114:", "PASS" if ok else "FAIL")
results["T7114"] = ok


# ============================================================
print()
print("=" * 72)
print("T7115 - effective_skill_level_mode uses override when set")
print("=" * 72)
# led_wall_absen has skill_level_mode='binary' explicitly while its
# category (equipment) defaults to tiered_3.
led_wall = env.ref("neon_training.cert_type_led_wall_absen")
ok = (led_wall.skill_level_mode == "binary"
      and led_wall.effective_skill_level_mode == "binary"
      and cat_equipment.skill_level_mode == "tiered_3")
print("  type override:", led_wall.skill_level_mode,
      "effective:", led_wall.effective_skill_level_mode,
      "category default:", cat_equipment.skill_level_mode)
print("T7115:", "PASS" if ok else "FAIL")
results["T7115"] = ok


# ============================================================
print()
print("=" * 72)
print("T7116 - training_user can READ category but not CREATE")
print("=" * 72)
read_ok = _try(lambda: Category.with_user(u_train_user).search([]).mapped("code"))
create_err, _ = _try(lambda: Category.with_user(u_train_user).create({
    "name": "User Should Fail",
    "code": "user_fail",
    "skill_level_mode": "binary",
}))
ok = (read_ok[0] is None
      and isinstance(read_ok[1], list)
      and len(read_ok[1]) == 4
      and isinstance(create_err, AccessError))
print("  read returned:", read_ok[1] if read_ok[0] is None else read_ok[0])
print("  create blocked:", isinstance(create_err, AccessError))
print("T7116:", "PASS" if ok else "FAIL")
results["T7116"] = ok


# ============================================================
print()
print("=" * 72)
print("T7117 - training_user can READ type but not CREATE")
print("=" * 72)
read_ok = _try(lambda: CertType.with_user(u_train_user).search_count([]))
create_err, _ = _try(lambda: CertType.with_user(u_train_user).create({
    "name": "User Type Fail",
    "code": "user_type_fail",
    "category_id": cat_equipment.id,
    "sign_off_authority": "lead_tech",
}))
ok = (read_ok[0] is None
      and read_ok[1] >= 22
      and isinstance(create_err, AccessError))
print("  read count:", read_ok[1] if read_ok[0] is None else read_ok[0])
print("  create blocked:", isinstance(create_err, AccessError))
print("T7117:", "PASS" if ok else "FAIL")
results["T7117"] = ok


# ============================================================
print()
print("=" * 72)
print("T7118 - training_signoff can CREATE type but NOT category")
print("=" * 72)
type_err, signoff_type = _try(lambda: CertType.with_user(u_train_signoff).create({
    "name": "Signoff Created",
    "code": "signoff_created",
    "category_id": cat_equipment.id,
    "sign_off_authority": "lead_tech",
}))
cat_err, _ = _try(lambda: Category.with_user(u_train_signoff).create({
    "name": "Signoff Should Fail",
    "code": "signoff_cat_fail",
    "skill_level_mode": "binary",
}))
ok = (type_err is None
      and signoff_type
      and isinstance(cat_err, AccessError))
print("  type create:", "OK" if type_err is None else type(type_err).__name__)
print("  category create blocked:", isinstance(cat_err, AccessError))
print("T7118:", "PASS" if ok else "FAIL")
results["T7118"] = ok


# ============================================================
print()
print("=" * 72)
print("T7119 - training_admin can CREATE both category + type")
print("=" * 72)
cat_err, admin_cat = _try(lambda: Category.with_user(u_train_admin).create({
    "name": "Admin Created",
    "code": "admin_created",
    "skill_level_mode": "binary",
}))
type_err, admin_type = _try(lambda: CertType.with_user(u_train_admin).create({
    "name": "Admin Type",
    "code": "admin_type",
    "category_id": admin_cat.id if admin_cat else cat_equipment.id,
    "sign_off_authority": "lead_tech",
}))
ok = bool(cat_err is None and admin_cat
          and type_err is None and admin_type)
print("  category create:", "OK" if cat_err is None else type(cat_err).__name__)
print("  type create:", "OK" if type_err is None else type(type_err).__name__)
print("T7119:", "PASS" if ok else "FAIL")
results["T7119"] = ok


# ============================================================
print()
print("=" * 72)
print("T7120 - training_admin CANNOT unlink category (perm_unlink=0)")
print("=" * 72)
# Use the T7119 admin-created category as victim so we don't try to
# delete a seeded row.
err, _ = _try(lambda: admin_cat.with_user(u_train_admin).unlink()
              if admin_cat else None)
ok = isinstance(err, AccessError)
print("  unlink blocked:", isinstance(err, AccessError),
      "error class:", type(err).__name__ if err else None)
print("T7120:", "PASS" if ok else "FAIL")
results["T7120"] = ok


# ============================================================
print()
print("=" * 72)
print("T7121 - training_admin CANNOT unlink type (perm_unlink=0)")
print("=" * 72)
err, _ = _try(lambda: admin_type.with_user(u_train_admin).unlink()
              if admin_type else None)
ok = isinstance(err, AccessError)
print("  unlink blocked:", isinstance(err, AccessError),
      "error class:", type(err).__name__ if err else None)
print("T7121:", "PASS" if ok else "FAIL")
results["T7121"] = ok


# ============================================================
print()
print("=" * 72)
print("T7122 - mail.thread wired on category (message_post works)")
print("=" * 72)
err, msg = _try(lambda: cat_equipment.message_post(
    body="P7a.M1 smoke -- category chatter probe.",
    subject="smoke probe",
))
ok = bool(err is None and msg)
print("  message_post:", "OK" if err is None else type(err).__name__)
print("T7122:", "PASS" if ok else "FAIL")
results["T7122"] = ok


# ============================================================
print()
print("=" * 72)
print("T7123 - mail.thread wired on type (message_post works)")
print("=" * 72)
ma3 = env.ref("neon_training.cert_type_ma3_console")
err, msg = _try(lambda: ma3.message_post(
    body="P7a.M1 smoke -- type chatter probe.",
    subject="smoke probe",
))
ok = bool(err is None and msg)
print("  message_post:", "OK" if err is None else type(err).__name__)
print("T7123:", "PASS" if ok else "FAIL")
results["T7123"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7100, 7124)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
