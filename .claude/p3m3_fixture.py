"""Prep two event_jobs for the P3.M3 browser walkthrough.

Self-healing on rerun:
- If JOB-000533 / EVT-000038 already exist, leave them in place but
  ensure crew_chief assignment is present and lead_tech is set.
- Otherwise create fresh fixtures.

Why this script lives in .claude/: it sets up data for manual browser
verification, not for automated tests. It's safe to rerun whenever
the live fixture state drifts.
"""
from odoo import fields

tatenda = env["res.users"].search(
    [("login", "=", "tatenda@neonhiring.co.zw")], limit=1)
crew_user = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
# Local "Lead Tech" stand-in: whoever is in group_neon_jobs_crew_leader.
# On Hetzner that's ranganai@; locally it's p2m75_lead.
lead_tech = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)

if not (tatenda and crew_user and lead_tech):
    raise SystemExit("MISSING USER — cannot prep fixtures")

# Pick a clean client + venue
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search(
    [("is_venue", "=", True), ("name", "not like", "TBD%")], limit=1)


def _ensure(label, day_offset, with_crew_chief=False, with_lead_tech=True):
    """Idempotently ensure a P3M3BROWSE fixture exists for this label.
    Re-uses existing rows when found; restores missing pieces (crew
    chief, lead tech)."""
    summary = "P3M3BROWSE " + label
    J = env["commercial.job"].search(
        [("equipment_summary", "=", summary)], limit=1)
    if J:
        EJ = J.event_job_ids[:1]
        # Reset state to draft so the walkthrough has somewhere to go.
        # The state-write block respects _allow_state_write.
        if EJ and EJ.state != "draft":
            EJ.with_context(_allow_state_write=True).write({
                "state": "draft",
                "closeout_completed_at": False,
            })
    else:
        J = env["commercial.job"].create({
            "partner_id": client.id, "venue_id": venue.id,
            "event_date": fields.Date.add(fields.Date.today(), days=day_offset),
            "currency_id": env.company.currency_id.id,
            "equipment_summary": summary,
        })
        J.write({"state": "active", "soft_hold_until": False})
        EJ = J.event_job_ids[:1]
    # Lead Tech (always — even on rerun, ensure it's set)
    if with_lead_tech and EJ.lead_tech_id != lead_tech:
        EJ.lead_tech_id = lead_tech.id
    if not with_lead_tech:
        EJ.lead_tech_id = False
    # Crew Chief assignment (restore if missing)
    if with_crew_chief:
        existing = env["commercial.job.crew"].sudo().search([
            ("job_id", "=", J.id),
        ])
        chief = existing.filtered(lambda c: c.user_id == crew_user)
        if not chief:
            env["commercial.job.crew"].sudo().create({
                "job_id": J.id, "user_id": crew_user.id,
                "role": "tech", "state": "confirmed",
                "is_crew_chief": True,
            })
        else:
            chief.write({"is_crew_chief": True, "state": "confirmed"})
    EJ.invalidate_recordset()
    return J, EJ


# Fixture A: walkthrough event_job — lead_tech set, crew_chief set,
# state=draft so the full forward path is exercisable.
J_A, EJ_A = _ensure("A walkthrough", 60, with_crew_chief=True)

# Fixture B: separate event_job for the cancel test — minimal setup,
# state=draft.
J_B, EJ_B = _ensure("B cancel test", 75, with_crew_chief=False, with_lead_tech=False)

env.cr.commit()

print()
print("=" * 72)
print("FIXTURE A — full walkthrough (draft → planning → … → closed)")
print("=" * 72)
print("  commercial.job:        %s (id=%d)" % (J_A.name, J_A.id))
print("  commercial.event.job:  %s (id=%d)" % (EJ_A.name, EJ_A.id))
print("  state:                 %s" % EJ_A.state)
print("  lead_tech_id:          %s (id=%d)" % (
    EJ_A.lead_tech_id.name, EJ_A.lead_tech_id.id))
chief = env["commercial.job.crew"].search([
    ("job_id", "=", J_A.id), ("is_crew_chief", "=", True),
], limit=1)
print("  crew_chief assignment: id=%d user=%s (login=%s)" % (
    chief.id, chief.user_id.name, chief.user_id.login))
print("  event_job.crew_chief_id: %s" % (EJ_A.crew_chief_id.name or "(unset)"))

print()
print("=" * 72)
print("FIXTURE B — cancel test (separate draft event_job)")
print("=" * 72)
print("  commercial.job:        %s (id=%d)" % (J_B.name, J_B.id))
print("  commercial.event.job:  %s (id=%d)" % (EJ_B.name, EJ_B.id))
print("  state:                 %s" % EJ_B.state)

print()
print("Run this script anytime the fixture drifts. It restores missing")
print("crew_chief assignments + lead_tech without recreating the rows.")
