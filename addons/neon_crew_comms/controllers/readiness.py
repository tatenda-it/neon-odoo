# -*- coding: utf-8 -*-
"""B11 / WA-3 -- served readiness board (manager-scoped).

Mirrors the neon_status served-page pattern: GET /neon/readiness renders
a self-contained board (auth='user', manager/crew-leader gate, sudo
aggregate); POST /neon/readiness/send is the manual "send digest now"
trigger (re-gated in action_send_now). Read-only board; the only write
is the gated, explicit send.
"""
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Manager-scoped (NOT all internal users): the can_edit_crew set.
READINESS_BOARD_GROUPS = (
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
)


def board_may_view(user):
    """Internal users in the ops set only (portal/public always out)."""
    if user.share:
        return False
    return any(user.has_group(g) for g in READINESS_BOARD_GROUPS)


class NeonReadinessController(http.Controller):

    def _html(self, template, values, status=200):
        html = request.env["ir.qweb"]._render(template, values)
        resp = request.make_response(
            "<!DOCTYPE html>\n" + str(html),
            headers=[("Content-Type", "text/html; charset=utf-8")])
        resp.status_code = status
        return resp

    @http.route("/neon/readiness", type="http", auth="user",
                methods=["GET"], website=False)
    def readiness_board(self, **kw):
        if not board_may_view(request.env.user):
            return self._html(
                "neon_crew_comms.readiness_denied", {}, status=403)
        data = request.env["neon.readiness.digest"].collect()
        return self._html(
            "neon_crew_comms.readiness_board", {"data": data})

    @http.route("/neon/readiness/send", type="json", auth="user",
                methods=["POST"])
    def readiness_send(self, **kw):
        if not board_may_view(request.env.user):
            return {"ok": False, "error": "access_denied"}
        # action_send_now re-checks the manager gate (defence in depth).
        res = request.env["neon.readiness.digest"].action_send_now()
        return {"ok": True, "result": res}
