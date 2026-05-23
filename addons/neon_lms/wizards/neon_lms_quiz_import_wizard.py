# -*- coding: utf-8 -*-
"""Bulk Quiz Import wizard -- LMS admin polish M1.

CSV paste OR file upload -> dry-run preview -> atomic per-row
import with rollback on validation error.
"""
import base64
import csv
import io
from collections import OrderedDict

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_HEADER = [
    "question_text", "type",
    "option_1_text", "option_1_correct",
    "option_2_text", "option_2_correct",
    "option_3_text", "option_3_correct",
    "option_4_text", "option_4_correct",
    "points", "explanation", "correct_answer",
]

_TYPE_ALIASES = {
    "mc": "multiple_choice",
    "multiple_choice": "multiple_choice",
    "tf": "true_false",
    "true_false": "true_false",
    "sa": "short_answer",
    "short_answer": "short_answer",
}


def _truthy(val):
    if val is None:
        return False
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "t")


class NeonLMSQuizImportWizard(models.TransientModel):
    _name = "neon.lms.quiz.import.wizard"
    _description = "Neon LMS - Bulk Quiz Import Wizard"

    module_id = fields.Many2one(
        "neon.lms.module",
        string="Module",
        required=True,
        help="Target module. All imported questions land "
             "here.",
    )
    csv_data = fields.Text(
        string="CSV Data",
        help="Paste CSV directly. Header row required: "
             + ", ".join(_HEADER),
    )
    csv_file = fields.Binary(
        string="CSV File",
        help="Upload a CSV file as an alternative to pasting.",
    )
    csv_file_name = fields.Char(string="CSV File Name")
    default_question_type = fields.Selection(
        [("multiple_choice", "Multiple Choice"),
         ("true_false", "True/False"),
         ("short_answer", "Short Answer")],
        string="Default Type",
        default="multiple_choice",
        required=True,
        help="Applied when a row leaves the 'type' column "
             "blank.",
    )
    default_points = fields.Integer(
        string="Default Points",
        default=1,
        help="Applied when a row leaves the 'points' column "
             "blank or invalid.",
    )
    mode = fields.Selection(
        [("dry_run", "Dry Run (preview only)"),
         ("import", "Import")],
        string="Mode",
        default="dry_run",
        required=True,
    )
    preview_html = fields.Html(
        string="Preview",
        readonly=True,
        sanitize=False,
    )
    has_preview = fields.Boolean(
        string="Preview Run",
        default=False,
        help="True once Preview button has populated "
             "preview_html. Import button is disabled until "
             "this is set.",
    )
    wizard_state = fields.Text(
        string="Result Summary",
        readonly=True,
        help="Populated after action_import with the "
             "per-row outcome counts.",
    )

    # ------------------------------------------------------------------
    # File upload -> csv_data sync
    # ------------------------------------------------------------------
    @api.onchange("csv_file", "csv_file_name")
    def _onchange_csv_file(self):
        """If the admin uploads a CSV file, decode and copy
        into csv_data so the preview parser only needs one
        source of truth.
        """
        for rec in self:
            if rec.csv_file:
                try:
                    raw = base64.b64decode(rec.csv_file)
                    rec.csv_data = raw.decode(
                        "utf-8-sig", errors="replace")
                except Exception:  # noqa: BLE001
                    rec.csv_data = ""

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_rows(self):
        """Parse self.csv_data into a list of dicts. One pass,
        no DB writes. Each row dict gets:
          - row_num (int, 1-indexed starting at the first
            data row, header is row 0)
          - raw (the source dict)
          - status: 'ok' / 'skipped' / 'error'
          - reason (str, populated for skipped/error)
          - parsed (dict suitable for question create()
            when status=='ok')
          - options (list of {'option_text', 'is_correct'}
            dicts when relevant)
        """
        self.ensure_one()
        if not self.csv_data or not self.csv_data.strip():
            raise UserError(_(
                "Provide CSV data either via paste or file "
                "upload before preview / import."))
        rows = []
        try:
            reader = csv.DictReader(
                io.StringIO(self.csv_data))
        except Exception as e:  # noqa: BLE001
            raise UserError(_(
                "CSV parse error: %s") % e) from e
        # Header sanity check -- DictReader.fieldnames is set
        # after first read.
        if reader.fieldnames is None:
            raise UserError(_(
                "CSV header row missing."))
        missing = [h for h in ("question_text", "type")
                   if h not in reader.fieldnames]
        if missing:
            raise UserError(_(
                "CSV header is missing required column(s): "
                "%s") % ", ".join(missing))

        for idx, raw in enumerate(reader, start=1):
            entry = {
                "row_num": idx,
                "raw": dict(raw),
                "status": "ok",
                "reason": "",
                "parsed": {},
                "options": [],
            }
            text = (raw.get("question_text") or "").strip()
            if not text:
                entry["status"] = "skipped"
                entry["reason"] = "missing question_text"
                rows.append(entry)
                continue

            type_raw = (raw.get("type") or "").strip().lower()
            q_type = _TYPE_ALIASES.get(
                type_raw, self.default_question_type)
            if q_type not in _TYPE_ALIASES.values():
                entry["status"] = "error"
                entry["reason"] = (
                    "unknown type '%s'" % type_raw)
                rows.append(entry)
                continue

            try:
                points = int(
                    (raw.get("points") or "").strip()
                    or self.default_points)
            except ValueError:
                points = self.default_points

            parsed = {
                "module_id": self.module_id.id,
                "question_text": text,
                "question_type": q_type,
                "points": points,
                "explanation": (raw.get("explanation")
                                or "").strip() or False,
            }

            options = []
            if q_type == "multiple_choice":
                for i in range(1, 5):
                    opt_text = (raw.get(
                        "option_%d_text" % i) or "").strip()
                    if not opt_text:
                        continue
                    options.append({
                        "option_text": opt_text,
                        "is_correct": _truthy(raw.get(
                            "option_%d_correct" % i)),
                    })
                if not options:
                    entry["status"] = "error"
                    entry["reason"] = (
                        "multiple_choice with no options")
                elif not any(o["is_correct"] for o in options):
                    entry["status"] = "error"
                    entry["reason"] = (
                        "multiple_choice with no correct "
                        "option flagged")
            elif q_type == "true_false":
                # Always synthesize True/False options. The
                # CSV's option_1_correct flag dictates which
                # is correct; if neither flagged, default to
                # True correct.
                t_correct = _truthy(
                    raw.get("option_1_correct"))
                f_correct = _truthy(
                    raw.get("option_2_correct"))
                if not (t_correct or f_correct):
                    t_correct = True
                options = [
                    {"option_text": "True",
                     "is_correct": bool(t_correct)},
                    {"option_text": "False",
                     "is_correct": bool(f_correct)
                                   and not t_correct},
                ]
            elif q_type == "short_answer":
                correct = (raw.get("correct_answer")
                           or "").strip()
                if not correct:
                    entry["status"] = "error"
                    entry["reason"] = (
                        "short_answer with empty "
                        "correct_answer")
                else:
                    parsed["correct_answer"] = correct

            entry["parsed"] = parsed
            entry["options"] = options
            rows.append(entry)
        return rows

    # ------------------------------------------------------------------
    # Preview action
    # ------------------------------------------------------------------
    def _render_preview(self, rows):
        """Build the preview_html table from parsed rows."""
        ok_n = sum(1 for r in rows if r["status"] == "ok")
        skip_n = sum(1 for r in rows
                     if r["status"] == "skipped")
        err_n = sum(1 for r in rows
                    if r["status"] == "error")
        lines = [
            "<div>",
            "<p><b>%d rows parsed</b> -- %d ok, %d skipped, "
            "%d error</p>" % (
                len(rows), ok_n, skip_n, err_n),
            "<table class='table table-sm'>",
            "<thead><tr>"
            "<th>Row</th><th>Status</th><th>Type</th>"
            "<th>Question</th><th>Options/Notes</th></tr>"
            "</thead>",
            "<tbody>",
        ]
        for r in rows:
            qtext = (r["parsed"].get("question_text")
                     or r["raw"].get("question_text")
                     or "")[:80]
            qtype = (r["parsed"].get("question_type")
                     or "(unset)")
            if r["status"] == "ok":
                if r["options"]:
                    notes = " | ".join(
                        "%s%s" % (
                            o["option_text"],
                            " *" if o["is_correct"] else "")
                        for o in r["options"])
                else:
                    notes = ("correct: %s" % r["parsed"].get(
                        "correct_answer", "(n/a)")
                             if qtype == "short_answer"
                             else "(no options)")
            else:
                notes = r["reason"]
            cls = {"ok": "table-success",
                   "skipped": "table-warning",
                   "error": "table-danger"}.get(
                       r["status"], "")
            lines.append(
                "<tr class='%s'>"
                "<td>%d</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td></tr>" % (
                    cls, r["row_num"], r["status"],
                    qtype, qtext, notes))
        lines.append("</tbody></table></div>")
        return "".join(lines)

    def action_parse_preview(self):
        self.ensure_one()
        rows = self._parse_rows()
        self.preview_html = self._render_preview(rows)
        self.has_preview = True
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Import action
    # ------------------------------------------------------------------
    def action_import(self):
        self.ensure_one()
        if self.mode != "import":
            raise UserError(_(
                "Switch Mode to 'Import' before pressing the "
                "Import button. Dry Run only previews."))
        if not self.has_preview:
            # Force at least one preview pass so the admin
            # sees the parsed table before commit.
            raise UserError(_(
                "Run Preview at least once before Import."))

        Question = self.env["neon.lms.quiz.question"]
        rows = self._parse_rows()
        created = 0
        per_row_errors = []
        for r in rows:
            if r["status"] != "ok":
                continue
            try:
                with self.env.cr.savepoint():
                    # Combine option_ids into the create()
                    # vals so the @api.constrains-driven
                    # completeness check sees both question
                    # + options in a single transaction
                    # (per reference_odoo17_batch_create_
                    # constraint_timing.md).
                    vals = dict(r["parsed"])
                    if r["options"]:
                        vals["option_ids"] = [
                            (0, 0, o) for o in r["options"]]
                    Question.create(vals)
                created += 1
            except (ValidationError, UserError) as e:
                per_row_errors.append(
                    (r["row_num"], str(e)))

        summary_lines = [
            "Created: %d question(s)" % created,
            "Per-row errors: %d" % len(per_row_errors),
        ]
        for row_num, msg in per_row_errors:
            summary_lines.append(
                "  row %d: %s" % (row_num, msg.splitlines()[0]
                                  if msg else "(no detail)"))
        self.wizard_state = "\n".join(summary_lines)

        # Re-render preview with the import outcome appended.
        suffix = (
            "<p><b>Import complete.</b> %d created, "
            "%d row error(s).</p>" % (
                created, len(per_row_errors)))
        self.preview_html = (
            (self.preview_html or "") + suffix)

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
