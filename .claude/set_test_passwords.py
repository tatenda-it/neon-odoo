"""Set known passwords on P2.M7.x test users for browser-tier testing."""
logins = [
    "p2m75_sales", "p2m75_mgr", "p2m75_lead", "p2m75_crew",
    "p2m75_other", "p2m75_t20",
    "p2m7_crew", "p2m7_crew_only", "p2m7_fresh",
]
users = env["res.users"].search([("login", "in", logins)])
print("Found users:")
for u in users.sorted("login"):
    print("  id=", u.id, " login=", u.login, " name=", u.name)
# Using ORM write so Odoo hashes the password correctly. Raw SQL on
# res_users.password would store plaintext and break login.
users.write({"password": "test123"})
env.cr.commit()
print()
print("Set password 'test123' on", len(users), "users.")
