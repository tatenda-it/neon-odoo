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
    # 17.0.1.13.0 = WA-12.2 F1-F8 (unscripted proof #2 walls + the F8 ruling):
    # F1 echo==draft (pairs with neon_finance 17.0.7.11.0 engine-gate fix);
    # F2 matcher exact-name-first + per-item confidence (weak hits -> per-item
    # pick in the echo, never silently drafted; confidence counts meaningful
    # word-start tokens only); F3 q_items natural corrections (per-item
    # `replace <old> = <new>` det + LLM-translated; show/preview != yes); F4
    # multi-item at q_confirm routes through EXTRACTION (never a single `add`
    # parse); F5 brief address -> partner street + event subject -> event-job
    # client notes; F6 greeting mid-session -> resume/cancel offer; F7 multi-
    # word cancels (verb + filler only; 'delete the X line' never cancels;
    # 'no' at qc_dupe stays 'add new'); F8 rep-priced unpriced items (stated
    # price -> manual line ONLY where no catalogue rate resolves, loudly
    # flagged in echo/summary/ping/PDF, `price <item> <amt>` at q_items,
    # guard EVOLVES to 'no silent zero/no invented rate' -- a real-rate manual
    # line passes; engine items keep stated prices as hints). Extraction
    # schema + few-shots drawn from the REAL proof briefs (552/574).
    # pwa12 53/53; pwa13 15/15, pwa6 58/58, pwa8 33/33 (shared-matcher
    # regressions green). + adversarial-review fixes (12 confirmed): F2
    # confidence gate now enforced at the THREE remaining consumers (q_itemreq,
    # direct Quote: -> confirm gate, q_confirm `add`) so a weak token-overlap
    # never drafts as a confident line (MATCH-1/FSM-3); q_items re-typed weak
    # items surface as picks AFTER the LLM translate (MATCH-2/FSM-5, ordered so
    # a conversational correction still reaches translate); ambiguous
    # qty/price/replace tokens refuse with the colliding names (FSM-4);
    # apply_multi reports only true adds + routes a dup's qty to the existing
    # line (MATCH-3/FSM-6); 'resume' (a Meta opt-in word) replaced by the
    # advertised '*continue*' (FSM-1); 'no' at qc_email skips-email not cancels
    # (FSM-2); greeting check skipped at q_client so a greeting-named client
    # resolves (FSM-8); translated yes/cancel handled, submit stays explicit
    # (FSM-7); the F5 event-name write is actor-honest (FSM-9). pwa12 60/60.
    # 17.0.1.14.0 = M-A..M-C matcher overhaul (proof #3 — the systemic matcher
    # failure). _wa6_match_one is now FAMILY-SCOPED & dimension-aware: never
    # cross-category (a "screen" resolves only within the visual/LED-SCREEN
    # family, never a BOOTH); exact dimensional match ("6m x 2m" == the
    # "6M X 2M LED SCREEN" product after case/x/spacing normalisation), nearest
    # size only when a size isn't stocked; family derived from the NAME when the
    # product carries no equipment_category_id (the catalogue-load gap) or from
    # an LLM category hint. parse_qty no longer reads a dimension ("3 x 2") as a
    # qty. Synonyms: bare "led" removed from visual (shared w/ lighting cans);
    # +molefay/can/zoom/rgbwauv (lighting), +totem (trussing). M-B catalogue
    # discovery ("what screens do you have" -> the family pick-list by exact
    # name); M-C correction lead-in strip ("no, it's an LED screen" re-searches,
    # never 'none'). M-E role fallback already in place (partner function ->
    # group lens). pwa12 62/62; pwa6 58/58, pwa8 33/33, pwa13 15/15.
    # ⚠️ BASELINE: a superseding Resolver v2 (re-map equipment_category_id from
    # Robin's CSV `category` column, not keyword-guessing) is incoming.
    # 17.0.1.15.0: Resolver v2 SUPPORT (a) — neon.equipment.alias store (UI-
    # reviewable team-slang map; only CONFIRMED rows applied). No matcher wiring
    # yet — the funnel + golden set follow once Robin confirms the seeded rows.
    # 17.0.1.16.0: Resolver v2 FUNNEL — _wa6_match_one rewritten S0-S8 (normalise
    # → CONFIRMED-alias expand → family → dimensional/casing-dup → exact →
    # pg_trgm category-scoped rank → grounded LLM shortlist → discovery). New
    # _r2_* helpers; bare-leading-count qty guard; alias cache-bust on write.
    # Byte-compat return dict. Money gate: _wa12_run_price now confidence-gated.
    # 17.0.1.16.1: live-wire fixes — single-item matching EXCLUDES the Packages
    # family (a bare "smoke machine" no longer leaks to a DJ package); confirmed
    # product-alias short-circuit tolerates a generic-noun residue ("smoke
    # machine" -> the confirmed smoke product).
    # 17.0.1.17.0: WA-12.3 pick/correct interaction layer (B tappable pick +
    # variant framing, C edit-by-line-number, D conversational multi-correction).
    # Buffer schema v3 (one ordered `lines` list, stable lid, single pending
    # pick). Matcher byte-UNCHANGED; the variant signal is derived builder-side.
    # 17.0.1.18.0: WA-12.4 ONE-ITEM STEPPER (fixes Robin's "where do I tap" →
    # matched-as-item regression). Client-before-items, then resolve items ONE
    # at a time (✅+[✓/✗] for confident, LIST for ambiguous/family, counter
    # "① of N"); FOCUSED sub-state (all input applies to the cursor item, a
    # question/unrecognised → HELP+reshow NEVER a new line); finalize → UNCHANGED
    # draft path (totals/VAT/discount/intake intact). PACKAGES scoping: single-
    # item words exclude Packages; "package"/a package name scopes within (one
    # per-day line, parity unchanged). Buffer v4 (per-line state + cursor + focus
    # + seq). intents wa12_ok/wa12_change. C/D edits relocated POST-DRAFT.
    # 17.0.1.18.1: WA-12.5 Stage A live-wire fixes — item-drop deterministic net
    # (_wa12_match_slot_items re-splits each LLM item name); post-draft QUESTION
    # guard -> plain HELP (never an edit); plain-language repair/help (no command
    # syntax). Wire-level golden harness pwa12_5 5/5.
    # 17.0.1.19.0: WA-12.6 STRUCTURED one-at-a-time collection (NEW SPINE; drops
    # whole-brief LLM extraction as the failure point). Deterministic FSM:
    # client(q_client/qc_*) -> qs_event (date/RANGE -> duration_days, the MONEY
    # fix) -> qs_item (ONE item at a time, category-scoped packages-excluded list
    # / ✓✗ card / custom line) -> q_confirm review. A dump resets to step 1 (no
    # bulk-parse); client locked. pwa12_6 wire harness 7/7. NOT a complete cutover
    # yet (old pwa12 flow suite + review-step wire-test pending). NOT deployed.
    # 17.0.1.20.0: WA-12.6 QUOTE-BY-TEMPLATE (PRIMARY collection) + date fixes.
    # PART A: a quote trigger ("Quote a client" tap / "quote") now sends a
    # copy-fill TEMPLATE skeleton; the rep fills + sends ONE message, parsed by
    # _wa12_template_extract_fields (deterministic labels + synonyms; LLM
    # extractor is the forgiving fallback) -> the EXISTING matcher +
    # _wa12_quote_from_slots -> a ONE-reply draft. UNMATCHED items FLAG as
    # lettered pending picks (A/B/C) -> never dead-end; submit BLOCKED until
    # each is set ("A = <item>" / a custom "@ $price") or dropped ("drop A").
    # The structured stepper stays as the FALLBACK (inline "Quote: <brief>",
    # "step"/"guide me", or an unparseable reply). Contact/Phone/Email on the
    # template = new-client intake in one message (company + child contact).
    # PART B Bug 1: a DATE RANGE persists BOTH ends -- end_date_txt rides extras
    # through the SHARED _wa12_quote_from_slots -> _wa12_provision_chain (so the
    # stepper path persists it too, not just the template). Venue: free-text ->
    # event job client_notes (venue_full_address is COMPUTED, not writable).
    # Days (chargeable duration_days) stays separate from the event date span.
    # Carries the held 19.3 default-align. Adversarial review (4 lenses,
    # verify-each) -> 6 confirmed + fixed: #1 HIGH (all-unmatched zero-line
    # template billed days=1 not the Days value -> wa12_days buffered + zero-line
    # recalc guarded); #2 MED (unfilled "- 1 x" skeleton lines became phantom
    # flags -> bare-qty-prefix rejected); #3 LOW (matched no-rate "@ $price" not
    # promoted -> F8 promotion added to the template path); #4 LOW (ambiguous
    # label synonyms false-positived casual prose -> for/subject/when/place/
    # number/mail dropped); #5 NIT (>26 unmatched silently dropped -> visible
    # overflow sentinel keeps submit blocked). #6 NIT (1-char "drop A" vs a
    # 1-char line-remove token) -> LOW polish backlog.
    # 17.0.1.19.3: provider-default alignment (no quote-spine change). The WA-12
    # extraction lane (_wa12_llm_chat) read-defaulted the
    # neon_channels.whatsapp_provider_key param to "groq" while _wa_provider /
    # handle_inbound / the wa_config_params seed default to "google" (Gemini).
    # Aligned to "google" so a DELETED param can't split the lanes (Copilot on
    # Gemini, WA-12 on Groq). ZERO runtime effect while the param is set; the
    # live flip is the prod System Parameter ("groq"->"google"), done in Settings.
    # 17.0.1.19.2: WA-12.6 review polish. (B) the q_confirm fall-through no
    # longer prints a command-syntax cheat sheet -> plain language only. (C)
    # WHOLE-QUOTE discount + target-total at the review step: "discount <amt>"
    # / "total <amt>" (default VAT-INCLUSIVE so the displayed Total lands exactly
    # on target) and an "ex vat"/"on goods" override (ex-VAT goods basis, VAT on
    # top); distributed as a uniform per-line discount_pct; quote.wa12_discount_
    # note labels the basis on the summary/PDF; the note is cleared on any
    # per-line edit (no stale label). (A) the deterministic Hello/menu "Quote a
    # client" row taps into begin_structured (new wa12_start sentinel +
    # _wa12_handle_start_tap, re-checks _wa12_can_quote).
    # 17.0.1.19.1: WA-12.6 CUTOVER complete + refinements. (a) DURATION: a date
    # RANGE never auto-assumes the day count -> bot ASKS "how many chargeable
    # days?" (Robin's billing convention; await_days FSM); _wa12_parse_event_dates
    # now returns is_range. (b) STRUCTURED new-client intake (qc_*) resumes INTO
    # qs_event (not the old item path). (c) no-command-syntax: dropped the
    # "(e.g. `2x RGB LED CAN`)" template from the bare-intent reply. (d) old
    # pwa12 flow suite reworked/retired to the structured spine (T-48/T-58 = dead
    # convo lane; T-43r/T-45r re-prove the no-cat-rule $ + rep-priced surfaces);
    # review-step MONEY wire-test hardened (VAT 15% exact + discount math exact)
    # + no-command-syntax sweep. pwa12 61/61, pwa12_6 11/11.
    # 17.0.1.20.2: custom-line "CUSTOM" DOUBLING fix. The "add custom <desc> at
    # <amt>" handler baked "[CUSTOM] " into the stored line NAME, while the PDF
    # template ALSO renders a line_type-driven CUSTOM badge -> "CUSTOM [CUSTOM]
    # <desc>". Now the name stores the CLEAN description; the SINGLE marker is
    # line_type-driven (PDF CUSTOM badge + the draft tag, changed from "[CUSTOM]"
    # to "✍️ " so no "[CUSTOM]" text appears anywhere). _wa12_build_lines was
    # already clean; only the add-custom path + the draft tag changed.
    # 17.0.1.20.1: the q_confirm REVIEW/draft reply renders as a WhatsApp
    # interactive 3-button message [✏️ Change a line][➕ Add item][👁 Preview]
    # (was plain text; the menu already shipped interactive). Submit stays a
    # TYPED 'yes' (deliberate money-commit); discount/VAT stay typed values. Taps
    # map to the EXISTING handlers (preview = the PDF; change/add = the plain
    # prompt for the <n> = <item> / add <item> grammar) -- no new edit logic.
    # _wa6_send_buttons falls back to numbered text if the interactive send
    # fails (menu resilience pattern). 3 new wa_payload intents (wa12_rv_*).
    "version": "17.0.1.20.2",
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
        "views/neon_equipment_alias_views.xml",
        "views/readiness_templates.xml",
        "data/ir_cron.xml",
        "data/readiness_cron.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
