"""Diagnose: what does kpi_cash return on this DB, and what USD bank
journals are present?"""
print("=" * 72)
print("USD bank journals (broad search)")
print("=" * 72)
Journal = env["account.journal"].sudo()
usd = env.ref("base.USD")
all_bank = Journal.search([("type", "in", ("bank", "cash"))])
print("All bank/cash journals on this DB:", len(all_bank))
for j in all_bank:
    print(f"  id={j.id} name={j.name} type={j.type} "
          f"currency_id={j.currency_id and j.currency_id.name or '(company)'} "
          f"company_currency={j.company_id.currency_id.name}")

print()
print("=" * 72)
print("Model search result")
print("=" * 72)
bc = Journal.search([
    ("type", "in", ("bank", "cash")),
    ("currency_id.name", "in", ("USD", False)),
])
print("dotted-domain result:", len(bc), bc.mapped("name"))

print()
print("=" * 72)
print("kpi_cash output (as p8a_director)")
print("=" * 72)
Users = env["res.users"]
u = Users.search([("login", "=", "p8a_director")], limit=1)
Dashboard = env["neon.dashboard"]
data = Dashboard.with_user(u).get_dashboard_data()
print("kpi_cash:", data["kpi"]["kpi_cash"])
