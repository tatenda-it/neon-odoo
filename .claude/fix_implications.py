# Set the implied_ids edges that security.xml couldn't because the
# group records are inside <data noupdate="1">. Writing via ORM also
# auto-propagates the implied groups to all existing users in the
# source group.
g_user = env.ref('neon_jobs.group_neon_jobs_user')
g_manager = env.ref('neon_jobs.group_neon_jobs_manager')
salesman = env.ref('sales_team.group_sale_salesman_all_leads')
sale_mgr = env.ref('sales_team.group_sale_manager')
billing = env.ref('account.group_account_invoice')

# Add edges if missing
def ensure(source, implied, label):
    if implied not in source.implied_ids:
        source.write({'implied_ids': [(4, implied.id)]})
        print(f"  added edge: {source.name} → {label}")
    else:
        print(f"  edge already present: {source.name} → {label}")

print("Setting implication edges:")
ensure(g_user, salesman, "salesman_all_leads")
ensure(g_manager, sale_mgr, "sale_manager")
ensure(g_manager, billing, "account.group_account_invoice")

env.cr.commit()
print()
print("Verifying group propagation on the 4 browser-smoke users:")
for login in ['p2m75_sales', 'p2m75_mgr', 'p2m75_lead', 'p2m75_crew']:
    u = env['res.users'].search([('login', '=', login)], limit=1)
    if not u:
        print(f"  {login}: NOT FOUND")
        continue
    has_salesman = salesman in u.groups_id
    has_sale_mgr = sale_mgr in u.groups_id
    has_billing = billing in u.groups_id
    print(f"  {login}: salesman_all_leads={has_salesman} "
          f"sale_manager={has_sale_mgr} billing={has_billing}")
