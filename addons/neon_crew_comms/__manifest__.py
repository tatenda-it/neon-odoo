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
    "version": "17.0.1.1.0",
    "summary": "B11/WA-2 WhatsApp-to-ops: human-triggered crew "
               "assignment confirmations + reminders, two-way tap-back "
               "(Confirm / Can't make it) reusing the crew workflow. "
               "WA-3: manager readiness digest + served board.",
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
        "views/readiness_templates.xml",
        "data/ir_cron.xml",
        "data/readiness_cron.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
