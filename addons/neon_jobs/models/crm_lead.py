# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = "crm.lead"

    commercial_job_ids = fields.One2many(
        "commercial.job",
        "crm_lead_id",
        string="Commercial Jobs",
    )
    commercial_job_count = fields.Integer(
        string="Commercial Job Count",
        compute="_compute_commercial_job_count",
    )

    @api.depends("commercial_job_ids")
    def _compute_commercial_job_count(self):
        for rec in self:
            rec.commercial_job_count = len(rec.commercial_job_ids)

    # ============================================================
    # === Write override — CRM linkage automation (P2.M3)
    # ============================================================
    def write(self, vals):
        watching_stage = "stage_id" in vals
        watching_active = "active" in vals
        if not (watching_stage or watching_active):
            return super().write(vals)

        old_stage = {rec.id: rec.stage_id.id for rec in self} if watching_stage else {}
        old_active = {rec.id: rec.active for rec in self} if watching_active else {}

        res = super().write(vals)

        if watching_stage:
            new_stage_id = vals.get("stage_id")
            new_stage = self.env["crm.stage"].browse(new_stage_id) if new_stage_id else self.env["crm.stage"]
            if new_stage:
                for rec in self:
                    if old_stage.get(rec.id) == new_stage.id:
                        continue
                    if new_stage.is_proposal_stage:
                        rec._neon_jobs_on_proposal_stage()
                    if new_stage.is_confirmation_stage:
                        rec._neon_jobs_on_confirmation_stage()
                    # NOTE: "Won" stage (id 16) is_won=True with neither flag set.
                    # Future hook: when operational definition of completed-vs-won
                    # is clearer, wire action_complete() here.

        if watching_active:
            new_active = vals.get("active")
            for rec in self:
                if old_active.get(rec.id) and not new_active:
                    rec._neon_jobs_on_lost()

        return res

    # ============================================================
    # === Stage handlers
    # ============================================================
    def _neon_jobs_primary_sale_order(self):
        self.ensure_one()
        return self.order_ids.filtered(lambda o: o.state != "cancel").sorted(
            key=lambda o: o.create_date or fields.Datetime.now(),
            reverse=True,
        )[:1]

    def _neon_jobs_on_proposal_stage(self):
        self.ensure_one()
        if self.commercial_job_ids:
            # Idempotency: don't double-create. (T7 guard.)
            return
        if not self.partner_id:
            _logger.warning(
                "neon_jobs: crm.lead %s reached proposal stage without partner_id; "
                "skipping Commercial Job creation.", self.id,
            )
            self.message_post(body=_(
                "Commercial Job NOT created — lead has no Client (partner) set. "
                "Add a client and re-trigger by toggling the stage."
            ))
            return
        Job = self.env["commercial.job"].sudo()
        primary_order = self._neon_jobs_primary_sale_order()
        currency = (
            self.company_id.currency_id
            or self.env.company.currency_id
        )

        event_date_is_placeholder = not self.date_deadline
        event_date = self.date_deadline or fields.Date.add(fields.Date.today(), days=14)

        tbd_venue = self.env.ref("neon_jobs.partner_tbd_venue", raise_if_not_found=False)
        venue_id = tbd_venue.id if tbd_venue else False

        vals = {
            "partner_id": self.partner_id.id,
            "crm_lead_id": self.id,
            "sale_order_id": primary_order.id if primary_order else False,
            "currency_id": currency.id,
            "quoted_value": self.expected_revenue or 0.0,
            "event_date": event_date,
            "event_date_is_placeholder": event_date_is_placeholder,
            "venue_id": venue_id,
        }
        job = Job.create(vals)

        if job.needs_attention:
            self._neon_jobs_schedule_attention_activity(job)

        self.message_post(body=_(
            "Commercial Job %s created (pending) on stage transition to proposal stage."
        ) % job.name)

    def _neon_jobs_schedule_attention_activity(self, job):
        """Surface placeholder values to the salesperson as a mail.activity."""
        self.ensure_one()
        responsible = self.user_id or job.create_uid or self.env.user
        activity_type = self.env.ref(
            "mail.mail_activity_data_todo", raise_if_not_found=False,
        )
        self.env["mail.activity"].sudo().create({
            "res_model_id": self.env["ir.model"]._get("commercial.job").id,
            "res_id": job.id,
            "summary": _("Fix event date and/or venue on %s") % job.name,
            "note": job.needs_attention_reason or _("Replace placeholder values."),
            "date_deadline": fields.Date.add(fields.Date.today(), days=3),
            "user_id": responsible.id,
            "activity_type_id": activity_type.id if activity_type else False,
        })

    def _neon_jobs_on_confirmation_stage(self):
        self.ensure_one()
        pending = self.commercial_job_ids.filtered(lambda j: j.state == "pending")
        if not pending:
            _logger.info(
                "neon_jobs: crm.lead %s reached confirmation stage with no pending "
                "Commercial Job. Skipping activation (no retroactive create).", self.id,
            )
            self.message_post(body=_(
                "Lead moved to confirmation stage but no pending Commercial Job "
                "is linked. No job was activated."
            ))
            return
        pending.sudo().action_activate()
        for job in pending:
            self.message_post(body=_(
                "Commercial Job %s activated on stage transition to confirmation stage."
            ) % job.name)

    def _neon_jobs_on_lost(self):
        self.ensure_one()
        pending = self.commercial_job_ids.filtered(lambda j: j.state == "pending")
        if not pending:
            _logger.info(
                "neon_jobs: crm.lead %s archived as lost with no pending Commercial Job. "
                "Log only.", self.id,
            )
            self.message_post(body=_(
                "Lead archived as lost — no pending Commercial Job to archive."
            ))
            return
        # Propagate lead.lost_reason_id when available; jobs without loss_reason
        # need the wizard before archive succeeds.
        lead_reason = self.lost_reason_id.name if self.lost_reason_id else False
        if lead_reason:
            for job in pending:
                if not job.loss_reason:
                    job.sudo().write({"loss_reason": lead_reason})
        ready = pending.filtered(lambda j: j.loss_reason)
        if ready:
            ready.sudo().action_archive_lost()
            for job in ready:
                self.message_post(body=_(
                    "Commercial Job %s archived (lost) on lead deactivation."
                ) % job.name)
        outstanding = pending - ready
        if outstanding:
            self.message_post(body=_(
                "Open the Loss Capture wizard to record details for: %s."
            ) % ", ".join(outstanding.mapped("name")))

    # ============================================================
    # === UI helper — open the loss wizard from a lead button
    # ============================================================
    def action_open_loss_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Capture Loss Details"),
            "res_model": "commercial.job.loss.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_lead_id": self.id},
        }
