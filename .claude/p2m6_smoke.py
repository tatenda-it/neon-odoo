"""P2.M6 smoke tests — Calendar view + actions + computed fields.

Visual rendering is verified separately in browser. These tests cover
data shape (compute fields), domain logic (actions), and arch presence
(view XML)."""
from lxml import etree

from odoo import fields

print("=" * 72)
print("SETUP")
print("=" * 72)

# Reuse hard cleanup pattern
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["commercial.job.crew"].sudo().search([]).unlink()
env["res.partner"].sudo().search([("name", "like", "P2M6")]).unlink()
env.cr.commit()

# Grant the test runner manager rights so we can write any
# operational_status / state directly without chaining through the
# transition matrix.
env.user.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_manager").id)],
})

venue = env["res.partner"].create({
    "name": "P2M6 Venue", "is_company": True, "is_venue": True,
})
room = env["venue.room"].create({
    "name": "P2M6 Room", "venue_id": venue.id, "capacity": 100,
})
client = env["res.partner"].create({
    "name": "P2M6 Client", "is_company": True,
})
env.cr.commit()

base_date = fields.Date.add(fields.Date.today(), days=60)


def mk_job(**kw):
    vals = {
        "partner_id": client.id, "venue_id": venue.id,
        "venue_room_id": room.id, "event_date": base_date,
        "currency_id": env.company.currency_id.id,
    }
    vals.update(kw)
    return env["commercial.job"].create(vals)


results = {}

# ============================================================
print()
print("=" * 72)
print("T1 - operational_status_color mapping")
print("=" * 72)
expected = {
    "planning": 5, "soft_hold": 2, "confirmed": 10, "pre_event": 3,
    "live": 11, "wrapped": 4, "done": 7,
}
fails = []
for status, color in expected.items():
    j = mk_job()
    j.write({"operational_status": status})
    if j.operational_status_color != color:
        fails.append("%s expected=%d got=%d" % (
            status, color, j.operational_status_color))
ok = not fails
print("T1: mappings checked =", len(expected),
      " fails =", fails or "none")
print("T1:", "PASS" if ok else "FAIL")
results["T1"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T2 - color recomputes on operational_status change")
print("=" * 72)
j = mk_job()
init = j.operational_status_color  # planning -> 5
j.write({"operational_status": "soft_hold"})
mid = j.operational_status_color   # -> 2
j.write({"operational_status": "live"})
end = j.operational_status_color   # -> 11
ok = (init == 5 and mid == 2 and end == 11)
print("T2: planning ->", init, " soft_hold ->", mid, " live ->", end)
print("T2:", "PASS" if ok else "FAIL")
results["T2"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T3 - calendar_display_name prefix mapping")
print("=" * 72)
cases = [
    ("reject", "⚠ P2M6 Client"),
    ("warning", "▷ P2M6 Client"),
    ("overridden", "✓ P2M6 Client"),
    ("pass", "P2M6 Client"),
    ("not_run", "P2M6 Client"),
]
fails = []
for gate, expected_label in cases:
    j = mk_job()
    j.write({"gate_result": gate})
    actual = j.calendar_display_name
    if actual != expected_label:
        fails.append("%s expected=%r got=%r" % (gate, expected_label, actual))

# No-partner case — partner_id is required at DB level, so use an
# in-memory new() record to exercise the compute branch.
in_mem = env["commercial.job"].new({"gate_result": "pass"})
in_mem._compute_calendar_display_name()
no_partner_ok = (in_mem.calendar_display_name == "Untitled")
j_no_partner = in_mem  # for the print statement
ok = (not fails) and no_partner_ok
print("T3: gate prefix fails =", fails or "none",
      " no-partner label =", j_no_partner.calendar_display_name,
      " (expected 'Untitled')")
print("T3:", "PASS" if ok else "FAIL")
results["T3"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T4 - Live Pipeline action domain returns only pending+active")
print("=" * 72)
# Clean prior so domain assertion is clean
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
# Create five fixtures in distinct states. Use manager to bypass guards.
mgr = env.ref("base.user_admin")
fixtures = {}
states = ["pending", "active", "completed", "cancelled", "archived"]
for st in states:
    j = mk_job()
    # Force state via sudo + bypass write guard by setting via SQL-style
    # write as admin (admin is manager via post_init_hook)
    if st == "pending":
        pass
    elif st == "active":
        j.write({"state": "active", "soft_hold_until": False})
    elif st == "completed":
        j.write({"state": "active", "soft_hold_until": False})
        j.write({"state": "completed"})
    elif st == "cancelled":
        j.write({"state": "cancelled"})
    elif st == "archived":
        j.write({"loss_reason": "smoke", "state": "archived"})
    fixtures[st] = j
env.cr.commit()

live_action = env.ref("neon_jobs.commercial_job_calendar_live_pipeline_action")
import ast
domain = ast.literal_eval(live_action.domain) if live_action.domain else []
live_jobs = env["commercial.job"].search(domain + [("id", "in", [j.id for j in fixtures.values()])])
returned_states = set(live_jobs.mapped("state"))
ok = returned_states == {"pending", "active"}
print("T4: returned states =", returned_states)
print("T4:", "PASS" if ok else "FAIL")
results["T4"] = ok

# ============================================================
print()
print("=" * 72)
print("T5 - All Events action returns everything")
print("=" * 72)
all_action = env.ref("neon_jobs.commercial_job_calendar_all_events_action")
all_domain = ast.literal_eval(all_action.domain) if all_action.domain else []
all_jobs = env["commercial.job"].search(all_domain + [("id", "in", [j.id for j in fixtures.values()])])
ok = set(all_jobs.mapped("state")) == set(states)
print("T5: returned states =", set(all_jobs.mapped("state")))
print("T5:", "PASS" if ok else "FAIL")
results["T5"] = ok

# ============================================================
print()
print("=" * 72)
print("T6 - Search view filters")
print("=" * 72)
# Make a fresh pending job with expiring_soon hold and gate=reject
soon_j = mk_job(event_date=fields.Date.add(fields.Date.today(), days=200))
soon_j.write({"soft_hold_until": fields.Date.add(fields.Date.today(), days=2)})
# Trigger soft_hold_state recompute
soon_j.invalidate_recordset(["soft_hold_state"])
soon_j._compute_soft_hold_state()

reject_j = mk_job(event_date=fields.Date.add(fields.Date.today(), days=210))
reject_j.write({"gate_result": "reject"})

warn_j = mk_job(event_date=fields.Date.add(fields.Date.today(), days=220))
warn_j.write({"gate_result": "warning"})

env.cr.commit()

# Parse search view to confirm filter names exist
sv = env.ref("neon_jobs.commercial_job_view_search")
arch_doc = etree.fromstring(sv.arch)
filter_names = {f.get("name") for f in arch_doc.findall(".//filter")}
needed = {"filter_soft_hold_expiring_soon", "filter_gate_reject",
          "filter_gate_warning", "group_operational_status"}
missing = needed - filter_names
# Now apply each domain manually to verify they return the right jobs
soon_match = env["commercial.job"].search([("soft_hold_state", "=", "expiring_soon")])
reject_match = env["commercial.job"].search([("gate_result", "=", "reject")])
warn_match = env["commercial.job"].search([("gate_result", "=", "warning")])

ok = (not missing
      and soon_j in soon_match
      and reject_j in reject_match
      and warn_j in warn_match)
print("T6: missing filters =", missing or "none")
print("    soft hold match contains soon_j:", soon_j in soon_match)
print("    reject match contains reject_j:", reject_j in reject_match)
print("    warning match contains warn_j:", warn_j in warn_match)
print("T6:", "PASS" if ok else "FAIL")
results["T6"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T7 - group_by Operational Status via read_group")
print("=" * 72)
grouped = env["commercial.job"].read_group(
    [("id", "in", [soon_j.id, reject_j.id, warn_j.id])],
    fields=["operational_status"],
    groupby=["operational_status"],
)
print("T7: groups =",
      [(g["operational_status"], g["operational_status_count"]) for g in grouped])
ok = len(grouped) >= 1  # All three default to planning
results["T7"] = ok
print("T7:", "PASS" if ok else "FAIL")
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T8 - Menu items + sequences")
print("=" * 72)
m_live = env.ref("neon_jobs.menu_calendar_live_pipeline", raise_if_not_found=False)
m_all = env.ref("neon_jobs.menu_calendar_all_events", raise_if_not_found=False)
ok_live = m_live and m_live.sequence == 5 and m_live.action.id == live_action.id
ok_all = m_all and m_all.sequence == 7 and m_all.action.id == all_action.id
parent_ok = (m_live.parent_id == env.ref("neon_jobs.menu_operations_root")
             and m_all.parent_id == env.ref("neon_jobs.menu_operations_root"))
ok = ok_live and ok_all and parent_ok
print("T8: live seq=", m_live.sequence if m_live else None,
      " all seq=", m_all.sequence if m_all else None,
      " parent ok=", parent_ok)
print("T8:", "PASS" if ok else "FAIL")
results["T8"] = ok

# ============================================================
print()
print("=" * 72)
print("T9 - Calendar arch contains all spec'd popover fields")
print("=" * 72)
cv = env.ref("neon_jobs.commercial_job_view_calendar")
arch = etree.fromstring(cv.arch)
field_names = [f.get("name") for f in arch.findall(".//field")]
expected_order = [
    "calendar_display_name", "partner_id", "venue_id", "venue_room_id",
    "operational_status", "gate_result", "crew_total_count",
    "crew_confirmed_count", "equipment_count", "sub_hire_required",
    "logistics_flag", "soft_hold_state",
]
missing = [f for f in expected_order if f not in field_names]
first_is_display_name = field_names and field_names[0] == "calendar_display_name"
ok = not missing and first_is_display_name
print("T9: missing =", missing or "none",
      " first field =", field_names[0] if field_names else None)
print("T9:", "PASS" if ok else "FAIL")
results["T9"] = ok

# ============================================================
print()
print("=" * 72)
print("T10 - No quoted_value in calendar arch")
print("=" * 72)
ok = "quoted_value" not in field_names
print("T10: 'quoted_value' in arch =", "quoted_value" in field_names)
print("T10:", "PASS" if ok else "FAIL")
results["T10"] = ok

# ============================================================
print()
print("=" * 72)
print("T11 - date_start / date_stop attributes")
print("=" * 72)
cal = arch.find(".//calendar") if arch.tag != "calendar" else arch
date_start = cal.get("date_start")
date_stop = cal.get("date_stop")
# date_stop is event_end_date_calendar (a computed Date that coalesces to
# event_date when event_end_date is blank). Required because Odoo 17's
# calendar widget drops events when the date_stop field is NULL on a
# Date-type pair.
ok = (date_start == "event_date" and date_stop == "event_end_date_calendar")
print("T11: date_start =", date_start, " date_stop =", date_stop)
print("T11:", "PASS" if ok else "FAIL")
results["T11"] = ok

# ============================================================
print()
print("=" * 72)
print("T12 - quick_create disabled, event_open_popup enabled")
print("=" * 72)
qc = cal.get("quick_create")
ep = cal.get("event_open_popup")
cnf = cal.get("create_name_field")
color_attr = cal.get("color")
mode_attr = cal.get("mode")
ok = (qc in ("0", "false", "False")
      and ep in ("1", "true", "True")
      and cnf == "calendar_display_name"
      and color_attr == "operational_status_color"
      and mode_attr == "month")
print("T12: quick_create=", qc, " event_open_popup=", ep,
      " create_name_field=", cnf, " color=", color_attr, " mode=", mode_attr)
print("T12:", "PASS" if ok else "FAIL")
results["T12"] = ok

# ============================================================
print()
print("=" * 72)
print("T13 - event_end_date_calendar falls back to event_date when blank")
print("=" * 72)
j13 = mk_job(event_end_date=False)
ok = j13.event_end_date_calendar == j13.event_date
print("T13: event_date=", j13.event_date,
      " event_end_date=", j13.event_end_date,
      " event_end_date_calendar=", j13.event_end_date_calendar)
print("T13:", "PASS" if ok else "FAIL")
results["T13"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("T14 - event_end_date_calendar matches event_end_date when set")
print("=" * 72)
end = fields.Date.add(base_date, days=2)
j14 = mk_job(event_end_date=end)
ok = j14.event_end_date_calendar == end
print("T14: event_date=", j14.event_date,
      " event_end_date=", j14.event_end_date,
      " event_end_date_calendar=", j14.event_end_date_calendar)
print("T14:", "PASS" if ok else "FAIL")
results["T14"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10", "T11", "T12", "T13", "T14"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
