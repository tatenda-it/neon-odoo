# -*- coding: utf-8 -*-
"""P7k smoke -- lesson-render fix (transform logic) + lime->white.

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7k_smoke.py

ITEM 1: exercises the one-shot transform script
(scripts/migrate_p7k_slide_render.py) in-process -- the target
predicate (document + html_content + no pdf), the dry-run
conversion (document -> article, html preserved byte-for-byte,
NOTHING committed), idempotency, and that a real pdf document is
never touched. The end-to-end render is proven on the prod clone
+ by p7k_browser_smoke.py.

ITEM 2: the invented lime accent (#c8f36b) is gone from the
branding SCSS (style declarations), and the gate badge carries
the approved white-pill + grape text/border treatment.

Also asserts the transform script obeys the one-shot invariants
(not in manifest data, not imported by the addon, no cron/hook).

All mutations roll back on shell exit; apply=True is never called.
"""
import importlib.util
import re

from odoo import fields  # noqa: F401

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


ADDON = "/mnt/extra-addons/neon_lms"
SCRIPT = ADDON + "/scripts/migrate_p7k_slide_render.py"
SCSS = ADDON + "/static/src/scss/neon_lms_branding.scss"
QUIZSCSS = ADDON + "/static/src/scss/neon_lms_quiz.scss"
MANIFEST = ADDON + "/__manifest__.py"
INIT = ADDON + "/__init__.py"

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()

# ---- load the transform script as a module (must NOT auto-run) ----
spec = importlib.util.spec_from_file_location("p7k_xform", SCRIPT)
xform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xform)
_check("T-P7K-00",
       all(hasattr(xform, f) for f in
           ("target_slides", "convert_slides", "report_state", "main")),
       "transform script exposes target_slides/convert_slides/report_state/main")

ch = Ch.search([("neon_branded", "=", True)], limit=1)
_check("T-P7K-01", bool(ch), "branded Neon channel exists")

# ---- seed a BROKEN slide (document + html + no pdf) + a real-pdf
#      document + an article, to test the predicate boundaries.
broken = Sl.create({
    "name": "P7K SMOKE broken lesson", "channel_id": ch.id,
    "is_category": False, "slide_category": "document",
    "slide_type": "pdf", "source_type": "local_file",
    "sequence": 5001, "html_content": "<p>P7K marker body text.</p>"})
realpdf = Sl.create({
    "name": "P7K SMOKE real pdf", "channel_id": ch.id,
    "is_category": False, "slide_category": "document",
    "slide_type": "pdf", "source_type": "local_file",
    "sequence": 5002, "binary_content": b"JVBERi0xLjQK",
    "html_content": "<p>has a pdf, must NOT convert.</p>"})
article = Sl.create({
    "name": "P7K SMOKE article", "channel_id": ch.id,
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 5003,
    "html_content": "<p>already article.</p>"})

targets = xform.target_slides(env)
_check("T-P7K-02", broken.id in targets.ids,
       "broken doc+html+no-pdf is targeted")
_check("T-P7K-03",
       realpdf.id not in targets.ids and article.id not in targets.ids,
       "real-pdf document + article are NOT targeted")

# ---- dry-run conversion: flips to article, preserves html, no commit ----
html_before = broken.html_content
report = xform.convert_slides(env, apply=False)
_check("T-P7K-04", report["targeted"] >= 1 and report["committed"] is False,
       "dry-run targets the broken set + commits NOTHING: %s" % report.get("note"))
_check("T-P7K-05", report["html_preserved"] is True,
       "html_content preserved byte-for-byte in the conversion")
_check("T-P7K-06",
       report["after"]["document"] < report["before"]["document"]
       and report["after"]["article"] > report["before"]["article"],
       "document count drops, article count rises in the dry-run")
# the dry-run rolled back -> the broken slide is still document + same html
broken.invalidate_recordset()
_check("T-P7K-07",
       broken.slide_category == "document"
       and broken.html_content == html_before,
       "dry-run left the DB untouched (still document, html intact)")

# ---- idempotency: once a slide is article it is no longer a target ----
broken.write({"slide_category": "article", "slide_type": "article"})
_check("T-P7K-08", broken.id not in xform.target_slides(env).ids,
       "converted slide is no longer targeted (idempotent re-run = no-op)")

# ---- ITEM 2: lime gone from SCSS style; gate badge grape treatment ----
scss = open(SCSS, encoding="utf-8").read()
quiz_scss = open(QUIZSCSS, encoding="utf-8").read()


def _style_only(text):
    # strip // line comments before checking for the lime hex in declarations
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in text.splitlines())


_check("T-P7K-09",
       "#c8f36b" not in _style_only(scss)
       and "#c8f36b" not in _style_only(quiz_scss)
       and "$neon-lime" not in quiz_scss,
       "no lime #c8f36b / $neon-lime in branding.scss OR quiz.scss style")
_check("T-P7K-10",
       re.search(r"background:\s*#ffffff;\s*color:\s*#6B21A8;\s*"
                 r"border:\s*1px solid #6B21A8", scss) is not None,
       "gate badge = white pill + grape text + grape border")

# ---- one-shot invariants: not wired into the running module ----
manifest = open(MANIFEST, encoding="utf-8").read()
init = open(INIT, encoding="utf-8").read()
# 'migrate_p7k' may appear in the manifest *comment*; it must NOT appear
# inside the "data": [...] list, and the addon __init__ must not import it.
data_block = manifest.split('"data"', 1)[-1].split("]", 1)[0]
_check("T-P7K-11",
       "migrate_p7k" not in data_block
       and "scripts" not in init
       and "post_init" not in manifest,
       "transform script is one-shot: not in data[], not imported, no hook")

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print("Total: {}/{} passed".format(passed, total))
if passed != total:
    print("FAILED:")
    for k, v in results.items():
        if not v:
            print("  {}: FAIL".format(k))
env.cr.rollback()
