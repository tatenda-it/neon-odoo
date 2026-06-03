# -*- coding: utf-8 -*-
"""P7f -- internal certificate verification lookup.

A transient wizard: enter a certificate number OR verification token,
resolve the cert, and report its validity (active / REVOKED / expired /
not found). Internal only -- no public route (a public name-exposing
page is a who-sees-what decision, deferred per Gate 1). Searches with
active_test=False so REVOKED (active=False) certs resolve as 'revoked'
rather than 'not found'.
"""
from odoo import _, api, fields, models


class NeonTrainingCertVerifyWizard(models.TransientModel):
    _name = "neon.training.cert.verify.wizard"
    _description = "Certificate Verification Lookup"

    query = fields.Char(
        string="Certificate No. / Verification Token",
        help="Paste the certificate number (e.g. NEON-AUD-2026-0001) "
        "or the verification token from a certificate.")
    result_html = fields.Html(string="Result", readonly=True)
    resolved_cert_id = fields.Many2one(
        "neon.training.certification", readonly=True)

    def _lookup(self, query):
        """Return (cert_or_empty, status) for the query. status in
        valid / revoked / expired / suspended / draft / not_found."""
        q = (query or "").strip()
        Cert = self.env["neon.training.certification"].sudo().with_context(
            active_test=False)
        if not q:
            return Cert, "not_found"
        cert = Cert.search(
            ["|", ("certificate_number", "=", q),
             ("verification_token", "=", q)], limit=1)
        if not cert:
            return Cert, "not_found"
        if not cert.active:
            return cert, "revoked"
        if cert.state == "active":
            return cert, "valid"
        return cert, cert.state  # expired / suspended / draft / pending

    def action_lookup(self):
        self.ensure_one()
        cert, status = self._lookup(self.query)
        if status == "not_found":
            html = (
                "<div style='color:#b00020;font-weight:600'>"
                "&#10007; No certificate matches that number or token."
                "</div>")
            self.resolved_cert_id = False
        else:
            badge = {
                "valid": ("#1a7f37", "&#10003; VALID"),
                "revoked": ("#b00020", "&#10007; REVOKED"),
                "expired": ("#b06b00", "&#9888; EXPIRED"),
                "suspended": ("#b06b00", "&#9888; SUSPENDED"),
            }.get(status, ("#b06b00", "&#9888; " + status.upper()))
            html = (
                "<div style='font-weight:700;color:%s;font-size:16px'>%s</div>"
                "<table style='margin-top:8px'>"
                "<tr><td><b>Holder:</b></td><td>%s</td></tr>"
                "<tr><td><b>Certificate:</b></td><td>%s</td></tr>"
                "<tr><td><b>Number:</b></td><td>%s</td></tr>"
                "<tr><td><b>Issued:</b></td><td>%s</td></tr>"
                "</table>"
            ) % (
                badge[0], badge[1],
                cert.user_id.name or "-",
                cert.type_id.name or "-",
                cert.certificate_number or "-",
                fields.Date.to_string(cert.date_obtained) or "-",
            )
            self.resolved_cert_id = cert.id
        self.result_html = html
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
