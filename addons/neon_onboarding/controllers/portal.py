# -*- coding: utf-8 -*-
"""Portal controllers for /my/onboarding routes.

Phase 7b M8: profile route + portal home card.
Phase 7b M9: self-upload cert wizard.

The M9 upload flow creates a neon.training.certification in
state='draft' first, then calls action_submit_for_verification
to transition to pending_verification (which fires the M7
routing override -- Robin + Munashe become followers).

External-trainer-required cert types (M3 seed: driver, fire
safety, etc.) need external_trainer_name OR signed_off_by_id
set before leaving draft. M9 sets external_trainer_name to
'Self-uploaded; pending verification' as the semantic marker:
the candidate asserts they got the cert externally and
uploads proof; admin verifies authenticity during the
verification step.
"""
import base64
import logging

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


_M9_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_M9_UPLOAD_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
_M9_SELF_UPLOADED_TRAINER_MARKER = (
    "Self-uploaded; pending verification")


class NeonOnboardingPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        """Surface an onboarding counter on /my so portal
        users see a card linking to their profile.
        """
        values = super()._prepare_home_portal_values(counters)
        if "onboarding_count" in counters:
            candidate = request.env[
                "neon.onboarding.candidate"
            ].sudo().search([
                ("user_id", "=", request.env.user.id),
            ], limit=1)
            values["onboarding_count"] = (
                1 if candidate else 0)
        return values

    @http.route(
        ["/my/onboarding"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_onboarding(self, **kw):
        """Render the candidate's profile + required certs +
        collected certs. Returns a no-candidate template
        when the requesting user has no candidate record
        linked.
        """
        user = request.env.user
        candidate = request.env[
            "neon.onboarding.candidate"
        ].sudo().search([
            ("user_id", "=", user.id),
        ], limit=1)

        if not candidate:
            return request.render(
                "neon_onboarding.portal_no_candidate", {})

        values = {
            "candidate": candidate,
            "required_certs": candidate.required_cert_type_ids,
            "collected_certs": candidate.collected_cert_ids,
            "page_name": "onboarding",
            "upload_success": (
                kw.get("upload") == "success"),
        }
        return request.render(
            "neon_onboarding.portal_my_onboarding", values)

    # ============================================================
    # M9 -- self-upload cert wizard
    # ============================================================
    def _m9_get_candidate_or_redirect(self):
        """Locate the candidate for the requesting user.
        Returns (candidate, None) on success, (None, redirect)
        otherwise.
        """
        user = request.env.user
        candidate = request.env[
            "neon.onboarding.candidate"
        ].sudo().search([
            ("user_id", "=", user.id),
        ], limit=1)
        if not candidate:
            return None, request.redirect("/my/onboarding")
        if candidate.state != "cert_collection":
            # Upload only valid during cert collection. Other
            # states either pre-date the upload window
            # (candidate) or post-date it (probationary /
            # active).
            return None, request.redirect("/my/onboarding")
        return candidate, None

    @http.route(
        ["/my/onboarding/upload"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_onboarding_upload_list(self, **kw):
        """List cert types the candidate can upload. Excludes
        types that already have a cert in pending or active
        state (idempotency).
        """
        candidate, redir = self._m9_get_candidate_or_redirect()
        if redir:
            return redir
        existing_blocking = candidate.collected_cert_ids.filtered(
            lambda c: c.state in (
                "pending_verification", "active")
        ).mapped("type_id")
        available_types = (
            candidate.required_cert_type_ids - existing_blocking)
        values = {
            "candidate": candidate,
            "available_types": available_types,
            "page_name": "onboarding_upload",
        }
        return request.render(
            "neon_onboarding.portal_upload_list", values)

    @http.route(
        ["/my/onboarding/upload/<int:cert_type_id>"],
        type="http",
        auth="user",
        website=True,
        methods=["GET", "POST"],
        csrf=True,
    )
    def portal_onboarding_upload_form(self, cert_type_id, **kw):
        """GET: show upload form. POST: process upload + create
        cert + attachment + audit + submit_for_verification
        (which triggers M7 routing override).
        """
        candidate, redir = self._m9_get_candidate_or_redirect()
        if redir:
            return redir

        cert_type = request.env[
            "neon.training.certification.type"
        ].sudo().browse(cert_type_id)
        if (not cert_type.exists()
                or cert_type not in candidate.required_cert_type_ids):
            return request.redirect("/my/onboarding/upload")

        if request.httprequest.method == "POST":
            error = self._m9_process_upload(
                candidate, cert_type, kw)
            if error:
                values = {
                    "candidate": candidate,
                    "cert_type": cert_type,
                    "error": error,
                    "page_name": "onboarding_upload",
                }
                return request.render(
                    "neon_onboarding.portal_upload_form",
                    values)
            return request.redirect(
                "/my/onboarding?upload=success")

        values = {
            "candidate": candidate,
            "cert_type": cert_type,
            "page_name": "onboarding_upload",
        }
        return request.render(
            "neon_onboarding.portal_upload_form", values)

    def _m9_process_upload(self, candidate, cert_type, form):
        """Validate + create cert + attachment + audit.
        Returns error message (str) on validation failure,
        None on success. Extracted as a method so smoke tests
        can call it directly without HTTP layer.
        """
        uploaded_file = request.httprequest.files.get("cert_file")
        date_obtained = form.get("date_obtained")
        date_expires = form.get("date_expires") or False

        if not uploaded_file or not date_obtained:
            return ("File and date obtained are required.")

        # File-size check via seek/tell (FileStorage doesn't
        # expose .size directly).
        uploaded_file.seek(0, 2)
        file_size = uploaded_file.tell()
        uploaded_file.seek(0)
        if file_size > _M9_UPLOAD_MAX_BYTES:
            return ("File too large; max 10 MB.")

        filename_lower = (uploaded_file.filename or "").lower()
        if not any(filename_lower.endswith(ext)
                   for ext in _M9_UPLOAD_EXTENSIONS):
            return ("File must be PDF, JPG, or PNG.")

        return self._m9_create_cert_record(
            candidate, cert_type, uploaded_file,
            date_obtained, date_expires)

    def _m9_create_cert_record(
            self, candidate, cert_type, uploaded_file,
            date_obtained, date_expires):
        """Cert + attachment + audit + submit_for_verification.
        Returns None on success, error message on Phase 7a
        constraint failure (which the form template surfaces
        back to the user).

        Pulled out as a method so smoke can call directly with
        mocked uploaded_file values.
        """
        # External-trainer-required cert types need a marker.
        # Self-upload semantic: candidate asserts external
        # provenance, admin verifies.
        cert_vals = {
            "user_id": candidate.user_id.id,
            "candidate_id": candidate.id,
            "type_id": cert_type.id,
            "date_obtained": date_obtained,
            "date_expires": date_expires or False,
        }
        if cert_type.category_id.requires_external_trainer:
            cert_vals["external_trainer_name"] = (
                _M9_SELF_UPLOADED_TRAINER_MARKER)

        Cert = request.env["neon.training.certification"]
        try:
            cert = Cert.sudo().create(cert_vals)
        except Exception as e:  # noqa: BLE001
            _logger.warning(
                "neon_onboarding M9: cert create failed for "
                "candidate %s, type %s: %s",
                candidate.display_name, cert_type.name, e)
            return ("Cert creation failed: %s" % str(e))

        # Attachment
        file_bytes = uploaded_file.read()
        request.env["ir.attachment"].sudo().create({
            "name": uploaded_file.filename,
            "datas": base64.b64encode(file_bytes),
            "res_model": "neon.training.certification",
            "res_id": cert.id,
            "mimetype": (uploaded_file.mimetype
                         or "application/octet-stream"),
        })

        # Submit for verification -- this fires the M7 routing
        # override (Robin + Munashe become followers via the
        # _create_verification_todo path) AND the constrains
        # hook that auto-advances candidate to probationary
        # when all required certs are verified.
        #
        # Auth path: Phase 7a's action_submit_for_verification
        # check requires env.user == cert.user_id OR env.user
        # has signoff/admin. We chain with_user(candidate.
        # user_id).sudo() so env.user is the portal user (cert
        # owner -- check passes) AND su=True (ACL bypassed
        # for the underlying write).
        try:
            cert.with_user(
                candidate.user_id
            ).sudo().action_submit_for_verification()
        except Exception as e:  # noqa: BLE001
            _logger.warning(
                "neon_onboarding M9: submit_for_verification "
                "failed on cert %d: %s", cert.id, e)
            # Cert + attachment persisted; admin can manually
            # submit. Not a fatal error for the upload.

        # Audit log -- candidate.user_id is the actor (portal
        # user submitting their own cert).
        request.env["neon.onboarding.audit.log"].sudo().create({
            "candidate_id": candidate.id,
            "action": "cert_uploaded",
            "actor_id": candidate.user_id.id,
            "reason": "Self-uploaded %s via portal" % cert_type.name,
            "previous_state": candidate.state,
            "new_state": candidate.state,
        })
        _logger.info(
            "neon_onboarding M9: cert %d (%s) self-uploaded "
            "for candidate %s.",
            cert.id, cert_type.name, candidate.display_name)
        return None
