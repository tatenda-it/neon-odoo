"""neon_banking_statement smoke -- per-account running-ledger READ over the
existing ledger. [TEST-BS] posted fixtures on Petty Cash, single transaction,
rollback at end (no commit). Asserts running balance, counterpart code, and
the zero-row case (no empty-set crash)."""
from odoo.exceptions import AccessError  # noqa: F401

results = []


def chk(n, c, d=""):
    results.append((n, bool(c))); print(("  ok  " if c else "FAIL  ") + "%-46s %s" % (n, d))


AM = env["account.move"].sudo()
A = env["account.account"].sudo()
gj = env["account.journal"].sudo().search([("type", "=", "general")], limit=1)
petty = A.search([("code", "=", "101501")], limit=1)
bank = A.search([("code", "=", "101401")], limit=1)
exp = A.search([("code", "=", "613000")], limit=1)


def mk(d, label, dr, cr, counter):
    mv = AM.create({"move_type": "entry", "journal_id": gj.id, "date": d,
                    "ref": "[TEST-BS] " + label,
                    "line_ids": [(0, 0, {"account_id": petty.id, "name": label, "debit": dr, "credit": cr}),
                                 (0, 0, {"account_id": counter.id, "name": label, "debit": cr, "credit": dr})]})
    mv.action_post()
    return mv


mk("2026-06-01", "Opening", 500, 0, bank)
mk("2026-06-02", "Replenish", 200, 0, bank)
mk("2026-06-03", "Stationery", 0, 80, exp)
mk("2026-06-04", "Snacks", 0, 50, exp)

lines = env["account.move.line"].sudo().search(
    [("account_id.code", "=", "101501"), ("parent_state", "=", "posted")], order="date, id")
bals = lines.mapped("neon_running_balance")
chk("running balance cumulative + ordered", bals == [500.0, 700.0, 620.0, 570.0], "=%s" % bals)
codes = lines.mapped("neon_counterpart_code")
chk("counterpart code = the other account", codes == ["101401", "101401", "613000", "613000"], "=%s" % codes)
chk("Dr/Cr map to debit/credit", lines.mapped("debit") == [500.0, 200.0, 0.0, 0.0]
    and lines.mapped("credit") == [0.0, 0.0, 80.0, 50.0])

# zero-row: an account with no lines -> compute must not crash (empty-IN class)
zlines = env["account.move.line"].sudo().search(
    [("account_id.code", "=", "101402"), ("parent_state", "=", "posted")])
try:
    zlines._compute_neon_running_balance()
    chk("zero-row compute runs clean (no empty-set crash)", True, "lines=%d" % len(zlines))
except Exception as e:
    chk("zero-row compute runs clean (no empty-set crash)", False, str(e)[:80])

# read-only: the statement views carry create/edit/delete = 0
v = env.ref("neon_banking_statement.view_neon_statement_tree")
chk("statement view is read-only", 'create="0"' in v.arch and 'edit="0"' in v.arch)

env.cr.rollback()
passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
