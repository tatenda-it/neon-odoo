{
    'name': 'Neon Channels',
    'version': '17.0.1.0.0',
    'category': 'CRM',
    'summary': 'WhatsApp Business API integration for Neon Events Elements CRM',
    'description': """
        Integrates WhatsApp Business API with Odoo CRM.
        - Receives incoming WhatsApp messages via Meta webhook
        - Creates and updates CRM leads automatically
        - Sends WhatsApp messages from CRM
    """,
    'author': 'Neon Events Elements',
    'website': 'https://neonhiring.com',
    'depends': [
        'base',
        'crm',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/whatsapp_config_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
