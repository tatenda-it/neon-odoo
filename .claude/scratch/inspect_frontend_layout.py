View = env["ir.ui.view"]
fl = View.search([("key", "=", "web.frontend_layout")], limit=1)
print(f"=== web.frontend_layout ===")
print(f"id: {fl.id}, name: {fl.name}, active: {fl.active}")
print(f"\narch:\n{fl.arch}")

print(f"\n=== views inheriting web.frontend_layout ===")
inheritors = View.search([("inherit_id", "=", fl.id)])
for v in inheritors:
    print(f"\n--- {v.key} (xml_id={v.xml_id}, id={v.id}, active={v.active}, priority={v.priority}) ---")
    print((v.arch or "")[:1500])
