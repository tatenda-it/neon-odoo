# -*- coding: utf-8 -*-
"""CABS bank-statement CSV importer.

Parses the CABS export (USD + ZWG share one layout) and creates a native
account.bank.statement + lines for reconciliation. Robust to both date formats
(DD/MM/YYYY and DD MMM YY), comma-thousands, quotes, blank/charge rows, and
multi-line transactions sharing a Reference.
"""
import base64
import csv
import io
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError

# header signature (lower-cased) used to locate the column row dynamically
_HEADER_SIG = ["post date", "reference", "narrative", "value date",
               "debit", "credit", "closing balance"]
# Currency (from the metadata row) -> CABS bank journal by default-account code
_CCY_TO_ACCOUNT_CODE = {"USD": "101401", "ZWG": "101405"}
_START_LABEL = "balance at period start"
_END_LABEL = "balance at period end"


def _norm(cell):
    return (cell or "").strip().strip('"').strip()


def _parse_amount(cell):
    """'16,100.00' / '2087.25' / '' / '-131.95' -> float (0.0 when blank)."""
    s = _norm(cell).replace(",", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        raise UserError(_("Could not read the amount %r in the statement file.") % cell)


def _parse_date(cell):
    """DD/MM/YYYY (Zimbabwe convention, confirmed) OR DD MMM YY."""
    s = _norm(cell)
    if "/" in s:
        return datetime.strptime(s, "%d/%m/%Y").date()
    return datetime.strptime(s.title(), "%d %b %y").date()


class NeonBankStatementImportWizard(models.TransientModel):
    _name = "neon.bank.statement.import.wizard"
    _description = "Import CABS Bank Statement (CSV)"

    statement_file = fields.Binary(string="Statement file (CSV)", required=True)
    filename = fields.Char(string="File name")

    def _decode_rows(self):
        try:
            raw = base64.b64decode(self.statement_file)
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception as exc:
            raise UserError(_("Could not read the file: %s") % exc)
        return list(csv.reader(io.StringIO(text)))

    def _journal_for(self, currency_code, account_number):
        code = _CCY_TO_ACCOUNT_CODE.get((currency_code or "").upper())
        if not code:
            raise UserError(_(
                "Unrecognised statement currency %r. Expected USD or ZWG.") % currency_code)
        journal = self.env["account.journal"].search(
            [("default_account_id.code", "=", code), ("type", "=", "bank")], limit=1)
        if not journal:
            raise UserError(_(
                "No CABS bank journal found for currency %s (account %s).")
                % (currency_code, code))
        return journal

    def action_import(self):
        self.ensure_one()
        rows = self._decode_rows()

        # 1) metadata + dynamic header location
        meta, header_idx = {}, None
        for i, row in enumerate(rows):
            cells = [_norm(c) for c in row]
            if cells and cells[0] in ("Account Number:", "Account Name:", "Currency"):
                meta[cells[0].rstrip(":")] = cells[1] if len(cells) > 1 else ""
            if [c.lower() for c in cells[:7]] == _HEADER_SIG:
                header_idx = i
                break
        if header_idx is None:
            raise UserError(_(
                "Could not find the statement header row "
                "(Post date, Reference, Narrative, Value Date, Debit, Credit, "
                "Closing Balance). Is this a CABS CSV export?"))

        journal = self._journal_for(meta.get("Currency"), meta.get("Account Number"))

        # 2) walk the data rows
        balance_start = balance_end = None
        lines = []
        for row in rows[header_idx + 1:]:
            cells = [_norm(c) for c in row]
            cells += [""] * (7 - len(cells))  # pad short rows
            post_date, ref, narrative, value_date, debit, credit, closing = cells[:7]
            label = ref.lower()
            if label == _START_LABEL:
                balance_start = _parse_amount(closing)
                continue
            if label == _END_LABEL:
                balance_end = _parse_amount(closing)
                continue
            if not post_date:
                continue  # blank separator row
            amount = _parse_amount(credit) - _parse_amount(debit)  # in=+, out=-
            narration = ("Value date: %s" % value_date) if value_date else False
            lines.append((0, 0, {
                "journal_id": journal.id,
                "date": _parse_date(post_date),
                "payment_ref": narrative or ref,
                "ref": ref,
                "amount": amount,
                "narration": narration,
            }))

        if not lines:
            raise UserError(_("No transaction lines were found in the file."))

        stmt_vals = {
            "name": "%s - %s" % (journal.name, self.filename or fields.Date.context_today(self)),
            "journal_id": journal.id,
            "line_ids": lines,
        }
        if balance_start is not None:
            stmt_vals["balance_start"] = balance_start
        if balance_end is not None:
            stmt_vals["balance_end_real"] = balance_end
        statement = self.env["account.bank.statement"].create(stmt_vals)

        return {
            "type": "ir.actions.act_window",
            "name": _("Imported Statement"),
            "res_model": "account.bank.statement",
            "res_id": statement.id,
            "view_mode": "form",
            "target": "current",
        }
