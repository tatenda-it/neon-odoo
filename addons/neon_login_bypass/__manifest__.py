{
    'name': 'Neon Login Bypass',
    'version': '17.0.1.0.0',
    'category': 'Neon',
    'summary': 'Render /web/login bare (skip website chrome).',
    'description': """
Deactivates the stock `website.login_layout` view so that `/web/login`
renders with the bare `web.login_layout` template (Neon-branded) instead
of being wrapped in `website.layout` (which introduces the "YourLogo"
placeholder and the generic "About us" footer).

Portal routes (/my/*) and other website-themed surfaces are unaffected
because they render via `portal.frontend_layout`, not `web.login_layout`.
""",
    'author': 'Neon Events Elements',
    'website': 'https://neonhiring.com',
    'depends': ['web', 'website'],
    'data': [
        'views/neon_login_bypass_views.xml',
    ],
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
