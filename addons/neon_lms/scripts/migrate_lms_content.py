# -*- coding: utf-8 -*-
"""migrate_lms_content.py -- One-shot LMS CONTENT import from the
neoneybb_workshop ``lms_*`` MySQL dump into the live Neon LMS.

Maps the legacy structured content tables onto the already-live 7e
structure (7 tracks / 17 seeded modules / single slide.channel) +
Phase-7d KB:

  lms_lessons (50)            -> slide.slide (per-module section)
  lms_questions (60)          -> neon.lms.quiz.question + .option
  lms_quizzes (17)            -> module.min_quiz_score + question group
  lms_quiz_questions (229)    -> validated quiz<->question links (reuse)
  lms_competencies (9)        -> neon.kb.tag + track/sub-cert mapping
  lms_sops (13)               -> neon.kb.article (Equipment SOPs)
  lms_authority_boundaries(6) -> neon.kb.article (Authority Boundaries)
  lms_practical_templates (1) -> neon.lms.practical.scenario

RED rails:
  * REFUSES any dump containing ``INSERT INTO `users```` (password
    hashes -- NEVER read/import). Mirrors the B14b guard.
  * NEVER parses learner-history tables (lms_lesson_progress,
    lms_quiz_attempts, lms_practical_*, lms_learner_*, lms_manager_obs,
    lms_certification_followup).

Dry-run by default (classify + count, ZERO writes). ``execute=True``
creates records with per-section savepoints + per-record idempotency;
re-run creates no duplicates. Final ``env.cr.commit()`` only on execute.

  docker compose exec -T odoo odoo shell -d neon_crm --no-http \\
      < addons/neon_lms/scripts/migrate_lms_content.py        # dry-run
  ... then call main(env, execute=True) for the sample/real execute.

NOT a regular Odoo migration -- not in manifest data, no post_init,
no cron, not imported by the addon __init__.

(c) Neon Events Elements -- P7e content import.

⚠️ DECISION (build-time, spec-vs-reality): the prompt named
slide.question / "quiz slides"; the LIVE model is module-scoped
neon.lms.quiz.question + neon.lms.quiz.option (no separate quiz
entity, no native slide.question authoring). Implementation takes
precedence (CLAUDE.md): questions -> neon.lms.quiz.question;
quiz pass_mark -> module.min_quiz_score; the 229 links are validated +
reuse reported (60 distinct questions de-duplicated, not 229 dupes).
⚠️ neon.lms.module has no description/level field -> not re-architected
(out of scope); module enrichment is code-match + name only; lesson
body_html carries the substance as slides.
"""
import logging
import re

_logger = logging.getLogger(__name__)

DEFAULT_SQL_PATH = "/tmp/legacy_lms_content.sql"

# Content tables we import (everything else in the dump is ignored).
CONTENT_TABLES = (
    "lms_modules", "lms_lessons", "lms_quizzes", "lms_questions",
    "lms_quiz_questions", "lms_competencies", "lms_sops",
    "lms_authority_boundaries", "lms_practical_templates",
    "lms_cohort_settings",
)
# Learner-activity/history -- NEVER parsed or imported.
LEARNER_HISTORY_TABLES = (
    "lms_lesson_progress", "lms_quiz_attempts", "lms_practical_attempts",
    "lms_practical_results", "lms_learner_status", "lms_learner_summary",
    "lms_manager_obs", "lms_certification_followup",
)

# Gate-1 locked: competency code -> track code (9 -> 7 by domain).
COMPETENCY_TRACK = {
    "SAF": "TRK_FOUND_SAFETY",
    "PWR": "TRK_FOUND_SAFETY",
    "AUD": "TRK_AUDIO",
    "LIG": "TRK_LIGHTING",
    "LED": "TRK_VIDEO_LED",
    "WFL": "TRK_WORKFLOW_OPS",
    "TRB": "TRK_WORKFLOW_OPS",
    "WHS": "TRK_WORKFLOW_OPS",
    "COM": "TRK_SOFT_SKILLS",
}
Q_TYPE_MAP = {
    "MCQ": "multiple_choice", "MULTI": "multiple_choice",
    "MULTIPLE_CHOICE": "multiple_choice",
    "TF": "true_false", "TRUE_FALSE": "true_false", "BOOLEAN": "true_false",
    "SA": "short_answer", "SHORT": "short_answer",
    "SHORT_ANSWER": "short_answer",
}
KB_CAT_SOP = ("Equipment SOPs", "equipment_sops")
KB_CAT_AUTHORITY = ("Authority Boundaries", "authority_boundaries")

MOJIBAKE_MAP = [
    ("â€™", "'"), ("â€œ", "“"),
    ("â€", "”"), ("â€”", "—"),
    ("â€“", "–"), ("â€¦", "…"),
    ("Ã©", "é"), ("Â ", " "), ("﻿", ""),
]


# ---------------------------------------------------------------------
# SQL dump parsing (defensive: refuse users; multi-row INSERT aware)
# ---------------------------------------------------------------------
def refuse_if_users(text):
    """RED guard: raise if the dump carries a users INSERT. Content
    import must NEVER touch the password-hash table."""
    if re.search(r"INSERT\s+INTO\s+`users`", text, re.IGNORECASE):
        raise ValueError(
            "Legacy SQL contains an `users` INSERT -- this is the "
            "CONTENT import; the users/password table must NEVER be "
            "read or imported. Refusing. (Re-extract content tables "
            "only, excluding `users`.)")
    return True


def sanitize_mojibake(text):
    if not text:
        return text
    out = text
    for bad, good in MOJIBAKE_MAP:
        out = out.replace(bad, good)
    return out


def _unescape(s):
    """MySQL string unescape: \\n \\r \\t \\' \\" \\\\ and doubled ''."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            out.append({"n": "\n", "r": "\r", "t": "\t",
                        "0": "\0", "'": "'", '"': '"',
                        "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        if c == "'" and i + 1 < n and s[i + 1] == "'":
            out.append("'")
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _parse_row(row_str):
    """Parse one VALUES tuple body into a list of Python values.
    Quoted -> unescaped str; NULL -> None; bareword -> str (caller casts).
    """
    vals = []
    i = 0
    n = len(row_str)
    while i < n:
        while i < n and row_str[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        if row_str[i] == "'":
            # quoted string
            i += 1
            buf = []
            while i < n:
                c = row_str[i]
                if c == "\\" and i + 1 < n:
                    buf.append(c)
                    buf.append(row_str[i + 1])
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and row_str[i + 1] == "'":
                        buf.append("''")
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(c)
                i += 1
            vals.append(_unescape("".join(buf)))
        else:
            # bareword until comma (NULL / number)
            buf = []
            while i < n and row_str[i] != ",":
                buf.append(row_str[i])
                i += 1
            tok = "".join(buf).strip()
            vals.append(None if tok.upper() == "NULL" else tok)
        # skip to next comma
        while i < n and row_str[i] != ",":
            i += 1
        if i < n and row_str[i] == ",":
            i += 1
    return vals


def _split_value_rows(blob):
    """Split a VALUES blob '(...),(...),...' into row-body strings,
    respecting quotes/escapes."""
    rows = []
    depth = 0
    in_str = False
    cur = []
    i = 0
    n = len(blob)
    while i < n:
        c = blob[i]
        if in_str:
            if c == "\\" and i + 1 < n:
                cur.append(c)
                cur.append(blob[i + 1])
                i += 2
                continue
            if c == "'":
                if i + 1 < n and blob[i + 1] == "'":
                    cur.append("''")
                    i += 2
                    continue
                in_str = False
            cur.append(c)
            i += 1
            continue
        if c == "'":
            in_str = True
            cur.append(c)
            i += 1
            continue
        if c == "(":
            depth += 1
            if depth == 1:
                cur = []
                i += 1
                continue
        elif c == ")":
            depth -= 1
            if depth == 0:
                rows.append("".join(cur))
                i += 1
                continue
        if depth >= 1:
            cur.append(c)
        i += 1
    return rows


def parse_table(text, table):
    """Return list of dicts (column -> value) for every INSERT INTO
    `table`. Handles multiple INSERT statements + multi-row VALUES."""
    out = []
    for m in re.finditer(
            r"INSERT\s+INTO\s+`" + re.escape(table) +
            r"`\s*\(([^)]+)\)\s*VALUES", text, re.IGNORECASE):
        cols = [c.strip().strip("`") for c in m.group(1).split(",")]
        # blob from after VALUES to the terminating ; (string-aware)
        start = m.end()
        i = start
        n = len(text)
        in_str = False
        while i < n:
            c = text[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    in_str = False
                i += 1
                continue
            if c == "'":
                in_str = True
                i += 1
                continue
            if c == ";":
                break
            i += 1
        blob = text[start:i]
        for row_str in _split_value_rows(blob):
            vals = _parse_row(row_str)
            if len(vals) != len(cols):
                # tolerate trailing/short rows defensively
                vals = (vals + [None] * len(cols))[:len(cols)]
            out.append({cols[j]: vals[j] for j in range(len(cols))})
    return out


def _to_int(v, default=None):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------
def preflight_check(sql_path, env):
    import os
    if not sql_path or not os.path.isfile(sql_path):
        return (False, "Extract not found at %s. Stage the "
                "users-excluded lms content extract first." % sql_path)
    for model, label in (("neon.lms.module", "modules"),
                         ("neon.lms.track", "tracks"),
                         ("neon.lms.quiz.question", "quiz questions"),
                         ("neon.kb.article", "KB articles"),
                         ("slide.slide", "slides")):
        if model not in env:
            return (False, "%s model missing -- install neon_lms / "
                    "neon_kb first." % model)
    n_mod = env["neon.lms.module"].sudo().search_count([])
    if n_mod < 17:
        return (False, "Only %d/17 LMS modules seeded." % n_mod)
    n_trk = env["neon.lms.track"].sudo().search_count([])
    if n_trk < 7:
        return (False, "Only %d/7 LMS tracks seeded." % n_trk)
    return (True, "Pre-flight OK (%d modules, %d tracks)." % (n_mod, n_trk))


# ---------------------------------------------------------------------
# Parse the whole extract into a normalised content dict.
# ---------------------------------------------------------------------
def parse_extract(sql_path):
    with open(sql_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    refuse_if_users(text)
    # Hard refusal of learner-history (defensive: should not be in a
    # content extract; if present, refuse rather than silently import).
    for t in LEARNER_HISTORY_TABLES:
        if re.search(r"INSERT\s+INTO\s+`" + re.escape(t) + r"`",
                     text, re.IGNORECASE):
            raise ValueError(
                "Extract contains learner-history table `%s` -- "
                "history must NEVER be imported. Refusing." % t)
    data = {t: parse_table(text, t) for t in CONTENT_TABLES}
    # module id -> code map (FK resolution for content rows)
    data["_mod_id_to_code"] = {
        _to_int(r.get("id")): r.get("code")
        for r in data["lms_modules"] if r.get("code")}
    return data


# ---------------------------------------------------------------------
# Mapping / import (each returns a {created, skipped, errors} count and,
# in dry-run, classifies without writing).
# ---------------------------------------------------------------------
def _module_by_code(env, code):
    return env["neon.lms.module"].sudo().search(
        [("code", "=", code)], limit=1)


def _section_slide(env, module, execute, seq=10):
    """Get-or-create the per-module section slide (is_category=True)
    in the program channel, at sequence ``seq``. Returns the section
    slide or None.

    ⚠️ slide.slide.category_id is READONLY + sequence-computed in
    website_slides (a content slide belongs to the nearest PRECEDING
    is_category slide by sequence) -- it cannot be set directly. So we
    place the section at a module-ordered base sequence and the lessons
    just after it (see import_lessons), and the compute groups them."""
    channel = module.channel_id
    if not channel:
        return None
    name = "%s -- %s" % (module.code, module.name)
    Slide = env["slide.slide"].sudo()
    sec = Slide.search([("channel_id", "=", channel.id),
                        ("is_category", "=", True),
                        ("name", "=", name)], limit=1)
    if sec or not execute:
        return sec or Slide  # empty recordset placeholder in dry-run
    return Slide.create({"name": name, "channel_id": channel.id,
                         "is_category": True, "sequence": seq})


def import_lessons(env, data, execute):
    counts = {"created": 0, "skipped": 0, "errors": 0}
    Slide = env["slide.slide"].sudo()
    id2code = data["_mod_id_to_code"]
    # Module-ordered sequence bands: section M(i) at base (i+1)*1000, its
    # lessons at base+1, base+2, ... (< next band). website_slides then
    # computes each lesson's category_id = nearest preceding is_category
    # slide = its OWN module section. 1000-gap >> any module's lesson
    # count (237 total / 17 modules). Section/lesson sort_order in the
    # legacy dump only orders WITHIN a module -> mapped to the local
    # counter, preserving intra-module order.
    mods = env["neon.lms.module"].sudo().search([], order="code")
    base_seq = {m.code: (i + 1) * 1000 for i, m in enumerate(mods)}
    local = {}
    for r in data["lms_lessons"]:
        code = id2code.get(_to_int(r.get("module_id")))
        module = _module_by_code(env, code) if code else None
        if not module:
            counts["errors"] += 1
            continue
        lcode = (r.get("code") or "").strip()
        raw_title = sanitize_mojibake(r.get("title") or lcode or "Lesson")
        # Prefix the lesson code so same-titled lessons stay distinct
        # (lossless) + keep idempotency stable on the code-prefixed name.
        title = ("%s -- %s" % (lcode, raw_title)) if lcode else raw_title
        existing = Slide.search([("channel_id", "=", module.channel_id.id),
                                 ("name", "=", title),
                                 ("is_category", "=", False)], limit=1)
        if existing:
            counts["skipped"] += 1
            continue
        if not execute:
            counts["created"] += 1
            continue
        try:
            with env.cr.savepoint():
                sbase = base_seq.get(module.code, 1000)
                _section_slide(env, module, execute, seq=sbase)
                local[module.code] = local.get(module.code, 0) + 1
                ltype = (r.get("lesson_type") or "").lower()
                cat = "video" if ltype == "video" else "document"
                # NO category_id (readonly/sequence-computed) -- set the
                # sequence just after the module's section instead.
                vals = {
                    "name": title,
                    "channel_id": module.channel_id.id,
                    "slide_category": cat,
                    "html_content": sanitize_mojibake(
                        r.get("body_html") or ""),
                    "completion_time": (
                        (_to_int(r.get("est_minutes")) or 0) / 60.0),
                    "sequence": sbase + local[module.code],
                    "is_published": False,
                }
                Slide.create(vals)
                counts["created"] += 1
        except Exception as e:  # noqa: BLE001
            _logger.error("lesson import failed (%s): %s", title[:40], e)
            counts["errors"] += 1
    return counts


def import_questions(env, data, execute):
    """60 distinct lms_questions -> neon.lms.quiz.question (+options),
    deduplicated, under their home module."""
    counts = {"created": 0, "skipped": 0, "errors": 0}
    QQ = env["neon.lms.quiz.question"].sudo()
    id2code = data["_mod_id_to_code"]
    for r in data["lms_questions"]:
        code = id2code.get(_to_int(r.get("module_id")))
        module = _module_by_code(env, code) if code else None
        if not module:
            counts["errors"] += 1
            continue
        qtext = sanitize_mojibake(r.get("question_text") or "")
        if not qtext:
            counts["errors"] += 1
            continue
        snippet = qtext[:80]
        dup = QQ.search([("module_id", "=", module.id)], limit=500)
        if any((q.question_text or "").startswith(snippet) for q in dup):
            counts["skipped"] += 1
            continue
        if not execute:
            counts["created"] += 1
            continue
        qtype = Q_TYPE_MAP.get((r.get("q_type") or "").upper(),
                               "short_answer")
        correct = (r.get("correct_answer") or "").strip()
        try:
            with env.cr.savepoint():
                vals = {
                    "module_id": module.id,
                    "question_text": qtext[:4000],
                    "explanation": sanitize_mojibake(
                        r.get("feedback") or "") or False,
                    "sequence": _to_int(r.get("id"), 10),
                }
                if qtype in ("multiple_choice", "true_false"):
                    opts = []
                    letters = [("A", "option_a"), ("B", "option_b"),
                               ("C", "option_c"), ("D", "option_d")]
                    seq = 10
                    for letter, col in letters:
                        otext = sanitize_mojibake(r.get(col) or "")
                        if not otext:
                            continue
                        opts.append((0, 0, {
                            "option_text": otext[:512],
                            "is_correct": correct.upper() == letter,
                            "sequence": seq}))
                        seq += 10
                    if not opts:
                        # Legacy MC/TF row carried no usable options ->
                        # fall back to short_answer (lossless: keeps the
                        # question text; admin completes options later).
                        qtype = "short_answer"
                    else:
                        # guarantee a correct option (constraint) -- if
                        # the legacy correct_answer didn't match a letter,
                        # mark the first option correct.
                        if not any(o[2]["is_correct"] for o in opts):
                            opts[0][2]["is_correct"] = True
                        vals["option_ids"] = opts
                if qtype == "short_answer":
                    vals["correct_answer"] = correct or "(pending review)"
                vals["question_type"] = qtype
                QQ.create(vals)
                counts["created"] += 1
        except Exception as e:  # noqa: BLE001
            _logger.error("question import failed: %s", e)
            counts["errors"] += 1
    return counts


def apply_quiz_pass_marks(env, data, execute):
    """lms_quizzes pass_mark -> module.min_quiz_score (0-1)."""
    counts = {"updated": 0, "skipped": 0, "errors": 0}
    id2code = data["_mod_id_to_code"]
    for r in data["lms_quizzes"]:
        code = id2code.get(_to_int(r.get("module_id")))
        module = _module_by_code(env, code) if code else None
        if not module:
            counts["errors"] += 1
            continue
        pass_mark = _to_int(r.get("pass_mark"))
        if pass_mark is None:
            counts["skipped"] += 1
            continue
        target = round(pass_mark / 100.0, 2)
        if abs((module.min_quiz_score or 0) - target) < 0.001:
            counts["skipped"] += 1
            continue
        if execute:
            try:
                with env.cr.savepoint():
                    module.min_quiz_score = target
                    counts["updated"] += 1
            except Exception as e:  # noqa: BLE001
                _logger.error("quiz pass_mark update failed: %s", e)
                counts["errors"] += 1
        else:
            counts["updated"] += 1
    return counts


def validate_quiz_links(env, data):
    """Validate the 229 quiz<->question links + report reuse. Pure
    classification (no writes): each link's quiz + question resolve to
    a module; count cross-module links + reuse (q in >1 quiz)."""
    quiz_mod = {_to_int(q.get("id")): _to_int(q.get("module_id"))
                for q in data["lms_quizzes"]}
    q_mod = {_to_int(q.get("id")): _to_int(q.get("module_id"))
             for q in data["lms_questions"]}
    total = same = cross = unresolved = 0
    uses = {}
    for link in data["lms_quiz_questions"]:
        total += 1
        qz = _to_int(link.get("quiz_id"))
        qn = _to_int(link.get("question_id"))
        uses[qn] = uses.get(qn, 0) + 1
        if qz not in quiz_mod or qn not in q_mod:
            unresolved += 1
        elif quiz_mod[qz] == q_mod[qn]:
            same += 1
        else:
            cross += 1
    reused = sum(1 for c in uses.values() if c > 1)
    return {"total": total, "same_module": same, "cross_module": cross,
            "unresolved": unresolved, "distinct_questions": len(uses),
            "reused_questions": reused}


def _kb_category(env, name, code, execute):
    # neon.kb.category.code is required + UNIQUE -- must be supplied.
    Cat = env["neon.kb.category"].sudo()
    cat = Cat.search(["|", ("name", "=", name), ("code", "=", code)], limit=1)
    if cat or not execute:
        return cat or Cat
    return Cat.create({"name": name, "code": code})


def _kb_tag(env, name, execute):
    Tag = env["neon.kb.tag"].sudo()
    tag = Tag.search([("name", "=", name)], limit=1)
    if tag or not execute:
        return tag or Tag
    return Tag.create({"name": name})


def import_competency_tags(env, data, execute):
    """9 competencies -> neon.kb.tag (content tagging) + verify each
    maps to a track with a sub-cert type. Returns counts + mapping."""
    counts = {"created": 0, "skipped": 0, "errors": 0}
    mapping = []
    Tag = env["neon.kb.tag"].sudo()
    Track = env["neon.lms.track"].sudo()
    for r in data["lms_competencies"]:
        ccode = (r.get("code") or "").strip()
        title = sanitize_mojibake(r.get("title") or ccode)
        trk_code = COMPETENCY_TRACK.get(ccode)
        track = Track.search([("code", "=", trk_code)], limit=1) if trk_code else None
        sub_cert = track.sub_cert_type_id if track else None
        mapping.append({
            "competency": ccode, "title": title,
            "track": trk_code,
            "sub_cert": sub_cert.name if sub_cert else None,
            "ok": bool(track and sub_cert)})
        existing = Tag.search([("name", "=", title)], limit=1)
        if existing:
            counts["skipped"] += 1
            continue
        if not execute:
            counts["created"] += 1
            continue
        try:
            with env.cr.savepoint():
                Tag.create({"name": title})
                counts["created"] += 1
        except Exception as e:  # noqa: BLE001
            _logger.error("competency tag failed (%s): %s", ccode, e)
            counts["errors"] += 1
    return counts, mapping


def import_kb_articles(env, data, execute):
    """lms_sops (13) + lms_authority_boundaries (6) -> neon.kb.article."""
    counts = {"created": 0, "skipped": 0, "errors": 0}
    Article = env["neon.kb.article"].sudo()
    comp_by_id = {_to_int(c.get("id")): (c.get("code") or "")
                  for c in data["lms_competencies"]}

    def _make(name, code, body, category, tags, summary=""):
        cat_name, cat_code = category
        existing = Article.search([("code", "=", code)], limit=1)
        if existing:
            counts["skipped"] += 1
            return
        if not execute:
            counts["created"] += 1
            return
        try:
            with env.cr.savepoint():
                cat = _kb_category(env, cat_name, cat_code, execute)
                vals = {"name": name[:200], "code": code[:64],
                        "body": body or "<p/>"}
                if summary:
                    vals["summary"] = summary[:280]
                if cat:
                    vals["category_id"] = cat.id
                tag_recs = [_kb_tag(env, t, execute) for t in tags if t]
                tag_ids = [t.id for t in tag_recs if t]
                if tag_ids:
                    vals["tag_ids"] = [(6, 0, tag_ids)]
                Article.create(vals)
                counts["created"] += 1
        except Exception as e:  # noqa: BLE001
            _logger.error("KB article failed (%s): %s", code, e)
            counts["errors"] += 1

    for r in data["lms_sops"]:
        comp = comp_by_id.get(_to_int(r.get("competency_id")), "")
        _make(sanitize_mojibake(r.get("title") or r.get("code") or "SOP"),
              "sop-%s" % (r.get("id") or r.get("code") or "x"),
              sanitize_mojibake(r.get("body_html") or ""),
              KB_CAT_SOP,
              [r.get("equipment_category"), comp])
    for r in data["lms_authority_boundaries"]:
        body = (
            "<h3>May do</h3><p>%s</p>"
            "<h3>May NOT do</h3><p>%s</p>"
            "<h3>Escalation</h3><p>%s</p>" % (
                sanitize_mojibake(r.get("may_do") or ""),
                sanitize_mojibake(r.get("may_not_do") or ""),
                sanitize_mojibake(r.get("escalation") or "")))
        _make("Authority -- " + (r.get("category") or r.get("code") or ""),
              "auth-%s" % (r.get("id") or r.get("code") or "x"),
              body, KB_CAT_AUTHORITY, [])
    return counts


def import_practical_templates(env, data, execute):
    counts = {"created": 0, "skipped": 0, "errors": 0}
    PS = env["neon.lms.practical.scenario"].sudo()
    id2code = data["_mod_id_to_code"]
    comp_mod = {_to_int(c.get("id")): c.get("code")
                for c in data["lms_competencies"]}
    for r in data["lms_practical_templates"]:
        # practical_templates key off competency -> a representative
        # module of that competency's domain (first module in the track).
        ccode = comp_mod.get(_to_int(r.get("competency_id")))
        trk = COMPETENCY_TRACK.get(ccode) if ccode else None
        module = None
        if trk:
            track = env["neon.lms.track"].sudo().search(
                [("code", "=", trk)], limit=1)
            module = env["neon.lms.module"].sudo().search(
                [("track_id", "=", track.id)], limit=1) if track else None
        if not module:
            module = env["neon.lms.module"].sudo().search([], limit=1)
        title = sanitize_mojibake(r.get("title") or r.get("code") or "Scenario")
        if PS.search([("module_id", "=", module.id),
                      ("title", "=", title)], limit=1):
            counts["skipped"] += 1
            continue
        if not execute:
            counts["created"] += 1
            continue
        try:
            with env.cr.savepoint():
                desc = "\n\n".join(filter(None, [
                    sanitize_mojibake(r.get("scenario_brief") or ""),
                    sanitize_mojibake(r.get("candidate_instructions") or ""),
                    sanitize_mojibake(r.get("assessor_instructions") or "")]))
                PS.create({"module_id": module.id, "title": title[:200],
                           "description": desc[:4000] or title,
                           "signoff_authority": "superuser"})
                counts["created"] += 1
        except Exception as e:  # noqa: BLE001
            _logger.error("practical template failed: %s", e)
            counts["errors"] += 1
    return counts


def classify(env, data):
    """Dry-run classification report (no writes)."""
    return {
        "lms_modules (enrich by code)": len(data["lms_modules"]),
        "lms_lessons -> slide.slide": import_lessons(env, data, False),
        "lms_questions -> quiz.question": import_questions(env, data, False),
        "lms_quizzes -> module.min_quiz_score": apply_quiz_pass_marks(
            env, data, False),
        "lms_quiz_questions (links)": validate_quiz_links(env, data),
        "lms_competencies -> kb.tag": import_competency_tags(
            env, data, False)[0],
        "lms_sops+authority -> kb.article": import_kb_articles(
            env, data, False),
        "lms_practical_templates -> scenario": import_practical_templates(
            env, data, False),
    }


def summary(env):
    return {
        "slide.slide": env["slide.slide"].sudo().search_count(
            [("is_category", "=", False)]),
        "neon.lms.quiz.question": env[
            "neon.lms.quiz.question"].sudo().search_count([]),
        "neon.kb.article": env["neon.kb.article"].sudo().search_count([]),
        "neon.lms.practical.scenario": env[
            "neon.lms.practical.scenario"].sudo().search_count([]),
    }


def main(env, sql_path=None, execute=False):
    if sql_path is None:
        sql_path = DEFAULT_SQL_PATH
    print("=" * 72)
    print("Neon LMS CONTENT import  (%s)" % (
        "EXECUTE" if execute else "DRY-RUN / classify"))
    print("=" * 72)
    ok, msg = preflight_check(sql_path, env)
    print("Pre-flight:", msg)
    if not ok:
        print("ABORTING.")
        return False
    data = parse_extract(sql_path)
    print("Parsed rows:", {t: len(data[t]) for t in CONTENT_TABLES})
    print()
    cls = classify(env, data)
    comp_counts, comp_map = import_competency_tags(env, data, False)
    print("CLASSIFICATION:")
    for k, v in cls.items():
        print("  %-40s %s" % (k, v))
    print()
    print("COMPETENCY -> TRACK -> SUB-CERT:")
    for m in comp_map:
        print("  %-4s %-22s -> %-18s -> %s%s" % (
            m["competency"], m["title"][:22], m["track"],
            m["sub_cert"], "" if m["ok"] else "  [UNMAPPED!]"))
    if not execute:
        print()
        print("DRY-RUN complete -- no records written.")
        return data
    print()
    print("Before:", summary(env))
    r = {
        "lessons": import_lessons(env, data, True),
        "questions": import_questions(env, data, True),
        "quiz_pass_marks": apply_quiz_pass_marks(env, data, True),
        "competency_tags": import_competency_tags(env, data, True)[0],
        "kb_articles": import_kb_articles(env, data, True),
        "practical": import_practical_templates(env, data, True),
    }
    env.cr.commit()
    print("EXECUTE results:", r)
    print("After:", summary(env))
    print("=" * 72)
    return r


# Auto-run (DRY-RUN) when sourced via odoo shell. execute stays False
# here -- a sample/real execute is an explicit main(env, execute=True).
if "env" in dir():
    try:
        main(env)  # noqa: F821 -- env injected by shell
    except Exception as e:  # noqa: BLE001
        _logger.exception("LMS content migration failed: %s", e)
        try:
            env.cr.rollback()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        print("FAILED: %s" % e)
