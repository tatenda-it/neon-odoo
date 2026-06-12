# -*- coding: utf-8 -*-
{
    "name": "Neon Crew Comms",
    # B11 / WA-2 -- WhatsApp-to-ops: proactive crew messaging. A tiny
    # BRIDGE module (depends neon_jobs + neon_channels) so neither core
    # module has to take a dependency on the other. It holds:
    #   * the crew->phone resolver + notified_on/reminder_on anchors
    #     (_inherit commercial.job.crew),
    #   * the human-triggered "Notify crew" button + recipient wizard
    #     and "Send reminders" (_inherit commercial.job),
    #   * the crew tap-back (_inherit neon.whatsapp.message.handle_inbound)
    #     reusing the EXISTING decline wizard + action_confirm,
    #   * a cron-ready (but NOT enabled) day-before reminder.
    # The generic channel primitives (send_template, opt-out, STOP) live
    # in neon_channels; crew_confirm/crew_decline intents are registered
    # in neon_channels' wa_payload. (Gate-1 decision 3, WA-2.)
    # 17.0.1.0.1 = fix: crew_assignment body params 4->5 (add call-time
    # var; Meta 132000 param-count mismatch on the approved 5-var
    # template: name, job, date, time, role) + job_reminder var2 date->
    # call-time (job, time, venue, role). New _wa_time_label() sources
    # the earliest event_job load-in/dispatch/prep time, 'TBC' fallback.
    # 17.0.1.1.0 = B11/WA-3 readiness digest: neon.readiness.digest
    # collector (composite RAG from operational_status + crew), a
    # daily_readiness Meta template (4 fixed counts + static board URL),
    # a DISABLED daily cron + manager-gated manual send, and the served
    # /neon/readiness manager board (neon_status pattern). New layer; no
    # new stored columns.
    # 17.0.1.2.0 = B11/WA-6 crew + OD equipment face. NEW layer:
    #   * neon.wa.equip.session -- mapped-staff finalize conversation state
    #     (one row per staff phone; JSON line buffer; TTL).
    #   * whatsapp_message_wa6 -- the WA-6 method bank, intercepted in
    #     handle_inbound BEFORE super() (disjoint from crew/WA-5 intents):
    #     FACE 2 finalize (OD 3-button initiate -> free-text matcher ->
    #     review/confirm/fix -> proven line.create + allocate) and FACE 3
    #     warehouse checkout/check-in (reuse action_checkout[_all] + the
    #     check-in wizard headlessly). Gates are XML-id/login only (the
    #     group-58 lesson); two-factor = HMAC payload + sender-phone ->
    #     resolved-user re-check; per-job advisory lock ns 5593600.
    #   * commercial.event.job header button (OD-initiate), gated to the OD
    #     login / Neon Superuser in the planning/prep window.
    # WA-6 intents registered in neon_channels' wa_payload. No new cron.
    # 17.0.1.2.1 = P5.M11 touchpoint: WA-6 finalize confirm now calls the
    # unified line.action_allocate() (serial binds units / quantity
    # reserves a COUNT against quantity_on_hand) instead of the serial-only
    # _find_available_units + _bind path, and surfaces the engine's honest
    # short reason ("only N in inventory" vs "M committed on those dates").
    # 17.0.1.3.0 = WA-6.1 Face-3 crew-initiated dispatch (the trigger WA-6
    # omitted). A mapped lead_tech/crew_chief texts a TIGHT command
    # ("check out"/"checkout"/"check in"/"checkin" + equipment/gear
    # variants; equals/startswith, never substring) -> bot lists ONLY their
    # eligible jobs (checkout: confirmed holds; check-in: gear still out,
    # quantity clears once a checkin movement exists) -> they pick a number
    # -> bot SENDS the existing [Check out all][Item-by-item] /
    # [All returned good][Flag an item] buttons (the previously-missing
    # dispatch) -> existing _wa6_route_checkout/checkin. Fires ONLY for a
    # mapped role-holder with >=1 eligible job; everyone else falls through
    # to Copilot/client lane UNCHANGED. New co_pick/ci_pick session steps.
    # Reuses wa6_co_*/wa6_ci_* intents -- no neon_channels touch.
    # 17.0.1.4.0 = WA-6.2 OD WhatsApp-initiated finalize (kills the laptop
    # step as the PRIMARY entry; the Odoo header button stays SECONDARY).
    # The OD/superuser texts a TIGHT command ("finalize"/"finalise"/
    # "finalize equipment"; equals/startswith, never substring) -> bot lists
    # ONLY planning/prep jobs with NO equipment lines yet (strictly
    # from-scratch -- the WhatsApp finalize BUILDS the lines; an already-
    # finalized or pre-seeded job is edited in Odoo) -> OD picks a number ->
    # bot SENDS the EXISTING 3-button choice [I'll finalize][Send to crew
    # chief][Open in Odoo] for that job -> the proven Face-2 _wa6_route_
    # initiate flow takes over UNCHANGED. New fin_pick session step; reuses
    # wa6_fin_* intents -- NO neon_channels touch. Mirrors WA-6.1 exactly
    # (command -> list -> pick -> send buttons). Gated to OD/superuser via
    # has_group (XML id); a non-OD mapped sender falls through to Copilot,
    # an unmapped sender to the client lane -- the parser never steals a
    # turn. No new access power (a new face for the existing initiate gate).
    # 17.0.1.5.0 = WA-7 crew selection on WhatsApp (the last laptop seam).
    # The OD/superuser texts "select crew"/"assign crew" (tight parser) ->
    # list-then-pick ×3 in one session: (1) JOB = planning/prep event jobs
    # whose PARENT commercial.job has NO crew yet (from-scratch) -> (2)
    # PEOPLE = active mapped bot.users, multi-select "1, 3, 4" -> (3) CHIEF =
    # one of the picked -> [Confirm team][Change] -> create
    # commercial.job.crew rows on the parent (default role 'tech',
    # is_crew_chief on the chosen one) AS THE REAL ACTING USER (with_user;
    # holds can_edit_crew) -> crew_chief_id recomputes (the seam WA-6 reads)
    # -> [Notify the crew] fires the EXISTING WA-2 confirm/decline to each
    # picked person (NO send without the tap; D4). New cs_* steps on
    # neon.wa.equip.session; WA-7's intercept runs BEFORE WA-6 + claims ONLY
    # cs_* sessions, so WA-6 is untouched. New wa7_* intents in neon_channels
    # (17.0.1.18.0). Confirm-time from-scratch re-check + advisory lock ns
    # 5593700. neon_jobs UNCHANGED (reuses the crew model + constraints). No
    # new access power (OD/superuser already holds can_edit_crew via manager).
    # 17.0.1.6.0 = WA-8 Face 1 availability check on WhatsApp (PURE READ; no
    # books/holds/writes, NO money). An entitled MAPPED user texts a tight
    # command + a date (+ optional times) + a gear list ("free on 14 Aug?
    # 2.5 black truss x4, distro x2") -> a traffic-light availability PER ITEM
    # for that time-window, distinguishing "only N in inventory" from "N
    # committed on these dates" + naming the competing event. REUSES the WA-6
    # matcher (_wa6_match_one) + the P5.M11 engine primitives directly
    # (ConflictEngine._available_for_product supply MINUS
    # neon.equipment.reservation._committed_qty_for_product committed; serial
    # = active units, quantity = quantity_on_hand; transfer-destination holds
    # counted for free) -- neon_jobs UNCHANGED. TEXT-ONLY MVP: the locked edit
    # loop is TYPED on a sticky av_check session -- items stick, a typed new
    # date/time re-checks the SAME items, no time -> a conservative FULL-DAY
    # window, a date that is today/past is locked. Soft 2h TTL (vs the 12h
    # finalize TTL). TIMEZONE: Harare-local windows converted to UTC before
    # the overlap math. Entitlement widened (read-only, pre-authorised): OD/
    # superuser + sales/manager/crew-leader tiers + this-job chief/lead + any
    # active mapped bot.user. Intercept BETWEEN WA-7 and WA-6, claims ONLY
    # av_check; the tight parser (command + parseable date + >=1 matched item)
    # never steals a turn. NO buttons -> NO wa8_* intents -> neon_channels
    # UNTOUCHED. New av_check session step + _start_av; no new column / RBAC.
    # 17.0.1.6.1 = WA-8.1 (two real-phone-proof fixes; still neon_crew_comms
    # only, text-only): (1) TIGHTNESS TIER -- exact capacity (available ==
    # requested, free == needed) renders "tight, no spare" (was free); free
    # requires a genuine spare (available > requested); short only when
    # available < requested. (2) STRICTER FACE-1 ACCEPTANCE on top of the
    # shared matcher (NOT retuned -- Face 2 relies on its loose behaviour
    # behind its confirm step): a no-confirm answer is given only when the
    # matched product IS the kind of thing named -- its HEAD NOUN (last alpha
    # word, ignoring numbers/dimensions/model-codes, plural-folded) appears
    # in the query; else it is offered as a suggestion ("...closest: X. Reply
    # yes to check it, or refine") stored as a pending session item, and a
    # typed "yes" promotes + checks it. Fixes "smoke machine" silently
    # answering VERTICAL SMOKE MACHINE REMOTES. New _wa8_prepare/_is_confident
    # /_head_noun/_words/_fold + pending/last_window buffer keys. pwa8 33/33;
    # pwa6 Face-2 byte-unchanged (58/58).
    # 17.0.1.7.0 = B11/WA-10 post-event feedback loop. NEW method bank
    # (whatsapp_message_wa10) on neon.whatsapp.message, intercepted AFTER
    # WA-8 / before WA-6: on CHECK-IN LANDING (the neon_jobs check-in wizard
    # calls _wa10_on_checkin once per job, guarded by event_job.wa10_prompted)
    # it pushes sentiment prompts to THREE voices -- the sales owner (relayed
    # client CSAT), the OD, and every assigned crew member with a mapped
    # bot.user. A wa10_fb tap records a commercial.event.feedback row (the
    # extended P3.M7 model, channel='whatsapp') via with_user(the real voice)
    # -- honest create_uid, NO sudo -- find-or-update one-per-(event, author,
    # role) under a fresh advisory lock (ns 5593800); a short fb_notes session
    # UPDATES the row with a free-text note. A "feedback" PULL command lists
    # the sender's role-eligible WRAPPED events (fb_pull) to give feedback out
    # of band. New fb_pull/fb_notes session steps + _start_fb. Window-aware
    # push with an Odoo-activity fallback; the create sends NOTHING (mail
    # suppressed). New wa10_* intents in neon_channels (17.0.1.20.0); the model
    # extension + check-in hook live in neon_jobs (17.0.8.4.0).
    # 17.0.1.8.0 = B11/WA-12 quote-by-WhatsApp orchestration (the first
    # money-adjacent face). New whatsapp_message_wa12.py method bank: tight
    # Quote:/Price: parsers + sales-capable entitlement, the q_confirm/q_reject
    # FSM (new steps + _start_quote on wa_equip_session), provision->line-build
    # ->no_rule guard->submit, and the dual-payload approval dispatch (HMAC
    # in-window + template-QR; first-tap-wins advisory lock ns 5593900; gate +
    # audience resolved from the approver GROUP). Intercept wired after WA-10,
    # before WA-6. Provisioning + lifecycle live in neon_finance (17.0.7.10.0);
    # intents in neon_channels (17.0.1.21.0). LIVE behind Robin's money sign-off.
    # 17.0.1.8.1 = WA-12 pricing-engine fix (review): _wa12_build_lines no longer
    # reads product.list_price -- it creates the line with unit_rate=0.0 so the
    # finance pricing ENGINE resolves the rate (rule x bracket x day-multiplier)
    # via the product's equipment_category_id; an unruled category -> 'no_rule'
    # -> the guard blocks submit. The WA-12 lane can no longer fabricate a
    # 'manual'-priced line. Pairs with neon_finance 17.0.7.10.1.
    # 17.0.1.8.2 = WA-12 send-leg guard: _wa12_handle_send_to_client checks the
    # client has an email before action_send; absent -> honest refusal + state
    # stays 'approved' (no false "sent" on an undelivered quote). Rides the LIVE
    # batch with the quote-PDF design alignment (neon_finance 17.0.7.10.2).
    # 17.0.1.9.0 = WA-12 flexibility orchestration: the q_confirm draft-edit loop
    # (_wa12_match_line + price/discount/qty/days/add/remove/no-tax/with-tax/
    # client/add-custom), the line_type-aware no_rule guard, and discount/custom
    # rendering in the draft summary. Pairs with neon_finance flex model + report.
    # 17.0.1.10.0 = WA-13 quote/invoice retrieval + invoice-from-quote — a new
    # whatsapp_message_wa13.py: tight `Send quote/invoice <client|ref>` parsers,
    # explicit positive entitlement gates (quotes own-scope code domain for
    # sales / all for approver+OD; invoices approver+OD only), the doc_pick /
    # inv_pick / inv_confirm FSM (new steps + _start_inv on wa_equip_session),
    # Face-1 PDF retrieval (quotes via the WA-12 report action, posted invoices
    # via account.account_invoices), and Face-2 invoice-from-quote (approver-
    # gated two-phase confirm -> action_trigger_now -> DRAFT move; re-send the
    # auto-fired on_acceptance draft). Intercept wired after WA-12, before WA-6;
    # advisory lock ns 5594000. New wa13_inv_* intents in neon_channels
    # (17.0.1.22.0); reuses the existing P6.M7 invoice machinery (no new finance
    # engine; neon_finance 17.0.7.10.7 only makes Kudzai's grant durable). Money-
    # adjacent Face-2 behind Robin's sign-off + the approver group.
    # 17.0.1.10.1 = WA-12/WA-13 adversarial-review fixes (11 confirmed findings):
    # WA-13 -- release the WA-2 opt-out keywords before a live session claims
    # the turn (STOP no longer swallowed); re-gate the doc_pick / inv_* session
    # on the CURRENT phone owner EVERY turn (deactivated/deprivileged/remapped
    # can't keep pulling docs); a stray cross-feature interactive tap's TITLE is
    # never parsed as a session command (claim + re-prompt); the Face-2 confirm
    # VAT label tracks actual amount_tax (no/partial/incl). WA-12 -- the Price:
    # face prices through the ENGINE (rule x bracket), never product.list_price,
    # so Price: and Quote: agree; _wa12_after_edit guards action_recalculate_
    # pricing (a discount/_check_discount ValidationError -> clean reply, not a
    # silent half-applied turn); the same interactive-tap short-circuit in the
    # q_* session. (Latent multi-bracket discount-drift documented ⚠️ DECISION;
    # unreachable under binding-b flat product rules.) pwa12 27/27, pwa13 15/15.
    # 17.0.1.10.2 = WA-12 requester DRAFT preview: a `preview` (alias `pdf`)
    # edit-loop command, available throughout the q_confirm draft session, renders
    # the CURRENT draft via the existing DRAFT-stamped report -> send_document to
    # the REQUESTER. Pure preview -- no state change, no approval interaction,
    # repeatable after any edit. Reuses _wa12_send_pdf (existing report; no
    # neon_finance change). pwa12 28/28.
    # 17.0.1.10.3 = WA-12 phone-native hardening (proof walls; deterministic):
    # (a) PAYMENT TERMS auto-apply the company 7-day default (get-or-create) at
    # provision + re-ensure at submit -> the submit gate NEVER tells a phone
    # user to open an Odoo button; new `terms <text>` edit command (light-parses
    # 'N days'/'X%'). (b) DATE always shown in the draft summary; a bare-date
    # message mid-session SETS/confirms the event date (not the help menu).
    # (c) DATE TOLERANCE day-first: 25/09/26, 25/09/2026, 29 Sept 2026,
    # 15 september 2026, 15th Sep (ordinals + Sept normalised). (d) SYNONYMS:
    # cancel|delete|scrap (this); submit|submit/send for approval; conversational
    # quote triggers "make a quotation for"/"i want a quote for"/"quote for"
    # alongside "Quote:". No neon_finance/report change. pwa12 31/31, pwa13 15/15.
    # 17.0.1.10.4 = WA-12 new-client intake (LIVE-blocking): a client-resolver
    # miss / ambiguity now opens a guided in-session capture (qc_* FSM on
    # wa_equip_session) — list-then-pick existing (fixes the old >1 'be more
    # specific' dead-end) OR *new* -> company/individual -> name (seedable from
    # the typed name) -> NEAR-DUPLICATE check (fuzzy, both branches) -> [contact]
    # -> phone -> email (skippable). Creates the partner as the REP (create_uid)
    # with an E164 phone (joins the WA-9 phone_sanitized spine), email, and
    # ref='whatsapp_quote'; the quote then RESUMES in the same session with no
    # item/date re-entry (_wa12_quote_from_slots shared by the direct + resume
    # paths). No neon_finance/report change. pwa12 34/34, pwa13 15/15.
    # 17.0.1.11.0 = WA-12.2 conversational lane (Gate-1 ratified) — the LLM is a
    # TRANSLATOR at the door, extraction ONLY (never prices/approves/bypasses a
    # guard). DETERMINISTIC-FIRST: the tight parsers keep first claim; the LLM
    # runs only as a FALLBACK. Hook A (initiation) = _wa12_llm_intake_maybe,
    # invoked from handle_inbound AFTER every deterministic interceptor misses +
    # before the Copilot (sales-capable + multi-word free text -> extract
    # {client,items,date} -> deterministic match + resolve/intake + provision).
    # Hook B (in-session edit) = when q_confirm's deterministic parser misses,
    # translate the free text to ONE edit command + re-run the SAME guarded
    # _wa12_try_edit. Rides the WA provider (neon_channels.whatsapp_provider_key)
    # with a Groq fallback; relative dates resolved in Africa/Harare + echoed in
    # the (now always-visible) summary; GRACEFUL DEGRADATION — any LLM failure
    # returns None so the deterministic forms still quote. ⚠️ DECISION: hook A
    # runs one extraction per sales-user multi-word free-text turn; a non-quote
    # (intent=other) then falls to the Copilot = a 2nd call — accepted per the
    # ratified fallback design; a copilot-tool fold / cheap pre-gate is parked.
    # No neon_finance/report change. pwa12 37/37, pwa13 15/15.
    # 17.0.1.12.0 = WA-12.2 M1-M5 (unscripted proof #1 walls) + the approver-as-
    # requester addendum: M1 CONFIRM-BEFORE-DRAFT (q_items step -- extraction
    # returns ALL items, ONE confirm message lists every matched line @ the
    # ENGINE rate, stated prices are hints flagged never drafted, NO provision
    # until yes; corrections: remove/qty/date/client/re-type, complaint ->
    # repair); M5 bare intent -> q_client/q_itemreq slot-fill (never the generic
    # Copilot); M3 intake slot PRE-FILL from the brief (phone/email/contact --
    # only missing slots asked, entries acknowledged); M4 conversational repair
    # via deterministic complaint tokens + hook-B REPAIR. Addendum: the approval
    # ping no longer skips the requester (an MD/OD requester gets their own
    # Approve button; the ratified self-approval principle -- pairs with the
    # neon_finance 17.0.7.10.8 SoD scoping). pwa12 44/44, pwa13 15/15.
    "version": "17.0.1.12.0",
    "summary": "B11/WA-2 WhatsApp-to-ops: human-triggered crew "
               "assignment confirmations + reminders, two-way tap-back "
               "(Confirm / Can't make it) reusing the crew workflow. "
               "WA-3: manager readiness digest + served board. "
               "WA-6: crew + OD equipment face (finalize + warehouse "
               "checkout/check-in over WhatsApp).",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Operations",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        # commercial.job + commercial.job.crew + the decline wizard.
        "neon_jobs",
        # neon.whatsapp.message.send_template + wa_payload + phone_utils
        # + res.partner.wa_opt_out.
        "neon_channels",
    ],
    "data": [
        "security/ir.model.access.csv",
        "wizards/crew_notify_wizard_views.xml",
        "views/commercial_job_views.xml",
        "views/commercial_event_job_views.xml",
        "views/readiness_templates.xml",
        "data/ir_cron.xml",
        "data/readiness_cron.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
