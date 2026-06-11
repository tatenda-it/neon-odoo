# -*- coding: utf-8 -*-
"""WA-10 (B11) — apply the (b) crew READ-rule amendment on existing installs.

security/ir_rule.xml is <data noupdate="1">, so editing the EXISTING
commercial_event_feedback_rule_crew_read_own record in the XML does NOT
propagate on `-u` alone (the documented noupdate gotcha). This post-migrate
writes the amended domain_force onto the live rule so a crew member reads a
CLIENT row (wa_role=False) on their events exactly as before, but a WA-10
staff-voice row ONLY if they authored it. Idempotent (sets the final domain
regardless of the prior value). The new crew create/write rule is a NEW
record, so it loads from the XML even under noupdate -- no migration needed
for it. A fresh install loads the amended domain straight from the XML.
"""
from odoo import api, SUPERUSER_ID

_NEW_DOMAIN = (
    "['&', "
    "('event_job_id.commercial_job_id.crew_assignment_ids.user_id', '=', "
    "user.id), "
    "'|', ('wa_role', '=', False), ('captured_by', '=', user.id)]"
)
_NEW_NAME = ("Event Feedback: crew read own events' client rows + own "
             "staff-voice rows")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    rule = env.ref(
        "neon_jobs.commercial_event_feedback_rule_crew_read_own",
        raise_if_not_found=False)
    if rule and rule.domain_force != _NEW_DOMAIN:
        rule.write({"name": _NEW_NAME, "domain_force": _NEW_DOMAIN})
