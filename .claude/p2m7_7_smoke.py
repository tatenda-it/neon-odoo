"""P2.M7.7 smoke — final role visibility hardening."""
print("=" * 72)
print("SETUP")
print("=" * 72)

sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
crew_leader = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
crew_only = env["res.users"].search([("login", "=", "p2m75_crew")], limit=1)
munashe = env["res.users"].search([("login", "=", "munashe@neonhiring.co.zw")], limit=1)

# p2m75_sales was migrated to crew_leader-only in P2.M7.6; re-grant
# neon_jobs_user so this test exercises the sales-rep path.
user_grp = env.ref("neon_jobs.group_neon_jobs_user")
leader_grp = env.ref("neon_jobs.group_neon_jobs_crew_leader")
sales.write({
    "groups_id": [(4, user_grp.id), (3, leader_grp.id)],
})
env.cr.commit()

print("sales (p2m75_sales) groups:",
      [g.name for g in sales.groups_id
       if g.category_id.name in ("Neon Operations", "Sales", "Accounting")])
print("manager (p2m75_mgr) groups:",
      [g.name for g in manager.groups_id
       if g.category_id.name in ("Neon Operations", "Sales", "Accounting")])
print("crew_leader (p2m75_lead) groups:",
      [g.name for g in crew_leader.groups_id
       if g.category_id.name in ("Neon Operations", "Sales", "Accounting")])
print("crew_only (p2m75_crew) groups:",
      [g.name for g in crew_only.groups_id
       if g.category_id.name in ("Neon Operations", "Sales", "Accounting")])

# Look up the menus we'll test
SALES = env.ref("sale.sale_menu_root")
CRM = env.ref("crm.crm_menu_root")
INVOICING = env.ref("account.menu_finance")
OPS_DASH = env.ref("neon_jobs.menu_operations_dashboard")
MY_SCHED = env.ref("neon_jobs.menu_my_schedule")
MY_CAL = env.ref("neon_jobs.menu_my_calendar")
LIVE_PIPE = env.ref("neon_jobs.menu_calendar_live_pipeline")
ALL_EVENTS = env.ref("neon_jobs.menu_calendar_all_events")
COMM_JOBS = env.ref("neon_jobs.menu_commercial_job")
MASTER = env.ref("neon_jobs.menu_master_contract")
CREW_ASSIGN = env.ref("neon_jobs.menu_crew_assignments")
DASHBOARDS = env.ref("spreadsheet_dashboard.spreadsheet_dashboard_menu_root")

ALL_MENU_IDS = [
    SALES.id, CRM.id, INVOICING.id,
    OPS_DASH.id, MY_SCHED.id, MY_CAL.id,
    LIVE_PIPE.id, ALL_EVENTS.id, COMM_JOBS.id, MASTER.id, CREW_ASSIGN.id,
    DASHBOARDS.id,
]


def visible_to(user):
    """Return set of menu ids from ALL_MENU_IDS visible to user."""
    found = env["ir.ui.menu"].with_user(user).search([("id", "in", ALL_MENU_IDS)])
    return set(found.ids)


results = {}

# ============================================================
print()
print("=" * 72)
print("T34 - Sales user sees Sales menu")
print("=" * 72)
v = visible_to(sales)
ok = SALES.id in v
print("T34: SALES.id in visible?", ok)
print("T34:", "PASS" if ok else "FAIL")
results["T34"] = ok

# ============================================================
print()
print("=" * 72)
print("T35 - Sales user sees CRM menu")
print("=" * 72)
v = visible_to(sales)
ok = CRM.id in v
print("T35: CRM.id in visible?", ok)
print("T35:", "PASS" if ok else "FAIL")
results["T35"] = ok

# ============================================================
print()
print("=" * 72)
print("T36 - Sales user does NOT see Invoicing (manager-only per D4)")
print("=" * 72)
v = visible_to(sales)
ok = INVOICING.id not in v
print("T36: INVOICING in visible?", INVOICING.id in v, " (want False)")
print("T36:", "PASS" if ok else "FAIL")
results["T36"] = ok

# ============================================================
print()
print("=" * 72)
print("T37 - Crew Leader does NOT see Sales / CRM (Invoicing now reachable per P6.M5)")
print("=" * 72)
# P6.M5 deliberately extended account.menu_finance's groups_id to
# include group_neon_jobs_crew_leader so Ranganai (Lead Tech) can
# reach the Cost Lines submenu under Customers. Sales + CRM remain
# off-limits to crew_leader; only Invoicing's reach was widened.
# Test asserts the unchanged invariants and acknowledges the M5
# design change.
v = visible_to(crew_leader)
ok = (SALES.id not in v) and (CRM.id not in v)
print("T37: Sales?", SALES.id in v, " CRM?", CRM.id in v,
      " (Sales+CRM want False; Invoicing intentionally reachable per P6.M5)")
print("T37: Invoicing visible (P6.M5 design):", INVOICING.id in v)
print("T37:", "PASS" if ok else "FAIL")
results["T37"] = ok

# ============================================================
print()
print("=" * 72)
print("T38 - Crew Leader CAN see Operations sub-menus")
print("=" * 72)
v = visible_to(crew_leader)
ok = (OPS_DASH.id in v
      and MY_SCHED.id in v
      and LIVE_PIPE.id in v
      and ALL_EVENTS.id in v
      and COMM_JOBS.id in v
      and MASTER.id in v
      and CREW_ASSIGN.id in v
      and MY_CAL.id not in v)
print("T38: ops_dash?", OPS_DASH.id in v, " my_sched?", MY_SCHED.id in v,
      " live_pipe?", LIVE_PIPE.id in v, " all_events?", ALL_EVENTS.id in v,
      " comm_jobs?", COMM_JOBS.id in v, " master?", MASTER.id in v,
      " crew_assign?", CREW_ASSIGN.id in v,
      " my_cal?", MY_CAL.id in v, "(want False)")
print("T38:", "PASS" if ok else "FAIL")
results["T38"] = ok

# ============================================================
print()
print("=" * 72)
print("T39 - Crew does NOT see leaked Operations sub-menus")
print("=" * 72)
v = visible_to(crew_only)
ok = (LIVE_PIPE.id not in v
      and ALL_EVENTS.id not in v
      and COMM_JOBS.id not in v
      and MASTER.id not in v
      and CREW_ASSIGN.id not in v
      and OPS_DASH.id not in v
      and MY_SCHED.id in v
      and MY_CAL.id in v)
print("T39: live_pipe?", LIVE_PIPE.id in v,
      " all_events?", ALL_EVENTS.id in v,
      " comm_jobs?", COMM_JOBS.id in v,
      " master?", MASTER.id in v,
      " crew_assign?", CREW_ASSIGN.id in v,
      " ops_dash?", OPS_DASH.id in v, "(all want False)")
print("     my_sched?", MY_SCHED.id in v,
      " my_cal?", MY_CAL.id in v, "(want True)")
print("T39:", "PASS" if ok else "FAIL")
results["T39"] = ok

# ============================================================
print()
print("=" * 72)
print("T40 - Manager sees everything")
print("=" * 72)
v = visible_to(manager)
must_see = [SALES.id, CRM.id, INVOICING.id, OPS_DASH.id, LIVE_PIPE.id,
            ALL_EVENTS.id, COMM_JOBS.id, MASTER.id, CREW_ASSIGN.id,
            DASHBOARDS.id]
missing = [m for m in must_see if m not in v]
ok = not missing
print("T40: missing for manager =", missing or "none")
print("T40:", "PASS" if ok else "FAIL")
results["T40"] = ok

# ============================================================
print()
print("=" * 72)
print("T41 - Implication chain: sales user has sales_team.salesman_all_leads")
print("=" * 72)
salesman = env.ref("sales_team.group_sale_salesman_all_leads")
ok = salesman in sales.groups_id and salesman in munashe.groups_id
print("T41: p2m75_sales has salesman_all_leads?", salesman in sales.groups_id)
print("     munashe@ has salesman_all_leads?", salesman in munashe.groups_id)
print("T41:", "PASS" if ok else "FAIL")
results["T41"] = ok

# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T34", "T35", "T36", "T37", "T38", "T39", "T40", "T41"]
for k in order:
    v_ = results.get(k)
    mark = "PASS" if v_ is True else ("SKIP" if v_ is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))
