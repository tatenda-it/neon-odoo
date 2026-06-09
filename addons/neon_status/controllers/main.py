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
OVERALL_PCT = 89

TRACKS = [
    {"key": "core", "name": "Core ERP Programme", "pct": 91,
     "accent": "purple"},
    {"key": "ai", "name": "AI Equipment Module", "pct": 86,
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
    {"key": "WA-2", "title": "WhatsApp-to-ops", "pct": 100,
     "state": "live",
     "body": "Human-triggered crew confirmations + reminders LIVE — "
             "Notify Crew → approved template → tap Confirm / Can't-make-it "
             "→ assignment confirmed/declined (two-factor: HMAC + phone "
             "match); opt-out + rate-limit; verified on prod."},
    {"key": "WA-3", "title": "Readiness digest / broadcast", "pct": 100,
     "state": "live",
     "body": "Manager readiness digest LIVE — composite status+crew RAG "
             "(green/amber/red), manager/crew-leader gated, served "
             "/neon/readiness board, opt-out, daily cron shipped disabled; "
             "verified on prod (counts match the collector)."},
    {"key": "WA-4", "title": "Dual-role & intent routing", "pct": 100,
     "state": "live",
     "body": "Per-turn intent→lens for multi-role users LIVE — finance→"
             "Bookkeeper / HR→HR / ambiguous→2-button ask / explicit "
             "'as bookkeeper' override; routes only among lenses held "
             "(never widens access); '🔖 as <lens>' surfaced; verified "
             "on prod (Kudzaiishe)."},
    {"key": "WA-5", "title": "Client lane", "pct": 95,
     "state": "live",
     "body": "DONE & VERIFIED (neon_channels 17.0.1.17.0) — first "
             "client-facing surface: sandboxed client intake + raw-lead "
             "capture, 3-button assignee message (Chat / Open in Odoo / "
             "I'm not free), escalation→Munashe + assignment loop. The "
             "morning green run proved assign-persistence (leads keep "
             "their user_id), clean decline, and no duplication; the "
             "~hourly Meta re-delivery flood root cause (a public-env "
             "flush rolling back the assignment) is fixed via the "
             "su=True webhook flush. Minor sub-checks remain (Munashe "
             "3-button + cold-template phone round-trips) — post-go-live "
             "polish, not blocking done."},
    {"key": "WA-6", "title": "Crew + OD equipment face", "pct": 85,
     "state": "verifying",
     "body": "DEPLOYED (neon_crew_comms 17.0.1.2.0 + neon_channels "
             "17.0.1.17.0; 11 wa6_ intents live; wa6_od_login set) — "
             "Face 2 free-text FINALIZE (OD initiates → I'll finalize / "
             "send to crew chief → text the gear list → matcher → "
             "confirm / fix → dated reservations) + Face 3 WAREHOUSE "
             "checkout / check-in (narrow per-job lead/chief gate; runs "
             "as the real tapping user for an honest audit). Sales "
             "Face 1 deferred. Built on the PROVEN equipment engine — no "
             "reimplementation. Pending: in-window real-phone proof + "
             "Meta approval of the wa6_equip_finalize template "
             "(submitted)."},
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
        "name": "AI Equipment Module", "pct": 86, "accent": "teal",
        "live": "AI core = B1, B2 Conflict Engine, B3, B13 doc-gen, "
                "B14; B4 / B5 ready-to-fork. Field-tech arm = B11 "
                "WhatsApp — WA-0–WA-4 done (rails, memory + interactive "
                "renderer, crew-ops confirmations, readiness digest, "
                "dual-role lens routing), WA-5 client lane DONE & "
                "VERIFIED, WA-6 crew + OD equipment face DEPLOYED (in "
                "verification). Equipment flow proven end-to-end on prod "
                "(reserve→checkout→transfer→check-in, cleaned to "
                "baseline).",
        "remaining": "WA-6 in final verification (in-window real-phone "
                     "proof + Meta approval of wa6_equip_finalize); B10 "
                     "crew scheduler pending; B8 mobile / B9 QR / B16 "
                     "predictive deferred; B12 Drive dropped.",
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
    "B11 WA-2 WhatsApp-to-ops live (new neon_crew_comms bridge — ops "
    "'Notify Crew' sends the approved crew_assignment template; crew tap "
    "Confirm/Can't-make-it routes two-factor [HMAC + phone-match] to the "
    "existing confirm/decline workflow; opt-out + 12h rate-limit; "
    "reminder cron shipped disabled; verified end-to-end on prod).",
    "B11 WA-3 Readiness digest live (manager RAG digest — composite "
    "status+crew RAG; manager/crew-leader gated; served /neon/readiness "
    "board; opt-out; daily cron shipped disabled; verified end-to-end, "
    "counts match collector).",
    "B11 WA-4 dual-role lens routing live (per-turn intent→lens for "
    "multi-role users — finance→Bookkeeper / HR→HR / ambiguous→ask / "
    "explicit override; routes only among lenses the user holds, never "
    "widens access; audit records the applied lens; verified on prod "
    "with Kudzaiishe).",
    "B11 WA-5 client lane live & verified (first client-facing surface — "
    "sandboxed client intake + raw-lead capture; 3-button assignee "
    "message [Chat / Open in Odoo / I'm not free]; escalation→Munashe + "
    "assignment loop with two-factor decline; assign-persistence + clean "
    "decline + no-duplication proven on prod; the ~hourly Meta "
    "re-delivery flood root cause — a public-env flush rolling back the "
    "assignment — fixed via the su=True webhook flush).",
    "Equipment flow no-compromise prod proof (reserve → checkout → "
    "transfer → check-in verified end-to-end on the live workshop "
    "engine, then cleaned back to baseline) — the foundation the WA-6 "
    "equipment face reuses.",
]

DECIDED_NOT_BUILT = [
    # WA-5 client lane is DONE & VERIFIED (now in "Done & verified");
    # WA-6 crew + OD equipment face is DEPLOYED and in final verification
    # (see the WhatsApp cards) -- neither is "decided not built".
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
