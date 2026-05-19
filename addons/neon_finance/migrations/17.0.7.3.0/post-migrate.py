# -*- coding: utf-8 -*-
"""P6.M5 post-migration -- backfill quoted_budget on existing
accepted quotes.

M5 adds quoted_budget + quoted_budget_currency_id to
commercial.event.job and wires quote.action_accept to stamp them at
acceptance time. Production / dev databases that already have quotes
in 'accepted' state (none in dev as of 2026-05-19, but the migration
is defensive) need their event_jobs backfilled so the P&L view shows
sensible quoted_budget figures from milestone go-live.

The write goes through skip_finance_notification context so the
backfill itself doesn't fire activity TODOs on accepting quotes
(there's no cost.line creation here; the notification path lives on
cost.line.create). Belt-and-braces.
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Quote = env["neon.finance.quote"]
    accepted_quotes = Quote.search([("state", "=", "accepted")])
    if not accepted_quotes:
        return
    for quote in accepted_quotes:
        if not quote.event_job_id:
            continue
        quote.event_job_id.with_context(
            skip_finance_notification=True
        ).write({
            "quoted_budget": quote.amount_total,
            "quoted_budget_currency_id": quote.currency_id.id,
        })
