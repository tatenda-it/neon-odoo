{
    'name': 'Neon Channels',
    'version': '17.0.1.1.0',
    'summary': 'WhatsApp and Twilio integration for Neon Events Elements',
    'author': 'Tatenda Ngairongwe',
    'website': 'https://neonhiring.com',
    'category': 'CRM',
    'depends': ['base', 'crm', 'mail', 'utm'],
    'data': [
        'security/ir.model.access.csv',
        'views/whatsapp_config_views.xml',
        'views/twilio_config_views.xml',
        'views/login_template.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
