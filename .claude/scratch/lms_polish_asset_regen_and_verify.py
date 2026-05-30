"""Run inside odoo shell on prod: regen 4 asset bundles
then run the 5 deploy verifications. Single transaction;
env.cr.commit() at the asset stage so attachments persist.
"""
print("=" * 72)
print("STEP 1 -- Clear /web/assets/* attachments")
print("=" * 72)
Attachment = env["ir.attachment"]
old = Attachment.search([("url", "=like", "/web/assets/%")])
print(f"  attachments to clear: {len(old)}")
old.unlink()
env.cr.commit()
print("  cleared + committed")

print()
print("=" * 72)
print("STEP 2 -- Compile 4 backend bundles")
print("=" * 72)
IrQweb = env["ir.qweb"]
bundle_names = [
    "web.assets_backend",
    "web_editor.backend_assets_wysiwyg",
    "web.assets_web",
    "web.assets_frontend",
]
for bundle_name in bundle_names:
    try:
        bundle = IrQweb._get_asset_bundle(bundle_name)
        bundle.js()
        bundle.css()
        print(f"  {bundle_name}: compiled")
    except Exception as e:  # noqa: BLE001
        print(f"  {bundle_name}: ERR {e}")
env.cr.commit()
print("  committed")

print()
print("=" * 72)
print("STEP 3 -- Asset attachment counts (post-regen)")
print("=" * 72)
post = Attachment.search([("url", "=like", "/web/assets/%")])
print(f"  total /web/assets/* attachments: {len(post)}")
backend_attachments = Attachment.search([
    ("url", "=like", "/web/assets/%backend%")])
print(f"  /web/assets/%backend% attachments: "
      f"{len(backend_attachments)}")
for a in backend_attachments[:10]:
    print(f"    {a.url}")

# Verify the M3 JS is bundled inside the backend asset.
m3_marker = "neon_lms_autosave_indicator"
js_found_in = []
for a in backend_attachments.filtered(
        lambda x: x.url.endswith(".js")):
    try:
        raw = a.raw or b""
        if m3_marker.encode() in raw:
            js_found_in.append(a.url)
    except Exception as e:  # noqa: BLE001
        print(f"    err reading {a.url}: {e}")
print(f"  M3 autosave marker present in: "
      f"{js_found_in if js_found_in else 'NONE (PROBLEM)'}")

# ============================================================
print()
print("=" * 72)
print("STEP 4 -- 5 deploy verifications")
print("=" * 72)

# V1: module version
print()
print("V1 - neon_lms installed_version")
mod = env["ir.module.module"].search(
    [("name", "=", "neon_lms")], limit=1)
print(f"  installed_version: {mod.installed_version}")
print(f"  expected: 17.0.1.14.0")

# V2: Quiz import wizard model exists
print()
print("V2 - Quiz import wizard model registered")
wizard = env.get("neon.lms.quiz.import.wizard")
print(f"  registered: {wizard is not None}")

# V3: Module form notebook view exists
print()
print("V3 - Module form view loaded")
mv = env.ref(
    "neon_lms.view_neon_lms_module_form",
    raise_if_not_found=False)
print(f"  id: {mv.id if mv else 'MISSING'}, "
      f"name: {mv.name if mv else 'n/a'}")

# V4: Slide form inherit present
print()
print("V4 - Slide form inherit (M3) present")
slide_inherits = env["ir.ui.view"].search([
    ("model", "=", "slide.slide"),
    ("inherit_id", "!=", False),
])
neon_slide_inherit = [
    v for v in slide_inherits
    if "neon_lms" in (
        v.xml_id or v.key or "")]
print(f"  neon_lms inherits on slide.slide: "
      f"{len(neon_slide_inherit)}")
for v in neon_slide_inherit:
    print(f"    {v.xml_id or v.key} (id={v.id})")

# V5: Backend asset attachments
print()
print("V5 - Backend asset attachments")
print(f"  count: {len(backend_attachments)}")
print(f"  expected: 2 (js + css)")

print()
print("=" * 72)
print("DEPLOY VERIFY DONE")
print("=" * 72)
