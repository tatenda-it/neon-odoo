# Discovery for /web/login chrome wrapping on prod
# Run via: docker compose exec -T odoo odoo shell -d neon_crm --no-http < this_file.py

login_view = env['ir.ui.view'].search([('key', '=', 'web.login')], limit=1)
print(f"=== web.login view ===")
print(f"id: {login_view.id}, name: {login_view.name}, type: {login_view.type}")
print(f"inherit_id: {login_view.inherit_id.key if login_view.inherit_id else 'none'}")

inheritors = env['ir.ui.view'].search([('inherit_id', '=', login_view.id)])
print(f"\n=== views inheriting web.login ({len(inheritors)}) ===")
for v in inheritors:
    print(f"  {v.key}  (xml_id_module={v.xml_id.split('.')[0] if v.xml_id else '?'}, id={v.id}, active={v.active})")

login_layout = env['ir.ui.view'].search([('key', '=', 'web.login_layout')], limit=1)
print(f"\n=== web.login_layout ===")
print(f"id: {login_layout.id}, name: {login_layout.name}")
print(f"inherit_id: {login_layout.inherit_id.key if login_layout.inherit_id else 'none'}")

layout_inheritors = env['ir.ui.view'].search([('inherit_id', '=', login_layout.id)])
print(f"\n=== views inheriting web.login_layout ({len(layout_inheritors)}) ===")
for v in layout_inheritors:
    print(f"  {v.key}  (xml_id={v.xml_id}, id={v.id}, active={v.active})")
    print(f"    arch preview: {(v.arch or '')[:300]}")
    print()

signup = env['ir.ui.view'].search([('key', '=', 'web.login_signup_form')], limit=1)
print(f"\n=== web.login_signup_form ===")
print(f"id: {signup.id if signup else 'NOT FOUND'}")

# Home controller source for web_login
print(f"\n=== Home.web_login source ===")
from odoo.addons.web.controllers.home import Home
import inspect
try:
    src = inspect.getsource(Home.web_login)
    print(src[:1500])
except Exception as e:
    print(f"err: {e}")

# Check if website module's home overrides web_login
print(f"\n=== website's Home.web_login override? ===")
try:
    from odoo.addons.website.controllers.main import Website
    if hasattr(Website, 'web_login'):
        src = inspect.getsource(Website.web_login)
        print(src[:1500])
    else:
        print("Website class has no web_login override")
except Exception as e:
    print(f"err: {e}")

# Sometimes website injects via portal. Check portal too.
print(f"\n=== checking all Home subclasses ===")
import odoo.addons
for mod_name in ['website', 'portal', 'auth_signup', 'web_editor']:
    try:
        mod = __import__(f'odoo.addons.{mod_name}.controllers', fromlist=['*'])
    except Exception as e:
        print(f"  {mod_name}: import err {e}")

# List loaded controller classes that subclass Home
from odoo.http import Controller
def find_subclasses(cls, seen=None):
    seen = seen or set()
    out = []
    for sub in cls.__subclasses__():
        if sub in seen:
            continue
        seen.add(sub)
        out.append(sub)
        out.extend(find_subclasses(sub, seen))
    return out

print(f"\n=== Home subclasses ===")
for sub in find_subclasses(Home):
    print(f"  {sub.__module__}.{sub.__name__}  has_web_login={hasattr(sub, 'web_login') and sub.web_login is not Home.web_login}")
