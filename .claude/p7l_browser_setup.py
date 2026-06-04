# -*- coding: utf-8 -*-
"""P7l browser-smoke fixture setup (idempotent, COMMITTED).

Run once before p7l_browser_smoke.py:
    odoo shell -d <db> --no-http < p7l_browser_setup.py

Seeds two dedicated lessons on the branded channel, each put into the
DEAD-EMBED state (a real YouTube <iframe> block) and then run THROUGH
THE REAL TRANSFORM (scripts/migrate_p7l_video_search.py convert_html)
so they end as the "search YouTube" prompt:
  * "P7L BROWSER lesson"        -- CASE A (enriched wrapper at start)
  * "P7L BROWSER Capture lesson"-- CASE B (watch-and-learn mid-lesson)
    + the 450-style stale-sentence rephrase applied.

The browser smoke then opens each in the learner player and asserts the
search prompt renders (no dead <iframe> / "Video unavailable", a
clickable youtube.com/results link, and the real lesson body survived).

REAL-DATA-SAFE: conversion is scoped to each dedicated lesson via
convert_html (NOT the channel-wide convert()), so it can never touch
real lessons. Resetting + re-converting each run exercises the actual
transform end to end. Also ensures p2m75_sales is enrolled.
"""
import importlib.util

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()
Users = env["res.users"].sudo()
Enrollment = env["slide.channel.partner"].sudo()

SCRIPT = "/mnt/extra-addons/neon_lms/scripts/migrate_p7l_video_search.py"
spec = importlib.util.spec_from_file_location("p7l_xform", SCRIPT)
xform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xform)

ch = Ch.search([("neon_branded", "=", True)], limit=1)
assert ch, "no Neon branded channel"

MARKER_A = "P7L render proof A: this lesson body must survive the video swap."
ENRICHED = (
    '<div data-yt-enriched="1" style="margin:0 0 16px;padding:12px;'
    'background:#f6f8fb;border-left:4px solid #1565c0;border-radius:4px">'
    '<strong>Watch and learn</strong>'
    '<div style="margin:14px 0"><div style="font-weight:600">A tutorial</div>'
    '<div style="position:relative;padding-bottom:56.25%;height:0">'
    '<iframe style="position:absolute;width:100%;height:100%" '
    'src="https://www.youtube.com/embed/DEADID000A" allowfullscreen></iframe>'
    '</div></div></div>'
    '<h3>Why this matters</h3><p>' + MARKER_A + '</p>')

MARKER_B = "P7L render proof B: the Capture intro must survive."
STALE = xform.SENTENCE_FIXES[450][0]
FIXED = xform.SENTENCE_FIXES[450][1]
CAPTURE = (
    '<div style="margin:0 0 16px;padding:12px;background:#e8f4ff">'
    '<strong>Capture 3D</strong></div>'
    '<h3>What Capture is</h3><p>' + MARKER_B + '</p>'
    '<h3>Watch and learn</h3>'
    '<div style="margin:14px 0"><div style="font-weight:600">t1</div>'
    '<div style="position:relative"><iframe '
    'src="https://www.youtube.com/embed/DEADID00B1" allowfullscreen></iframe></div></div>'
    '<div style="margin:14px 0"><div style="font-weight:600">t2</div>'
    '<div style="position:relative"><iframe '
    'src="https://www.youtube.com/embed/DEADID00B2" allowfullscreen></iframe></div></div>'
    '<h3>Practice exercise</h3><ol>' + STALE + '</ol>')


def _seed(name, html):
    lesson = Sl.search([("channel_id", "=", ch.id), ("name", "=", name)], limit=1)
    vals = {
        "name": name, "channel_id": ch.id, "is_category": False,
        "slide_category": "article", "slide_type": "article",
        "sequence": 4998, "is_published": True,
        "binary_content": False, "url": False, "html_content": html,
    }
    if lesson:
        lesson.write(vals)
    else:
        lesson = Sl.create(vals)
    return lesson


# CASE A -- convert (block only) scoped to this lesson
lessonA = _seed("P7L BROWSER lesson", ENRICHED)
newA, okA, reasonA, _r, _b = xform.convert_html(lessonA.html_content, lessonA)
assert okA, "case A convert failed: %s" % reasonA
lessonA.html_content = newA

# CASE B (Capture) -- convert + the 450-style sentence rephrase
lessonB = _seed("P7L BROWSER Capture lesson", CAPTURE)
newB, okB, reasonB, _r, _b = xform.convert_html(lessonB.html_content, lessonB)
assert okB, "case B convert failed: %s" % reasonB
if STALE in newB:
    newB = newB.replace(STALE, FIXED, 1)
lessonB.html_content = newB

# ensure p2m75_sales is an enrolled member
sales = Users.search([("login", "=", "p2m75_sales")], limit=1)
if sales:
    enr = Enrollment.search([("partner_id", "=", sales.partner_id.id),
                             ("channel_id", "=", ch.id)], limit=1)
    if not enr:
        Enrollment.create({"partner_id": sales.partner_id.id,
                           "channel_id": ch.id, "member_status": "joined"})

env.cr.commit()
lessonA.invalidate_recordset()
lessonB.invalidate_recordset()
print("P7L fixture ready: A=%s (iframe=%s) B=%s (iframe=%s, stale_gone=%s)"
      % (lessonA.id, "<iframe" in str(lessonA.html_content),
         lessonB.id, "<iframe" in str(lessonB.html_content),
         STALE not in str(lessonB.html_content)))