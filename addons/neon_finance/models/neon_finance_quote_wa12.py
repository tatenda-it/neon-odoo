# -*- coding: utf-8 -*-
"""WA-12 — quote-by-WhatsApp provisioning + lifecycle layer on
neon.finance.quote.

The finance quote is event-job-bound: event_job_id is required, partner_id
is related through it, the event.job's commercial_job_id is required, and the
commercial.job requires partner + event_date + venue. A WhatsApp quote enquiry
has none of that, so WA-12 PROVISIONS a draft booking chain (Option 1, Tatenda
2026-06-11):

    commercial.job  (state='pending' -> NO event_job auto-cascade;
                     venue = the TBC placeholder; event_date parsed or
                     a placeholder)
      -> commercial.event.job  (is_quote_provisional=True, state='draft')
           -> neon.finance.quote  (this model)

While is_quote_provisional the event.job suppresses its three create-time
side-effects (the 9 checklists / the 'Set Lead Tech' event_created activity /
readiness alerting). On quote ACCEPTANCE the chain GRADUATES (action_accept ->
_graduate_from_quote_provisional REPLAYS those effects + flips the marker) so a
graduated job is operationally IDENTICAL to a normally-created one. A DEAD quote
(rejected / cancelled / expired) whose provisional chain has no other quotes and
no operational scope is ARCHIVED, so provisional shells never accumulate.

⚠️ Pricing is NOT here. The quote-build (line creation + the pricing-engine
recalc + the no_rule submit guard) lives in the neon_crew_comms WA-12
orchestration; this layer is purely the booking-chain provisioning + the
accept/death lifecycle hooks.
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class NeonFinanceQuoteWA12(models.Model):
    _inherit = "neon.finance.quote"

    @api.model
    def _wa12_tbc_venue(self):
        """The standing TBC placeholder venue (binding a), or empty."""
        return self.env.ref(
            "neon_finance.wa12_tbc_venue", raise_if_not_found=False)

    @api.model
    def _wa12_provision_chain(self, partner, event_date, currency,
                              salesperson, date_is_placeholder=False,
                              event_end_date=None):
        """Provision a draft booking chain for a phone quote and return the
        DRAFT quote (no lines yet — the orchestration adds + prices them).

        commercial.job stays 'pending' (so the pending->active event_job
        auto-cascade never fires) with the TBC venue; the event.job is created
        EXPLICITLY with is_quote_provisional=True (so its create-time
        side-effects are suppressed). ``event_date`` MUST be a real date (the
        caller defaults it + sets date_is_placeholder when the command carried
        none — commercial.job.event_date is required). Creates run as the
        salesperson via with_user(...).sudo() so create_uid is the real rep
        (the hard rule / WA-7 precedent), while sudo bypasses the cross-tier
        ACL the sales actor may not hold on the operational models."""
        if not partner or not partner.id:
            raise UserError(_(
                "WA-12: cannot provision a quote without a resolved client."))
        if not event_date:
            raise UserError(_(
                "WA-12: a provisional booking needs an event date "
                "(the caller must default it)."))
        venue = self._wa12_tbc_venue()
        if not venue:
            raise UserError(_(
                "WA-12: the TBC placeholder venue is missing — cannot "
                "provision a quote chain (neon_finance.wa12_tbc_venue)."))
        actor = (salesperson.id if salesperson and salesperson.id
                 else self.env.uid)
        cjob_vals = {
            "partner_id": partner.id,
            "event_date": event_date,
            "event_date_is_placeholder": bool(date_is_placeholder),
            "venue_id": venue.id,
            # state defaults 'pending' -> no event_job auto-cascade.
        }
        # Bug 1 (WA-12.6): a DATE RANGE must persist BOTH ends. event_end_date is
        # writable on commercial.job (commercial.event.job mirrors it read-only).
        # Guard end >= start so a bad range never inverts the span.
        if event_end_date and event_date and event_end_date >= event_date:
            cjob_vals["event_end_date"] = event_end_date
        cjob = self.env["commercial.job"].with_user(actor).sudo().create(
            cjob_vals)
        ejob = self.env["commercial.event.job"].with_user(actor).sudo().create({
            "commercial_job_id": cjob.id,
            "is_quote_provisional": True,
            # state defaults 'draft'; partner/venue/date related from cjob.
            # NB the free-text Venue: from the template does NOT go here --
            # venue_full_address is a COMPUTED field (from venue_id); the caller
            # appends the typed venue to client_notes instead (writable + shown).
        })
        quote = self.with_user(actor).sudo().create({
            "event_job_id": ejob.id,
            "currency_id": currency.id,
            "salesperson_id": salesperson.id,
        })
        _logger.info(
            "WA-12 provisioned quote %s on provisional chain "
            "(cjob %s / ejob %s) for %s.",
            quote.name, cjob.id, ejob.id, partner.display_name)
        return quote

    def _wa12_maybe_archive_provisional(self):
        """Binding (c): archive a DEAD quote's provisional chain when it has
        no other quotes AND no operational scope. Idempotent + defensive —
        archives ONLY when the event.job is_quote_provisional, this is its
        SOLE quote, and it has no equipment lines or crew assignments.
        event.job is archivable (active=False); commercial.job is not — it
        carries a lifecycle state, so a dead provisional chain is moved to
        'archived' (Lost). A draft/pending chain carries no movements, so the
        archive is clean."""
        for rec in self:
            ej = rec.event_job_id
            if not ej or not ej.is_quote_provisional:
                continue
            other_quotes = self.sudo().search_count([
                ("event_job_id", "=", ej.id), ("id", "!=", rec.id)])
            if other_quotes:
                continue
            cj = ej.commercial_job_id
            if ej.equipment_line_ids or (
                    cj and cj.crew_assignment_ids):
                continue
            ej.sudo().write({"active": False})
            if cj and cj.state in ("pending", "active"):
                cj.sudo().write({"state": "archived"})
            _logger.info(
                "WA-12 archived provisional chain for dead quote %s "
                "(ejob %s / cjob %s).",
                rec.name, ej.id, cj.id if cj else None)

    # ---- lifecycle hooks (super-then-extend; base sigs take no args) ----
    def action_accept(self):
        res = super().action_accept()
        # GRADUATION (binding d): the accepted chain becomes the real booking
        # — the event.job replays its deferred create-effects so it is
        # operationally identical to a normal job (no silent gap).
        for rec in self:
            ej = rec.event_job_id
            if ej and ej.is_quote_provisional:
                ej._graduate_from_quote_provisional()
        return res

    def action_reject(self):
        res = super().action_reject()
        self._wa12_maybe_archive_provisional()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._wa12_maybe_archive_provisional()
        return res

    @api.model
    def _cron_expire_quotes(self):
        # Let the base sweep walk sent->expired, then archive the provisional
        # chains of anything that just expired.
        n = super()._cron_expire_quotes()
        expired = self.sudo().search([
            ("state", "=", "expired"),
            ("event_job_id.is_quote_provisional", "=", True),
        ])
        if expired:
            expired._wa12_maybe_archive_provisional()
        return n
