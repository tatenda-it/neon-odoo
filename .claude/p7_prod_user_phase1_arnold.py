"""Phase 1 -- create arnold.m only. Single-record test before
batch. Commits the transaction so Tatenda can verify via UI."""
base_user_id = env.ref("base.group_user").id
jobs_crew_id = env.ref("neon_jobs.group_neon_jobs_crew").id

# Defensive: re-check no collision (paranoia after pre-flight).
existing = env["res.users"].sudo().with_context(
    active_test=False).search(
    [("login", "=", "arnold.m@neonhiring.co.zw")])
if existing:
    print("STOP: arnold.m@neonhiring.co.zw already exists; "
          f"uid={existing.id}")
    raise SystemExit(1)

u = env["res.users"].create({
    "name":      "Arnold M",
    "login":     "arnold.m@neonhiring.co.zw",
    "password":  "Neon2026!",
    "groups_id": [(6, 0, [base_user_id, jobs_crew_id])],
})
env.cr.commit()

print(f"Created uid={u.id}")
print(f"  login={u.login}")
print(f"  name={u.name}")
print(f"  active={u.active}")
print(f"  company={u.company_id.name}")
print(f"  groups (all, including implied):")
for g in u.groups_id.sorted("name"):
    print(f"    - {g.name}  ({g.category_id.name or 'no category'})")

# Final sanity assertions.
g_base = env.ref("base.group_user")
g_crew = env.ref("neon_jobs.group_neon_jobs_crew")
assert u.active, "User not active"
assert g_base in u.groups_id, "base.group_user missing"
assert g_crew in u.groups_id, "neon_jobs.group_neon_jobs_crew missing"
assert u.company_id.id == 1, f"Wrong company: {u.company_id.id}"
print()
print("All assertions passed. Tatenda -- verify via Settings > Users now.")
