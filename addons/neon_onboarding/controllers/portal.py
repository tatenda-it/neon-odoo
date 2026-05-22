# -*- coding: utf-8 -*-
"""Portal controller for /my/onboarding route.

Phase 7b M8. Portal users (created on cert_collection entry)
land here for their onboarding profile + required cert list.
M9 will add the self-upload wizard route; M10 will add the
my-jobs view.
"""
import logging

from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

_logger = logging.getLogger(__name__)


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
        }
        return request.render(
            "neon_onboarding.portal_my_onboarding", values)
