from odoo import fields
from odoo.exceptions import UserError

# Setup fixtures (idempotent)
venue = env["res.partner"].search([("name", "=", "Smoke Test Venue")], limit=1)
if not venue:
    venue = env["res.partner"].create({
        "name": "Smoke Test Venue", "is_company": True, "is_venue": True,
    })
client = env["res.partner"].search(
    [("is_company", "=", True), ("is_venue", "=", False),
     ("name", "!=", "Smoke Test Venue")], limit=1)
env.cr.commit()

print("=" * 70)
print("T4 RE-RUN - Manager bypass on action_archive_lost")
print("=" * 70)

mgr_group = env.ref("neon_jobs.group_neon_jobs_manager")
mgr_user = env["res.users"].search([("login", "ilike", "robin@")], limit=1)
if not mgr_user:
    mgr_user = env["res.users"].search([("login", "ilike", "munashe@")], limit=1)

if not mgr_user:
    print("T4 SKIP: no robin@ or munashe@ user found")
else:
    mgr_user.write({"groups_id": [(4, mgr_group.id)]})
    print("Promoted", mgr_user.name, "(", mgr_user.login, ") to manager")
    print("Has manager group?",
          mgr_user.has_group("neon_jobs.group_neon_jobs_manager"))

    job = env["commercial.job"].with_user(mgr_user).create({
        "partner_id": client.id, "venue_id": venue.id,
        "event_date": fields.Date.today(),
    })
    print("Created job", job.name, "loss_reason=", repr(job.loss_reason))

    try:
        job.action_archive_lost()
        if job.state == "archived":
            print("T4 PASS: manager archived without loss_reason; state=", job.state)
        else:
            print("T4 FAIL: state =", job.state, "(expected archived)")
    except UserError as e:
        print("T4 FAIL: still raising UserError -", str(e)[:120])
    except Exception as e:
        print("T4 FAIL:", type(e).__name__, "-", str(e)[:120])

    # Also confirm a non-manager session still gets blocked
    non_mgr = env["res.users"].search([("login", "ilike", "tatenda@")], limit=1)
    if non_mgr and not non_mgr.has_group("neon_jobs.group_neon_jobs_manager"):
        job2 = env["commercial.job"].with_user(non_mgr).create({
            "partner_id": client.id, "venue_id": venue.id,
            "event_date": fields.Date.today(),
        })
        try:
            job2.action_archive_lost()
            print("T4 REGRESSION: non-manager archived without loss_reason — security broken")
        except UserError:
            print("T4 PASS regression check: non-manager still blocked")

env.cr.rollback()
print("Rolled back T4 transaction.")
