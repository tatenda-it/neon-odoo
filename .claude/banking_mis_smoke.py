"""MIS_BUILDER smoke -- the 3 financial reports render + tie out arithmetically.
Runs in odoo shell. Verifies the OCA mis_builder templates compute against Neon's
chart (render) and the fundamental tie-out (Assets = Liabilities + P&L profit).
Accounting-correctness of the line mappings is Robin/bookkeeper sign-off, NOT this.
"""
results = []


def chk(n, c, d=""):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + "%-50s %s" % (n, d))


def cell0(r):
    cs = r.get("cells") or []
    return cs[0].get("val") if cs and cs[0].get("val") is not None else None


def rows(xmlid):
    inst = env.ref(xmlid)
    return {r.get("label"): cell0(r) for r in inst.compute().get("body", [])}


pl = rows("neon_mis_reports.mis_instance_pl")
chk("Profit & Loss renders", len(pl) > 0, "rows=%d" % len(pl))
bs = rows("neon_mis_reports.mis_instance_bs")
chk("Balance Sheet renders", len(bs) > 0, "rows=%d" % len(bs))
cf = rows("mis_builder_cash_flow.mis_instance_cash_flow")
chk("Cash Flow renders", len(cf) > 0, "rows=%d" % len(cf))

assets, liab, profit = bs.get("Assets"), bs.get("Liabilities"), pl.get("Profit")
if assets is not None and liab is not None and profit is not None:
    chk("BS ties: Assets == Liabilities + P&L profit",
        abs(assets - (liab + profit)) < 0.01,
        "%.2f == %.2f + %.2f" % (assets, liab, profit))
else:
    chk("BS tie-out values present", False,
        "assets=%s liab=%s profit=%s" % (assets, liab, profit))

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
