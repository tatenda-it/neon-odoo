"""P7a.M3 smoke -- per-category level UX + seed completion (15 tests).

T7300 available_levels computes 'pass,fail' for binary type (first_aid)
T7301 available_levels computes 'basic,expert,standard' for tiered_3 type (ma3)
T7302 available_levels computes 'driver,lead_tech,runner,tech' for custom type (lead_tech role)
T7303 available_levels empty when type_id unset
T7304 total seeded type count == 32 (22 from M1 + 10 from M3)
T7305 soft category has 11 types (7 from M1 + 4 from M3)
T7306 equipment category has 8 types (6 from M1 + 2 from M3)
T7307 safety category has 9 types (5 from M1 + 4 from M3)
T7308 Robin's 10 soft-skill conceptual categories represented (languages, MC, computer literacy, physical capability, venue knowledge, leadership, client-facing, photography, cash handling + driver licence in safety)
T7309 leadership_tier seeded with od_md sign-off
T7310 client_facing seeded with lead_tech sign-off
T7311 MA2 + Prolyte seeded under equipment
T7312 Class 2/3/5 + PSV seeded under safety with Zim Traffic Safety regulatory_body
T7313 _check_level_matches_mode still fires (constraint backstop intact)
T7314 dynamic_selection asset registered (manifest assets parsed without error)
"""
from datetime import date, timedelta

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

ma3 = env.ref("neon_training.cert_type_ma3_console")           # equipment tiered_3
first_aid = env.ref("neon_training.cert_type_first_aid")       # safety binary
lead_tech_type = env.ref("neon_training.cert_type_lead_tech")  # role custom


def _subject():
    """Helper: pick any user with the training_user group so fixture
    quirks don't bite. p7am2_subject from M2 is the canonical choice."""
    u = env["res.users"].search([("login", "=", "p7am2_subject")], limit=1)
    if not u:
        # Fall back to creating a transient subject for this smoke run.
        g = env.ref("neon_training.group_neon_training_user")
        internal = env.ref("base.group_user")
        u = env["res.users"].sudo().create({
            "name": "p7am3_subject",
            "login": "p7am3_subject",
            "email": "p7am3_subject@neon.local",
            "password": "test123",
            "groups_id": [(6, 0, [internal.id, g.id])],
        })
    return u


u_subject = _subject()


# ============================================================
print()
print("=" * 72)
print("T7300 - available_levels = 'fail,pass' for binary type (first_aid)")
print("=" * 72)
c = Cert.create({
    "user_id": u_subject.id,
    "type_id": first_aid.id,
    "date_obtained": date.today() - timedelta(days=1),
    "signed_off_by_id": u_subject.id,  # satisfy external trainer constraint
})
ok = c.available_levels == "fail,pass"
print("  available_levels:", c.available_levels)
print("T7300:", "PASS" if ok else "FAIL")
results["T7300"] = ok


# ============================================================
print()
print("=" * 72)
print("T7301 - available_levels = 'basic,expert,standard' for tiered_3 type (ma3)")
print("=" * 72)
c = Cert.create({
    "user_id": u_subject.id,
    "type_id": ma3.id,
    "date_obtained": date.today() - timedelta(days=1),
})
ok = c.available_levels == "basic,expert,standard"
print("  available_levels:", c.available_levels)
print("T7301:", "PASS" if ok else "FAIL")
results["T7301"] = ok


# ============================================================
print()
print("=" * 72)
print("T7302 - available_levels = 'driver,lead_tech,runner,tech' for custom (role tier)")
print("=" * 72)
c = Cert.create({
    "user_id": u_subject.id,
    "type_id": lead_tech_type.id,
    "date_obtained": date.today() - timedelta(days=1),
    "level": "lead_tech",
})
ok = c.available_levels == "driver,lead_tech,runner,tech"
print("  available_levels:", c.available_levels)
print("T7302:", "PASS" if ok else "FAIL")
results["T7302"] = ok


# ============================================================
print()
print("=" * 72)
print("T7303 - available_levels empty when type_id unset")
print("=" * 72)
# Build a NewId record (no commit) with no type to verify the compute.
nr = Cert.new({"user_id": u_subject.id})
ok = nr.available_levels == ""
print("  available_levels (no type):", repr(nr.available_levels))
print("T7303:", "PASS" if ok else "FAIL")
results["T7303"] = ok


# ============================================================
print()
print("=" * 72)
print("T7304 - total seeded type count = 40 (22 M1 + 10 M3 + 8 P7e M9)")
print("=" * 72)
# P7e M9 (2026-05-23) added 8 LMS-issued cert types:
# neon_foundations_safety + audio + lighting + video_led +
# workflow_ops + client_ready + rigging + technical (capstone).
n = CertType.search_count([])
ok = n == 40
print("  total types:", n)
print("T7304:", "PASS" if ok else "FAIL")
results["T7304"] = ok


# ============================================================
print()
print("=" * 72)
print("T7305 - soft category has 11 types (7 M1 + 4 M3)")
print("=" * 72)
soft = env.ref("neon_training.cert_category_soft")
n = len(soft.type_ids)
ok = n == 11
print("  soft type count:", n)
print("T7305:", "PASS" if ok else "FAIL")
results["T7305"] = ok


# ============================================================
print()
print("=" * 72)
print("T7306 - equipment category has 8 types (6 M1 + 2 M3)")
print("=" * 72)
equipment = env.ref("neon_training.cert_category_equipment")
n = len(equipment.type_ids)
ok = n == 8
print("  equipment type count:", n)
print("T7306:", "PASS" if ok else "FAIL")
results["T7306"] = ok


# ============================================================
print()
print("=" * 72)
print("T7307 - safety category has 9 types (5 M1 + 4 M3)")
print("=" * 72)
safety = env.ref("neon_training.cert_category_safety")
n = len(safety.type_ids)
ok = n == 9
print("  safety type count:", n)
print("T7307:", "PASS" if ok else "FAIL")
results["T7307"] = ok


# ============================================================
print()
print("=" * 72)
print("T7308 - Robin's 10 conceptual soft-skill categories represented")
print("=" * 72)
# Map: each 'conceptual category' -> a seeded cert type code that
# proves the category exists in the DB.
expected_codes = [
    "lang_english",          # Languages
    "mc_presentation",       # MC / Presentation
    "computer_literacy",     # Computer Literacy
    "heavy_lift",            # Physical Capability
    "venue_knowledge_harare",  # Local Venue Knowledge
    "leadership_tier",       # Leadership (M3 add)
    "client_facing",         # Client-Facing Comfort (M3 add)
    "photography",           # Photography / Videography (M3 add)
    "cash_handling",         # Cash Handling (M3 add)
    "class_4_driver",        # Driver Licence (sits in safety, counts conceptually)
]
found = CertType.search([("code", "in", expected_codes)]).mapped("code")
missing = sorted(set(expected_codes) - set(found))
ok = not missing
print("  expected:", len(expected_codes), "found:", len(found),
      "missing:", missing)
print("T7308:", "PASS" if ok else "FAIL")
results["T7308"] = ok


# ============================================================
print()
print("=" * 72)
print("T7309 - leadership_tier with od_md sign-off")
print("=" * 72)
lt = env.ref("neon_training.cert_type_leadership_tier")
ok = lt.sign_off_authority == "od_md" and lt.skill_level_mode == "binary"
print("  sign-off:", lt.sign_off_authority,
      "skill_mode:", lt.skill_level_mode)
print("T7309:", "PASS" if ok else "FAIL")
results["T7309"] = ok


# ============================================================
print()
print("=" * 72)
print("T7310 - client_facing with lead_tech sign-off")
print("=" * 72)
cf = env.ref("neon_training.cert_type_client_facing")
ok = cf.sign_off_authority == "lead_tech" and cf.skill_level_mode == "binary"
print("  sign-off:", cf.sign_off_authority,
      "skill_mode:", cf.skill_level_mode)
print("T7310:", "PASS" if ok else "FAIL")
results["T7310"] = ok


# ============================================================
print()
print("=" * 72)
print("T7311 - MA2 + Prolyte truss seeded under equipment")
print("=" * 72)
ma2 = env.ref("neon_training.cert_type_ma2_console")
prolyte = env.ref("neon_training.cert_type_truss_climbing_prolyte")
ok = (ma2.category_id.code == "equipment"
      and prolyte.category_id.code == "equipment"
      and ma2.skill_level_mode == "tiered_3"
      and prolyte.skill_level_mode == "binary")
print("  ma2 cat:", ma2.category_id.code,
      "mode:", ma2.skill_level_mode,
      "; prolyte cat:", prolyte.category_id.code,
      "mode:", prolyte.skill_level_mode)
print("T7311:", "PASS" if ok else "FAIL")
results["T7311"] = ok


# ============================================================
print()
print("=" * 72)
print("T7312 - Class 2/3/5 + PSV under safety with Zim regulatory_body")
print("=" * 72)
codes = ["class_2_driver", "class_3_driver", "class_5_driver",
         "psv_endorsement"]
rows = CertType.search([("code", "in", codes)])
expected_body = "Zimbabwe Traffic Safety Council"
ok = (len(rows) == 4
      and all(r.category_id.code == "safety" for r in rows)
      and all(r.regulatory_body == expected_body for r in rows)
      and all(r.validity_months == 60 for r in rows))
print("  count:", len(rows),
      "all safety:", all(r.category_id.code == "safety" for r in rows),
      "all 60mo:", all(r.validity_months == 60 for r in rows))
print("T7312:", "PASS" if ok else "FAIL")
results["T7312"] = ok


# ============================================================
print()
print("=" * 72)
print("T7313 - _check_level_matches_mode constraint backstop intact")
print("=" * 72)
# Direct create bypassing view: try setting level='standard' (tiered_3)
# on a binary type (first_aid). Constraint should fire.
err, _r = _try(lambda: Cert.create({
    "user_id": u_subject.id,
    "type_id": first_aid.id,
    "date_obtained": date.today() - timedelta(days=1),
    "level": "standard",
    "signed_off_by_id": u_subject.id,
}))
ok = isinstance(err, ValidationError)
print("  error class:", type(err).__name__ if err else None)
print("T7313:", "PASS" if ok else "FAIL")
results["T7313"] = ok


# ============================================================
print()
print("=" * 72)
print("T7314 - dynamic_selection JS asset declared in manifest")
print("=" * 72)
# Manifest-declared assets are loaded into the asset framework at
# boot rather than into ir.asset (which only holds DSL-style entries).
# Direct verification: re-parse the manifest via Odoo's loader and
# confirm the JS path is in the assets bundle.
import odoo
manifest = odoo.modules.module.load_information_from_description_file(
    "neon_training")
backend_bundle = (manifest.get("assets") or {}).get(
    "web.assets_backend", [])
target = "neon_training/static/src/js/neon_dynamic_selection.js"
# Version assertion is era-tolerant: Phase 7a started at
# 17.0.7.0.0, Phase 11 follow-on bumped to 17.0.8.0.x for the
# cert verifier routing override. Accept either era prefix.
# Asset-in-bundle is the load-bearing check.
version = manifest.get("version") or ""
ok = (target in backend_bundle
      and (version.startswith("17.0.7.")
           or version.startswith("17.0.8.")))
print("  manifest version:", version,
      "; target in bundle:", target in backend_bundle,
      "; bundle has", len(backend_bundle), "entry/entries")
print("T7314:", "PASS" if ok else "FAIL")
results["T7314"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(7300, 7315)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
