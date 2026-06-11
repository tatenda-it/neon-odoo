# -*- coding: utf-8 -*-
"""WA-11 — /neon/insights served page + JSON data endpoint.

Mirrors the neon_status served-page pattern: an ``auth='user'`` HTTP page
(403 template when denied) + a ``type='json'`` data endpoint, both gated to
the OD/superuser + Jobs Manager tier. The gate is ALSO enforced in the
collector (data layer), so a sales/crew user hitting the endpoint directly
is denied at the RPC, not merely menu-hidden. Read-only throughout.
"""
from odoo import http
from odoo.http import request
from odoo.exceptions import AccessError


class NeonInsightsController(http.Controller):

    def _collector(self):
        return request.env["neon.insights.collector"]

    def _may_view(self):
        return self._collector()._user_may_view(request.env.user)

    def _html(self, template, values, status=200):
        html = request.env["ir.qweb"]._render(template, values)
        resp = request.make_response(
            "<!DOCTYPE html>\n" + str(html),
            headers=[("Content-Type", "text/html; charset=utf-8")])
        resp.status_code = status
        return resp

    # -- page ----------------------------------------------------------
    @http.route("/neon/insights", type="http", auth="user",
                methods=["GET"], website=False)
    def insights_page(self, **kw):
        if not self._may_view():
            return self._html("neon_insights.insights_denied", {}, status=403)
        return self._html(
            "neon_insights.insights_page",
            {"data": self._collector().collect_all()})

    # -- data endpoint (filters / drilldown) --------------------------
    @http.route("/neon/insights/data", type="json", auth="user",
                methods=["POST"])
    def insights_data(self, view="all", **kw):
        """Read-only refresh / drilldown. The collector re-checks access and
        raises AccessError for a non-manager -> returned as access_denied."""
        c = self._collector()
        try:
            if view == "timeline" and kw.get("partner_id"):
                return {"ok": True,
                        "timeline": c.collect_partner_timeline(
                            kw["partner_id"])}
            if view == "stream":
                return {"ok": True, "stream": c.collect_stream(
                    role_filter=kw.get("role_filter", "all"),
                    sentiment_filter=kw.get("sentiment_filter", "all"))}
            if view == "aggregates":
                return {"ok": True, "aggregates": c.collect_aggregates()}
            return {"ok": True, "data": c.collect_all()}
        except AccessError:
            return {"ok": False, "error": "access_denied"}
