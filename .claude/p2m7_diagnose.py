"""P2.M7 bug 1 diagnosis — browser vs shell behaviour."""
from odoo import fields

# Ensure we have at least one fixture so computes have something to find
env.user.write({
    "groups_id": [(4, env.ref("neon_jobs.group_neon_jobs_manager").id)],
})

# Create a fixture that should appear in gate_issues
client = env["res.partner"].search([("is_company", "=", True),
                                      ("is_venue", "=", False)], limit=1)
venue = env["res.partner"].search([("is_venue", "=", True),
                                     ("name", "not like", "TBD%")], limit=1)
fix = env["commercial.job"].create({
    "partner_id": client.id, "venue_id": venue.id,
    "event_date": fields.Date.add(fields.Date.today(), days=30),
    "currency_id": env.company.currency_id.id,
})
fix.write({"state": "active", "soft_hold_until": False, "gate_result": "reject"})
env.cr.commit()

print("Fixture:", fix.name, "state=", fix.state, "gate=", fix.gate_result)

print()
print("=" * 60)
print("PATH A — shell pattern (create + read):")
print("=" * 60)
db = env["commercial.job.dashboard"].create({})
print("After create({}), id =", db.id)
print("  gate_issues_count =", db.gate_issues_count)
print("  gate_issues_top3.ids =", db.gate_issues_top3.ids)

print()
print("=" * 60)
print("PATH B — browser pattern (default_get + read on unsaved form):")
print("=" * 60)
# Simulate what the web client does for a new-form action without res_id
defaults = env["commercial.job.dashboard"].default_get([
    "gate_issues_count", "soft_hold_count", "crew_gap_count",
    "needs_attention_count", "cash_flow_count",
    "gate_issues_top3", "soft_hold_top3",
])
print("default_get returned:", defaults)

print()
print("=" * 60)
print("PATH C — onchange-like dry record read:")
print("=" * 60)
new_rec = env["commercial.job.dashboard"].new({})
print("new() id =", new_rec.id, "  (NewId, never persisted)")
print("  gate_issues_count =", new_rec.gate_issues_count)
print("  gate_issues_top3.ids =", new_rec.gate_issues_top3.ids)

print()
print("=" * 60)
print("PATH D — read() on persisted record:")
print("=" * 60)
data = db.read([
    "gate_issues_count", "soft_hold_count", "crew_gap_count",
    "needs_attention_count", "cash_flow_count",
    "gate_issues_top3", "soft_hold_top3",
])
print("read() returned:", data)
