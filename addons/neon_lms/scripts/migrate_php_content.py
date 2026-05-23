# -*- coding: utf-8 -*-
"""migrate_php_content.py -- One-shot LMS content import.

Parses the PHP legacy training pack
(neon_final_publication_master_for_upload.docx) and creates
slide.slide / neon.lms.quiz.question / neon.lms.practical.
scenario / neon.lms.sop records under the existing 17 modules
(seeded in P7e M1).

Run from the host:

    docker compose exec -T odoo \\
        odoo shell -d neon_crm --no-http < \\
        addons/neon_lms/scripts/migrate_php_content.py

NOT a regular Odoo migration -- runs once at admin discretion.
NOT auto-triggered (no post_init_hook, no cron, not listed in
manifest data files).

Pre-flight requirements:
1. neon_lms installed + P7e M1-M9 seeds present (17 modules,
   7 tracks, 6 operating authorities).
2. python-docx installed in the container (pip install
   python-docx). Deferred import -- module loads fine without
   it; only the actual import call fails.
3. docx file uploaded to a container-readable path (default:
   /home/odoo/tmp/neon_final_publication_master_for_upload.
   docx). Override by editing DEFAULT_DOCX_PATH or calling
   main(env, docx_path=...).

Idempotent: re-running skips existing records (matched by
module code + name/text prefix).

Per-section error handling: a failure in one section
(savepoint rollback) doesn't abort the rest. Final report
counts skipped/created/errored per section.
"""
import logging
import os
import re

_logger = logging.getLogger(__name__)


DEFAULT_DOCX_PATH = (
    "/home/odoo/tmp/"
    "neon_final_publication_master_for_upload.docx")


# Mojibake -> real character map.
# Source: html-to-docx export round-tripped UTF-8 through
# cp1252, leaving artifacts per audit findings (audit doc
# section 6, "Authoring-system artefacts to strip").
MOJIBAKE_MAP = [
    ("â€™", "'"),
    ("â€œ", "“"),
    ("â€", "”"),
    ("â€”", "—"),
    ("â€“", "–"),
    ("â€¦", "…"),
    ("Ã©", "é"),
    ("Ã ", "à"),
    ("Â ", " "),
    ("﻿", ""),
]


MODULE_PATTERN = re.compile(r"^M(\d{2})\b")
CITATION_PATTERN = re.compile(r"\[(?:file|cite):\d+\]")
QUIZ_LINE_PATTERN = re.compile(
    r"^(?:Question\s+\d+|\d+\.\s+)", re.IGNORECASE)
SCENARIO_LINE_PATTERN = re.compile(
    r"^(?:Practical(?:\s+(?:Quiz|Scenario))?|Scenario)\s*\d*",
    re.IGNORECASE)


SOP_KEYWORDS = [
    "Allen & Heath SQ6",
    "QU16",
    "QU24",
    "Midas / Behringer",
    "Audio-Technica wireless",
    "Shure wireless",
    "Wireless Workbench",
    "Dante",
    "PowerWorks Zethus",
    "RCF NX/TT+",
    "Avolites Titan Mobile",
    "Capture",
    "Kommander",
    "Projector / LED / HDMI",
    "Warehouse",
    "Outdoor generator",
    "Truss / stand",
]


def sanitize_mojibake(text):
    """Replace known html-to-docx UTF-8/cp1252 artifacts."""
    if not text:
        return text
    out = text
    for bad, good in MOJIBAKE_MAP:
        out = out.replace(bad, good)
    return out


def detect_module_code(line):
    """Return 'M01'..'M17' if line starts with one, else None.

    Heuristic: line must begin with M\\d\\d and the digits must
    be in [01, 17]. 'Module M01' returns None (no leading M01).
    'M18 Future' also returns None (out of range).
    """
    if not line:
        return None
    m = MODULE_PATTERN.match(line.strip())
    if not m:
        return None
    n = int(m.group(1))
    if 1 <= n <= 17:
        return "M%02d" % n
    return None


def strip_citations(text):
    """Remove [file:N] and [cite:N] markers (authoring artefacts)."""
    if not text:
        return text
    return CITATION_PATTERN.sub("", text).strip()


def preflight_check(docx_path, env):
    """Return (ok, message) tuple. ok=True only when all
    pre-conditions met. Used by main() before any import work."""
    if not docx_path or not os.path.exists(docx_path):
        return (
            False,
            "DOCX not found at %s. Upload it to a "
            "container-readable path first." % docx_path,
        )
    Module = env.get("neon.lms.module")
    if Module is None:
        return (
            False,
            "neon.lms.module model not registered. "
            "Install neon_lms (P7e M1+) first.",
        )
    n_mod = Module.sudo().search_count([])
    if n_mod < 17:
        return (
            False,
            "Only %d / 17 LMS modules seeded. Re-run M1 + "
            "M9 seed before importing content." % n_mod,
        )
    Track = env.get("neon.lms.track")
    n_trk = Track.sudo().search_count([]) if Track is not None else 0
    if n_trk < 7:
        return (
            False,
            "Only %d / 7 LMS tracks seeded." % n_trk,
        )
    Authority = env.get("neon.lms.operating.authority")
    n_auth = (
        Authority.sudo().search_count([])
        if Authority is not None else 0)
    if n_auth < 6:
        return (
            False,
            "Only %d / 6 LMS operating authorities "
            "seeded." % n_auth,
        )
    return (True, "Pre-flight OK.")


def existing_records_summary(env):
    """Return dict {model: count} for content models we'll
    touch. Used for before/after report."""
    return {
        "slide.slide": env["slide.slide"].sudo().search_count([]),
        "neon.lms.quiz.question": (
            env["neon.lms.quiz.question"].sudo().search_count([])),
        "neon.lms.practical.scenario": (
            env["neon.lms.practical.scenario"]
            .sudo().search_count([])),
        "neon.lms.sop": env["neon.lms.sop"].sudo().search_count([]),
    }


def quiz_question_exists(env, module_code, question_text):
    """Idempotency: match by (module.code, question text prefix)."""
    snippet = (question_text or "")[:80].strip()
    if not snippet:
        return False
    QQ = env["neon.lms.quiz.question"]
    found = QQ.sudo().search([
        ("module_id.code", "=", module_code),
    ], limit=200)
    return any(
        (q.question_text or "").startswith(snippet)
        for q in found)


def scenario_exists(env, module_code, title):
    PS = env["neon.lms.practical.scenario"]
    return bool(PS.sudo().search([
        ("module_id.code", "=", module_code),
        ("title", "=", title),
    ], limit=1))


def sop_exists(env, name):
    return bool(env["neon.lms.sop"].sudo().search(
        [("name", "=", name)], limit=1))


def parse_docx(docx_path):
    """Open docx + return list of (index, sanitised_text) tuples.

    python-docx is imported lazily so the module loads without
    the dep (smoke tests don't need it). If python-docx is
    missing at runtime, logs an error + returns [].
    """
    try:
        from docx import Document
    except ImportError:
        _logger.error(
            "python-docx not installed. Run: "
            "pip install python-docx -- then re-run the script.")
        return []
    doc = Document(docx_path)
    out = []
    for idx, para in enumerate(doc.paragraphs):
        text = (para.text or "").strip()
        if not text:
            continue
        text = sanitize_mojibake(text)
        text = strip_citations(text)
        if text:
            out.append((idx, text))
    return out


def import_module_slides(env, paragraphs):
    """One slide.slide per module under the matching channel.

    Strategy: collect each module's body paragraphs and create
    a single 'document'-type slide with the joined description.
    Rich per-lesson slide splitting is M14 polish.
    """
    Module = env["neon.lms.module"]
    Slide = env["slide.slide"]
    counts = {"created": 0, "skipped": 0, "errors": 0}
    current_code = None
    buffer = []

    def flush(code, body):
        if not code or not body:
            return
        module = Module.sudo().search(
            [("code", "=", code)], limit=1)
        if not module:
            counts["errors"] += 1
            return
        channel = getattr(module, "channel_id", None)
        if not channel:
            counts["skipped"] += 1
            return
        title = "%s content" % code
        existing = Slide.sudo().search([
            ("channel_id", "=", channel.id),
            ("name", "=", title),
        ], limit=1)
        if existing:
            counts["skipped"] += 1
            return
        try:
            with env.cr.savepoint():
                Slide.sudo().create({
                    "name": title,
                    "channel_id": channel.id,
                    "description": "\n\n".join(body)[:8000],
                    "slide_category": "document",
                })
                counts["created"] += 1
        except Exception as e:
            _logger.error(
                "Slide create failed for %s: %s", code, e)
            counts["errors"] += 1

    for _, text in paragraphs:
        code = detect_module_code(text)
        if code:
            flush(current_code, buffer)
            current_code = code
            buffer = []
            continue
        if current_code:
            buffer.append(text)
    flush(current_code, buffer)
    return counts


def import_quiz_questions(env, paragraphs):
    QQ = env["neon.lms.quiz.question"]
    Module = env["neon.lms.module"]
    counts = {"created": 0, "skipped": 0, "errors": 0}
    current_code = None
    for _, text in paragraphs:
        code = detect_module_code(text)
        if code:
            current_code = code
            continue
        if not current_code:
            continue
        if not QUIZ_LINE_PATTERN.match(text):
            continue
        if quiz_question_exists(env, current_code, text):
            counts["skipped"] += 1
            continue
        module = Module.sudo().search(
            [("code", "=", current_code)], limit=1)
        if not module:
            counts["errors"] += 1
            continue
        try:
            with env.cr.savepoint():
                # DECISION: bulk-imported questions land as
                # short_answer with placeholder correct_answer.
                # The PHP docx contains question text only --
                # options aren't structurally separable without
                # per-question regex tuning. Fake multiple-
                # choice options would be misleading; short_
                # answer + placeholder is honest about the
                # unfinished state. Admin classifies + sets
                # real correct answer post-import.
                vals = {
                    "module_id": module.id,
                    "question_text": text[:4000],
                    "question_type": "short_answer",
                    "correct_answer": "(pending admin review)",
                }
                QQ.sudo().create(vals)
                counts["created"] += 1
        except Exception as e:
            _logger.error(
                "Quiz create failed for %s: %s",
                current_code, e)
            counts["errors"] += 1
    return counts


def import_practical_scenarios(env, paragraphs):
    PS = env["neon.lms.practical.scenario"]
    Module = env["neon.lms.module"]
    counts = {"created": 0, "skipped": 0, "errors": 0}
    current_code = None
    for _, text in paragraphs:
        code = detect_module_code(text)
        if code:
            current_code = code
            continue
        if not current_code:
            continue
        if not SCENARIO_LINE_PATTERN.match(text):
            continue
        title = text[:200]
        if scenario_exists(env, current_code, title):
            counts["skipped"] += 1
            continue
        module = Module.sudo().search(
            [("code", "=", current_code)], limit=1)
        if not module:
            counts["errors"] += 1
            continue
        try:
            with env.cr.savepoint():
                # Required: module_id, title, description,
                # signoff_authority. Default authority to
                # 'lead_tech' for imported scenarios; admin
                # re-assigns post-import where stricter
                # signoff is needed (Robin/Munashe).
                vals = {
                    "module_id": module.id,
                    "title": title,
                    "description": text[:4000],
                    "signoff_authority": "lead_tech",
                }
                PS.sudo().create(vals)
                counts["created"] += 1
        except Exception as e:
            _logger.error(
                "Scenario create failed for %s: %s",
                current_code, e)
            counts["errors"] += 1
    return counts


def import_sops(env, paragraphs):
    SOP = env["neon.lms.sop"]
    counts = {"created": 0, "skipped": 0, "errors": 0}
    seen = set()
    # SOP section is at top of doc (audit paragraph indices
    # 7-32). Bound the search to the first ~300 paragraphs as
    # a guard against false positives later in the doc.
    for idx, text in paragraphs:
        if idx > 300:
            break
        for kw in SOP_KEYWORDS:
            if kw in seen:
                continue
            if kw.lower() in text.lower():
                if sop_exists(env, kw):
                    counts["skipped"] += 1
                    seen.add(kw)
                    break
                try:
                    with env.cr.savepoint():
                        # SOP uses `summary` (text) not
                        # `description`.
                        vals = {
                            "name": kw,
                            "summary": text[:4000],
                        }
                        SOP.sudo().create(vals)
                        counts["created"] += 1
                        seen.add(kw)
                except Exception as e:
                    _logger.error(
                        "SOP create failed for %s: %s", kw, e)
                    counts["errors"] += 1
                break
    return counts


def main(env, docx_path=None):
    """Entry point. Called automatically when this file is
    sourced via odoo shell. Pass docx_path explicitly to
    override the default."""
    if docx_path is None:
        docx_path = DEFAULT_DOCX_PATH
    print("=" * 72)
    print("Neon LMS PHP content migration")
    print("=" * 72)
    ok, msg = preflight_check(docx_path, env)
    print("Pre-flight: %s" % msg)
    if not ok:
        print("ABORTING. Resolve and re-run.")
        return False
    print()
    print("Before: %s" % existing_records_summary(env))
    print()
    paragraphs = parse_docx(docx_path)
    print("Parsed %d non-empty paragraphs from docx." % len(paragraphs))
    if not paragraphs:
        print(
            "No content extracted. Check docx integrity + "
            "python-docx install.")
        return False
    print()
    print("Importing module slides...")
    slide_counts = import_module_slides(env, paragraphs)
    print("  %s" % slide_counts)
    print()
    print("Importing quiz questions...")
    qq_counts = import_quiz_questions(env, paragraphs)
    print("  %s" % qq_counts)
    print()
    print("Importing practical scenarios...")
    sc_counts = import_practical_scenarios(env, paragraphs)
    print("  %s" % sc_counts)
    print()
    print("Importing SOPs...")
    sop_counts = import_sops(env, paragraphs)
    print("  %s" % sop_counts)
    env.cr.commit()
    print()
    print("=" * 72)
    print("MIGRATION COMPLETE")
    print("After: %s" % existing_records_summary(env))
    print("=" * 72)
    return True


# Auto-run when sourced via odoo shell. `env` is injected by
# the shell into the script's exec namespace. importlib-based
# smoke loads (which don't set `env`) skip this block.
if "env" in dir():
    try:
        main(env)  # noqa: F821 -- env from shell
    except Exception as e:  # noqa: BLE001
        _logger.exception("Migration failed: %s", e)
        try:
            env.cr.rollback()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        print("FAILED: %s" % e)
