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
TRACKS = [
    {"key": "core", "name": "Core ERP Programme", "pct": 94,
     "accent": "purple"},
    {"key": "ai", "name": "AI Equipment Module", "pct": 96,
     "accent": "teal"},
    {"key": "hr", "name": "HR & Payroll", "pct": 99,
     "accent": "amber"},
]

# Overall DERIVES from the three tracks (straight mean, rounded) so a track
# bump ALWAYS moves the donut -- never a hand-set literal (Robin direction,
# 13 Jun). (94 + 96 + 99) / 3 = 96.33 -> 96.
OVERALL_PCT = round(sum(t["pct"] for t in TRACKS) / len(TRACKS))

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
    {"key": "WA-5", "title": "Client lane", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED (neon_channels 17.0.1.17.0) — first "
             "client-facing surface: sandboxed client intake + raw-lead "
             "capture, 3-button assignee message (Chat / Open in Odoo / "
             "I'm not free), escalation→Munashe + assignment loop. The "
             "morning green run proved assign-persistence (leads keep "
             "their user_id), clean decline, and no duplication; the "
             "~hourly Meta re-delivery flood root cause (a public-env "
             "flush rolling back the assignment) is fixed via the "
             "su=True webhook flush. CLOSED OUT: the COLD-template "
             "handoff→assign loop is proven on real flows (Munashe got the "
             "wa5_lead_handoff template after a ~48h gap, tapped Assign, "
             "picked from the list, lead assigned + assignee notified — "
             "twice); buttons + rendering confirmed on the handsets. The "
             "two in-window link-reply buttons (Chat / Open-in-Odoo on the "
             "escalation message) are read-only conveniences, optional to "
             "tap."},
    {"key": "WA-6", "title": "Crew + OD equipment face", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED end-to-end on real phones (neon_crew_comms "
             "17.0.1.4.0). Face 2 free-text FINALIZE (OD initiates → I'll "
             "finalize / send to crew chief → text the gear list → matcher "
             "→ confirm / fix → reservations); Face 3 WAREHOUSE checkout / "
             "check-in via WA-6.1 crew-initiated dispatch (chief texts "
             "\"check out\"/\"check in\" → bot lists ONLY their eligible "
             "jobs → pick → buttons → action). Proof: finalize reserved "
             "full quantities, checkout + check-in movements logged with "
             "actor = the real crew member, qoh balanced. Narrow per-job "
             "lead/chief gate + two-factor throughout; built on the proven "
             "equipment engine (now quantity-aware, P5.M11). WA-6.2: the OD "
             "also STARTS finalize from WhatsApp (text \"finalize\" → list "
             "planning/prep from-scratch jobs → pick → the same 3-button "
             "choice), retiring the laptop step as the primary entry."},
    {"key": "WA-7", "title": "Crew selection", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED on a real phone (neon_crew_comms 17.0.1.5.0). "
             "The OD texts \"select crew\" → bot lists from-scratch "
             "planning/prep jobs → pick → multi-pick the team from mapped "
             "staff → pick the crew chief → Confirm (rows created as the "
             "real OD, silent) → 📣 Notify fires the existing WA-2 confirm/"
             "decline. Proof: Robin picked one crew member, she confirmed "
             "via her WA-2 tap, crew_chief_id recomputed, nobody else "
             "touched (binding pick held). Two-factor throughout; new wa7_* "
             "intents (neon_channels 17.0.1.18.0)."},
    {"key": "WA-8", "title": "Sales availability (Face 1)", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED on a real phone (neon_crew_comms 17.0.1.6.1) — "
             "the first sales-facing availability surface. An entitled "
             "mapped staffer texts \"free on <date>? <gear>\" → a per-item "
             "traffic light for that time-window: 🟢 spare / 🟡 tight, no "
             "spare / 🔴 short, distinguishing \"only N in inventory\" from "
             "\"N committed on these dates\" + naming the clashing event. "
             "PURE READ — never books, holds, or quotes money. Time-window "
             "overlap (same-day non-overlapping events share gear), "
             "Harare→UTC conversion; a TYPED edit loop (a new date/time "
             "re-checks the same gear), conservative full-day default, "
             "day-before lock. A low-confidence name match is offered as a "
             "suggestion (Reply 'yes' to check it), never silently answered "
             "(WA-8.1). Reuses the WA-6 matcher + the P5.M11 availability "
             "engine directly; neon_jobs unchanged; text-only (no new "
             "intents). Re-proof passed: 🟡 no-spare + 🔎 suggestion live, "
             "zero writes after the read."},
    {"key": "WA-9", "title": "Client contact-matching", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED on real phones (neon_channels 17.0.1.19.0). The "
             "client lane now links a new WhatsApp enquiry to an existing "
             "contact by exact phone match — a recognised customer's lead "
             "carries partner_id (else a prior closed lead's contact = a new "
             "opportunity under the same client; an unknown number stays "
             "blank for a human to qualify, NEVER auto-created). A returning "
             "client whose session expired folds into their still-open lead "
             "instead of spawning a duplicate orphan. pwa9 10/10, pwa5 "
             "125/125 unchanged, adversarial review 0 confirmed, regression "
             "clean. Proof A: a real-phone enquiry was born linked to the "
             "contact. Proof B: a second keyword text after the session "
             "expired FOLDED into the same open lead (chatter follow-up, zero "
             "new leads/partners, owner re-ping correct). [TEST-WA9] fixture "
             "torn down to baseline (leads 2 / partners 37)."},
    {"key": "WA-10", "title": "Post-event feedback loop", "pct": 100,
     "state": "live",
     "body": "DONE & VERIFIED on real phones (neon_jobs 17.0.8.4.0 + "
             "neon_crew_comms 17.0.1.7.0 + neon_channels 17.0.1.20.0). On "
             "CHECK-IN landing the bot asks three voices how the event went "
             "— the sales owner (how the CLIENT felt), the OD (operations), "
             "and every assigned crew member — each a one-tap sentiment + an "
             "optional typed note, building a feedback corpus on the existing "
             "event-feedback record (extended, not a new model). A "
             "\"feedback\" command pulls a staffer's wrapped events to "
             "comment out of band. Proof: a wrapped test event messaged "
             "EXACTLY the OD + the sales owner (nobody else, never a client "
             "phone), the taps recorded as the REAL person with the right "
             "voice, notes attached (find-or-update, no duplicates), zero "
             "stray sends. Written as the real author (no sudo); a person "
             "filling two roles is asked ONCE (crew voice proven in tests); "
             "crew read only their own notes. Read-only INSIGHTS over this "
             "corpus = WA-11 (now live)."},
    {"key": "WA-11", "title": "Client feedback insights", "pct": 100,
     "state": "live",
     "body": "LIVE (neon_insights 17.0.1.0.0) — a read-only, manager-tier "
             "page at /neon/insights over the WA-10 feedback corpus: a "
             "per-client satisfaction timeline (who's happy, who's drifting), "
             "a recent-feedback stream (filter by voice + sentiment), and "
             "sentiment trends by month (Africa/Harare) with recurring-"
             "concern flags. OD + managers ONLY — the gate is enforced at "
             "the DATA layer (a sales user is denied at the RPC, not just "
             "menu-hidden), strictly read-only, no sends. Installs with "
             "honest empty-states and fills as events wrap (built as a "
             "separate addon so the dashboard's variants are untouched). The "
             "AI \"how are clients feeling lately\" digest is the follow-on "
             "(WA-11.1)."},
    {"key": "WA-12", "title": "Quote-by-WhatsApp", "pct": 100,
     "state": "verifying",
     "body": "LIVE on prod (TEMPLATE-PRIMARY, after Robin's \"too many "
             "steps\"). The rep sends one copy-fill template (or the "
             "structured one-question-at-a-time fallback) -> an engine-priced "
             "draft from the REAL catalogue (547 products / per-product "
             "rules; $1 placeholders off), an MD/OD approval ping, [Preview "
             "PDF] (DRAFT-stamped), a TYPED \"yes\" submit (deliberate money "
             "commit), then the agreed-design PDF back. Shipped: whole-quote "
             "+ per-line discounts, VAT 15.5% toggle, custom lines (clean on "
             "the client PDF, marker internal-only + UPPERCASE to match the "
             "catalogue), date-range persists both ends + a Harare quotation "
             "date, configurable expiry. The matcher never crosses category "
             "or invents a product; unmatched items FLAG and block submit "
             "until resolved. Money sign-off given (Robin + Munashe). IN "
             "VERIFICATION -- the one open proof is a director self-approving "
             "their OWN quote on their phone (fill -> \"yes\" -> self-"
             "approve)."},
    {"key": "WA-12.2", "title": "Conversational quoting", "pct": 100,
     "state": "verifying",
     "body": "BUILT & DEPLOYED, gated with WA-12. Deterministic-first: the "
             "tight \"Quote:\" parser still claims exact commands; for natural "
             "phrasing an LLM TRANSLATES the brief into {client, items, qty, "
             "date} (extraction only -- it never prices, approves, or bypasses "
             "a guard) and hands it to the same deterministic engine, which "
             "confirms every matched line + rate BEFORE drafting. New-client "
             "intake (company/individual, near-duplicate check, phone/email) "
             "runs in-chat; reps can price genuinely-unpriced items by hand "
             "(loudly flagged). RESOLVER v2 (the matcher) is now live: a "
             "category-keystone (every catalogue product carries its family) + "
             "a UI-reviewed team-slang alias store + a funnel "
             "(normalise -> confirmed-alias -> dimensional -> exact -> pg_trgm "
             "rank -> grounded LLM shortlist -> discovery) that never crosses "
             "category and never invents a product; \"3 x 2 screen\" hits the "
             "exact LED screen, \"4 blinders\" = qty 4 molefays. Goes live "
             "with WA-12."},
    {"key": "WA-13", "title": "Quote / invoice retrieval", "pct": 100,
     "state": "verifying",
     "body": "BUILT & DEPLOYED, gated. Face 1 (retrieval): \"Send quote / "
             "invoice <client>\" returns the PDF -- sales see their own "
             "quotes, finance + MD/OD see all (posted invoices only); rides "
             "WA-12 going live. Face 2 (invoice-from-quote): an accepted quote "
             "-> a finance-approved DRAFT invoice on the existing multi-stage "
             "schedule engine; switches on at the Zoho -> Odoo finance "
             "cutover (Robin's call)."},
]

# Section 4 -- real track milestones (Live / Remaining per track).
TRACK_MILESTONES = [
    {
        "name": "Core ERP Programme", "pct": 94, "accent": "purple",
        "live": "Phases 1–10 (CRM, finance, commercial + event "
                "jobs, Action Centre, Workshop, Training/LMS 7a–7e, "
                "Finance Module, Dashboards, Venue Maps) + Phase 12 "
                "Copilot through M12.2 (read + write tools, confirmation "
                "cards).",
        "remaining": "Phase 11 cutover & training IN FLIGHT (15 Jun). Zoho "
                     "reference import BUILT + installed on prod "
                     "(neon_migration 17.0.1.0.0, verified INERT — live "
                     "quotes/sequences/customer-invoices untouched; loader "
                     "25/25, extractor contract-tested 11/11): pulls the "
                     "client + quote HISTORY into a dedicated read-only "
                     "archive (no AR migrated, Odoo ledger starts clean) — "
                     "blocked only on the Zoho creds-run that produces the "
                     "two export files, then dry-run → APPLY (≈895 customers "
                     "/ 2,019 estimates as reference). Crew load (10 "
                     "technicians) scripted + dry-run-validated, APPLY "
                     "pending on the prod terminal. Then PHP retirement + a "
                     "2-week parallel run. Quote-by-WhatsApp shipped "
                     "(template-primary); the one open proof is a director "
                     "self-approving their own quote on their phone.",
    },
    {
        "name": "AI Equipment Module", "pct": 96, "accent": "teal",
        "live": "AI core = B1, B2 Conflict Engine, B3, B13 doc-gen, "
                "B14, P5.M11 quantity-aware reservation engine (reserve/"
                "checkout/check-in honour quantity_on_hand); B4 / B5 "
                "ready-to-fork. Field-tech arm = B11 WhatsApp COMPLETE for "
                "the built scope — WA-0–WA-4, WA-5 client lane, WA-6 crew + "
                "OD equipment face (finalize + WA-6.1/6.2 dispatch), WA-7 "
                "crew selection, and WA-8 sales availability (read-only "
                "Face 1) — all DONE & VERIFIED on prod. The phone-"
                "native ops cycle is now real end-to-end: crew select → "
                "finalize → checkout → check-in, each proven on real phones, "
                "actor-audited, qoh balanced; sales can now check gear "
                "availability for a date/time-window before quoting.",
        "remaining": "B10 crew scheduler pending; B8 mobile / B9 QR / B16 "
                     "predictive deferred; B12 Drive dropped.",
    },
    {
        "name": "HR & Payroll", "pct": 99, "accent": "amber",
        "live": "BUILT & LIVE (neon_hr 17.0.6.0.0): employee master, "
                "leave, payroll, event-wages, commission, loans + the "
                "Zimbabwe statutory rules populated — PAYE, NSSA, AIDS "
                "Levy, NEC — with role-lens access verified 11 Jun "
                "(Kudzaiishe HR Admin; Robin / Munashe leave approvers).",
        "remaining": "Statutory-value finance confirmation before payroll "
                     "runs on the new rules: the NSSA daily-rate figure "
                     "($20/day) + deadline, the Labour-Act 5-day leave "
                     "wording, and NEC no-overtime — each rule carries a "
                     "needs_finance_confirmation flag awaiting Kudzai / "
                     "Robin's tick.",
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
    "leave, payroll, wages, loans, fleet/competency); HR role-lens "
    "CLIENT RENDER live & verified 11 Jun — R3b shipped the lens "
    "server-side, the dashboard now DRAWS its 5 KPI tiles + 3 panels "
    "(headcount + contracts/licences/leave) with honest empty-states; "
    "every non-HR lens byte-equivalent.",
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
    "P5.M11 quantity-aware reservation engine live (neon_jobs 17.0.8.3.0 "
    "— reserve/allocate/checkout/check-in now honour quantity_on_hand for "
    "bulk products [unit-less COUNT reservations] instead of only counting "
    "unit rows; serial per-unit binding unchanged; damaged-at-check-in "
    "decrements on-hand, actor-audited; migration collapsed the legacy "
    "one-unit-per-bulk-product gap).",
    "B11 WA-6 crew + OD equipment face live & verified end-to-end on real "
    "phones (neon_crew_comms 17.0.1.3.0 — Face 2 OD-initiated free-text "
    "finalize [matcher → confirm/fix → reservations]; WA-6.1 crew-"
    "initiated Face 3 [chief texts \"check out\"/\"check in\" → bot lists "
    "ONLY their eligible jobs → pick → checkout/check-in], movements "
    "actor-audited; narrow per-job gate + two-factor; sales Face 1 "
    "deferred).",
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
    "Phase-11 data-migration lanes (after the Zoho reference import): "
    "Maz / workshop open-job importer — awaiting the target-model confirm; "
    "FamCal events-as-reference; Excel crew-pay history.",
    "Build-lane order: WA-13 quote/invoice retrieval + invoice-from-quote → "
    "WA-11.1 \"how are clients feeling\" digest → Copilot M12.2 (variant "
    "fixes) + M12.3-A (provider plurality) LAST (no hurry).",
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
