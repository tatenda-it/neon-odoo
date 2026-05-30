"""Part 2 -- discovery on base.group_user implied_ids. Read-only."""
print("=" * 78)
print("QUERY 1 -- base.group_user implied_ids on this DB")
print("=" * 78)
base_user = env.ref("base.group_user")
print(f"base.group_user:")
print(f"  id={base_user.id}")
print(f"  name={base_user.name!r}")
print(f"  category={base_user.category_id.name!r}")
print(f"  members (active+inactive): {len(base_user.with_context(active_test=False).users)}")
print(f"  members (active only): {len(base_user.users)}")

print(f"\ndirect implied_ids ({len(base_user.implied_ids)}):")
for g in base_user.implied_ids.sorted("name"):
    xmlids = g.get_external_id() or {}
    xmlid = xmlids.get(g.id, "NO XMLID")
    cat = g.category_id.name or "(no category)"
    print(f"  - {g.name!r:<45} cat={cat!r:<28} [{xmlid}]")

print(f"\ntrans_implied_ids (transitive closure -- "
      f"{len(base_user.trans_implied_ids)}):")
for g in base_user.trans_implied_ids.sorted("name"):
    xmlids = g.get_external_id() or {}
    xmlid = xmlids.get(g.id, "NO XMLID")
    print(f"  - {g.name!r:<45} [{xmlid}]")


print()
print("=" * 78)
print("QUERY 4 -- installed modules (relevant to implied_ids "
      "expansion)")
print("=" * 78)
relevant_names = (
    "base", "web", "mail", "account", "sale", "crm", "product",
    "purchase", "stock", "hr", "calendar", "contacts",
    "spreadsheet_dashboard", "auditlog", "queue_job",
    "base_global_discount", "neon_crm_extensions",
    "neon_jobs", "neon_finance", "neon_training",
    "neon_sales", "neon_channels",
)
installed = env["ir.module.module"].search([
    ("state", "=", "installed"),
    ("name", "in", list(relevant_names)),
]).sorted("name")
print(f"installed modules (filtered to {len(relevant_names)} "
      f"relevant names): {len(installed)}")
for m in installed:
    print(f"  - {m.name:<32} v{m.latest_version}")


print()
print("=" * 78)
print("QUERY 5 -- existing-user audit: how many internal users "
      "have each problematic group?")
print("=" * 78)
all_internal = env["res.users"].with_context(
    active_test=False).search([
    ("groups_id", "in", base_user.id),
])
active_internal = all_internal.filtered("active")
print(f"All internal users (active+inactive): {len(all_internal)}")
print(f"Active internal users:                {len(active_internal)}")
print()
print("Active members of each notable group:")
problematic = [
    "base.group_no_one",
    "base.group_multi_currency",
    "product.group_product_pricelist",
    "mail.group_mail_template_editor",
    "base.group_partner_manager",
    "base.group_sanitize_override",
    "base.group_allow_export",
    "product.group_discount_per_so_line",
]
for grp_xmlid in problematic:
    grp = env.ref(grp_xmlid, raise_if_not_found=False)
    if not grp:
        print(f"  {grp_xmlid}: GROUP NOT FOUND")
        continue
    in_grp = active_internal.filtered(lambda u: grp in u.groups_id)
    print(f"  {grp_xmlid}")
    print(f"    members: {len(in_grp)}/{len(active_internal)} active "
          f"internal users")
    if 0 < len(in_grp) <= 8:
        for u in in_grp.sorted("login"):
            print(f"      - {u.login}")
