"""Phase 9 cleanup — remove P4.M9 production smoke seed data.

WHAT THIS REMOVES
=================
Every record created by `.claude/seed_p4m9_production_smoke.py`:

  * commercial.job records whose equipment_summary contains
    "[TEST-DELETE]" — cascade removes their event_jobs, scope_changes,
    feedback records, and the action.centre.items bound to them.
  * Orphaned action.centre.item records (source_id no longer resolves)
    that survived the FK cascade.
  * res.users with login prefix "p2m75_" — tries unlink, falls back
    to archive (active=False) if FK constraints block.
  * res.partner records with name containing "[TEST-DELETE]".

Idempotent — running twice is a no-op the second time (reports zero
counts).

INVOCATION
==========
  docker compose exec -T odoo odoo shell -d neon_crm \\
      < .claude/teardown_p4m9_dummy_data.py

WHEN TO RUN
===========
Phase 9 cutover, before Robin's team starts using the system for real.
Companion to `.claude/seed_p4m9_production_smoke.py`.
"""
MARKER = "[TEST-DELETE]"
USER_LOGIN_PREFIX = "p2m75_"

results = {
    "items_unlinked_via_cascade": 0,
    "items_unlinked_orphaned":    0,
    "scope_changes_unlinked":     0,
    "feedbacks_unlinked":         0,
    "event_jobs_unlinked":        0,
    "jobs_unlinked":              0,
    "users_unlinked":             0,
    "users_archived":             0,
    "partners_unlinked":          0,
}


print("=" * 72)
print("P4.M9 PRODUCTION TEARDOWN — START")
print("=" * 72)


# ============================================================
print()
print("Step 1: count current state before deletion")
print("-" * 72)
Job = env["commercial.job"].sudo()
EventJob = env["commercial.event.job"].sudo()
Scope = env["commercial.scope.change"].sudo()
Feedback = env["commercial.event.feedback"].sudo()
Item = env["action.centre.item"].sudo()
Users = env["res.users"].sudo()
Partners = env["res.partner"].sudo()

jobs = Job.search([("equipment_summary", "ilike", MARKER)])
event_jobs = EventJob.search([("commercial_job_id", "in", jobs.ids)])
scope_changes = Scope.search(
    [("event_job_id", "in", event_jobs.ids)])
feedbacks = Feedback.search(
    [("event_job_id", "in", event_jobs.ids)])
# Items linked to any of the above (polymorphic source)
src_models = env["ir.model"].sudo().search([
    ("model", "in", (
        "commercial.job",
        "commercial.event.job",
        "commercial.scope.change",
        "commercial.event.feedback",
    )),
])
items_to_cascade = Item.search([
    "|", "|", "|",
    "&", ("source_model_id.model", "=", "commercial.job"),
         ("source_id", "in", jobs.ids),
    "&", ("source_model_id.model", "=", "commercial.event.job"),
         ("source_id", "in", event_jobs.ids),
    "&", ("source_model_id.model", "=", "commercial.scope.change"),
         ("source_id", "in", scope_changes.ids),
    "&", ("source_model_id.model", "=", "commercial.event.feedback"),
         ("source_id", "in", feedbacks.ids),
])
users = Users.search([("login", "=like", USER_LOGIN_PREFIX + "%")])
test_partners = Partners.search(
    [("name", "ilike", MARKER)])

print("  to delete:")
print("    commercial.job:                    ", len(jobs))
print("    commercial.event.job (cascade):    ", len(event_jobs))
print("    commercial.scope.change (cascade): ", len(scope_changes))
print("    commercial.event.feedback (cascade):", len(feedbacks))
print("    action.centre.item (bound):        ", len(items_to_cascade))
print("    res.users (p2m75_*):               ", len(users))
print("    res.partner ([TEST-DELETE]):       ", len(test_partners))


# ============================================================
print()
print("Step 2: unlink action.centre.items bound to seed records")
print("-" * 72)
# Doing this explicitly first because the polymorphic source link
# is not a real FK — Postgres won't cascade it. We delete the
# items BEFORE deleting their sources so the unlink runs cleanly.
results["items_unlinked_via_cascade"] = len(items_to_cascade)
items_to_cascade.unlink()
print("  unlinked", results["items_unlinked_via_cascade"], "items")
env.cr.commit()


# ============================================================
print()
print("Step 3: unlink scope_changes + feedbacks + event_jobs")
print("-" * 72)
# Defensive: walk down explicitly rather than relying on
# ondelete='cascade' (which IS set on these FKs, but being explicit
# makes the teardown report transparent).
results["scope_changes_unlinked"] = len(scope_changes)
scope_changes.unlink()
print("  scope_changes:  ", results["scope_changes_unlinked"])

results["feedbacks_unlinked"] = len(feedbacks)
feedbacks.unlink()
print("  feedbacks:      ", results["feedbacks_unlinked"])

results["event_jobs_unlinked"] = len(event_jobs)
event_jobs.unlink()
print("  event_jobs:     ", results["event_jobs_unlinked"])

env.cr.commit()


# ============================================================
print()
print("Step 4: unlink commercial.job records")
print("-" * 72)
results["jobs_unlinked"] = len(jobs)
jobs.unlink()
print("  jobs:", results["jobs_unlinked"])
env.cr.commit()


# ============================================================
print()
print("Step 5: sweep orphaned action.centre.items")
print("-" * 72)
# Any item left behind whose source_id no longer resolves on its
# source_model_id. Should be zero if step 2 ran clean, but the
# polymorphic source means we can't rely on Postgres to enforce
# referential integrity — sweep defensively.
all_items = Item.search([("source_id", "!=", 0)])
orphans = Item.browse()
for it in all_items:
    if not it.source_model_id:
        orphans |= it
        continue
    model_name = it.source_model_id.model
    if model_name not in env:
        orphans |= it
        continue
    if not env[model_name].sudo().browse(it.source_id).exists():
        orphans |= it
results["items_unlinked_orphaned"] = len(orphans)
orphans.unlink()
print("  orphans:", results["items_unlinked_orphaned"])
env.cr.commit()


# ============================================================
print()
print("Step 6: unlink (or archive) p2m75_* users")
print("-" * 72)
for u in users:
    login = u.login
    try:
        u.unlink()
        results["users_unlinked"] += 1
        print("  unlinked", login)
    except Exception as e:
        # FK-block fallback — archive instead so the user disappears
        # from the UI but the audit trails referencing them stay
        # intact.
        try:
            u.write({"active": False})
            results["users_archived"] += 1
            print("  archived (unlink blocked) %s: %s" % (
                login, str(e)[:60]))
        except Exception as e2:
            print("  FAILED to remove %s: %s" % (
                login, str(e2)[:80]))
env.cr.commit()


# ============================================================
print()
print("Step 7: unlink test partners")
print("-" * 72)
for p in test_partners:
    try:
        p.unlink()
        results["partners_unlinked"] += 1
        print("  unlinked", p.name)
    except Exception as e:
        print("  WARN partner %s unlink failed: %s" % (
            p.name, str(e)[:80]))
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("TEARDOWN COMPLETE — counts")
print("=" * 72)
for k, v in results.items():
    print("  %-32s %d" % (k, v))

# Post-teardown sanity check
print()
print("Post-teardown state (should all be 0):")
print("  jobs with [TEST-DELETE]:    ",
      Job.search_count([("equipment_summary", "ilike", MARKER)]))
print("  p2m75_* users (active):     ",
      Users.search_count([("login", "=like", USER_LOGIN_PREFIX + "%")]))
print("  partners with [TEST-DELETE]:",
      Partners.search_count([("name", "ilike", MARKER)]))

env.cr.commit()
