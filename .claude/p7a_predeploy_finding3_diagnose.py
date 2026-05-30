"""Pre-deploy finding #3 diagnostic. Read-only -- no fix applied."""
print("=" * 80)
print("QUERY 1 -- All Training menus (recursive) with groups_id")
print("=" * 80)
root = env.ref("neon_training.menu_neon_training_root")


def collect_descendants(menu_recs):
    result = menu_recs
    for m in menu_recs:
        children = env["ir.ui.menu"].sudo().search(
            [("parent_id", "=", m.id)])
        if children:
            result |= collect_descendants(children)
    return result


all_training_menus = collect_descendants(root).sorted(
    lambda m: (m.parent_id.id or 0, m.sequence, m.id))

print(f"{'ID':<6} {'Name':<32} {'Parent':<28} {'Groups':<60}")
print("-" * 130)
for m in all_training_menus:
    groups_str = ", ".join(
        m.groups_id.mapped("name")) or "(empty - all users)"
    parent_str = m.parent_id.name or "TOP"
    print(f"{m.id:<6} {(m.name or '')[:31]:<32} "
          f"{parent_str[:27]:<28} {groups_str[:59]:<60}")

print()
print("=" * 80)
print("QUERY 2 -- admin user's actual groups (sorted)")
print("=" * 80)
admin = env.ref("base.user_admin")
print(f"admin user: {admin.login} (uid={admin.id})")
print(f"  total groups: {len(admin.groups_id)}")
for g in admin.groups_id.sorted("name"):
    xmlids = g.get_external_id() or {}
    xmlid = xmlids.get(g.id, "(no xmlid)")
    print(f"  - {g.name:<45} {xmlid}")

print()
print("=" * 80)
print("QUERY 3 -- Why is each invisible menu blocked?")
print("=" * 80)
invisible_xmlids = [
    "neon_training.menu_neon_training_dashboard",
    "neon_training.menu_neon_training_find_qualified_user",
    "neon_training.menu_neon_training_certifications",
    "neon_training.menu_neon_training_categories",
    "neon_training.menu_neon_training_types",
]
for xmlid in invisible_xmlids:
    m = env.ref(xmlid, raise_if_not_found=False)
    if not m:
        print(f"\n  {xmlid}: NOT FOUND")
        continue
    menu_groups = m.groups_id
    overlap = menu_groups & admin.groups_id
    print(f"\n  {xmlid} (id={m.id}):")
    print(f"    menu groups: {menu_groups.mapped('name')}")
    print(f"    admin overlap: "
          f"{overlap.mapped('name') if overlap else 'NONE -- BLOCKED'}")
    if not overlap and menu_groups:
        print(f"    -> admin needs ANY of: "
              f"{menu_groups.mapped('name')}")

print()
print("=" * 80)
print("QUERY 4 -- Visible menus (for comparison)")
print("=" * 80)
visible_xmlids = [
    "neon_training.menu_neon_training_cross_competencies",
    "neon_training.menu_neon_training_assignment_gate_log",
    "neon_training.menu_neon_training_reports",
    "neon_training.menu_neon_training_report_expiring",
    "neon_training.menu_neon_training_report_compliance",
    "neon_training.menu_neon_training_report_cross_competency",
    "neon_training.menu_neon_training_configuration",
]
for xmlid in visible_xmlids:
    m = env.ref(xmlid, raise_if_not_found=False)
    if not m:
        print(f"  {xmlid}: NOT FOUND")
        continue
    overlap = m.groups_id & admin.groups_id
    print(f"  {xmlid}:")
    print(f"    menu groups: "
          f"{m.groups_id.mapped('name') or '(empty - all users)'}")
    print(f"    admin overlap: "
          f"{overlap.mapped('name') if overlap else 'NONE'}")

print()
print("=" * 80)
print("QUERY 5 -- implied_ids chain verification")
print("=" * 80)
ta = env.ref("neon_training.group_neon_training_admin")
ts = env.ref("neon_training.group_neon_training_signoff")
tu = env.ref("neon_training.group_neon_training_user")
print(f"  training_admin.implied_ids: {ta.implied_ids.mapped('name')}")
print(f"  training_signoff.implied_ids: "
      f"{ts.implied_ids.mapped('name')}")
print(f"  training_user.implied_ids: {tu.implied_ids.mapped('name')}")
print()
print(f"  admin in training_admin: {admin in ta.users}")
print(f"  admin in training_signoff (transitively expected): "
      f"{admin in ts.users}")
print(f"  admin in training_user (transitively expected): "
      f"{admin in tu.users}")

# Bonus: list users in each training group to spot
# implied_ids propagation issues.
print()
print(f"  training_admin members ({len(ta.users)}): "
      f"{ta.users.mapped('login')}")
print(f"  training_signoff members ({len(ts.users)}): "
      f"{ts.users.mapped('login')}")
print(f"  training_user members ({len(tu.users)}): "
      f"{tu.users.mapped('login')}")
