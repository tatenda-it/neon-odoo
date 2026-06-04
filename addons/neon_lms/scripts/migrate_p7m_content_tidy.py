# -*- coding: utf-8 -*-
"""migrate_p7m_content_tidy.py -- One-shot LMS content tidy.

Two well-scoped, reversible content tasks on the branded Neon
channel. NOTHING is deleted, merged, or re-authored.

ITEM 1 -- quick-reference repositioning (labelling only):
  21 short summary lessons (dotted "Lx.y --" name + short
  html_content) in M01 (L1.1-L1.11) and M02 (L2.1-L2.10) read as
  confusing duplicates of the deep-dive lessons. They are already
  grouped at the start of each module; we add a "Quick Reference: "
  title prefix so the player clearly marks them. id 443
  ("L2.11 -- Ear Training - Frequency Recognition Pack", 4063
  chars) is dotted-named but a FULL ear-training lesson, not a
  summary -- excluded by the SHORT_MAX_HTML threshold. No
  re-sequencing (Gate-1: grouped-at-start). Reversible:
  revert_titles() strips the prefix.

ITEM 2 -- authoring-note cleanup (6 lessons):
  6 lessons leaked content-brief meta-commentary ("The source
  brief notes/requires/recommends that...") into learner text.
  Each is a targeted single-substring replace that drops the
  meta-reference while preserving meaning; all other content is
  preserved byte-for-byte. assert-before-replace: if the exact
  find-string is absent (already fixed / drift) the slide is
  skipped and reported, never corrupted. id 450's "placeholder
  logo" is legitimate 3D-modelling instruction -- NOT touched.

Run from the host:

    # DRY-RUN (default -- counts only, commits NOTHING):
    docker compose exec -T odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7m_content_tidy.py

    # APPLY (real write + commit) -- only with the flag:
    docker compose exec -T -e P7M_APPLY=1 odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7m_content_tidy.py

NOT a regular Odoo migration -- admin-run, once. NOT auto-
triggered (no post_init_hook, no cron, not in manifest data, not
imported by the addon __init__). Safe-by-default (dry-run unless
P7M_APPLY=1), atomic (single savepoint; any verify failure rolls
the whole batch back), idempotent (prefix-present / note-absent
targets are skipped).
"""
import logging
import os
import re

_logger = logging.getLogger(__name__)

QR_PREFIX = "Quick Reference: "
# the 21 summaries are <=861 chars; the L2.11 ear-training pack (4063)
# is a full lesson and must NOT be relabelled (Gate-1: exclude id 443).
SHORT_MAX_HTML = 1500
_DOT_RE = re.compile(r"^L\d+\.\d+\s*--")

# Item 2: exact plain-text sub-phrase -> replacement, per slide id.
# Verified present (once) in the raw html; the surrounding markup
# (<li>/<p>, links) is untouched.
AUTHOR_NOTE_FIXES = {
    453: ("The source brief notes that Lesson 2 needs a replacement PPE "
          "video and fuller written content, which means this topic is "
          "expected to support",
          "This topic supports"),
    455: ("The source brief requires technicians to",
          "Technicians must"),
    459: ("The source brief recommends that students practice",
          "Students should practice"),
    463: ("The source brief says students should build on",
          "Students should build on"),
    470: ("The source brief specifically recommends adding Capture to the "
          "lighting curriculum so students can",
          "Capture is part of the lighting curriculum, letting students"),
    476: ("The source brief recommends an advanced Capture lesson so "
          "students can",
          "This advanced Capture lesson helps students"),
}


def _channel(env):
    return env["slide.channel"].search([("neon_branded", "=", True)], limit=1)


def quick_ref_targets(env):
    """The 21 short summaries needing the prefix: branded-channel,
    non-category, dotted 'Lx.y --' name, short html, not already
    prefixed."""
    ch = _channel(env)
    if not ch:
        return env["slide.slide"].browse()
    cands = env["slide.slide"].search([
        ("channel_id", "=", ch.id), ("is_category", "=", False)])
    return cands.filtered(
        lambda s: _DOT_RE.match(s.name or "")
        and len(s.html_content or "") <= SHORT_MAX_HTML
        and not (s.name or "").startswith(QR_PREFIX))


def author_note_targets(env):
    """The author-note slides whose exact find-string is still present."""
    Slide = env["slide.slide"]
    out = Slide.browse()
    for sid, (find, _repl) in AUTHOR_NOTE_FIXES.items():
        s = Slide.browse(sid)
        if s.exists() and find in (s.html_content or ""):
            out |= s
    return out


def report_state(env):
    ch = _channel(env)
    Slide = env["slide.slide"]
    base = [("channel_id", "=", ch.id), ("is_category", "=", False)]
    prefixed = Slide.search_count(base + [("name", "=like", QR_PREFIX + "%")])
    sb_remaining = sum(
        1 for s in Slide.search(base)
        if "source brief" in (s.html_content or "").lower())
    return {
        "qr_prefixed": prefixed,
        "qr_pending": len(quick_ref_targets(env)),
        "author_notes_pending": len(author_note_targets(env)),
        "source_brief_remaining": sb_remaining,
    }


def convert(env, apply=False):
    qr = quick_ref_targets(env)
    notes = author_note_targets(env)
    before = report_state(env)
    report = {"apply": apply, "qr_targeted": len(qr),
              "note_targeted": len(notes), "before": before}

    if not qr and not notes:
        report["after"] = before
        report["committed"] = False
        report["note"] = "nothing pending -- idempotent no-op"
        return report

    # snapshots to prove preservation
    qr_html_before = {s.id: (s.html_content or "") for s in qr}
    note_other_before = {}  # full html minus the single find-substring

    env.cr.execute("SAVEPOINT p7m_tidy")
    try:
        # ITEM 1 -- title prefix only (html untouched)
        for s in qr:
            s.name = QR_PREFIX + s.name
        # ITEM 2 -- single targeted replace, assert-before-replace
        note_done = 0
        for s in notes:
            find, repl = AUTHOR_NOTE_FIXES[s.id]
            h = s.html_content or ""
            if find not in h:
                continue
            note_other_before[s.id] = h.replace(find, "\x00", 1)
            s.html_content = h.replace(find, repl, 1)
            note_done += 1

        qr.invalidate_recordset()
        notes.invalidate_recordset()
        after = report_state(env)
        report["after"] = after
        report["note_applied"] = note_done

        # verify: item-1 html byte-for-byte unchanged (only name changed)
        qr_html_ok = all(
            (s.html_content or "") == qr_html_before[s.id] for s in qr)
        # verify: item-2 changed ONLY the find-substring (rest byte-for-byte)
        note_ok = all(
            (env["slide.slide"].browse(sid).html_content or "")
            == note_other_before[sid].replace("\x00", AUTHOR_NOTE_FIXES[sid][1], 1)
            for sid in note_other_before)
        # verify: every targeted note no longer contains "source brief"
        sb_gone = all(
            "source brief" not in (env["slide.slide"].browse(sid).html_content or "").lower()
            for sid in note_other_before)

        report["qr_html_preserved"] = qr_html_ok
        report["note_content_preserved"] = note_ok
        report["source_brief_cleared"] = sb_gone

        if not (qr_html_ok and note_ok and sb_gone):
            env.cr.execute("ROLLBACK TO SAVEPOINT p7m_tidy")
            report["committed"] = False
            report["note"] = "ABORTED: a preservation/clear check failed -- rolled back"
            return report

        if apply:
            env.cr.execute("RELEASE SAVEPOINT p7m_tidy")
            env.cr.commit()
            report["committed"] = True
            report["note"] = "committed"
        else:
            env.cr.execute("ROLLBACK TO SAVEPOINT p7m_tidy")
            report["committed"] = False
            report["note"] = "DRY-RUN: rolled back, no write"
        return report
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT p7m_tidy")
        raise


def revert_titles(env):
    """Reversal for item 1: strip the 'Quick Reference: ' prefix."""
    ch = _channel(env)
    pref = env["slide.slide"].search([
        ("channel_id", "=", ch.id), ("is_category", "=", False),
        ("name", "=like", QR_PREFIX + "%")])
    for s in pref:
        s.name = s.name[len(QR_PREFIX):]
    return len(pref)


def main(env):
    apply = os.environ.get("P7M_APPLY") == "1"
    mode = "APPLY (real write + commit)" if apply else "DRY-RUN (no write)"
    print("=" * 72)
    print("P7m content tidy -- %s" % mode)
    print("=" * 72)
    report = convert(env, apply=apply)
    b, a = report["before"], report.get("after", report["before"])
    print("ITEM 1 quick-reference prefix:")
    print("  targeted (short Lx.y, unprefixed): %s" % report["qr_targeted"])
    print("  prefixed: %s -> %s" % (b["qr_prefixed"], a["qr_prefixed"]))
    print("  html byte-for-byte preserved: %s" % report.get("qr_html_preserved"))
    print("ITEM 2 author-note cleanup:")
    print("  targeted (find-string present): %s" % report["note_targeted"])
    print("  rephrased this run: %s" % report.get("note_applied"))
    print("  'source brief' remaining: %s -> %s"
          % (b["source_brief_remaining"], a["source_brief_remaining"]))
    print("  other content preserved byte-for-byte: %s"
          % report.get("note_content_preserved"))
    print("committed: %s   (%s)" % (report["committed"], report["note"]))
    print("=" * 72)
    if not apply:
        print("This was a DRY-RUN. Re-run with -e P7M_APPLY=1 to write + commit.")
    return report


# Auto-run when sourced via odoo shell. `env` injected by the shell.
# importlib-based smoke loads (no `env`) skip this block.
if "env" in dir():
    try:
        main(env)  # noqa: F821 -- env from shell
    except Exception as e:  # noqa: BLE001
        _logger.exception("P7m content tidy failed: %s", e)
        try:
            env.cr.rollback()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        print("FAILED: %s" % e)
