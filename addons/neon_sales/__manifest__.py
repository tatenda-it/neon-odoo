# -*- coding: utf-8 -*-
{
    'name': 'Neon Sales',
    'version': '17.0.1.3.0',
    'category': 'Sales',
    'summary': 'Sales-cycle customisations for Neon Events Elements',
    'description': """
Neon Sales
==========
Customisations on the Odoo sale module for Neon Events Elements
quoting and order workflow:
- Optional covering letter / introductory paragraph on quotes
- (Future: P1.M3.C QWeb template extensions for ZIMRA + banking
  + branded layout)
    """,
    'author': 'Neon Events Elements Pvt Ltd',
    'website': 'https://neonhiring.com',
    'license': 'LGPL-3',
    'depends': ['sale_management', 'neon_finance', 'sale_global_discount'],
    'data': [
        'data/product_pricelist.xml',
        'data/sale_groups.xml',
        'views/sale_order_views.xml',
        'views/sale_report_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
