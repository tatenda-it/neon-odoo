"""Asset regen + 7 deploy verifications for Phase 7c prod.
Runs inside odoo shell on prod (--no-http).
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
print("STEP 2 -- Compile 4 bundles")
print("=" * 72)
IrQweb = env["ir.qweb"]
for b in ("web.assets_backend",
          "web.assets_web",
          "web_editor.backend_assets_wysiwyg",
          "web.assets_frontend"):
    try:
        bundle = IrQweb._get_asset_bundle(b)
        bundle.js()
        bundle.css()
        print(f"  {b}: compiled")
    except Exception as e:  # noqa: BLE001
        print(f"  {b}: ERR {e}")
env.cr.commit()

# Asset attachment counts post-regen.
backend = Attachment.search(
    [("url", "=like", "/web/assets/%backend%")])
all_assets = Attachment.search(
    [("url", "=like", "/web/assets/%")])
print(f"  /web/assets/% total: {len(all_assets)}")
print(f"  /web/assets/%backend%: {len(backend)}")

# ============================================================
print()
print("=" * 72)
print("VERIFICATIONS (7 checks)")
print("=" * 72)

# V1 -- Module versions
print()
print("V1 - module versions")
for name in ("neon_training", "neon_external_training"):
    mod = env["ir.module.module"].sudo().search(
        [("name", "=", name)])
    print(f"  {name}: {mod.installed_version} "
          f"(state={mod.state})")

# V2 -- Vendor seeds present
print()
print("V2 - vendor seeds")
vendor_count = env[
    "neon.external.training.vendor"].sudo().search_count([])
print(f"  vendor total: {vendor_count} (expect 5)")
for xmlid in (
    "neon_external_training.vendor_vid",
    "neon_external_training.vendor_red_cross_zim",
    "neon_external_training.vendor_allen_heath",
    "neon_external_training.vendor_avolites",
    "neon_external_training.vendor_yamaha_pro",
):
    rec = env.ref(xmlid, raise_if_not_found=False)
    status = "OK" if rec else "MISSING"
    name = rec.name.strip() if rec else "n/a"
    print(f"  {xmlid}: {status} ({name})")

# V3 -- FK constraint
print()
print("V3 - FK constraint on cert.external_booking_id")
env.cr.execute("""
    SELECT conname, pg_get_constraintdef(oid)
      FROM pg_constraint
     WHERE conrelid = 'neon_training_certification'::regclass
       AND contype = 'f'
       AND conname =
           'neon_training_certification_'
           'external_booking_id_fkey'
""")
row = env.cr.fetchone()
print(f"  FK present: {row is not None}")
if row:
    print(f"  def: {row[1]}")

# V4 -- Dashboard counters for Robin
print()
print("V4 - dashboard external counters")
robin = env["res.users"].sudo().search(
    [("login", "=", "robin@neonhiring.co.zw")], limit=1)
if not robin:
    print("  Robin user MISSING")
else:
    dash = env["neon.training.dashboard"].with_user(
        robin).sudo().create({})
    print(f"  upcoming: {dash.external_bookings_upcoming}")
    print(f"  pending_completion: "
          f"{dash.external_bookings_pending_completion}")

# V5 -- Sequence registered
print()
print("V5 - booking sequence")
seq = env["ir.sequence"].sudo().search(
    [("code", "=", "neon.external.training.booking")])
print(f"  sequence present: {bool(seq)}")
if seq:
    print(f"  prefix: {seq.prefix} padding={seq.padding}")

# V6 -- Cron registered + active
print()
print("V6 - 3d reminder cron")
cron = env.ref(
    "neon_external_training.cron_external_training_reminder_3d",
    raise_if_not_found=False)
if cron:
    print(f"  cron present: True")
    print(f"  active: {cron.active}")
    print(f"  interval: {cron.interval_number} "
          f"{cron.interval_type}")
    print(f"  code: {cron.code}")
else:
    print("  cron MISSING")

# V7 -- Login bypass invariant preserved
print()
print("V7 - website.login_layout active flag")
wlayout = env.ref(
    "website.login_layout", raise_if_not_found=False)
if wlayout:
    print(f"  active: {wlayout.active} (expect False)")
else:
    print("  view MISSING")

# Bonus -- module count
print()
print("Module count (installed)")
installed = env["ir.module.module"].sudo().search(
    [("state", "=", "installed")])
print(f"  total installed: {len(installed)}")
