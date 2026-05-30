"""Phase 7d post-deploy asset regen.
Purges built /web/assets/* attachments, then re-compiles
the 4 bundles to materialise neon_kb's portal templates +
neon_training's dashboard view changes."""

attachments = env['ir.attachment'].search([
    ('url', '=like', '/web/assets/%')
])
purged = len(attachments)
attachments.unlink()
env.cr.commit()
print(f"Purged: {purged} /web/assets/* attachments")

IrQweb = env['ir.qweb']
results = {}
for b in ('web.assets_backend', 'web.assets_web',
          'web_editor.backend_assets_wysiwyg',
          'web.assets_frontend'):
    try:
        bundle = IrQweb._get_asset_bundle(b)
        bundle.js()
        bundle.css()
        results[b] = "OK"
    except Exception as e:
        results[b] = f"ERR: {e}"
env.cr.commit()
print("Asset regen results:")
for k, v in results.items():
    print(f"  {k}: {v}")

new_attachments = env['ir.attachment'].search_count([
    ('url', '=like', '/web/assets/%')
])
print(f"New /web/assets/* attachments: {new_attachments}")
