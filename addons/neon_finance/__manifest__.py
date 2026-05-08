# -*- coding: utf-8 -*-
{
    'name': 'Neon Finance',
    'version': '17.0.1.1.0',
    'summary': 'Zimbabwe finance configuration for Neon Events Elements',
    'description': """
Neon Finance
============
Zimbabwe-specific finance configuration: ZWG currency ownership,
ZIMRA VAT tax records (15.5% standard, 0% zero-rated), tax groups,
and supporting structure for Phase 1 Finance build.

This module pairs with neon_crm_extensions but is functionally
independent — it depends only on the upstream account module.
""",
    'author': 'Neon Events Elements',
    'website': 'https://www.neonhiring.co.zw',
    'category': 'Accounting/Localizations',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
    ],
    'data': [
        'data/res_currency_data.xml',
        'data/account_tax_data.xml',
        'data/res_company_logo.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
