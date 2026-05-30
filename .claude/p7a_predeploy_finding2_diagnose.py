"""Pre-deploy finding #2 diagnostic. Runs the 5 queries from
Tatenda's prompt. Read-only — no fix applied."""
import ast
import os

print("=" * 72)
print("QUERY 1 -- Training-related menus in DB")
print("=" * 72)
training_menus = env['ir.ui.menu'].search([
    '|', '|',
    ('name', 'ilike', 'training'),
    ('name', 'ilike', 'certif'),
    ('name', 'ilike', 'cross-comp')
])
print(f"Training-related menus found: {len(training_menus)}")
for m in training_menus:
    parent_label = m.parent_id.name or 'TOP-LEVEL'
    groups = m.groups_id.mapped('full_name')
    action_label = (m.action.name if m.action else '(no action)')
    print(f"  ID={m.id}, name={m.name!r}, parent={parent_label!r}, "
          f"groups={groups}, action={action_label!r}")

print()
print("=" * 72)
print("QUERY 2 -- menu_neon_training_root xmlid resolution")
print("=" * 72)
try:
    root = env.ref('neon_training.menu_neon_training_root')
    parent_label = root.parent_id.name or 'TOP-LEVEL'
    print(f"menu_neon_training_root EXISTS: id={root.id}, "
          f"name={root.name!r}, parent={parent_label!r}, "
          f"active={root.active}, sequence={root.sequence}, "
          f"groups={root.groups_id.mapped('full_name')}, "
          f"action={(root.action.name if root.action else None)!r}")
except Exception as e:
    print(f"menu_neon_training_root MISSING: {type(e).__name__}: {e}")

print()
print("=" * 72)
print("QUERY 3 -- workshop_root comparison (neon_workshop OR neon_jobs)")
print("=" * 72)
# Tatenda's prompt referenced neon_workshop.menu_neon_workshop_root,
# but the actual Workshop functionality lives inside neon_jobs in
# this repo. Try BOTH for transparency.
for xmlid in [
    'neon_workshop.menu_neon_workshop_root',
    'neon_jobs.menu_workshop_root',
    'neon_jobs.menu_neon_jobs_root',
]:
    try:
        ref = env.ref(xmlid)
        parent_label = ref.parent_id.name or 'TOP-LEVEL'
        print(f"  {xmlid} EXISTS: id={ref.id}, name={ref.name!r}, "
              f"parent={parent_label!r}, sequence={ref.sequence}")
    except Exception as e:
        print(f"  {xmlid} MISSING: {type(e).__name__}: {e}")

print()
print("=" * 72)
print("QUERY 4 -- manifest data list")
print("=" * 72)
# ast.literal_eval cannot parse the manifest -- it starts with a
# comment line. Strip comments + leading whitespace before parsing.
with open('/mnt/extra-addons/neon_training/__manifest__.py') as f:
    raw = f.read()
# Find the first '{' and parse from there.
brace_at = raw.find('{')
manifest = ast.literal_eval(raw[brace_at:])
print(f"data files loaded by neon_training: {len(manifest.get('data', []))}")
for f in manifest.get('data', []):
    print(f"  - {f}")

print()
print("=" * 72)
print("QUERY 5 -- menu XML file contents check")
print("=" * 72)
menu_xml_path = '/mnt/extra-addons/neon_training/views/neon_training_menu.xml'
if os.path.exists(menu_xml_path):
    print(f"Menu XML file exists: {menu_xml_path}")
    with open(menu_xml_path) as f:
        content = f.read()
    print(f"File size: {len(content)} bytes")
    if 'menu_neon_training_root' in content:
        print("xmlid 'menu_neon_training_root' present in file")
    else:
        print("WARNING: xmlid 'menu_neon_training_root' NOT in file")
    # Also enumerate the menuitem ids defined in the file.
    import re
    ids = re.findall(r'<menuitem\s+id="([^"]+)"', content)
    print(f"\nmenuitem ids defined in file ({len(ids)}):")
    for x in ids:
        print(f"  - {x}")
else:
    print(f"WARNING: Menu XML file does NOT exist: {menu_xml_path}")

print()
print("=" * 72)
print("QUERY 6 (bonus) -- ir.model.data rows for the menu xmlid")
print("=" * 72)
rows = env['ir.model.data'].search([
    ('module', '=', 'neon_training'),
    ('name', '=', 'menu_neon_training_root'),
])
print(f"ir.model.data rows matching neon_training.menu_neon_training_root: {len(rows)}")
for r in rows:
    print(f"  id={r.id}, res_id={r.res_id}, model={r.model}, "
          f"noupdate={r.noupdate}")

print()
print("=" * 72)
print("QUERY 7 (bonus) -- load_web_menus output for SUPERUSER")
print("=" * 72)
menus = env['ir.ui.menu'].load_web_menus(False)
top_level_apps = menus.get('root', {}).get('children', [])
print(f"Top-level apps visible to current user "
      f"(env.user={env.user.login}): {len(top_level_apps)}")
for app_id in top_level_apps:
    info = menus.get(str(app_id), {})
    print(f"  id={app_id}, name={info.get('name')!r}, "
          f"xmlid={info.get('xmlid')!r}")
