# -*- coding: utf-8 -*-
"""P7l smoke -- dead-video -> search-prompt transform logic.

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7l_smoke.py

Exercises the one-shot transform (scripts/migrate_p7l_video_search.py)
in-process: the search-block markup matches the existing 66
byte-for-byte; the query generator's encoding + per-module suffix +
Capture/M10/equipment overrides; the two structural cases (enriched
wrapper / watch-and-learn) with byte-for-byte round-trip
reconstruction; the live target predicate + dry-run (commits NOTHING)
+ idempotency; the 450 sentence rephrase; and the one-shot invariants.
All mutations roll back on shell exit; apply=True is never called.
"""
import importlib.util
import re

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


ADDON = "/mnt/extra-addons/neon_lms"
SCRIPT = ADDON + "/scripts/migrate_p7l_video_search.py"
MANIFEST = ADDON + "/__manifest__.py"
INIT = ADDON + "/__init__.py"

Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()


# ---- a fake slide so the pure helpers can run without the ORM ----
class _Cat:
    def __init__(self, name):
        self.name = name


class _Slide:
    def __init__(self, name, cat):
        self.name = name
        self.category_id = _Cat(cat)


# ---- load the transform script as a module (must NOT auto-run) ----
spec = importlib.util.spec_from_file_location("p7l_xform", SCRIPT)
xform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xform)
_check("T-P7L-00",
       all(hasattr(xform, f) for f in
           ("target_slides", "convert", "convert_html", "build_query",
            "report_state", "main")),
       "transform script exposes the expected callables")

ch = Ch.search([("neon_branded", "=", True)], limit=1)
_check("T-P7L-01", bool(ch), "branded Neon channel exists")

# ---- the search block matches the existing 66 byte-for-byte ----
EXISTING_66 = (
    '<div class="resources"><h3>Find a tutorial on YouTube</h3>'
    '<p>Use this link to find a current video tutorial on this topic. '
    'Watch a few results and pick the one that best matches the lesson content.</p>'
    '<p><a href="https://www.youtube.com/results?search_query=QQ" '
    'target="_blank" rel="noopener">Search YouTube for this topic</a></p></div>')
_check("T-P7L-02", (xform.SEARCH_BLOCK % "QQ") == EXISTING_66,
       "SEARCH_BLOCK is byte-identical to the existing-66 markup")

# ---- query encoding: spaces -> '+', parens -> %28/%29 ----
ppe = _Slide("L2 -- Personal Protective Equipment (PPE) for Technicians",
             "M02 -- Audio Basics")
_check("T-P7L-03",
       xform.build_query(ppe)
       == "Personal+Protective+Equipment+%28PPE%29+for+Technicians+live+sound+tutorial",
       "query encoding matches existing convention (got %r)" % xform.build_query(ppe))

# ---- per-module suffix ----
mh = _Slide("L01 -- Moving head anatomy", "M05 -- Lighting Advanced")
_check("T-P7L-04",
       xform.build_query(mh) == "Moving+head+anatomy+stage+lighting+DMX+tutorial",
       "M05 suffix = stage lighting DMX tutorial (got %r)" % xform.build_query(mh))

# ---- equipment manufacturer-targeted ----
m14 = _Slide("L5 -- Recording cues, cue lists and playback",
             "M14 -- Avolites Titan Mobile")
m15 = _Slide("L5 -- Channel processing", "M15 -- Allen and Heath SQ6")
m16 = _Slide("L5 -- Scenes, cues and timeline playback",
             "M16 -- Kommander Media Server")
_check("T-P7L-05",
       "Avolites+Titan+tutorial" in xform.build_query(m14)
       and "Allen+and+Heath+SQ6+tutorial" in xform.build_query(m15)
       and "Kommander+media+server+tutorial" in xform.build_query(m16),
       "equipment queries target the manufacturer")

# ---- Capture + M10 fault-discipline overrides ----
cap = _Slide("L4.11-CAP -- Introduction to Capture 3D Visualization Software",
             "M04 -- Lighting Basics")
af = _Slide("L06 -- Audio fault scenarios", "M10 -- Fault Finding")
lf = _Slide("L07 -- Lighting fault scenarios", "M10 -- Fault Finding")
vf = _Slide("L08 -- Video fault scenarios", "M10 -- Fault Finding")
_check("T-P7L-06",
       "Capture+Visualisation+tutorial" in xform.build_query(cap)
       and xform.build_query(af).endswith("live+sound+tutorial")
       and xform.build_query(lf).endswith("stage+lighting+DMX+tutorial")
       and xform.build_query(vf).endswith("event+video+LED+wall+tutorial"),
       "Capture + M10 fault-discipline overrides applied")

# ---- CASE A: enriched wrapper at start (nested divs + iframe) ----
CASE_A = (
    '<div data-yt-enriched="1" style="padding:12px">'
    '<strong>Watch and learn</strong>'
    '<div style="margin:14px 0"><div style="font-weight:600">vid title</div>'
    '<div style="position:relative">'
    '<iframe src="https://www.youtube.com/embed/abc123"></iframe></div></div>'
    '</div>'
    '<h3>Why this matters</h3><p>Real lesson text that must survive.</p>')
newA, okA, reasonA, removedA, blockA = xform.convert_html(CASE_A, mh)
_check("T-P7L-07",
       okA and reasonA == "enriched"
       and newA.startswith(blockA)
       and "<h3>Why this matters</h3><p>Real lesson text that must survive.</p>" in newA
       and not re.search(r"<iframe", newA, re.I)
       and newA.replace(blockA, removedA, 1) == CASE_A,
       "CASE A: block-at-start, body preserved, 0 iframe, round-trips (%s)" % reasonA)

# ---- CASE B: watch-and-learn mid-lesson + the stale 450 sentence ----
STALE = xform.SENTENCE_FIXES[450][0]
CASE_B = (
    '<div style="margin:0 0 16px">callout intro</div>'
    '<h3>What this is</h3><p>Authored intro that must survive.</p>'
    '<h3>Watch and learn</h3>'
    '<div style="margin:14px 0"><div>t1</div>'
    '<div><iframe src="https://youtu.be/x1"></iframe></div></div>'
    '<div style="margin:14px 0"><div>t2</div>'
    '<div><iframe src="https://www.youtube.com/embed/y2"></iframe></div></div>'
    '<h3>Software access</h3><p>tail text.</p>'
    '<ol>' + STALE + '</ol>')
newB, okB, reasonB, removedB, blockB = xform.convert_html(CASE_B, cap)
_check("T-P7L-08",
       okB and reasonB == "watch-and-learn"
       and newB.startswith('<div style="margin:0 0 16px">callout intro</div>'
                           '<h3>What this is</h3><p>Authored intro that must survive.</p>')
       and not re.search(r"<iframe", newB, re.I)
       and blockB in newB
       and newB.replace(blockB, removedB, 1) == CASE_B,
       "CASE B: in-place, intro preserved, 0 iframe, round-trips (%s)" % reasonB)

# ---- negative: an iframe outside the recognised block is rejected ----
BAD = CASE_A + '<p><iframe src="https://www.youtube.com/embed/stray"></iframe></p>'
_, okBad, reasonBad, _, _ = xform.convert_html(BAD, mh)
_check("T-P7L-09", (not okBad) and "outside" in reasonBad,
       "stray iframe outside the wrapper is refused (%s)" % reasonBad)

# ---- sentence-fix strings are sane ----
f450, r450 = xform.SENTENCE_FIXES[450]
_check("T-P7L-10",
       "three embedded YouTube tutorials" in f450
       and "search link" in r450 and "embedded" not in r450,
       "450 sentence rephrase drops 'embedded', points at the search link")

# ---- live: seed iframe + plain lessons, test the predicate ----
seedA = Sl.create({
    "name": "P7L SMOKE enriched", "channel_id": ch.id, "is_category": False,
    "slide_category": "article", "sequence": 6001, "html_content": CASE_A})
seedB = Sl.create({
    "name": "P7L SMOKE watch", "channel_id": ch.id, "is_category": False,
    "slide_category": "article", "sequence": 6002, "html_content": CASE_B})
seedPlain = Sl.create({
    "name": "P7L SMOKE plain", "channel_id": ch.id, "is_category": False,
    "slide_category": "article", "sequence": 6003,
    "html_content": "<h3>No video</h3><p>plain lesson.</p>"})

targets = xform.target_slides(env)
_check("T-P7L-11",
       seedA.id in targets.ids and seedB.id in targets.ids
       and seedPlain.id not in targets.ids,
       "iframe lessons targeted, plain lesson is not")


# ---- curated exclusion (lesson 443): id-keyed with a name-substring guard ----
class _ExSlide:
    def __init__(self, sid, name):
        self.id = sid
        self.name = name


_check("T-P7L-17",
       xform._is_curated_excluded(
           _ExSlide(443, "L2.11 -- Ear Training - Frequency Recognition Pack"))
       and not xform._is_curated_excluded(_ExSlide(443, "Some other lesson"))
       and not xform._is_curated_excluded(_ExSlide(999, "Ear Training")),
       "443 excluded only when the name guard matches; other ids never excluded")

xform.CURATED_EXCLUDE[seedA.id] = "P7L SMOKE enriched"
try:
    _check("T-P7L-18", seedA.id not in xform.target_slides(env).ids,
           "a curated-excluded iframe lesson is dropped from the target set")
finally:
    xform.CURATED_EXCLUDE.pop(seedA.id, None)

# ---- inject seedB into SENTENCE_FIXES so the sentence path fires ----
xform.SENTENCE_FIXES[seedB.id] = xform.SENTENCE_FIXES[450]
try:
    html_before = seedA.html_content
    report = xform.convert(env, apply=False)
    _check("T-P7L-12",
           report["targeted"] >= 2 and report["converted"] == report["targeted"]
           and report["preserved"] is True and report["committed"] is False
           and report["after"]["iframe_lessons"] == 0
           and not report["failures"],
           "dry-run converts all targets, preserved, 0 iframe after, no commit: %s"
           % report.get("note"))
    _check("T-P7L-13", report["sentence_fixed"] >= 1,
           "450-style sentence rephrase fired in the convert flow")
finally:
    xform.SENTENCE_FIXES.pop(seedB.id, None)

# dry-run rolled back -> seedA still carries its iframe
seedA.invalidate_recordset()
_check("T-P7L-14",
       re.search(r"<iframe", str(seedA.html_content or ""), re.I) is not None
       and str(seedA.html_content) == str(html_before),
       "dry-run left the DB untouched (seed still has its iframe)")

# ---- idempotency: a converted slide is no longer a target ----
seedA.write({"html_content": xform.SEARCH_BLOCK % "x"
             + "<h3>Why this matters</h3><p>Real lesson text that must survive.</p>"})
_check("T-P7L-15", seedA.id not in xform.target_slides(env).ids,
       "converted slide (no iframe) is not targeted (idempotent re-run = no-op)")

# ---- one-shot invariants: not wired into the running module ----
manifest = open(MANIFEST, encoding="utf-8").read()
init = open(INIT, encoding="utf-8").read()
data_block = manifest.split('"data"', 1)[-1].split("]", 1)[0]
_check("T-P7L-16",
       "migrate_p7l" not in data_block
       and "scripts" not in init
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
