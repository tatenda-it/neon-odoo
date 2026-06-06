# -*- coding: utf-8 -*-
"""B11 -- Programme Status board controller.

Two routes, both ``auth='user'`` and both behind the same internal-user
+ audience gate:

* ``GET  /neon/status``      -- renders the board (server-side initial
  read so the page is correct before any JS runs).
* ``POST /neon/status/data`` -- ``type='json'`` refresh endpoint; returns
  the same live aggregates the "Refresh live status" button re-reads.

Read-only throughout. The live reads happen in ``neon.status.live``
(``.sudo()``, aggregates only) -- see that model for the ACL rationale.
"""
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# AUDIENCE GATE (Gate-1 decision 2, B11)
# ---------------------------------------------------------------------
# Empty tuple == "all internal users" (the shipped audience: the board
# returns non-sensitive aggregates, so it is a shared team progress
# board). To tighten to leadership later, set this to a tuple of group
# xmlids, e.g.:
#     STATUS_BOARD_GROUPS = (
#         "neon_core.group_neon_superuser",
#         "neon_core.group_neon_bookkeeper",
#     )
# Portal / public users are ALWAYS excluded regardless of this value.
STATUS_BOARD_GROUPS = ()


# ---------------------------------------------------------------------
# PLANNING CONSTANTS (editable page judgment -- NOT prod-computable)
# ---------------------------------------------------------------------
# The milestone percentages are a planning judgment, kept here as plain
# editable constants. Only the "Live from prod" box reads real-time
# values (via neon.status.live). Bump these numbers as the programme
# moves; the donut + bars + WA cards all derive from this one block.
OVERALL_PCT = 85

TRACKS = [
    {"key": "core", "name": "Core ERP Programme", "pct": 91,
     "accent": "purple"},
    {"key": "ai", "name": "AI Equipment Module", "pct": 73,
     "accent": "teal"},
    {"key": "hr", "name": "HR & Payroll", "pct": 92,
     "accent": "amber"},
]

# B11 WhatsApp module breakdown (inside the AI Equipment Module track).
WA_MODULES = [
    {"key": "WA-0", "title": "Foundation & rails", "pct": 100,
     "state": "live",
     "body": "Transport, role-scoped replies, Gemini + Groq fallback, "
             "money guardrail, signed webhook."},
    {"key": "WA-1", "title": "Memory + interactive renderer", "pct": 100,
     "state": "live",
     "body": "Conversation memory LIVE (phone-format bug class closed); "
             "interactive renderer LIVE — reply buttons + lists + "
             "CTA-URL, role-driven; Confirm-tap reuses the write.log "
             "gate (verified on prod), money walled off."},
    {"key": "WA-2", "title": "WhatsApp-to-ops", "pct": 0,
     "state": "roadmap",
     "body": "Crew confirmations, equipment-ready pings, job reminders "
             "(roadmap)."},
    {"key": "WA-3", "title": "Readiness digest / broadcast", "pct": 0,
     "state": "roadmap",
     "body": "Scheduled role-aware digests (roadmap)."},
    {"key": "WA-4", "title": "Dual-role & intent routing", "pct": 0,
     "state": "roadmap",
     "body": "Answer-by-intent for multi-role users (Kudzaiishe finance "
             "vs HR), guardrail-aware (roadmap)."},
    {"key": "WA-5", "title": "(reserved)", "pct": 0,
     "state": "roadmap",
     "body": "Scope not yet defined."},
]

# Section 4 -- real track milestones (Live / Remaining per track).
TRACK_MILESTONES = [
    {
        "name": "Core ERP Programme", "pct": 91, "accent": "purple",
        "live": "Phases 1–10 (CRM, finance, commercial + event "
                "jobs, Action Centre, Workshop, Training/LMS 7a–7e, "
                "Finance Module, Dashboards, Venue Maps) + Phase 12 "
                "Copilot through M12.2 (read + write tools, confirmation "
                "cards).",
        "remaining": "Phase 11 cutover & training; M12.2 P4–P7 / "
                     "M12.3 parked.",
    },
    {
        "name": "AI Equipment Module", "pct": 73, "accent": "teal",
        "live": "AI core = B1, B2 Conflict Engine, B3, B13 doc-gen, "
                "B14; B4 / B5 ready-to-fork. Field-tech arm = B11 "
                "WhatsApp (live frontier; WA-0 + WA-1 done — rails, "
                "memory + interactive renderer).",
        "remaining": "WA-2–WA-5 roadmap; B10 crew scheduler pending; "
                     "B8 mobile / B9 QR / B16 predictive deferred; "
                     "B12 Drive dropped.",
    },
    {
        "name": "HR & Payroll", "pct": 92, "accent": "amber",
        "live": "R1a, R1b, R2 (leave, payroll, wages, loans) + access "
                "wired (Kudzaiishe HR Admin, Robin / Munashe leave "
                "approvers).",
        "remaining": "R3.",
    },
]

# Section 6 -- governance lists. RECONSTRUCTED from project memory
# (the previous board was a chat artifact); Tatenda confirms wording at
# Gate 2 before prod.
DONE_VERIFIED = [
    "Phases 1–10 core ERP live on crm.neonhiring.com (CRM, Finance "
    "Module rebuild, commercial + event jobs, Action Centre, Workshop "
    "Inventory).",
    "Training & LMS 7a–7e live (cert issuance, quizzes, branded "
    "course pages, footer).",
    "Dashboards 8A + 8B live (Director / Sales / Bookkeeper / Lead Tech "
    "variants, Edit Layout).",
    "Phase 9 Venue Maps live (pin picker + modal map).",
    "Phase 12 AI Sales Copilot through M12.2 (read + write tools, "
    "two-phase confirmation cards, write-audit log).",
    "HR & Payroll R1a / R1b / R2 / R3a / R3b live (employee master, "
    "leave, payroll, wages, loans, fleet/competency, HR role-lens).",
    "B11 WA-0 + WA-1 live (WhatsApp Copilot rails — role-scoped "
    "replies, Gemini + Groq fallback, money guardrail, signed webhook; "
    "conversation memory + boundary phone normalization; interactive "
    "renderer — reply buttons + lists + tap-back Confirm/Cancel reusing "
    "the write.log gate under the resolved-user identity, verified on "
    "prod, money structurally walled off).",
    "neon_ai_core extraction live (shared AI engine; Copilot Confirm "
    "accepted).",
    "neon_jobs escalation-gate fix live (cron quiet; manager gate "
    "intact).",
]

DECIDED_NOT_BUILT = [
    "WA-2 WhatsApp-to-ops (crew confirmations, equipment-ready pings, "
    "job reminders).",
    "WA-3 readiness digest / broadcast (scheduled role-aware digests).",
    "WA-4 dual-role & intent routing (answer-by-intent for multi-role "
    "users, guardrail-aware).",
    "B10 crew scheduler.",
    "B4 sub-hire drafting / B5 post-event reconciliation — "
    "ready-to-fork.",
    "M11.1 AI adapters (Anthropic / Gemini / Ollama) + Compare "
    "Providers tool.",
]

PARKED_BACKLOG = [
    "B8 mobile app / B9 QR scanning / B16 predictive maintenance — "
    "deferred.",
    "B12 Google Drive integration — dropped.",
    "WA-5 — reserved, scope not yet defined.",
    "Phase 11 cross-module scroll-fix sweep + cutover & training.",
    "M12.2 P4–P7 / M12.3 Copilot scope — parked.",
    "Leaflet bootstrap consolidation (deferred from Phase 9).",
    "main-branch reconciliation (production line tracked via phase tags).",
]


def user_may_view(user):
    """Audience gate as a pure predicate (no ``request`` dependency, so
    it is unit-testable from the smoke). Internal users only
    (portal/public always excluded), then the optional group gate ---
    empty ``STATUS_BOARD_GROUPS`` == every internal user."""
    # share=True -> portal/public. Never allowed.
    if user.share:
        return False
    if not STATUS_BOARD_GROUPS:
        return True
    return any(user.has_group(g) for g in STATUS_BOARD_GROUPS)


class NeonStatusController(http.Controller):

    # -- gate ----------------------------------------------------------
    def _user_may_view(self):
        return user_may_view(request.env.user)

    def _render_values(self):
        """Shared context: live aggregates + the planning constants."""
        live = request.env["neon.status.live"].collect()
        return {
            "live": live,
            "overall_pct": OVERALL_PCT,
            "tracks": TRACKS,
            "wa_modules": WA_MODULES,
            "track_milestones": TRACK_MILESTONES,
            "done_verified": DONE_VERIFIED,
            "decided_not_built": DECIDED_NOT_BUILT,
            "parked_backlog": PARKED_BACKLOG,
        }

    def _html_response(self, template, values, status=200):
        """Render a self-contained template and ship it with a DOCTYPE.

        QWeb templates can't carry a ``<!DOCTYPE>`` node (not valid XML),
        so the board renders to a string and the doctype is prepended
        here -- otherwise browsers fall into quirks mode."""
        html = request.env["ir.qweb"]._render(template, values)
        resp = request.make_response(
            "<!DOCTYPE html>\n" + str(html),
            headers=[("Content-Type", "text/html; charset=utf-8")])
        resp.status_code = status
        return resp

    # -- page ----------------------------------------------------------
    @http.route("/neon/status", type="http", auth="user",
                methods=["GET"], website=False)
    def status_page(self, **kw):
        if not self._user_may_view():
            return self._html_response(
                "neon_status.programme_status_denied", {}, status=403)
        return self._html_response(
            "neon_status.programme_status_page", self._render_values())

    # -- refresh endpoint ---------------------------------------------
    @http.route("/neon/status/data", type="json", auth="user",
                methods=["POST"])
    def status_data(self, **kw):
        """Server-side, read-only refresh. Returns aggregates only."""
        if not self._user_may_view():
            return {"ok": False, "error": "access_denied"}
        return {"ok": True, "live": request.env["neon.status.live"].collect()}
