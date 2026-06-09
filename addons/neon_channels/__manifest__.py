{
    'name': 'Neon Channels',
    # 17.0.1.2.0 = WhatsApp (Meta Cloud API) + Twilio transport + bot.user.
    # 17.0.1.3.0 = B11/WA-0 rails: WhatsApp Copilot (resolution + scope
    # intersection reusing neon_ai_core), single-call agent (Gemini
    # default), two-phase guardrail via cta_url confirm-in-Odoo, no money
    # tools, X-Hub-Signature-256 verification, verify-token-from-config,
    # Twilio identity converged on neon.bot.user (authorised_numbers
    # deprecated, data retained). DEPENDS on neon_ai_core now.
    # 17.0.1.4.0 = B11/WA-1: stateful WhatsApp Copilot (conversation
    # memory, last 10 msgs / 30 min per sender, current inbound excluded)
    # + single-source phone normalization (phone_utils.to_e164) applied at
    # the handle_inbound boundary -> canonical E.164 stored; resolve() +
    # history match + lead-intake all canonical, raw `from` kept for the
    # outbound SEND. Method-only (no schema/data). Interactive renderer
    # (buttons/list/cards) remains DEFERRED.
    # 17.0.1.5.0 = B11/WA-1: interactive renderer (the deferred half).
    # Outbound reply-buttons + list senders (send_buttons / send_list)
    # with a MANDATORY text fallback (send_interactive_or_text); a new
    # HMAC-signed tap-back payload scheme (wa_payload) + handle_tap
    # router; Confirm/Cancel taps reuse the EXISTING write.log
    # propose->confirm->execute path (execute under the resolved user's
    # identity, ACL fires); <=3 stage picker; pick-one list from
    # list-producing read tools (get_my_pipeline / get_jobs_this_week);
    # capability menu from whatsapp_tools. Code-driven triggering; money
    # tools structurally unreachable via any interactive path.
    # Method-only (no schema/data; reuses database.secret +
    # action_wa_pending_writes).
    # 17.0.1.6.0 = B11/WA-2 channel primitives: send_template (proactive
    # Meta TEMPLATE send, body params + quick-reply payload buttons OR a
    # URL button, message_type='template' audit); res.partner.wa_opt_out
    # (+date) opt-out flag honoured by send_template; STOP/START keyword
    # intercept in handle_inbound (any sender, before routing); two crew
    # tap-back intents added to wa_payload.INTENTS (crew_confirm /
    # crew_decline -- routed by the neon_crew_comms bridge). Adds a
    # res.partner column -> -u + snapshot.
    # 17.0.1.7.0 = B11/WA-4 dual-role lens routing: for users holding 2+
    # role-tiers, route each turn to the lens matching the message INTENT
    # (rule-based finance/HR classifier + explicit override + ambiguous
    # ->2-button ask reusing the WA-1 renderer; new 'lens' wa_payload
    # intent + _tap_lens). run_turn gains an optional variant override.
    # Routing only ever picks among lenses the user already holds (never
    # unlocks a tool their groups don't grant); single-role users
    # unchanged. Method-only (no schema/data).
    # 17.0.1.8.0 = B11/WA-5 client intake lane (FIRST client-facing
    # surface). An UNMAPPED sender now enters a STRUCTURALLY tool-less
    # client lane (finite state machine over canned strings + one raw
    # crm.lead create; no LLM, no Copilot, no tool registry) instead of
    # the bare raw-lead intake: greet + 3-button menu, canned service
    # info, quote capture, pricing/bespoke/complaint/"talk to team"
    # handoff. PART 2 (mapped staff): client lead -> notify the escalation
    # target (login-resolved, single backstop) with an Assign button ->
    # WA-1 list of group_neon_finance_sales ∩ bot.user (minus escalation
    # target + OD/owner, both by login -- a superuser-salesperson stays
    # assignable) -> set lead.user_id -> notify assignee -> "I'm not free"
    # clears user_id + bounces to escalation (never auto-reassign, never
    # unowned; Odoo activity fallback). New 'assign_open'/'assign_pick'/
    # 'assignee_decline' wa_payload intents + _wa5_handle_assign_tap.
    # NET-NEW model neon.wa.client.session + WhatsApp crm.tag/utm
    # source+medium + escalation-login config param -> -u + snapshot.
    # 17.0.1.9.0 = B11/WA-5.1 (window-aware staff escalation) + WA-5.0
    # (robustness). Staff escalation/assignee/bounce notifies are now
    # WINDOW-AWARE: recipient's 24h window open -> free-form interactive
    # (as before); closed -> a UTILITY template (wa5_lead_handoff /
    # wa5_lead_assigned, Design Y: name+summary+quick-reply, opt-out
    # respected) that re-opens the window; the human-routed Odoo activity
    # ALWAYS lands. Template quick-reply taps (inbound type='button')
    # route through handle_tap. WA-5.0: escalate-ONCE guard (an unowned
    # lead no longer re-escalates on every client message -> chatter
    # append + ack); assign_pick idempotent (repeat tap = no-op ack);
    # decline split-states (unowned / different-owner / current-owner)
    # with correct "sent back to the team" copy; html2plaintext on every
    # WhatsApp body + template summary (no leaked <p>); audit records the
    # real path/result (no blanket state='sent'). Method-only (no
    # schema/data; the 2 templates live in Meta).
    # 17.0.1.10.0 = B11/WA-5.2 debounced re-handoff: a returning client's
    # follow-up on an EXISTING lead now appends to the chatter AND
    # re-notifies the human handling it (assignee if owned, else
    # re-escalate Munashe) -- DEBOUNCED to at most once per
    # wa5_renotify_minutes (default 10), so the rapid triple-fire stays
    # suppressed but a genuine later follow-up alerts a human (the WA-5.1
    # escalate-once over-correction). Honest client ack (only promise
    # contact when a human was (re)notified or already owns the lead).
    # Chatter now uses markupsafe.Markup so <b>/<br/> render + the client
    # text is auto-escaped (fixes the &lt;b&gt; leak since WA-5). NET-NEW
    # neon.wa.client.session.last_notify column + wa5_renotify_minutes
    # param -> -u + snapshot. No new Meta template (reuses the 2 Active).
    # 17.0.1.11.0 = B11/WA-5.3 assignee three-button consolidation +
    # HARD idempotency lock. The in-window assignee message is now THREE
    # reply-buttons [Chat with client] [Open in Odoo] [I'm not free]: Chat
    # /Odoo are reply-buttons that REPLY with the wa.me / Odoo deep-link on
    # tap (a reply-button can't BE a URL -- D3), decline is unchanged. New
    # assignee_chat / assignee_odoo wa_payload intents + handlers. HARD
    # lock: a per-lead pg_try_advisory_xact_lock serializes concurrent
    # taps / webhook re-entry so assign / decline / re-notify each fire
    # EXACTLY once (kills any duplicate-message flood). Decline-once: the
    # first decline by the current owner always replies "sent it back to
    # the team" + unassigns + notifies Munashe ONCE (never "already
    # declined" on a first tap). Method-only (no schema/data; the cold-
    # window template is unchanged, still the Meta-approved single
    # quick-reply).
    # 17.0.1.12.0 = B11/WA-5.4 prod-fix. ROOT CAUSE (WA-5.3 prod): the
    # crm.lead.user_id write fired Odoo's NATIVE CRM assignment
    # notification, which -- under the auth='public' webhook env -- read
    # crm.lead as the Public user at the deferred flush -> AccessError ->
    # HTTP 403 -> the whole request ROLLED BACK (user_id never persisted;
    # each assign_pick re-assigned + re-acked, Meta retried on 403 -> x5;
    # the later decline read None -> "already declined"). FIX 1+2:
    # _wa5_set_owner writes user_id with tracking_disable +
    # mail_auto_subscribe_no_notify + mail_create_nolog (no native notify
    # -> no public read -> no 403 -> user_id persists), on BOTH the
    # assign_pick + decline writes. DEFENSE-IN-DEPTH: the webhook
    # controller now flush_all()s inside its try (catch + rollback + clean
    # 200) so a deferred error is never a silent 403/rollback + Meta-retry
    # storm. FIX 3a: the manager/escalation message is a clean short body +
    # the single Assign button (raw wa.me/Odoo URLs removed). Method-only.
    # WA-5.5 (17.0.1.13.0): the WA-5.4 flush ran in the PUBLIC webhook env --
    # a deferred crm.lead recompute -> AccessError -> the rollback UNDID the
    # assignment + audit row + advisory lock while the Meta sends had already
    # left, so assignments were silently lost and every Meta re-delivery
    # re-sent (unaudited). Fix: request.env(su=True).flush_all() so the
    # deferred recompute runs as superuser (matching handle_inbound's sudo).
    # Method-only.
    # 17.0.1.14.0 = B11/WA-5.6: the MANAGER (escalation) in-window message
    # now renders the SAME THREE reply-buttons as the assignee --
    # [Chat with client] [Open in Odoo] [Assign salesperson] (new
    # escalation_chat / escalation_odoo intents reusing the lead-based link
    # reply; assign_open = the existing assignee list, unchanged). Applied
    # to BOTH _wa5_notify_escalation + the decline-bounce. Client number
    # kept in the body. The assignee interactive path is untouched. Cold-
    # window templates keep their single approved quick-reply (>3-button
    # mix is an in-window-only feature -- known cold-template limit).
    # Method-only. (Cold wa5_lead_assigned enrichment -- client number +
    # wa.me URL button -- is a SEPARATE Meta-template resubmission, pending
    # Tatenda's verification of the proposed structure.)
    # 17.0.1.15.0 = B11/WA-5.7: wire the cold-window assignee path to the
    # now Meta-ACTIVE wa5_lead_assigned -- which is 3-param (name, summary,
    # CLIENT PHONE) + the "I'm not free" quick-reply, NO URL button (wa.me
    # URL buttons are Meta-banned, so dropped). _wa5_staff_notify gains
    # template_extra_params (appended in declared order); _wa5_notify_
    # assignee + _wa5_notify_followup_assignee pass [client phone] as the
    # 3rd body param so a cold assignee gets the client number in the body.
    # Param count is a contract (132000). No send_template URL enhancement
    # needed (URL button dropped). Method-only.
    # 17.0.1.16.0 = B11/WA-5 TEST-INFRA: reset a DESIGNATED standing test
    # number so the SAME number can re-run the whole client intake flow
    # (greeting -> quote -> handoff -> assign -> decline) as a "fresh"
    # client, instead of hunting for a new UNMAPPED number each run. New
    # wa5_test_numbers config param (CSV of E.164; EMPTY default) DESIGNATES
    # the test number(s); the reset REFUSES anything not listed so it can
    # never wipe a real client. Every lead a designated number creates is
    # stamped a new TEST-CLIENT crm.tag (auto, in _wa5_create_client_lead)
    # for easy find + purge. _wa5_reset_test_client(phone): deletes the
    # TEST-CLIENT-tagged leads (double-gated on phone AND tag), RESETS the
    # intake session in place (step=greeted, lead_id/last_notify cleared --
    # the model is perm_unlink=0), and purges the number's own WhatsApp
    # audit rows. One-click UI: a base.group_system server action ("Reset
    # WA-5 Test Client") bound to the session list resets all designated
    # numbers + shows a notification. Shell: env['neon.whatsapp.message']
    # ._wa5_reset_test_client("+263..."). Adds a crm.tag + 2 data records +
    # a server action -> -u + snapshot. No new tool / intent / RBAC change.
    'version': '17.0.1.16.0',
    'summary': 'WhatsApp + Twilio integration + WA-0 role-aware WhatsApp '
               'Copilot rails (on neon_ai_core)',
    'author': 'Tatenda Ngairongwe',
    'website': 'https://neonhiring.com',
    'category': 'CRM',
    # neon_ai_core: shared AI engine (tool registry, chat adapters incl.
    # Gemini, two-phase write guardrail, role resolver). It brings
    # neon_core (tier groups) transitively. No neon_jobs dep -- the
    # business tools register into the shared registry globally; the
    # confirm act_window is gated by neon_core tier groups only.
    'depends': ['base', 'crm', 'mail', 'utm', 'neon_ai_core'],
    'data': [
        'security/ir.model.access.csv',
        # WA-0 data: provider row + WA provider selection. Load before
        # views (the confirm act_window references neon_core groups via
        # the neon_ai_core->neon_core dependency).
        'data/gemini_provider_seed.xml',
        'data/wa_config_params.xml',
        # WA-5: WhatsApp crm.tag + utm source/medium + escalation login.
        'data/wa5_client_data.xml',
        # WA-5 test-infra: the one-click "Reset WA-5 Test Client" server
        # action (references model_neon_wa_client_session, so AFTER the
        # model is loaded; calls a method at run-time, not load-time).
        'data/wa5_test_reset_action.xml',
        'views/whatsapp_config_views.xml',
        'views/twilio_config_views.xml',
        'views/bot_user_views.xml',
        'views/login_template.xml',
        # WA-0 confirm-in-Odoo deep-link target (form + act_window).
        'views/whatsapp_writelog_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
