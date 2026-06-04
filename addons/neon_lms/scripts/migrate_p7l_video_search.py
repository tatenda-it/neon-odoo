# -*- coding: utf-8 -*-
"""migrate_p7l_video_search.py -- One-shot LMS dead-video fix.

125 Neon Workshop lessons carry YouTube <iframe> embeds whose video
IDs are ~97% fabricated (404 -> "Video unavailable" in the player).
Robin (content owner) declined curating replacements; instead we
convert each dead embed to the SAME "search YouTube for this topic"
prompt that 66 other lessons in this course already use, so the
learner gets a working link to find a current video and there are
ZERO dead embeds.

Of the 125 iframe lessons, 124 are converted; lesson 443 (L2.11 Ear
Training) is CURATED-EXCLUDED -- see CURATED_EXCLUDE below.

WHAT CHANGES (only the video block; everything else byte-for-byte):
  * CASE A (122 lessons): a single <div data-yt-enriched="1">...</div>
    wrapper at the START of html_content holds all the iframes. The
    whole wrapper is replaced by the search-prompt block.
  * CASE B (2 Capture lessons, 450 + 451): videos sit mid-lesson under
    an <h3>Watch and learn</h3> heading as consecutive
    <div style="margin:14px 0">...</div> blocks. That heading + run is
    replaced IN PLACE by the search-prompt block.
  * SENTENCE FIX (450 only): the now-stale "<li>Watch the three
    embedded YouTube tutorials...</li>" sentence is rephrased to point
    at the search link (assert-before-replace; 451 has no such line and
    is skipped).

The search query = quote_plus(deprefixed-title + " " + per-module
suffix); the suffix is the dominant one each module already uses in
its existing search prompts (Capture + M10 fault disciplines + the
three equipment manufacturers get topic-targeted overrides). The
search-prompt MARKUP is byte-identical to the existing 66.

INTEGRITY: per slide we reconstruct the original from the result by
swapping the search block back for the removed video block (and the
sentence back) and assert it equals the original byte-for-byte -- so
the ONLY change is the intended one. Plus: 0 <iframe> remain and a
youtube.com/results link is present. Any failure rolls the whole
batch back.

Run from the host:

    # DRY-RUN (default -- counts only, commits NOTHING):
    docker compose exec -T odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7l_video_search.py

    # APPLY (real write + commit) -- only with the flag:
    docker compose exec -T -e P7L_APPLY=1 odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7l_video_search.py

NOT a regular Odoo migration -- admin-run, once. NOT auto-triggered
(no post_init_hook, no cron, not in manifest data, not imported by the
addon __init__). Safe-by-default (dry-run unless P7L_APPLY=1), atomic
(single savepoint), idempotent (a converted slide has no iframe so it
is no longer a target; a fixed sentence is no longer found).
"""
import logging
import os
import re
from urllib.parse import quote_plus

_logger = logging.getLogger(__name__)

# ---- detection ----
IFRAME_YT_RE = re.compile(
    r"<iframe[^>]*?(?:youtube(?:-nocookie)?\.com|youtu\.be)", re.I)
ANY_IFRAME_RE = re.compile(r"<iframe", re.I)
ENRICHED_RE = re.compile(r'<div\s+data-yt-enriched="1"', re.I)
WATCH_H3_RE = re.compile(r'<h3>\s*Watch and learn\s*</h3>', re.I)
VIDEO_DIV_RE = re.compile(r'<div\s+style="margin:14px 0">', re.I)
DIV_TAG_RE = re.compile(r'<(/?)div\b', re.I)
PREFIX_RE = re.compile(r'^L\d+(?:\.\d+)?(?:-[A-Za-z]+)?\s*--\s*', re.I)
CODE_RE = re.compile(r'(M\d{2})')

# ---- query suffix per module (dominant suffix the existing 66 use) ----
MODULE_SUFFIX = {
    "M02": "live sound tutorial",
    "M03": "live sound tutorial",
    "M04": "stage lighting DMX tutorial",
    "M05": "stage lighting DMX tutorial",
    "M06": "event video LED wall tutorial",
    "M07": "event video LED wall tutorial",
    "M08": "event power generator safety tutorial",
    "M09": "tutorial live event production",
    "M10": "tutorial live event production",
    "M11": "live sound tutorial",
    "M12": "tutorial live event production",
    "M13": "tutorial live event production",
    # equipment: manufacturer-targeted. (The existing 66 equipment
    # prompts are off-by-one buggy -- we do NOT replicate that.)
    "M14": "Avolites Titan tutorial",
    "M15": "Allen and Heath SQ6 tutorial",
    "M16": "Kommander media server tutorial",
}
DEFAULT_SUFFIX = "tutorial live event production"

# the existing 66 search-prompt block -- matched byte-for-byte.
SEARCH_BLOCK = (
    '<div class="resources"><h3>Find a tutorial on YouTube</h3>'
    '<p>Use this link to find a current video tutorial on this topic. '
    'Watch a few results and pick the one that best matches the lesson content.</p>'
    '<p><a href="https://www.youtube.com/results?search_query=%s" '
    'target="_blank" rel="noopener">Search YouTube for this topic</a></p></div>'
)

# Gate-1 addition: rephrase the now-stale "watch the embedded tutorials"
# sentence so it matches the search-link reality. assert-before-replace;
# 451 has no such sentence and is skipped.
SENTENCE_FIXES = {
    450: ("<li>Watch the three embedded YouTube tutorials, taking notes "
          "on navigation and interface.</li>",
          "<li>Use the YouTube search link above to find current video "
          "tutorials, taking notes on navigation and interface.</li>"),
}

# Gate-2 apply decision (Tatenda, 2026-06-04): EXCLUDE curated lessons
# from genericisation. Lesson 443 "L2.11 -- Ear Training - Frequency
# Recognition Pack" has 4 individually-labelled videos, each already with
# a direct "Open on YouTube" link -- a generic search prompt regresses it.
# Its dead-embed cleanup (drop dead iframes, KEEP the 4 Open-on-YouTube
# links) is a SEPARATE micro-task pending Robin's call -- NOT handled here.
# id-keyed (matches this codebase's one-shot prod-id convention, cf.
# SENTENCE_FIXES) with a name-substring guard so a drifted id cannot be
# excluded by accident. -> conversion set is 124, not 125.
CURATED_EXCLUDE = {443: "Ear Training"}


def _is_curated_excluded(slide):
    guard = CURATED_EXCLUDE.get(slide.id)
    return bool(guard) and guard in (slide.name or "")


def _channel(env):
    return env["slide.channel"].search([("neon_branded", "=", True)], limit=1)


def deprefix(name):
    return PREFIX_RE.sub("", name or "").strip()


def module_code(slide):
    m = CODE_RE.match(slide.category_id.name or "") if slide.category_id else None
    return m.group(1) if m else None


def build_query(slide):
    code = module_code(slide)
    name = slide.name or ""
    # topic overrides where the course already uses an established suffix
    if "Capture" in name:
        suffix = "Capture Visualisation tutorial"          # matches existing 470/476
    elif code == "M10" and re.search(r"audio fault", name, re.I):
        suffix = "live sound tutorial"                     # matches existing 511
    elif code == "M10" and re.search(r"lighting fault", name, re.I):
        suffix = "stage lighting DMX tutorial"             # matches existing 512
    elif code == "M10" and re.search(r"video fault", name, re.I):
        suffix = "event video LED wall tutorial"           # matches existing 513
    else:
        suffix = MODULE_SUFFIX.get(code, DEFAULT_SUFFIX)
    return quote_plus(deprefix(slide.name) + " " + suffix)


def balanced_div(h, start_idx):
    """Return (start, end) of the balanced <div>...</div> opening at
    start_idx, walking nested div tags. None if unbalanced."""
    depth = 0
    for m in DIV_TAG_RE.finditer(h, start_idx):
        if m.group(1) == "":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start_idx, h.index(">", m.end()) + 1
    return None


def convert_html(h, slide):
    """Return (newhtml, ok, reason, removed, block).

    ``removed`` is the exact video span taken out; ``block`` is the
    search-prompt block put in. Pure string ops -- byte-preserving.
    """
    h = str(h or "")  # de-Markup so concatenating the plain-str block does not escape it
    block = SEARCH_BLOCK % build_query(slide)

    em = ENRICHED_RE.search(h)
    if em:
        # CASE A: a single enriched wrapper, holding every iframe.
        if len(ENRICHED_RE.findall(h)) != 1:
            return (h, False, "multiple enriched wrappers", None, block)
        span = balanced_div(h, em.start())
        if not span:
            return (h, False, "unbalanced enriched div", None, block)
        s, e = span
        if ANY_IFRAME_RE.search(h[:s]) or ANY_IFRAME_RE.search(h[e:]):
            return (h, False, "iframe outside enriched wrapper", None, block)
        new = h[:s] + block + h[e:]
        return (new, True, "enriched", h[s:e], block)

    wm = WATCH_H3_RE.search(h)
    if wm:
        # CASE B: 'Watch and learn' heading + consecutive video divs.
        hstart = wm.start()
        cur = wm.end()
        end = None
        while True:
            ws = re.match(r"\s*", h[cur:]).end()
            nxt = cur + ws
            if VIDEO_DIV_RE.match(h, nxt):
                vspan = balanced_div(h, nxt)
                if not vspan:
                    return (h, False, "unbalanced video div", None, block)
                cur = vspan[1]
                end = cur
            else:
                break
        if end is None:
            return (h, False, "no video divs after Watch-and-learn", None, block)
        if ANY_IFRAME_RE.search(h[:hstart]) or ANY_IFRAME_RE.search(h[end:]):
            return (h, False, "iframe outside watch-and-learn section", None, block)
        new = h[:hstart] + block + h[end:]
        return (new, True, "watch-and-learn", h[hstart:end], block)

    return (h, False, "no recognised video block", None, block)


def target_slides(env):
    """The 124: branded-channel content slides whose html_content has a
    YouTube <iframe>, MINUS the curated-excluded lessons (443). The
    predicate stops matching after conversion."""
    ch = _channel(env)
    if not ch:
        return env["slide.slide"].browse()
    cands = env["slide.slide"].search([
        ("channel_id", "=", ch.id), ("is_category", "=", False)])
    return cands.filtered(
        lambda s: IFRAME_YT_RE.search(str(s.html_content or ""))
        and not _is_curated_excluded(s))


def report_state(env):
    ch = _channel(env)
    Slide = env["slide.slide"]
    base = [("channel_id", "=", ch.id), ("is_category", "=", False)]
    cands = Slide.search(base)
    iframe = sum(1 for s in cands if IFRAME_YT_RE.search(str(s.html_content or "")))
    iframes_total = sum(
        len(ANY_IFRAME_RE.findall(str(s.html_content or ""))) for s in cands)
    search = sum(1 for s in cands
                 if "youtube.com/results" in str(s.html_content or ""))
    return {"content_slides": len(cands), "iframe_lessons": iframe,
            "iframes_total": iframes_total, "search_lessons": search}


def convert(env, apply=False):
    targets = target_slides(env)
    before = report_state(env)
    report = {"apply": apply, "targeted": len(targets), "before": before,
              "converted": 0, "sentence_fixed": 0, "cases": {},
              "failures": []}

    if not targets:
        report["after"] = before
        report["preserved"] = True
        report["committed"] = False
        report["note"] = "no iframe lessons -- nothing to convert (idempotent no-op)"
        return report

    # snapshot originals to prove byte-for-byte reconstruction
    originals = {s.id: str(s.html_content or "") for s in targets}

    env.cr.execute("SAVEPOINT p7l_video")
    try:
        preserved = True
        for s in targets:
            h0 = originals[s.id]
            new, ok, reason, removed, block = convert_html(h0, s)
            if not ok:
                report["failures"].append((s.id, s.name, reason))
                preserved = False
                continue
            report["cases"][reason] = report["cases"].get(reason, 0) + 1

            # Gate-1 sentence fix (assert-before-replace; only 450 matches)
            sent_pair = None
            if s.id in SENTENCE_FIXES:
                find, repl = SENTENCE_FIXES[s.id]
                if find in new:
                    new = new.replace(find, repl, 1)
                    sent_pair = (find, repl)
                    report["sentence_fixed"] += 1

            # integrity: reconstruct the original from the result; the ONLY
            # difference must be [video block -> search block] (+ sentence).
            recon = new.replace(block, removed, 1)
            if sent_pair:
                recon = recon.replace(sent_pair[1], sent_pair[0], 1)
            if recon != h0:
                report["failures"].append((s.id, s.name, "reconstruction mismatch"))
                preserved = False
                continue
            if ANY_IFRAME_RE.search(new):
                report["failures"].append((s.id, s.name, "iframe survived"))
                preserved = False
                continue
            if "youtube.com/results" not in new:
                report["failures"].append((s.id, s.name, "no search link"))
                preserved = False
                continue

            s.html_content = new
            report["converted"] += 1

        targets.invalidate_recordset()
        after = report_state(env)
        report["after"] = after
        report["preserved"] = preserved

        # exclusion-robust invariant: converting N targets removes exactly N
        # iframe-lessons; any curated-excluded iframe lesson (443) is left.
        ok_all = (preserved and not report["failures"]
                  and report["converted"] == len(targets)
                  and after["iframe_lessons"]
                  == before["iframe_lessons"] - report["converted"])
        if not ok_all:
            env.cr.execute("ROLLBACK TO SAVEPOINT p7l_video")
            report["committed"] = False
            report["note"] = "ABORTED: a check failed -- rolled back, no write"
            return report

        if apply:
            env.cr.execute("RELEASE SAVEPOINT p7l_video")
            env.cr.commit()
            report["committed"] = True
            report["note"] = "committed"
        else:
            env.cr.execute("ROLLBACK TO SAVEPOINT p7l_video")
            report["committed"] = False
            report["note"] = "DRY-RUN: rolled back, no write"
        return report
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT p7l_video")
        raise


def main(env):
    apply = os.environ.get("P7L_APPLY") == "1"
    mode = "APPLY (real write + commit)" if apply else "DRY-RUN (no write)"
    print("=" * 72)
    print("P7l dead-video -> search-prompt -- %s" % mode)
    print("=" * 72)
    report = convert(env, apply=apply)
    b, a = report["before"], report.get("after", report["before"])
    print("Branded content slides: %s" % b["content_slides"])
    print("Targeted iframe lessons (excludes curated 443): %s" % report["targeted"])
    print("  iframe lessons : %s -> %s  (remaining = curated-excluded)"
          % (b["iframe_lessons"], a["iframe_lessons"]))
    print("  iframes total  : %s -> %s  (remaining = 443's untouched embeds)"
          % (b["iframes_total"], a["iframes_total"]))
    print("  search lessons : %s -> %s" % (b["search_lessons"], a["search_lessons"]))
    print("  converted      : %s   (cases: %s)" % (report["converted"], report["cases"]))
    print("  sentence fixed  : %s   (lesson 450)" % report["sentence_fixed"])
    print("  byte-for-byte reconstruction preserved: %s" % report["preserved"])
    if report["failures"]:
        print("  FAILURES:")
        for sid, name, reason in report["failures"]:
            print("    [%s] %r -- %s" % (sid, name, reason))
    print("  committed: %s   (%s)" % (report["committed"], report["note"]))
    print("=" * 72)
    if not apply:
        print("This was a DRY-RUN. Re-run with -e P7L_APPLY=1 to write + commit.")
    return report


# Auto-run when sourced via odoo shell. `env` injected by the shell.
# importlib-based smoke loads (no `env`) skip this block.
if "env" in dir():
    try:
        main(env)  # noqa: F821 -- env from shell
    except Exception as e:  # noqa: BLE001
        _logger.exception("P7l video fix failed: %s", e)
        try:
            env.cr.rollback()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        print("FAILED: %s" % e)
