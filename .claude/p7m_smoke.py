# -*- coding: utf-8 -*-
"""P7m smoke -- LMS content tidy (quick-ref prefix + author-note cleanup).

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7m_smoke.py

Exercises the one-shot transform (scripts/migrate_p7m_content_tidy.py)
in-process: the quick-ref predicate (dotted name + short html, excludes
the long L2.11-style pack + already-prefixed), the dry-run prefix (name
only, html byte-for-byte), the author-note find/replace pairs (drop
'source brief' meta, preserve the rest, assert-before-replace), idem-
potency, and the one-shot invariants. apply=True is never called; all
seeds roll back on shell exit.
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
SCRIPT = ADDON + "/scripts/migrate_p7m_content_tidy.py"
MANIFEST = ADDON + "/__manifest__.py"
INIT = ADDON + "/__init__.py"

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()

spec = importlib.util.spec_from_file_location("p7m_tidy", SCRIPT)
xf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xf)
_check("T-P7M-00",
       all(hasattr(xf, f) for f in
           ("quick_ref_targets", "author_note_targets", "convert",
            "report_state", "revert_titles", "main")),
       "transform exposes the expected entry points")

ch = Ch.search([("neon_branded", "=", True)], limit=1)
_check("T-P7M-01", bool(ch), "branded Neon channel exists")

# ---- ITEM 2 dict integrity (static, prod-id-independent) ----
ok = True
for sid, (find, repl) in xf.AUTHOR_NOTE_FIXES.items():
    if "source brief" not in find.lower() or repl == find \
       or "source brief" in repl.lower():
        ok = False
_check("T-P7M-02", ok and len(xf.AUTHOR_NOTE_FIXES) == 6,
       "6 author-note pairs; each find has 'source brief', repl drops it")

# ---- seed lessons for item-1 predicate ----
short_dot = Sl.create({
    "name": "L9.1 -- P7M Smoke Short", "channel_id": ch.id,
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 9001,
    "html_content": "<p>short quick-ref summary.</p>"})
long_dot = Sl.create({
    "name": "L9.2 -- P7M Smoke Long Pack", "channel_id": ch.id,
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 9002,
    "html_content": "<p>%s</p>" % ("x" * 1700)})
nondot = Sl.create({
    "name": "L9 -- P7M Smoke Deep", "channel_id": ch.id,
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 9003,
    "html_content": "<p>deep dive.</p>"})

qr = xf.quick_ref_targets(env)
_check("T-P7M-03", short_dot.id in qr.ids,
       "short dotted lesson is a quick-ref target")
_check("T-P7M-04",
       long_dot.id not in qr.ids and nondot.id not in qr.ids,
       "long dotted (L2.11-style) + non-dotted are NOT targeted")

# ---- item-1 dry-run: prefix name, html untouched, no commit ----
html_before = short_dot.html_content
rep = xf.convert(env, apply=False)
_check("T-P7M-05", rep["committed"] is False and rep["qr_targeted"] >= 1,
       "dry-run targets quick-ref + commits nothing: %s" % rep.get("note"))
_check("T-P7M-06", rep.get("qr_html_preserved") is True,
       "quick-ref html byte-for-byte preserved (name-only change)")
short_dot.invalidate_recordset()
_check("T-P7M-07",
       not short_dot.name.startswith(xf.QR_PREFIX)
       and short_dot.html_content == html_before,
       "dry-run rolled back: name unprefixed, html intact")

# ---- item-1 idempotency: a pre-prefixed lesson is not re-targeted ----
short_dot.name = xf.QR_PREFIX + short_dot.name
_check("T-P7M-08", short_dot.id not in xf.quick_ref_targets(env).ids,
       "already-prefixed lesson is not re-targeted")
short_dot.name = short_dot.name[len(xf.QR_PREFIX):]

# ---- ITEM 2 end-to-end (inject the seed id into the fix table) ----
find, repl = xf.AUTHOR_NOTE_FIXES[455]
note = Sl.create({
    "name": "L9 -- P7M Note", "channel_id": ch.id,
    "is_category": False, "slide_category": "article",
    "slide_type": "article", "sequence": 9004,
    "html_content": "<h3>Why this matters</h3><ul><li>%s respond appropriately "
                    "to emergencies.</li><li>Keep this line untouched.</li></ul>"
                    % find})
xf.AUTHOR_NOTE_FIXES[note.id] = (find, repl)
try:
    _check("T-P7M-09", note.id in xf.author_note_targets(env).ids,
           "seeded note lesson is an author-note target")
    rep2 = xf.convert(env, apply=False)
    _check("T-P7M-10",
           rep2.get("source_brief_cleared") is True
           and rep2.get("note_content_preserved") is True
           and rep2["committed"] is False,
           "dry-run: source brief cleared, rest preserved, no commit: %s"
           % rep2.get("note"))
    # confirm the rephrase semantics on the seeded html (simulate the replace)
    after = note.html_content.replace(find, repl, 1)
    _check("T-P7M-11",
           "source brief" not in after.lower()
           and repl in after and "Keep this line untouched." in after,
           "replace drops 'source brief', inserts repl, preserves siblings")
finally:
    del xf.AUTHOR_NOTE_FIXES[note.id]

# ---- one-shot invariants ----
manifest = open(MANIFEST, encoding="utf-8").read()
init = open(INIT, encoding="utf-8").read()
data_block = manifest.split('"data"', 1)[-1].split("]", 1)[0]
_check("T-P7M-12",
       "migrate_p7m" not in data_block and "scripts" not in init
       and "post_init" not in manifest,
       "transform is one-shot: not in data[], not imported, no hook")

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
