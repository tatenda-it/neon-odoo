"""neon_weekly_budget smoke -- model loads, totals compute, menu gated to
finance. [TEST-WB] fixtures, single transaction, rollback at end."""
results = []


def chk(n, c, d=""):
    results.append((n, bool(c))); print(("  ok  " if c else "FAIL  ") + "%-50s %s" % (n, d))


W = env["neon.weekly.budget"].sudo()
L = env["neon.weekly.budget.line"].sudo()
USD = env.ref("base.USD")

w = W.create({"week_start": "2026-06-22", "currency_id": USD.id})
L.create({"week_id": w.id, "date": "2026-06-22", "details": "[TEST-WB] NSSA",
          "amount": 120.0, "paid": 0.0, "status": "pending", "currency_id": USD.id})
L.create({"week_id": w.id, "date": "2026-06-23", "details": "[TEST-WB] Fuel",
          "amount": 80.0, "paid": 80.0, "status": "paid", "currency_id": USD.id})
w.invalidate_recordset()

chk("week name auto-computed", w.name == "Week of 2026-06-22", "name=%r" % w.name)
chk("total_planned sums line amounts", w.total_planned == 200.0, "=%s" % w.total_planned)
chk("total_paid sums line paid", w.total_paid == 80.0, "=%s" % w.total_paid)
chk("status selection has planned/pending/paid",
    {"planned", "pending", "paid"} <= {s[0] for s in L._fields["status"].selection})

# menu gated to finance roles, NOT base.group_user
m = env.ref("neon_weekly_budget.menu_weekly_budget_root")
mg = set(m.groups_id.ids)
chk("menu NOT gated to base.group_user (not universal)",
    env.ref("base.group_user").id not in mg)


def sees(login):
    u = env["res.users"].sudo().search([("login", "=", login)], limit=1)
    return bool(u and (mg & set(u.groups_id.ids)))


chk("menu visible to bookkeeper", sees("p2m75_book"))
chk("menu visible to approver", sees("p2m75_approver"))
chk("menu HIDDEN for sales", not sees("p2m75_sales"))
chk("menu HIDDEN for crew", not sees("p2m75_crew"))

env.cr.rollback()
passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
