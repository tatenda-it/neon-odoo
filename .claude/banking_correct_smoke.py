"""BUILD 4 correct-entry smoke -- runs in odoo shell, ROLLS BACK. Logs an
expense via the wizard, corrects it, and asserts the audit-clean trail:
original stays posted (no deletion), reversal POSTED + linked, corrected posted,
original+reversal net zero on cash; payments are refused (guard-respect);
amount<=0 blocked.
"""
results = []


def chk(n, c, d=""):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + "%-50s %s" % (n, d))


petty = env["account.account"].search([("code", "=", "101501")], limit=1)
exp = env["account.account"].search([("code", "=", "613000")], limit=1)


def seed(ref, amt=100.0):
    env["neon.cash.expense.wizard"].create({
        "cash_account_id": petty.id, "expense_account_id": exp.id, "amount": amt,
        "tax_treatment": "exclusive", "description": ref}).action_save()
    return env["account.move"].search([("ref", "=", ref)], limit=1)


orig = seed("[TEST-C4] orig")
cw = env["neon.cash.correct.wizard"].with_context(default_original_move_id=orig.id).create({})
chk("prefill detects cash + counterpart + outflow",
    cw.cash_account_id.code == "101501" and cw.counterpart_account_id.code == "613000" and cw.is_outflow,
    "cash=%s cp=%s out=%s" % (cw.cash_account_id.code, cw.counterpart_account_id.code, cw.is_outflow))
cw.write({"amount": 80.0, "description": "[TEST-C4] corrected"})
cw.action_post_correction()
rev = orig.reversal_move_id
corr = env["account.move"].search([("ref", "=", "[TEST-C4] corrected")], limit=1)
chk("original still posted (NO deletion)", orig.exists() and orig.state == "posted")
chk("reversal POSTED + linked to original", rev.state == "posted" and rev.reversed_entry_id == orig)
chk("corrected entry posted at new amount", corr.state == "posted" and any(abs(l.debit - 80.0) < 0.01 for l in corr.line_ids))
net = sum((orig.line_ids + rev.line_ids).filtered(lambda l: l.account_id.code == "101501").mapped(lambda l: l.debit - l.credit))
chk("original + reversal net ZERO on cash", abs(net) < 0.01, "net=%s" % net)

# guard-respect: a payment move is refused (so the SCH- register guard isn't bypassed)
j = env["account.journal"].search([("default_account_id.code", "=", "101401"), ("type", "=", "bank")], limit=1)
vendor = env["res.partner"].search([], limit=1)
pay = env["account.payment"].create({"payment_type": "outbound", "partner_type": "supplier",
                                      "partner_id": vendor.id, "journal_id": j.id, "amount": 50.0})
pay.action_post()
refused = False
try:
    env["neon.cash.correct.wizard"].with_context(default_original_move_id=pay.move_id.id).create({})
except Exception:
    refused = True
chk("payment move refused (guard-respect)", refused)

# amount<=0 blocked on a fresh entry
o2 = seed("[TEST-C4] orig2")
blocked = False
try:
    z = env["neon.cash.correct.wizard"].with_context(default_original_move_id=o2.id).create({})
    z.write({"amount": 0.0})
    z.action_post_correction()
except Exception:
    blocked = True
chk("amount<=0 blocked", blocked)

env.cr.rollback()
passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
