# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CommercialJobCrew(models.Model):
    _name = "commercial.job.crew"
    _description = "Commercial Job Crew Assignment"
    _inherit = ["mail.thread"]
    _order = "job_id desc, role, id"

    job_id = fields.Many2one(
        "commercial.job",
        string="Commercial Job",
        required=True,
        ondelete="cascade",
        tracking=True,
    )
    # TODO (Phase 5 - Workshop): Crew identity should support
    # non-Odoo-user freelancers. Currently user_id assumes the crew
    # member has a res.users record, which only fits permanent crew
    # with Odoo logins. Phase 5 should expand to either:
    #   - Allow res.partner-based assignment (any partner record,
    #     login optional)
    #   - Or add separate partner_id field for freelancers, keep
    #     user_id for logged-in crew
    # See userMemory: crew = mix of permanent and freelance, most
    # NOT Odoo users; notified via WhatsApp (neon_channels).
    user_id = fields.Many2one(
        "res.users",
        string="Crew Member",
        required=True,
        tracking=True,
    )
    role = fields.Selection(
        [
            ("lead_tech", "Lead Tech"),
            ("tech", "Tech"),
            ("runner", "Runner"),
            ("driver", "Driver"),
            ("other", "Other"),
        ],
        string="Role",
        default="tech",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending Confirmation"),
            ("confirmed", "Confirmed"),
            ("declined", "Declined"),
        ],
        string="Confirmation",
        default="pending",
        required=True,
        tracking=True,
    )
    assigned_on = fields.Datetime(
        string="Assigned On",
        default=fields.Datetime.now,
        readonly=True,
    )
    responded_on = fields.Datetime(
        string="Responded On",
        readonly=True,
        tracking=True,
    )
    decline_reason = fields.Text(
        string="Decline Reason",
        tracking=True,
        help="Required when state = declined. Triggers MD/OD reassignment activity.",
    )
    notification_sent = fields.Boolean(
        string="Notification Sent",
        default=False,
        help="Set to True once Odoo activity + WhatsApp message dispatched. "
        "Notification logic implemented in P2.M2+.",
    )
    # P3.M1 — per-event Crew Chief flag. At most one crew assignment per
    # job may carry this. Drives event_job.crew_chief_id (computed) and
    # downstream state-transition authority in P3.M3 (Crew Chief moves
    # dispatched → in_progress → strike → returned).
    is_crew_chief = fields.Boolean(
        string="Crew Chief",
        default=False,
        tracking=True,
        help="Mark exactly one crew member as Crew Chief for this job. "
        "The Crew Chief leads the team on site and may be the Lead Tech "
        "themselves for smaller events.",
    )

    # Convenience related fields for the tree view
    job_event_date = fields.Date(
        related="job_id.event_date",
        string="Event Date",
        store=True,
    )
    job_partner_id = fields.Many2one(
        related="job_id.partner_id",
        string="Client",
        store=True,
    )

    _sql_constraints = [
        (
            "unique_user_per_job",
            "UNIQUE (job_id, user_id)",
            "This crew member is already assigned to this job.",
        ),
    ]

    @api.constrains("is_crew_chief", "job_id")
    def _check_single_crew_chief(self):
        for rec in self:
            if not rec.is_crew_chief:
                continue
            other = self.sudo().search([
                ("job_id", "=", rec.job_id.id),
                ("is_crew_chief", "=", True),
                ("id", "!=", rec.id),
            ], limit=1)
            if other:
                raise ValidationError(_(
                    "Only one Crew Chief is allowed per Commercial Job. "
                    "%(existing)s is already marked Crew Chief on "
                    "%(job)s."
                ) % {
                    "existing": other.user_id.name,
                    "job": rec.job_id.name,
                })

    def name_get(self):
        result = []
        for rec in self:
            display = f"{rec.user_id.name} ({dict(self._fields['role'].selection).get(rec.role, '')})"
            if rec.job_id:
                display = f"{rec.job_id.name} — {display}"
            result.append((rec.id, display))
        return result

    # ============================================================
    # === Crew response actions (P2.M7)
    # Real Odoo + WhatsApp dispatch lives in P2.M2 stubs and remains
    # for later. These methods are the minimum to wire the My Schedule
    # confirm/decline buttons.
    # ============================================================
    def action_confirm(self):
        for rec in self:
            rec.write({
                "state": "confirmed",
                "responded_on": fields.Datetime.now(),
            })
        return True

    def action_open_decline_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Decline Crew Assignment"),
            "res_model": "commercial.job.crew.decline.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_crew_id": self.id},
        }

    # ============================================================
    # === Capacity Gate re-trigger (P2.M4)
    # commercial.job.write() can't see O2m changes from this side, so we
    # fire the parent's gate ourselves when an assignment touches an
    # active job.
    #
    # Crew tier (post P2.M7.6) lacks write on commercial.job — they can
    # only confirm/decline their own assignment, and the gate refresh
    # is a system-driven side effect, not direct user mutation. Elevate
    # with sudo() so a crew member confirming their own assignment
    # doesn't trip the access check on the parent job.
    # ============================================================
    def _retrigger_parent_gate(self, jobs):
        for job in jobs.filtered(lambda j: j.state == "active").sudo():
            result = job._evaluate_capacity_gate()
            job._persist_gate_result(result, post_change_chatter=True)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self._retrigger_parent_gate(recs.mapped("job_id"))
        return recs

    def write(self, vals):
        affecting = {"user_id", "state", "job_id"}.intersection(vals.keys())
        old_jobs = self.mapped("job_id") if affecting else self.env["commercial.job"]
        res = super().write(vals)
        if affecting:
            self._retrigger_parent_gate(old_jobs | self.mapped("job_id"))
        return res

    def unlink(self):
        old_jobs = self.mapped("job_id")
        res = super().unlink()
        self._retrigger_parent_gate(old_jobs)
        return res
