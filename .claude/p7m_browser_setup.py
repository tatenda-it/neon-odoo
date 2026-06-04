# -*- coding: utf-8 -*-
"""P7m browser-smoke fixture (idempotent, COMMITTED).

Run before p7m_browser_smoke.py:
    odoo shell -d <db> --no-http < p7m_browser_setup.py

Seeds two lessons in the branded channel and applies the REAL transform
operations to them (the script's QR_PREFIX + an AUTHOR_NOTE_FIXES pair),
so the browser smoke renders genuinely-transformed content:
  * a short dotted lesson -> title gets the "Quick Reference: " prefix;
  * a lesson carrying the 'source brief' meta -> rephrased (meta dropped).
Ensures p2m75_sales enrolment. Real-data-safe: only the two P7M seeds
are touched (scoped, not the global convert).
"""
import importlib.util

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()
Users = env["res.users"].sudo()
Enrollment = env["slide.channel.partner"].sudo()

spec = importlib.util.spec_from_file_location(
    "p7m_tidy", "/mnt/extra-addons/neon_lms/scripts/migrate_p7m_content_tidy.py")
xf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xf)

ch = Ch.search([("neon_branded", "=", True)], limit=1)
assert ch, "no Neon branded channel"

QR_BASE = "L9.1 -- P7M QR Browser Demo"
find, repl = xf.AUTHOR_NOTE_FIXES[455]
NOTE_META = ("<h3>Why this matters</h3><ul><li>%s respond appropriately to "
             "emergencies and understand incident reporting in live event "
             "settings.</li><li>Protect life first.</li></ul>" % find)


def _seed(name, vals):
    rec = Sl.search([("channel_id", "=", ch.id), ("name", "=", name)], limit=1)
    if rec:
        rec.write(vals)
    else:
        rec = Sl.create(dict(vals, name=name, channel_id=ch.id))
    return rec

# QR lesson: reset to unprefixed, then apply the script's prefix
qr = Sl.search([("channel_id", "=", ch.id),
                ("name", "in", [QR_BASE, xf.QR_PREFIX + QR_BASE])], limit=1)
qr_vals = {"is_category": False, "slide_category": "article",
           "slide_type": "article", "sequence": 9101, "is_published": True,
           "html_content": "<p>Bite-sized safety summary.</p>"}
if qr:
    qr.write(dict(qr_vals, name=QR_BASE))
else:
    qr = Sl.create(dict(qr_vals, name=QR_BASE, channel_id=ch.id))
qr.name = xf.QR_PREFIX + QR_BASE   # the real transform op

# Note lesson: reset to meta state, then apply the script's find/replace
note = _seed("L9 -- P7M Note Browser Demo", {
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 9102, "is_published": True,
    "html_content": NOTE_META})
if find in (note.html_content or ""):
    note.html_content = note.html_content.replace(find, repl, 1)

sales = Users.search([("login", "=", "p2m75_sales")], limit=1)
if sales:
    enr = Enrollment.search([("partner_id", "=", sales.partner_id.id),
                             ("channel_id", "=", ch.id)], limit=1)
    if not enr:
        Enrollment.create({"partner_id": sales.partner_id.id,
                           "channel_id": ch.id, "member_status": "joined"})

env.cr.commit()
print("P7M fixture ready: qr id=%s name=%r | note id=%s source_brief_present=%s"
      % (qr.id, qr.name, note.id,
         "source brief" in (note.html_content or "").lower()))
