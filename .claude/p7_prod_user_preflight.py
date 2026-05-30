"""Pre-flight checks for prod tech-crew user creation.
Read-only. No writes. Safe to run multiple times."""
print("=" * 72)
print("PRE-FLIGHT 3 -- jobs_crew group existence")
print("=" * 72)
crew_group = env.ref(
    "neon_jobs.group_neon_jobs_crew", raise_if_not_found=False)
if not crew_group:
    print("STOP: neon_jobs.group_neon_jobs_crew NOT FOUND")
    print("neon_jobs module state:")
    print(env["ir.module.module"].search(
        [("name", "=", "neon_jobs")]).read(
        ["name", "state", "latest_version"]))
else:
    print(f"jobs_crew group OK: id={crew_group.id}")
    print(f"  category: {crew_group.category_id.name}")
    print(f"  current members: {len(crew_group.users)}")
    print(f"  implied_ids: {crew_group.implied_ids.mapped('name')}")
    base_user = env.ref("base.group_user")
    print(f"  -> base.group_user implied: "
          f"{base_user in crew_group.implied_ids}")

print()
print("=" * 72)
print("PRE-FLIGHT 4 -- collision check for 9 target logins")
print("=" * 72)
target_logins = [
    "arnold.m@neonhiring.co.zw",
    "john@neonhiring.co.zw",
    "bothwell@neonhiring.co.zw",
    "kelvin@neonhiring.co.zw",
    "stanley@neonhiring.co.zw",
    "kudzai.m@neonhiring.co.zw",
    "trymore@neonhiring.co.zw",
    "oswell@neonhiring.co.zw",
    "lovejoy@neonhiring.co.zw",
]
existing = env["res.users"].sudo().with_context(
    active_test=False).search([("login", "in", target_logins)])
existing_by_login = {u.login: u for u in existing}

print(f"{'target_login':<35} {'exists':<8} {'conflict_uid':<13} "
      f"{'active':<7}")
print("-" * 70)
collisions = 0
for login in target_logins:
    if login in existing_by_login:
        u = existing_by_login[login]
        print(f"{login:<35} {'YES':<8} {u.id:<13} {str(u.active):<7}")
        collisions += 1
    else:
        print(f"{login:<35} {'no':<8} {'-':<13} {'-':<7}")

print()
print(f"Total collisions: {collisions}/9")
if collisions:
    print("STOP -- collisions present. Report to Tatenda before proceeding.")
else:
    print("OK -- no collisions. Safe to proceed with Phase 1 (arnold.m).")

print()
print("=" * 72)
print("PRE-FLIGHT 5 -- prod company context")
print("=" * 72)
companies = env["res.company"].sudo().search([])
print(f"Companies in prod: {len(companies)}")
for c in companies:
    print(f"  id={c.id}  name={c.name!r}")
