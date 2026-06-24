"""P-A / BUILD-1 — operating-expense chart seed smoke.

"Odoo accounting as-is": neon_finance ADDS the operating-expense accounts
Odoo's generic 47-account chart lacks, tagging each with
``account.account.neon_source = 'seed_accounting'`` so they are distinguishable
from the generic chart (and from future Zoho-reconciled accounts). Proves:

  (A) the neon_source origin-tag field exists on account.account;
  (B) all 13 new expense accounts exist with the right code / name / type and
      are tagged 'seed_accounting' on the main company;
  (C) EXACTLY 13 accounts carry neon_source='seed_accounting' (this module
      created no more, no fewer — no accidental dupes);
  (D) the existing generic chart is UNTOUCHED: every one of the 47 known
      generic accounts is present with its expected account_type (receivable /
      payable / suspense / tax / the reused expense accounts all intact), and
      NONE of them carries the neon_source tag;
  (E) NO duplicate of the reused accounts (Rent / Bank Fees / Salary Expenses /
      Purchase of Equipments) — each reused code resolves to exactly one
      account that is NOT seed-tagged (reused, never recreated);
  (F) the 13 seed codes do not collide with any occupied 6xxxxx code.

Read-only against the seeded data (loaded by `-u neon_finance`); rolls back any
incidental state at the end.
"""

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


Acc = env['account.account'].with_context(active_test=False)
MAIN_CO = env.ref('base.main_company')

# --- expected new seed set: code -> name ----------------------------------
SEED = {
    '613000': 'Electricity & Utilities',
    '614000': 'Security',
    '615000': 'Repairs & Maintenance',
    '616000': 'Fuel & Oils',
    '617000': 'Motor Vehicle (Licences & Repairs)',
    '618000': 'Travel & Accommodation',
    '619000': 'Internet & Phone',
    '621000': 'Printing & Stationery',
    '622000': 'Office Supplies',
    '623000': 'Protective Clothing',
    '624000': 'Staff Welfare',
    '625000': 'Professional Fees',
    '626000': 'Marketing & Advertising',
}

# --- the generic 47 (code -> expected account_type) -----------------------
# Captured read-only from the live dev DB at GATE-0 (2026-06-23). The whole
# point of this build is that these stay EXACTLY as they are.
GENERIC_47 = {
    '101000': 'asset_current', '101300': 'asset_receivable',
    '101401': 'asset_cash', '101402': 'asset_current',
    '101403': 'asset_current', '101404': 'asset_current',
    '101501': 'asset_cash', '101701': 'asset_current',
    '110100': 'asset_current', '110200': 'asset_current',
    '110300': 'asset_current', '110400': 'asset_current',
    '121000': 'asset_receivable', '121100': 'asset_current',
    '131000': 'asset_current', '132000': 'asset_current',
    '141000': 'asset_prepayments', '151000': 'asset_fixed',
    '191000': 'asset_non_current', '201000': 'liability_current',
    '211000': 'liability_payable', '211100': 'liability_current',
    '230000': 'liability_current', '230100': 'liability_current',
    '230200': 'liability_current', '251000': 'liability_current',
    '252000': 'liability_current', '291000': 'liability_non_current',
    '301000': 'equity', '302000': 'equity',
    '400000': 'income', '441000': 'income', '442000': 'income',
    '443000': 'expense', '450000': 'income_other',
    '500000': 'expense_direct_cost', '600000': 'expense',
    '611000': 'expense', '612000': 'expense', '620000': 'expense',
    '630000': 'expense', '641000': 'expense', '642000': 'expense',
    '643000': 'income', '961000': 'expense', '962000': 'expense',
    '999999': 'equity_unaffected',
}

# reused expense accounts that MUST NOT be duplicated by the seed
REUSED = {
    '611000': 'Purchase of Equipments', '612000': 'Rent',
    '620000': 'Bank Fees', '630000': 'Salary Expenses',
}

OCCUPIED_6XXXXX = {'600000', '611000', '612000', '620000',
                   '630000', '641000', '642000', '643000'}

try:
    # (A) field exists ------------------------------------------------------
    chk("(A) account.account has neon_source field",
        'neon_source' in env['account.account']._fields)

    # (B) each seed account present, correct type, tagged, right company ----
    for code, name in SEED.items():
        a = Acc.search([('code', '=', code), ('company_id', '=', MAIN_CO.id)])
        ok = (len(a) == 1 and a.name == name
              and a.account_type == 'expense'
              and a.neon_source == 'seed_accounting')
        chk("(B) %s %s — expense, seed-tagged, single, main co" % (code, name),
            ok)

    # (C) exactly 13 seed-tagged accounts -----------------------------------
    tagged = Acc.search([('neon_source', '=', 'seed_accounting')])
    chk("(C) exactly 13 accounts tagged seed_accounting (got %d)" % len(tagged),
        len(tagged) == 13)
    chk("(C) the 13 tagged codes == the expected seed codes",
        set(tagged.mapped('code')) == set(SEED))

    # (D) generic 47 untouched: present, right type, NOT seed-tagged --------
    for code, atype in GENERIC_47.items():
        a = Acc.search([('code', '=', code), ('company_id', '=', MAIN_CO.id)])
        chk("(D) generic %s present, type=%s, not seed-tagged" % (code, atype),
            len(a) == 1 and a.account_type == atype and not a.neon_source)
    # belt-and-braces: the 47 generic codes are all non-tagged
    nontagged_codes = set(
        Acc.search([('neon_source', '=', False)]).mapped('code'))
    chk("(D) all 47 generic codes are in the non-tagged set",
        set(GENERIC_47).issubset(nontagged_codes))

    # (E) reused accounts: exactly one, NOT recreated by the seed -----------
    for code, name in REUSED.items():
        a = Acc.search([('code', '=', code), ('company_id', '=', MAIN_CO.id)])
        chk("(E) reused %s '%s' — single, not seed-tagged" % (code, name),
            len(a) == 1 and a.name == name and not a.neon_source)
        # no seed account shares its name (didn't recreate under a new code)
        same_name = Acc.search([('name', '=', name),
                                ('company_id', '=', MAIN_CO.id)])
        chk("(E) only one account named '%s' (no duplicate)" % name,
            len(same_name) == 1)

    # (F) no code collision -------------------------------------------------
    chk("(F) seed codes disjoint from occupied 6xxxxx codes",
        set(SEED).isdisjoint(OCCUPIED_6XXXXX))
    chk("(F) seed codes disjoint from ALL generic codes",
        set(SEED).isdisjoint(set(GENERIC_47)))

finally:
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
