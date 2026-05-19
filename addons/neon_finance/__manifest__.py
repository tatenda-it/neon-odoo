# -*- coding: utf-8 -*-
{
    'name': 'Neon Finance',
    'version': '17.0.7.0.0',
    'summary': 'Zimbabwe finance configuration + Phase 6 pricing engine '
               'foundation + quote model for Neon Events Elements',
    'description': """
Neon Finance
============
Phase 1: ZWG currency ownership, ZIMRA VAT tax records (15.5%
standard, 0% zero-rated), tax groups, partner-bank tweaks.

Phase 6 (this milestone, P6.M1): pricing rule + bracket + day-type
multiplier + USD/ZiG conversion rate schema, plus the four finance
role groups (user / sales / bookkeeper / approver). Extends
neon.equipment.category with a cost_strategy field driving quote
and cost-line behaviour downstream.
""",
    'author': 'Neon Events Elements Pvt Ltd',
    'website': 'https://neonhiring.com',
    'category': 'Accounting/Localizations',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        # P6.M1 — extends neon.equipment.category with cost_strategy
        # and auto-spawns day_multiplier rows for new categories.
        # Cycle check (pre-build): neon_jobs has no reverse deps
        # onto neon_finance or neon_sales.
        'neon_jobs',
    ],
    'data': [
        # security must load first so groups exist before ACL CSV
        # references them.
        'security/security.xml',
        'security/ir.model.access.csv',
        # P6.M2 — record rules for the quote model (must load AFTER
        # the CSV so the model exists in the registry).
        'security/ir_rule.xml',
        # Phase 1 data unchanged.
        'data/res_currency_data.xml',
        'data/account_tax_data.xml',
        'data/res_company_profile.xml',
        'data/res_company_logo.xml',
        'data/res_company_banks.xml',
        'data/account_journal_data.xml',
        # P6.M1 sequences must load before the pricing-rule seed
        # data so the default `next_by_code` lookup succeeds when
        # each rule is created. P6.M2 adds two more sequences (QUO-
        # USD-, QUO-ZIG-) into the same file.
        'data/ir_sequence_data.xml',
        'data/pricing_rule_seed_data.xml',
        # P6.M2 — daily cron for quote expiry.
        'data/ir_cron_data.xml',
        # Views.
        'views/res_partner_bank_views.xml',
        'views/neon_finance_pricing_rule_views.xml',
        'views/neon_finance_day_multiplier_views.xml',
        'views/neon_finance_conversion_rate_views.xml',
        'views/neon_equipment_category_views.xml',
        # P6.M2 — quote stack views.
        'views/neon_finance_payment_term_views.xml',
        'views/neon_finance_quote_line_views.xml',
        'views/neon_finance_quote_views.xml',
        'wizard/neon_finance_payment_term_wizard_views.xml',
        # Menus load last so action ref()s resolve.
        'views/neon_finance_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
