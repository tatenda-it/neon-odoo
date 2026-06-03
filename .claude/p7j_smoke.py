# -*- coding: utf-8 -*-
"""P7j smoke -- slide/channel cover override + global-footer Useful-Links removal.

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7j_smoke.py

Item 1: slide.channel._get_placeholder_filename returns the Neon event
cover for neon_branded channels (covers all 237 slides via the slide->
channel delegation + the channel card), super() otherwise. Item 2: the
"Useful Links" column is removed from the global footer via a module
inheritance of website.footer_custom (the rendered result is in the
browser smoke). Mutations roll back at the end.
"""
import os

from odoo.modules.module import get_module_path

env = env(context=dict(env.context, mail_notify_force_send=False,
                       tracking_disable=True))
results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()
ch = Ch.search([("neon_track_ids", "!=", False)], limit=1)
_check("T-P7J-00", bool(ch), "Neon channel exists")

NEON = "neon_lms/static/src/img/neon_slide_cover.jpg"
img_fields = ["image_%s" % s for s in (1920, 1024, 512, 256, 128)]

# ---- item 1: cover override (neon_branded=True) ----
ch.neon_branded = True
_check("T-P7J-01", ch._get_placeholder_filename("image_1024") == NEON,
       "channel image_1024 -> %r" % ch._get_placeholder_filename("image_1024"))
_check("T-P7J-02", all(ch._get_placeholder_filename(f) == NEON for f in img_fields),
       "all image sizes -> Neon cover")
_check("T-P7J-03", ch._get_placeholder_filename("logo") != NEON,
       "non-image field falls through to super()")
sl = Sl.search([("channel_id", "=", ch.id), ("is_category", "=", False)], limit=1)
_check("T-P7J-04", bool(sl) and sl._get_placeholder_filename("image_1024") == NEON,
       "slide delegates to channel -> Neon cover (covers the 237 slides)")

# ---- non-branded falls through to the stock website_slides default ----
ch.neon_branded = False
fallback = ch._get_placeholder_filename("image_1024")
_check("T-P7J-05", fallback != NEON, "non-branded -> not the Neon cover (%r)" % fallback)
_check("T-P7J-06", "website_slides" in fallback,
       "non-branded -> stock website_slides default (%r)" % fallback)

# ---- the cover asset ships in the module ----
path = os.path.join(get_module_path("neon_lms"),
                    "static", "src", "img", "neon_slide_cover.jpg")
_check("T-P7J-07", os.path.exists(path) and os.path.getsize(path) > 50000,
       "neon_slide_cover.jpg shipped (size=%s)" % (os.path.exists(path) and os.path.getsize(path)))

# ---- item 2: global-footer Useful-Links removal view ----
fv = env.ref("neon_lms.neon_remove_footer_useful_links", raise_if_not_found=False)
_check("T-P7J-08", bool(fv) and fv.active
       and fv.inherit_id.key == "website.footer_custom",
       "Useful-Links-removal view active + inherits website.footer_custom")

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print("Total: {}/{} passed".format(passed, total))
for k in sorted(results):
    if not results[k]:
        print("  {}: FAIL".format(k))

env.cr.rollback()
