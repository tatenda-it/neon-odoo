# -*- coding: utf-8 -*-
"""P7k browser-smoke fixture setup (idempotent, COMMITTED).

Run once before p7k_browser_smoke.py:
    odoo shell -d <db> --no-http < p7k_browser_setup.py

Leaves the branded channel with a known lesson that was put into
the BROKEN state (slide_category='document'/'pdf', html_content,
no pdf payload) and then run THROUGH THE REAL TRANSFORM SCRIPT
(scripts/migrate_p7k_slide_render.py, apply=True) so it ends as
'article'. The browser smoke then renders it and asserts the
html_content body shows (no "Loading..." hang). Resetting +
re-converting every run means each regression exercises the
actual document->article transform end to end.

Also guarantees p2m75_sales is enrolled (the harness logs in as
that member). Real-data-safe: only the dedicated P7K lesson is
touched.
"""
import importlib.util

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()
Users = env["res.users"].sudo()
Enrollment = env["slide.channel.partner"].sudo()

MARKER = "P7K render proof: this article body must display to the learner."
SCRIPT = "/mnt/extra-addons/neon_lms/scripts/migrate_p7k_slide_render.py"

ch = Ch.search([("neon_branded", "=", True)], limit=1)
assert ch, "no Neon branded channel"

# get-or-create the dedicated P7K browser lesson, RESET to broken state
lesson = Sl.search([("channel_id", "=", ch.id),
                    ("name", "=", "P7K BROWSER lesson")], limit=1)
vals = {
    "name": "P7K BROWSER lesson", "channel_id": ch.id,
    "is_category": False, "slide_category": "document",
    "slide_type": "pdf", "source_type": "local_file",
    "sequence": 4999, "is_published": True,
    "binary_content": False, "url": False,
    "html_content": "<h2>P7K</h2><p>%s</p>" % MARKER,
}
if lesson:
    lesson.write(vals)
else:
    lesson = Sl.create(vals)

# run the REAL transform (apply=True) -> the broken lesson becomes article
spec = importlib.util.spec_from_file_location("p7k_xform", SCRIPT)
xform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xform)
report = xform.convert_slides(env, apply=True)

# ensure p2m75_sales is an enrolled member
sales = Users.search([("login", "=", "p2m75_sales")], limit=1)
if sales:
    enr = Enrollment.search([("partner_id", "=", sales.partner_id.id),
                             ("channel_id", "=", ch.id)], limit=1)
    if not enr:
        Enrollment.create({"partner_id": sales.partner_id.id,
                           "channel_id": ch.id, "member_status": "joined"})

env.cr.commit()
lesson.invalidate_recordset()
print("P7K fixture ready: lesson id=%s category=%s published=%s converted=%s"
      % (lesson.id, lesson.slide_category, lesson.is_published,
         report.get("committed")))
