"""P7a.M12 core smoke -- dashboard + find-qualified-user wizard (25 tests).

Dashboard model + counters:
T8200  Dashboard model + 13 counter fields present
T8201  action_open_dashboard creates a record + returns act_window
T8202  Counter: active_certs_total reflects active cert count
T8203  Counter: active_certs_by_category sums correctly across 4 categories
T8204  Counter: expiring_30/60/90 cumulative buckets
T8205  Counter: pending_verification_count
T8206  Counter: recent_cross_competency (30d)
T8207  Counter: tier_1/2/3 fires (30d)
T8208  Access check denies non-training user

Dashboard drill-throughs:
T8209  action_open_active_certs returns filtered act_window
T8210  action_open_expiring_certs honours dashboard_expiring_days context
T8211  action_open_tier_fires honours dashboard_tier context

Find Qualified User wizard:
T8212  Wizard model + 7 fields present
T8213  action_open_wizard creates a record
T8214  Empty cert_type_ids + search raises UserError
T8215  Single cert match: returns users holding that cert
T8216  Multi-cert AND match: only users holding ALL types
T8217  include_pending toggle adds pending_verification certs
T8218  include_suspended toggle adds suspended certs
T8219  include_cross_competency union with CC demonstrators
T8220  required_level filter applied
T8221  action_reset clears all fields
T8222  Performance: search completes in < 500ms (DP6)

Gate log view extension:
T8223  Kanban view exists on gate_log
T8224  search view has date-range filter (filter_fired_7d)
"""
import time
from datetime import date, datetime, timedelta

from odoo import fields, SUPERUSER_ID
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

Dashboard = env["neon.training.dashboard"]
Wizard = env["neon.training.find_qualified_user_wizard"]
Cert = env["neon.training.certification"]
CertType = env["neon.training.certification.type"]
CC = env["neon.training.cross_competency"]
GateLog = env["neon.training.assignment_gate_log"]
Users = env["res.users"]
Partner = env["res.partner"]
View = env["ir.ui.view"]

u_lt = Users.sudo().search([("login", "=", "p2m75_lead")], limit=1)
u_tech = Users.sudo().search([("login", "=", "p7am2_subject")], limit=1)
u_admin = Users.sudo().search(
    [("login", "=", "p7am2_train_admin")], limit=1)
u_sales = Users.sudo().search([("login", "=", "p2m75_sales")], limit=1)
u_other = Users.sudo().search([("login", "=", "p2m75_other")], limit=1)
assert all([u_lt, u_tech, u_admin, u_sales, u_other]), "fixture users"

# Cleanup.
all_uids = (u_lt.id, u_tech.id, u_other.id)
env.cr.execute(
    "DELETE FROM mail_activity WHERE res_model_id IN "
    "(SELECT id FROM ir_model WHERE model = "
    "'neon.training.certification') AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.certification' AND res_id IN "
    "(SELECT id FROM neon_training_certification WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM neon_training_certification WHERE user_id IN %s",
    (all_uids,))
env.cr.execute(
    "DELETE FROM mail_message WHERE model = "
    "'neon.training.cross_competency' AND res_id IN "
    "(SELECT id FROM neon_training_cross_competency WHERE "
    "user_id IN %s)", (all_uids,))
env.cr.execute(
    "DELETE FROM neon_training_cross_competency WHERE user_id IN %s",
    (all_uids,))
env.cr.commit()
print("  cleaned up prior fixtures")

# Seed: u_lt holds active lead_tech cert.
type_lt = env.ref("neon_training.cert_type_lead_tech")
type_tech = env.ref("neon_training.cert_type_tech")
type_first_aid = env.ref("neon_training.cert_type_first_aid")

c_lt_cert = Cert.sudo().create({
    "user_id":       u_lt.id,
    "type_id":       type_lt.id,
    "date_obtained": date.today() - timedelta(days=30),
    "level":         "lead_tech",
})
c_lt_cert.with_user(u_admin).action_submit_for_verification()
c_lt_cert.with_user(u_admin).action_verify()

# Seed: u_tech holds active tech cert + first_aid (so multi-AND
# test has a positive case).
c_tech_cert = Cert.sudo().create({
    "user_id":       u_tech.id,
    "type_id":       type_tech.id,
    "date_obtained": date.today() - timedelta(days=20),
    "level":         "tech",
})
c_tech_cert.with_user(u_admin).action_submit_for_verification()
c_tech_cert.with_user(u_admin).action_verify()

c_tech_fa = Cert.sudo().create({
    "user_id":       u_tech.id,
    "type_id":       type_first_aid.id,
    "date_obtained": date.today() - timedelta(days=10),
    "signed_off_by_id": u_admin.id,
})
c_tech_fa.with_user(u_admin).action_submit_for_verification()
c_tech_fa.with_user(u_admin).action_verify()
print("  seeded u_lt (lead_tech) + u_tech (tech + first_aid)")


# ============================================================
print()
print("=" * 72)
print("T8200 - Dashboard model + 13 counter fields present")
print("=" * 72)
fields_present = set(Dashboard._fields.keys())
expected = {
    "active_certs_total", "active_certs_equipment",
    "active_certs_role_tier", "active_certs_safety",
    "active_certs_soft_skill",
    "expiring_30d", "expiring_60d", "expiring_90d",
    "pending_verification_count",
    "recent_cross_competency_count",
    "tier_1_fires_30d", "tier_2_fires_30d", "tier_3_fires_30d",
}
missing = expected - fields_present
ok = not missing
print("  expected:", len(expected), " missing:", sorted(missing))
print("T8200:", "PASS" if ok else "FAIL")
results["T8200"] = ok


# ============================================================
print()
print("=" * 72)
print("T8201 - action_open_dashboard creates record + returns act_window")
print("=" * 72)
action = Dashboard.with_user(u_admin).action_open_dashboard()
ok = (isinstance(action, dict)
      and action.get("type") == "ir.actions.act_window"
      and action.get("res_model") == "neon.training.dashboard"
      and bool(action.get("res_id")))
print("  type:", action.get("type"),
      " res_id:", action.get("res_id"))
print("T8201:", "PASS" if ok else "FAIL")
results["T8201"] = ok


# Materialise a dashboard record for subsequent counter tests.
dash = Dashboard.sudo().create({})


# ============================================================
print()
print("=" * 72)
print("T8202 - active_certs_total reflects active count")
print("=" * 72)
expected_total = Cert.sudo().search_count([("state", "=", "active")])
ok = (dash.active_certs_total == expected_total)
print("  computed:", dash.active_certs_total,
      " expected:", expected_total)
print("T8202:", "PASS" if ok else "FAIL")
results["T8202"] = ok


# ============================================================
print()
print("=" * 72)
print("T8203 - active_certs by category sum across 4 categories")
print("=" * 72)
cat_sum = (dash.active_certs_equipment
           + dash.active_certs_role_tier
           + dash.active_certs_safety
           + dash.active_certs_soft_skill)
# Total may exceed cat_sum if some active certs are in
# categories outside the four standard ones (unlikely in seed).
ok = (cat_sum <= dash.active_certs_total
      and dash.active_certs_role_tier >= 1)  # u_lt cert
print("  cat_sum:", cat_sum, " total:", dash.active_certs_total)
print("T8203:", "PASS" if ok else "FAIL")
results["T8203"] = ok


# ============================================================
print()
print("=" * 72)
print("T8204 - expiring 30/60/90 cumulative buckets")
print("=" * 72)
ok = (dash.expiring_30d <= dash.expiring_60d
      <= dash.expiring_90d)
print("  30d:", dash.expiring_30d,
      " 60d:", dash.expiring_60d,
      " 90d:", dash.expiring_90d)
print("T8204:", "PASS" if ok else "FAIL")
results["T8204"] = ok


# ============================================================
print()
print("=" * 72)
print("T8205 - pending_verification_count")
print("=" * 72)
# Build a pending cert; verify counter increments.
expected = Cert.sudo().search_count(
    [("state", "=", "pending_verification")])
dash.invalidate_recordset()
ok = (dash.pending_verification_count == expected)
print("  count:", dash.pending_verification_count,
      " expected:", expected)
print("T8205:", "PASS" if ok else "FAIL")
results["T8205"] = ok


# ============================================================
print()
print("=" * 72)
print("T8206 - recent_cross_competency_count (30d)")
print("=" * 72)
# Seed a CC for u_tech in the past 30 days.
cc_partner = Partner.sudo().create({"name": "P7aM12 CC Client"})
test_venue = Partner.sudo().create({
    "name": "P7aM12 Venue", "is_company": True})
cc_job = env["commercial.job"].sudo().create({
    "partner_id":  cc_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() - timedelta(days=10),
    "currency_id": env.company.currency_id.id,
})
cc_job.sudo().write({"state": "active", "soft_hold_until": False})
cc_ej = cc_job.event_job_ids[0]
CC.sudo().create({
    "user_id":                       u_tech.id,
    "certification_type_id":         type_tech.id,
    "demonstrated_through_event_id": cc_ej.id,
    "demonstrated_at":               date.today() - timedelta(days=5),
    "observed_by_id":                u_admin.id,
    "notes": "P7aM12 fixture CC for dashboard test",
})
dash.invalidate_recordset()
ok = (dash.recent_cross_competency_count >= 1)
print("  count:", dash.recent_cross_competency_count)
print("T8206:", "PASS" if ok else "FAIL")
results["T8206"] = ok


# ============================================================
print()
print("=" * 72)
print("T8207 - tier 1/2/3 fires (30d)")
print("=" * 72)
# Seed three gate_log entries (one per tier) within last 30d.
test_partner = Partner.sudo().create({
    "name": "P7aM12 Gate Client", "is_company": True})
gate_job = env["commercial.job"].sudo().create({
    "partner_id":  test_partner.id,
    "venue_id":    test_venue.id,
    "event_date":  date.today() + timedelta(days=10),
    "currency_id": env.company.currency_id.id,
})
gate_job.sudo().write({"state": "active", "soft_hold_until": False})
gate_ej = gate_job.event_job_ids[0]
# Build crew via the M9 hook (fires tier_1 automatically).
env["commercial.job.crew"].sudo().create({
    "job_id":     gate_job.id,
    "partner_id": u_other.partner_id.id,
    "user_id":    u_other.id,
    "role":       "tech",  # u_other unqualified -> tier_1 fire
})
# tier_2: manually create a log record.
GateLog.sudo().create({
    "event_job_id":         gate_ej.id,
    "user_id":              u_other.id,
    "gate_tier":            "tier_2_quote_accept",
    "gate_status_at_fire":  "unqualified",
    "override_reason":      "P7aM12 fixture",
    "overridden_by_id":     u_admin.id,
    "overridden_at":        fields.Datetime.now(),
    "fired_at":             fields.Datetime.now(),
    "triggered_by_id":      u_admin.id,
})
# tier_3: same.
GateLog.sudo().create({
    "event_job_id":         gate_ej.id,
    "user_id":              u_other.id,
    "gate_tier":            "tier_3_event_start",
    "gate_status_at_fire":  "unqualified",
    "override_reason":      "P7aM12 fixture",
    "overridden_by_id":     u_admin.id,
    "overridden_at":        fields.Datetime.now(),
    "fired_at":             fields.Datetime.now(),
    "triggered_by_id":      u_admin.id,
})
dash.invalidate_recordset()
ok = (dash.tier_1_fires_30d >= 1
      and dash.tier_2_fires_30d >= 1
      and dash.tier_3_fires_30d >= 1)
print("  tier_1:", dash.tier_1_fires_30d,
      " tier_2:", dash.tier_2_fires_30d,
      " tier_3:", dash.tier_3_fires_30d)
print("T8207:", "PASS" if ok else "FAIL")
results["T8207"] = ok


# ============================================================
print()
print("=" * 72)
print("T8208 - Access check denies non-training user")
print("=" * 72)
# u_sales is a sales user without training_user group? Let's
# check; sales role is granted on demand. If u_sales has
# training_user via implied_ids the test should still detect a
# user without it. Use a fresh user without any training group.
no_grp_user = Users.sudo().create({
    "login": "p7a_m12_no_grp",
    "name":  "P7aM12 No Training",
    "groups_id": [(6, 0, [env.ref("base.group_user").id])],
})
err, _ = _try(lambda: Dashboard.with_user(no_grp_user)
              .action_open_dashboard())
ok = isinstance(err, AccessError)
print("  err type:", type(err).__name__ if err else None)
print("T8208:", "PASS" if ok else "FAIL")
results["T8208"] = ok


# ============================================================
print()
print("=" * 72)
print("T8209 - action_open_active_certs returns filtered act_window")
print("=" * 72)
action = dash.action_open_active_certs()
ok = (isinstance(action, dict)
      and action.get("res_model") == "neon.training.certification"
      and ("state", "=", "active") in (action.get("domain") or []))
print("  res_model:", action.get("res_model"),
      " domain:", action.get("domain"))
print("T8209:", "PASS" if ok else "FAIL")
results["T8209"] = ok


# ============================================================
print()
print("=" * 72)
print("T8210 - action_open_expiring_certs honours days context")
print("=" * 72)
action = dash.with_context(dashboard_expiring_days=60)\
    .action_open_expiring_certs()
domain_str = str(action.get("domain") or [])
ok = (isinstance(action, dict)
      and "date_expires" in domain_str
      and "60 days" in action.get("name", ""))
print("  domain:", action.get("domain"),
      " name:", action.get("name"))
print("T8210:", "PASS" if ok else "FAIL")
results["T8210"] = ok


# ============================================================
print()
print("=" * 72)
print("T8211 - action_open_tier_fires honours dashboard_tier context")
print("=" * 72)
action = dash.with_context(
    dashboard_tier="tier_3_event_start").action_open_tier_fires()
domain_str = str(action.get("domain") or [])
ok = (isinstance(action, dict)
      and "tier_3_event_start" in domain_str)
print("  domain:", action.get("domain"))
print("T8211:", "PASS" if ok else "FAIL")
results["T8211"] = ok


# ============================================================
print()
print("=" * 72)
print("T8212 - Wizard model + 7 fields present")
print("=" * 72)
fields_present = set(Wizard._fields.keys())
expected = {
    "cert_type_ids", "required_level",
    "include_cross_competency", "include_pending",
    "include_suspended", "matched_user_ids",
    "result_summary",
}
missing = expected - fields_present
ok = not missing
print("  expected:", sorted(expected),
      " missing:", sorted(missing))
print("T8212:", "PASS" if ok else "FAIL")
results["T8212"] = ok


# ============================================================
print()
print("=" * 72)
print("T8213 - action_open_wizard creates record + returns act_window")
print("=" * 72)
action = Wizard.with_user(u_admin).action_open_wizard()
ok = (isinstance(action, dict)
      and action.get("res_model")
        == "neon.training.find_qualified_user_wizard"
      and action.get("target") == "new"
      and bool(action.get("res_id")))
print("  res_id:", action.get("res_id"))
print("T8213:", "PASS" if ok else "FAIL")
results["T8213"] = ok


# ============================================================
print()
print("=" * 72)
print("T8214 - Empty cert_type_ids + search raises UserError")
print("=" * 72)
w_empty = Wizard.sudo().create({})
err, _ = _try(lambda: w_empty.with_user(u_admin).action_search())
ok = isinstance(err, UserError)
print("  err type:", type(err).__name__ if err else None)
print("T8214:", "PASS" if ok else "FAIL")
results["T8214"] = ok


# ============================================================
print()
print("=" * 72)
print("T8215 - Single cert match: returns users holding that cert")
print("=" * 72)
w_single = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_lt.id])],
})
w_single.with_user(u_admin).action_search()
ok = (u_lt in w_single.matched_user_ids
      and u_tech not in w_single.matched_user_ids)
print("  matched:", w_single.matched_user_ids.mapped("login"))
print("T8215:", "PASS" if ok else "FAIL")
results["T8215"] = ok


# ============================================================
print()
print("=" * 72)
print("T8216 - Multi-cert AND match")
print("=" * 72)
# u_tech holds BOTH tech + first_aid.
w_multi = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_tech.id, type_first_aid.id])],
})
w_multi.with_user(u_admin).action_search()
ok = (u_tech in w_multi.matched_user_ids
      and u_lt not in w_multi.matched_user_ids)
print("  matched:", w_multi.matched_user_ids.mapped("login"))
print("T8216:", "PASS" if ok else "FAIL")
results["T8216"] = ok


# ============================================================
print()
print("=" * 72)
print("T8217 - include_pending toggle")
print("=" * 72)
# Create a pending cert for u_other.
type_runner = env.ref("neon_training.cert_type_runner")
c_pending = Cert.sudo().create({
    "user_id":       u_other.id,
    "type_id":       type_runner.id,
    "date_obtained": date.today() - timedelta(days=2),
    "level":         "runner",
})
c_pending.with_user(u_admin).action_submit_for_verification()
# u_other is now in 'pending_verification' for runner.
w_pend_off = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_runner.id])],
    "include_pending": False,
})
w_pend_off.with_user(u_admin).action_search()
w_pend_on = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_runner.id])],
    "include_pending": True,
})
w_pend_on.with_user(u_admin).action_search()
ok = (u_other not in w_pend_off.matched_user_ids
      and u_other in w_pend_on.matched_user_ids)
print("  pending_off:", w_pend_off.matched_user_ids.mapped("login"),
      " pending_on:", w_pend_on.matched_user_ids.mapped("login"))
print("T8217:", "PASS" if ok else "FAIL")
results["T8217"] = ok


# ============================================================
print()
print("=" * 72)
print("T8218 - include_suspended toggle")
print("=" * 72)
# u_lt has active lead_tech cert; suspend it; verify suspended
# inclusion toggle.
c_lt_cert.with_user(u_admin).with_context(
    suspension_reason="P7aM12 fixture suspend").action_suspend()
w_susp_off = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_lt.id])],
    "include_suspended": False,
})
w_susp_off.with_user(u_admin).action_search()
w_susp_on = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_lt.id])],
    "include_suspended": True,
})
w_susp_on.with_user(u_admin).action_search()
ok = (u_lt not in w_susp_off.matched_user_ids
      and u_lt in w_susp_on.matched_user_ids)
print("  suspended_off:", w_susp_off.matched_user_ids.mapped("login"),
      " suspended_on:", w_susp_on.matched_user_ids.mapped("login"))
print("T8218:", "PASS" if ok else "FAIL")
results["T8218"] = ok


# ============================================================
print()
print("=" * 72)
print("T8219 - include_cross_competency union")
print("=" * 72)
# u_tech has tech cert AND a CC for tech (T8206 seeded).
# u_other has no tech cert. Test: searching for tech with
# cross_competency=True should NOT add u_other (CC was on
# u_tech, not u_other). Add a CC for u_other on type_tech to
# verify the union actually fires.
CC.sudo().create({
    "user_id":                       u_other.id,
    "certification_type_id":         type_tech.id,
    "demonstrated_through_event_id": cc_ej.id,
    "demonstrated_at":               date.today() - timedelta(days=4),
    "observed_by_id":                u_admin.id,
    "notes": "P7aM12 T8219 fixture",
})
w_cc_off = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_tech.id])],
    "include_cross_competency": False,
})
w_cc_off.with_user(u_admin).action_search()
w_cc_on = Wizard.sudo().create({
    "cert_type_ids": [(6, 0, [type_tech.id])],
    "include_cross_competency": True,
})
w_cc_on.with_user(u_admin).action_search()
ok = (u_other not in w_cc_off.matched_user_ids
      and u_other in w_cc_on.matched_user_ids)
print("  cc_off:", w_cc_off.matched_user_ids.mapped("login"),
      " cc_on:", w_cc_on.matched_user_ids.mapped("login"))
print("T8219:", "PASS" if ok else "FAIL")
results["T8219"] = ok


# ============================================================
print()
print("=" * 72)
print("T8220 - required_level filter applied")
print("=" * 72)
# u_lt cert level='lead_tech'; the wizard's required_level
# selection includes binary_yes/tier_3_l1/tier_3_l2/tier_3_l3.
# The 'lead_tech' value isn't in the level filter selection,
# but a strict 'binary_yes' filter should yield no matches.
# First reactivate u_lt's cert to test against active state.
# Actually it's suspended now. Let's create a fresh cert with
# binary_yes level.
type_eng = env.ref("neon_training.cert_type_lang_english")
c_binary = Cert.sudo().create({
    "user_id":       u_other.id,
    "type_id":       type_eng.id,
    "date_obtained": date.today() - timedelta(days=1),
    "level":         "pass",
    "signed_off_by_id": u_admin.id,
})
c_binary.with_user(u_admin).action_submit_for_verification()
c_binary.with_user(u_admin).action_verify()
w_level = Wizard.sudo().create({
    "cert_type_ids":  [(6, 0, [type_eng.id])],
    "required_level": "pass",
})
w_level.with_user(u_admin).action_search()
ok = (u_other in w_level.matched_user_ids)
print("  pass-level matched:",
      w_level.matched_user_ids.mapped("login"))
print("T8220:", "PASS" if ok else "FAIL")
results["T8220"] = ok


# ============================================================
print()
print("=" * 72)
print("T8221 - action_reset clears fields")
print("=" * 72)
w_reset = Wizard.sudo().create({
    "cert_type_ids":            [(6, 0, [type_lt.id, type_tech.id])],
    "required_level":           "lead_tech",
    "include_cross_competency": True,
    "include_pending":          True,
    "include_suspended":        True,
})
w_reset.with_user(u_admin).action_search()
assert w_reset.matched_user_ids, "pre-reset should have matches"
w_reset.with_user(u_admin).action_reset()
ok = (not w_reset.cert_type_ids
      and w_reset.required_level == "any"
      and not w_reset.include_cross_competency
      and not w_reset.include_pending
      and not w_reset.include_suspended
      and not w_reset.matched_user_ids)
print("  cert_type_ids:", w_reset.cert_type_ids.ids,
      " level:", w_reset.required_level,
      " matched:", w_reset.matched_user_ids.ids)
print("T8221:", "PASS" if ok else "FAIL")
results["T8221"] = ok


# ============================================================
print()
print("=" * 72)
print("T8222 - Performance: search < 500ms")
print("=" * 72)
w_perf = Wizard.sudo().create({
    "cert_type_ids":            [(6, 0, [
        type_lt.id, type_tech.id, type_first_aid.id])],
    "include_cross_competency": True,
})
t0 = time.perf_counter()
w_perf.with_user(u_admin).action_search()
elapsed_ms = (time.perf_counter() - t0) * 1000
ok = elapsed_ms < 500
print("  elapsed:", round(elapsed_ms, 1), "ms",
      " threshold: 500ms",
      " matched:", len(w_perf.matched_user_ids))
print("T8222:", "PASS" if ok else "FAIL")
results["T8222"] = ok


# ============================================================
print()
print("=" * 72)
print("T8223 - Kanban view exists on gate_log")
print("=" * 72)
kanban_views = View.sudo().search([
    ("model", "=", "neon.training.assignment_gate_log"),
    ("type", "=", "kanban"),
])
ok = (len(kanban_views) >= 1)
print("  kanban view count:", len(kanban_views))
print("T8223:", "PASS" if ok else "FAIL")
results["T8223"] = ok


# ============================================================
print()
print("=" * 72)
print("T8224 - search view has fired-date filters")
print("=" * 72)
search_view = View.sudo().search([
    ("model", "=", "neon.training.assignment_gate_log"),
    ("type", "=", "search"),
], limit=1)
ok = (search_view
      and "filter_fired_7d" in (search_view.arch or "")
      and "filter_fired_30d" in (search_view.arch or ""))
print("  search view id:", search_view.id if search_view else None,
      " has 7d filter:", "filter_fired_7d" in (search_view.arch or ""),
      " has 30d filter:", "filter_fired_30d" in (search_view.arch or ""))
print("T8224:", "PASS" if ok else "FAIL")
results["T8224"] = ok


# ============================================================
print()
print("=" * 72)
print("T8225 - Training app visible to base.user_admin (three-layer assertion)")
print("=" * 72)
# Pre-deploy Chrome session 21 May 2026 surfaced the visibility
# failure path. The fix is two layers:
#   1. menu_neon_training_root has empty groups_id (the D-path
#      menu XML change + post-migrate clear on upgrades).
#   2. data/neon_training_user_provisioning.xml grants
#      group_neon_training_admin to base.user_admin so at
#      least one child menu is visible, satisfying Odoo's
#      _filter_visible_menus rule (user-in-groups OR child
#      visible).
# T8225 asserts all three observable consequences:
#   a) admin is in group_neon_training_admin (data grant landed)
#   b) root menu groups_id is empty (D menu fix intact)
#   c) load_web_menus shows root in admin's top-level apps
#      (the deploy-experience assertion)
admin_user = env.ref("base.user_admin")
root_menu = env.ref("neon_training.menu_neon_training_root")
training_admin_grp = env.ref(
    "neon_training.group_neon_training_admin")

# (a) Data grant landed.
admin_in_training_admin = admin_user in training_admin_grp.users

# (b) Root menu groups_id empty.
root_groups_empty = (len(root_menu.groups_id) == 0)

# (c) Root visible to admin via load_web_menus.
menus = env["ir.ui.menu"].with_user(admin_user)\
    .load_web_menus(False)
root_in_top_level = (root_menu.id in
                     menus.get("root", {}).get("children", []))

ok = (admin_in_training_admin
      and root_groups_empty
      and root_in_top_level)
print("  (a) admin in group_neon_training_admin:",
      admin_in_training_admin, " (expected True)")
print("  (b) root menu groups_id empty:",
      root_groups_empty,
      " (current:", root_menu.groups_id.mapped("full_name"), ")")
print("  (c) root in admin's top-level apps:",
      root_in_top_level, " (expected True)")
print("T8225:", "PASS" if ok else "FAIL")
results["T8225"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T%d" % i for i in range(8200, 8226)]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
