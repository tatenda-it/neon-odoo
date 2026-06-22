# -*- coding: utf-8 -*-
{
    'name': 'Neon Sales',
    'version': '17.0.1.4.0',
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
    # sale_crm pulled in (QUOTE-UX-2) so we can override its CRM "My
    # Quotations" menu (sale_crm.sale_order_menu_quotations_crm) to point at
    # the engine quote action.
    'depends': ['sale_management', 'sale_crm', 'neon_finance',
                'sale_global_discount'],
    'data': [
        # group must load before the menu gating that references it
        'security/neon_legacy_group.xml',
        'data/product_pricelist.xml',
        'data/sale_groups.xml',
        # QUOTE-UX-2: hide stock quote doors + redirect CRM door + top-level
        'data/quote_ux2_menu_gating.xml',
        'views/sale_order_views.xml',
        'views/sale_report_templates.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
