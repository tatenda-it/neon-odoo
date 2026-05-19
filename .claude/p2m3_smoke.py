from odoo import fields
from odoo.exceptions import UserError

print("=" * 70)
print("SETUP")
print("=" * 70)
print("Setup user:", env.user.name, env.user.login)

# Clean any prior smoke run
env["commercial.job"].sudo().search([("name", "like", "JOB-")]).unlink()
env["crm.lead"].sudo().search([("name", "like", "P2M3 Smoke")]).unlink()
env.cr.commit()

quote_sent = env.ref("__export__.crm_stage_8", raise_if_not_found=False)
if not quote_sent:
    quote_sent = env["crm.stage"].browse(8)
confirmed = env["crm.stage"].browse(11)
new_enquiry = env["crm.stage"].browse(5)
print("Quote Sent: id=", quote_sent.id, " is_proposal_stage=", quote_sent.is_proposal_stage)
print("Confirmed:  id=", confirmed.id, " is_confirmation_stage=", confirmed.is_confirmation_stage)
print("New Enquiry id=", new_enquiry.id, " name=", new_enquiry.name)

client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False),
     ("name", "not in", ("TBD — Set Venue",))], limit=1)
print("Client:", client.name, "id=", client.id)

tbd_venue = env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
print("TBD venue: id=", tbd_venue.id if tbd_venue else None,
      " is_venue=", tbd_venue.is_venue if tbd_venue else None)
env.cr.commit()

results = {}


def mk_lead(suffix, **kw):
    vals = {
        "name": "P2M3 Smoke " + suffix,
        "partner_id": client.id,
        "stage_id": new_enquiry.id,
        "expected_revenue": 5000.0,
    }
    vals.update(kw)
    return env["crm.lead"].create(vals)


# ============================================================
print()
print("=" * 70)
print("T1 - Lead in New stage does NOT create a job")
print("=" * 70)
lead = mk_lead("T1")
ok = len(lead.commercial_job_ids) == 0
print("T1:", "PASS" if ok else "FAIL",
      "- jobs linked:", len(lead.commercial_job_ids))
results["T1"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T2 - Lead -> Quote Sent creates pending job, crm_lead_id linked")
print("=" * 70)
lead = mk_lead("T2")
lead.write({"stage_id": quote_sent.id})
jobs = lead.commercial_job_ids
ok_count = len(jobs) == 1
ok_state = jobs and jobs[0].state == "pending"
ok_link = jobs and jobs[0].crm_lead_id == lead
ok_partner = jobs and jobs[0].partner_id == client
ok_quoted = jobs and jobs[0].quoted_value == 5000.0
print("T2: jobs=", len(jobs), " state=", jobs[0].state if jobs else None,
      " crm_lead_id->lead:", ok_link, " partner OK:", ok_partner,
      " quoted_value=", jobs[0].quoted_value if jobs else None)
ok = all([ok_count, ok_state, ok_link, ok_partner, ok_quoted])
print("T2:", "PASS" if ok else "FAIL")
results["T2"] = ok
t2_job = jobs[0] if jobs else None
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T3 - Lead -> Confirmed activates the linked pending job")
print("=" * 70)
if t2_job:
    lead = t2_job.crm_lead_id
    lead.write({"stage_id": confirmed.id})
    t2_job.invalidate_recordset()
    ok = t2_job.state == "active"
    print("T3: state after Confirmed=", t2_job.state)
    print("T3:", "PASS" if ok else "FAIL")
    results["T3"] = ok
else:
    print("T3 SKIP: no job from T2")
    results["T3"] = None
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T4 - Fresh lead -> active=False without going Quote Sent")
print("    Expect: no job, no error, chatter log only")
print("=" * 70)
lead = mk_lead("T4")
try:
    lead.write({"active": False})
    no_jobs = len(lead.commercial_job_ids) == 0
    print("T4: jobs after lost=", len(lead.commercial_job_ids),
          " active=", lead.active)
    ok = no_jobs and not lead.active
    print("T4:", "PASS" if ok else "FAIL")
    results["T4"] = ok
except Exception as e:
    print("T4 FAIL: unexpected", type(e).__name__, ":", e)
    results["T4"] = False
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T5 - Lead Quote Sent -> active=False, then wizard archives the job")
print("=" * 70)
lead = mk_lead("T5")
lead.write({"stage_id": quote_sent.id})
job = lead.commercial_job_ids
print("T5 setup: created job", job.name, "state=", job.state)
# Move to lost via active=False (no lost_reason_id set)
lead.write({"active": False})
print("T5 mid: job state after active=False (no lost_reason_id)=", job.state,
      " (expected: pending — wizard needed)")
wizard = env["commercial.job.loss.wizard"].create({
    "lead_id": lead.id,
    "loss_reason": "T5 — competitor undercut on price",
    "lost_to_competitor": "AcmeEvents",
})
print("T5 wizard: job_ids resolved =", [j.name for j in wizard.job_ids])
wizard.action_confirm()
job.invalidate_recordset()
ok_state = job.state == "archived"
ok_reason = job.loss_reason and "competitor undercut" in job.loss_reason
ok_compet = job.lost_to_competitor == "AcmeEvents"
print("T5: state=", job.state, " loss_reason=", job.loss_reason,
      " competitor=", job.lost_to_competitor)
ok = ok_state and ok_reason and ok_compet
print("T5:", "PASS" if ok else "FAIL")
results["T5"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T6 - write() with unrelated key does not trigger any handler")
print("=" * 70)
lead = mk_lead("T6")
lead.write({"stage_id": quote_sent.id})
job = lead.commercial_job_ids
created_at = job.create_date
# Write an unrelated field — should not double-create or do anything
lead.write({"description": "noise"})
lead.write({"expected_revenue": 6000.0})
jobs_after = lead.commercial_job_ids
ok_no_dup = len(jobs_after) == 1
ok_same = jobs_after[0].create_date == created_at
print("T6: jobs after unrelated writes =", len(jobs_after),
      " same create_date:", ok_same)
ok = ok_no_dup and ok_same
print("T6:", "PASS" if ok else "FAIL")
results["T6"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T7 - Quote Sent -> Confirmed rapidly: no double-create, no double-activate")
print("=" * 70)
lead = mk_lead("T7")
lead.write({"stage_id": quote_sent.id})
n1 = len(lead.commercial_job_ids)
lead.write({"stage_id": confirmed.id})
n2 = len(lead.commercial_job_ids)
job = lead.commercial_job_ids
# Try moving stage again (no-op for activation; pending->active already happened)
try:
    lead.write({"stage_id": confirmed.id})
    n3 = len(lead.commercial_job_ids)
    same = job.state == "active"
    print("T7: after Quote Sent jobs=", n1, " after Confirmed jobs=", n2,
          " re-Confirmed jobs=", n3, " state=", job.state)
    ok = (n1 == 1) and (n2 == 1) and (n3 == 1) and same
    print("T7:", "PASS" if ok else "FAIL")
    results["T7"] = ok
except Exception as e:
    print("T7 FAIL: rapid transition raised", type(e).__name__, ":", e)
    results["T7"] = False
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T8 - Lead w/o date_deadline -> Quote Sent: TBD venue + today+14,")
print("     needs_attention=True, mail.activity created")
print("=" * 70)
lead = mk_lead("T8")
# Make sure salesperson is set so the activity has an owner
lead.write({"user_id": env.uid, "date_deadline": False})
lead.write({"stage_id": quote_sent.id})
job = lead.commercial_job_ids
expected_event = fields.Date.add(fields.Date.today(), days=14)
ok_event = job.event_date == expected_event
ok_placeholder = job.event_date_is_placeholder is True
ok_venue = job.venue_id == tbd_venue
ok_needs = job.needs_attention is True
ok_reason = job.needs_attention_reason and "placeholder" in job.needs_attention_reason
activity = env["mail.activity"].search([
    ("res_model", "=", "commercial.job"),
    ("res_id", "=", job.id),
])
ok_activity = bool(activity)
ok_summary = activity and ("Fix event date" in activity[0].summary or "venue on" in activity[0].summary)
print("T8: event_date=", job.event_date, " (expected", expected_event, ")")
print("    placeholder flag=", job.event_date_is_placeholder,
      " venue=", job.venue_id.name, " needs_attention=", job.needs_attention)
print("    reason=", job.needs_attention_reason)
print("    activities=", len(activity), " summary=",
      activity[0].summary if activity else None)
ok = all([ok_event, ok_placeholder, ok_venue, ok_needs, ok_reason,
          ok_activity, ok_summary])
print("T8:", "PASS" if ok else "FAIL")
results["T8"] = ok
t8_job = job
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T9 - Update only venue_id -> needs_attention stays True")
print("=" * 70)
real_venue = env["res.partner"].search([
    ("is_venue", "=", True),
    ("id", "!=", tbd_venue.id),
], limit=1)
if not real_venue:
    real_venue = env["res.partner"].create({
        "name": "T9 Real Venue", "is_company": True, "is_venue": True,
    })
t8_job.write({"venue_id": real_venue.id})
t8_job.invalidate_recordset()
# event_date placeholder still True so needs_attention should stay True
ok = (t8_job.needs_attention is True
      and t8_job.venue_id == real_venue
      and t8_job.event_date_is_placeholder is True)
print("T9: venue=", t8_job.venue_id.name,
      " event_date_placeholder=", t8_job.event_date_is_placeholder,
      " needs_attention=", t8_job.needs_attention,
      " reason=", t8_job.needs_attention_reason)
print("T9:", "PASS" if ok else "FAIL")
results["T9"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("T10 - Update event_date -> needs_attention auto-clears")
print("=" * 70)
t8_job.write({"event_date": fields.Date.add(fields.Date.today(), days=60)})
t8_job.invalidate_recordset()
ok = (t8_job.needs_attention is False
      and t8_job.event_date_is_placeholder is False
      and not t8_job.needs_attention_reason)
print("T10: event_date=", t8_job.event_date,
      " placeholder=", t8_job.event_date_is_placeholder,
      " needs_attention=", t8_job.needs_attention,
      " reason=", t8_job.needs_attention_reason)
print("T10:", "PASS" if ok else "FAIL")
results["T10"] = ok
env.cr.commit()

# ============================================================
print()
print("=" * 70)
print("FULL SUMMARY")
print("=" * 70)
order = ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9", "T10")
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
