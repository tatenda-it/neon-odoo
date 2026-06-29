# -*- coding: utf-8 -*-
from odoo import fields, models


class CrmLead(models.Model):
    """2E bridge (install-safe half). Tracks whether a won/confirmed opportunity
    has been turned into an operational Event Job, WITHOUT coupling to
    commercial.event.job internals (whose live schema must be confirmed before
    wiring the real link + T-3 allocation view).
    """

    _inherit = "crm.lead"

    neon_event_job_created = fields.Boolean(
        string="Event Job Created",
        default=False,
        help="Set when this confirmed deal has been turned into an operational "
             "Event Job. NOTE: wire this to the real commercial.event.job "
             "conversion in the completion step (see module README).",
    )
    neon_event_job_ref = fields.Char(
        string="Event Job Reference",
        help="Free-text reference to the Event Job, pending the real m2o link "
             "to commercial.event.job once its schema is confirmed.",
    )
    neon_event_job_note = fields.Char(string="Conversion Note")

    def action_neon_flag_event_job(self):
        """Manual: mark this deal as converted to an Event Job (bridge stub).
        The real conversion (creating the commercial.event.job) is the
        completion step, not this."""
        for lead in self:
            lead.neon_event_job_created = True
        return True
