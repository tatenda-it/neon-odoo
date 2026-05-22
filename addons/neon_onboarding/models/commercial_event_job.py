# -*- coding: utf-8 -*-
"""commercial.event.job inherit -- refresh candidate jobs
counter in real-time on event_job completion.

Phase 7b M6 amendment (22 May 2026). Resolves the M5-logged
limitation where probationary_jobs_completed didn't refresh
on event_job completion because cross-model state changes
aren't expressible in @api.depends from the candidate side.

Hook lives in neon_onboarding (not neon_jobs) per the
M_N-owns-the-fix pattern: the onboarding feature wants the
refresh, so the touch is on neon_onboarding's _inherit. Zero
Phase 7a + zero neon_jobs files modified.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class CommercialEventJobOnboardingRefresh(models.Model):
    _inherit = "commercial.event.job"

    def write(self, vals):
        """When state transitions to 'completed', force-
        recompute probationary_jobs_completed on every
        candidate whose user is on the crew of this event's
        parent commercial.job. Fires synchronously so the
        kanban + ready badge reflect the new count
        immediately.

        Defensive against missing neon.onboarding.candidate
        model (env.get returns None when neon_onboarding is
        not installed -- though if this inherit fires the
        module IS installed, so the check is belt-and-
        braces).
        """
        res = super().write(vals)
        if vals.get("state") != "completed":
            return res
        Candidate = self.env.get("neon.onboarding.candidate")
        if Candidate is None:
            return res
        for event_job in self:
            crew_user_ids = (
                event_job.commercial_job_id
                .crew_assignment_ids
                .mapped("user_id")
                .ids
            )
            if not crew_user_ids:
                continue
            candidates = self.env[
                "neon.onboarding.candidate"
            ].sudo().search([
                ("user_id", "in", crew_user_ids),
                ("state", "in",
                 ["probationary", "active"]),
            ])
            if candidates:
                candidates._compute_probationary_jobs_completed()
                candidates.flush_recordset(
                    ["probationary_jobs_completed"])
                _logger.info(
                    "neon_onboarding M6: refreshed "
                    "probationary_jobs_completed on %d "
                    "candidate(s) after event_job %s "
                    "completion.",
                    len(candidates), event_job.display_name)
        return res
