# -*- coding: utf-8 -*-
"""migrate_p7k_slide_render.py -- One-shot lesson-render fix.

P7e imported the 237 Neon Workshop lessons as slide_category
='document' / slide_type='pdf' / source_type='local_file' but
with NO pdf payload (binary_content / url / document_google_url
all empty). The real lesson text lives in html_content.

Result on the live player: the 'document' branch of
website_slides_templates_lesson.xml renders <t t-out=
"slide.embed_code"/> -- and embed_code RAISES RuntimeError for
a pdf document with no file -- so every lesson hangs on
"Loading..." and no content ever shows.

The fix: flip those slides to slide_category='article' (the
template's 'article' branch renders <div t-field=
"slide.html_content"/>). _compute_slide_type maps article ->
'article' automatically; we set it explicitly too so the result
is independent of compute ordering. html_content is the source
of truth and is preserved byte-for-byte -- NO content is
re-authored, created, or deleted.

Run from the host:

    # DRY-RUN (default -- counts only, commits NOTHING):
    docker compose exec -T odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7k_slide_render.py

    # APPLY (real write + commit) -- only with the flag:
    docker compose exec -T -e P7K_APPLY=1 odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_p7k_slide_render.py

NOT a regular Odoo migration -- runs once at admin discretion.
NOT auto-triggered (no post_init_hook, no cron, not listed in
manifest data files, not imported by the addon __init__).

Safe-by-default: without P7K_APPLY=1 the conversion is applied
inside a savepoint and ROLLED BACK after counting, so sourcing
the script can never mutate prod by accident.

Idempotent: the target predicate (document + html_content + no
pdf) no longer matches once a slide is article, so re-running is
a no-op.

Atomic: the whole set is converted in ONE savepoint; if the
html-preservation check fails for any slide the savepoint is
rolled back -- a partial failure can never leave a half-
converted course.
"""
import logging
import os

_logger = logging.getLogger(__name__)


def target_slides(env):
    """The broken set: branded-channel content slides that are
    document/pdf carrying html_content but no actual pdf file.

    Restricting to 'has html_content AND no pdf payload' means we
    never touch a document slide that legitimately holds a PDF,
    and the predicate stops matching after conversion (idempotency).
    """
    channels = env["slide.channel"].search([("neon_branded", "=", True)])
    if not channels:
        return env["slide.slide"].browse()
    candidates = env["slide.slide"].search([
        ("channel_id", "in", channels.ids),
        ("is_category", "=", False),
        ("slide_category", "=", "document"),
    ])
    return candidates.filtered(
        lambda s: s.html_content
        and not s.binary_content
        and not s.url
        and not s.document_google_url
    )


def report_state(env):
    """Distribution snapshot across the branded channels (for the
    before/after preflight)."""
    channels = env["slide.channel"].search([("neon_branded", "=", True)])
    Slide = env["slide.slide"]
    base = [("channel_id", "in", channels.ids), ("is_category", "=", False)]
    return {
        "channels": len(channels),
        "document": Slide.search_count(base + [("slide_category", "=", "document")]),
        "article": Slide.search_count(base + [("slide_category", "=", "article")]),
        "pdf_type": Slide.search_count(base + [("slide_type", "=", "pdf")]),
        "broken_target": len(target_slides(env)),
        "sections": Slide.search_count(
            [("channel_id", "in", channels.ids), ("is_category", "=", True)]),
    }


def convert_slides(env, apply=False):
    """Convert the broken set to article in ONE atomic savepoint.

    Returns a report dict. With apply=False (default) the write is
    rolled back after counting (dry-run). With apply=True the write
    is committed -- but only after every slide's html_content is
    verified unchanged; any mismatch rolls the whole batch back.
    """
    targets = target_slides(env)
    before = report_state(env)
    report = {"apply": apply, "targeted": len(targets), "before": before}

    if not targets:
        report["after"] = before
        report["html_preserved"] = True
        report["committed"] = False
        report["note"] = "no broken slides -- nothing to convert (idempotent no-op)"
        return report

    # snapshot html BEFORE the write to prove byte-for-byte preservation
    html_before = {s.id: (s.html_content or "") for s in targets}

    env.cr.execute("SAVEPOINT p7k_convert")
    try:
        targets.write({"slide_category": "article", "slide_type": "article"})
        targets.invalidate_recordset()
        preserved = all(
            (s.html_content or "") == html_before[s.id] for s in targets)
        report["after"] = report_state(env)
        report["html_preserved"] = preserved

        if not preserved:
            env.cr.execute("ROLLBACK TO SAVEPOINT p7k_convert")
            report["committed"] = False
            report["note"] = "ABORTED: html_content changed -- rolled back, no write"
            return report

        if apply:
            env.cr.execute("RELEASE SAVEPOINT p7k_convert")
            env.cr.commit()
            report["committed"] = True
            report["note"] = "committed"
        else:
            env.cr.execute("ROLLBACK TO SAVEPOINT p7k_convert")
            report["committed"] = False
            report["note"] = "DRY-RUN: rolled back, no write"
        return report
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT p7k_convert")
        raise


def main(env):
    apply = os.environ.get("P7K_APPLY") == "1"
    mode = "APPLY (real write + commit)" if apply else "DRY-RUN (no write)"
    print("=" * 72)
    print("P7k lesson-render fix -- %s" % mode)
    print("=" * 72)
    report = convert_slides(env, apply=apply)
    b, a = report["before"], report.get("after", report["before"])
    print("Branded channels: %s   Section headers (untouched): %s"
          % (b["channels"], b["sections"]))
    print("Targeted broken slides (document + html + no pdf): %s"
          % report["targeted"])
    print("  document: %s -> %s" % (b["document"], a["document"]))
    print("  article:  %s -> %s" % (b["article"], a["article"]))
    print("  pdf type: %s -> %s" % (b["pdf_type"], a["pdf_type"]))
    print("  html_content preserved byte-for-byte: %s" % report["html_preserved"])
    print("  committed: %s   (%s)" % (report["committed"], report["note"]))
    print("=" * 72)
    if not apply:
        print("This was a DRY-RUN. Re-run with -e P7K_APPLY=1 to write + commit.")
    return report


# Auto-run when sourced via odoo shell. `env` is injected by the
# shell into the script's exec namespace. importlib-based smoke
# loads (which don't set `env`) skip this block.
if "env" in dir():
    try:
        main(env)  # noqa: F821 -- env from shell
    except Exception as e:  # noqa: BLE001
        _logger.exception("P7k render fix failed: %s", e)
        try:
            env.cr.rollback()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        print("FAILED: %s" % e)
