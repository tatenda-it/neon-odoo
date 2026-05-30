"""Phase 7d post-deploy verification -- 8 checks."""

print("=" * 70)
print("CHECK 1: Module versions")
print("=" * 70)
for name in ('neon_training', 'neon_lms', 'neon_kb'):
    mod = env['ir.module.module'].search([
        ('name', '=', name)
    ])
    print(f"  {name}: {mod.installed_version} state={mod.state}")

print()
print("=" * 70)
print("CHECK 2: Category seeds")
print("=" * 70)
category_count = env['neon.kb.category'].search_count([])
print(f"  Category seed count: {category_count}")
for xmlid in (
    'neon_kb.category_audio',
    'neon_kb.category_lighting',
    'neon_kb.category_video',
    'neon_kb.category_safety',
    'neon_kb.category_admin',
):
    rec = env.ref(xmlid, raise_if_not_found=False)
    print(f"  {xmlid}: {'OK' if rec else 'MISSING'}"
          + (f"  (name={rec.name!r})" if rec else ""))

print()
print("=" * 70)
print("CHECK 3: 3 M2M join tables")
print("=" * 70)
for table in (
    'neon_kb_article_cert_type_rel',
    'neon_kb_article_sop_rel',
    'neon_kb_article_module_rel',
):
    env.cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = %s
    """, [table])
    result = env.cr.fetchone()
    print(f"  join table {table}: "
          f"{'OK' if result else 'MISSING'}")

print()
print("=" * 70)
print("CHECK 4: Dashboard KB counters (as Robin)")
print("=" * 70)
robin = env['res.users'].search([
    ('login', '=', 'robin@neonhiring.co.zw')
])
if not robin:
    print("  Robin user MISSING")
else:
    dash = env['neon.training.dashboard'].with_user(
        robin).search([], limit=1)
    if not dash:
        dash = env['neon.training.dashboard'].with_user(
            robin).create({})
    print(f"  KB counters: "
          f"published={dash.kb_articles_published} "
          f"recent_30d={dash.kb_articles_recent_30d}")

print()
print("=" * 70)
print("CHECK 5: SOP reverse pointer (kb_article_ids)")
print("=" * 70)
sop_model = env['neon.lms.sop']
has_kb_field = 'kb_article_ids' in sop_model._fields
print(f"  sop.kb_article_ids field: "
      f"{'OK' if has_kb_field else 'MISSING'}")

print()
print("=" * 70)
print("CHECK 6: Portal /my/kb routes")
print("=" * 70)
routes_found = []
for rule in env['ir.http'].routing_map().iter_rules():
    if '/my/kb' in str(rule):
        routes_found.append(str(rule))
print(f"  Portal /my/kb routes: {len(routes_found)} found")
for r in routes_found:
    print(f"    {r}")

print()
print("=" * 70)
print("CHECK 7: Login bypass invariant (website.login_layout)")
print("=" * 70)
wlayout = env.ref('website.login_layout',
                  raise_if_not_found=False)
if wlayout:
    print(f"  website.login_layout active: {wlayout.active}")
else:
    print("  website.login_layout: not found")

print()
print("=" * 70)
print("CHECK 8: External training regression (5 vendors)")
print("=" * 70)
et_count = env['neon.external.training.vendor'].search_count([])
print(f"  External training vendors: {et_count}")

print()
print("=" * 70)
print("VERIFICATION COMPLETE")
print("=" * 70)
