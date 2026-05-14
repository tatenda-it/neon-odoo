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
    # P5.M1 (Q18) — crew identity supports both permanent users and
    # freelance contacts. partner_id is the canonical identity field
    # (always set). user_id is optional — set only for crew members
    # who have an Odoo login (permanent crew). Freelancers carry a
    # res.partner record only; WhatsApp dispatch (P5.M11+) reaches
    # them via partner_id.phone / partner_id.mobile.
    partner_id = fields.Many2one(
        "res.partner",
        string="Crew Contact",
        required=True,
        tracking=True,
        domain="[('is_company', '=', False)]",
        help="The crew member as a contact. Required. For permanent "
        "crew, this auto-populates from their user_id when you pick "
        "a user. For freelancers, leave user_id blank and pick the "
        "contact directly.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Crew User Account",
        tracking=True,
        help="Optional — set only when the crew member has an Odoo "
        "login. Freelancers leave this blank.",
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
            "unique_partner_per_job",
            "UNIQUE (job_id, partner_id)",
            "This crew contact is already assigned to this job.",
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
                existing_name = (
                    other.partner_id.name
                    or (other.user_id.name if other.user_id else _("(no name)"))
                )
                raise ValidationError(_(
                    "Only one Crew Chief is allowed per Commercial Job. "
                    "%(existing)s is already marked Crew Chief on "
                    "%(job)s."
                ) % {
                    "existing": existing_name,
                    "job": rec.job_id.name,
                })

    @api.constrains("is_crew_chief", "user_id")
    def _check_crew_chief_has_user(self):
        """P5.M1 — Crew Chief role drives commercial.event.job.crew_chief_id
        which is a Many2one to res.users. A freelancer with no user_id
        can't take that slot; raise rather than silently failing.
        """
        for rec in self:
            if rec.is_crew_chief and not rec.user_id:
                raise ValidationError(_(
                    "Crew Chief must be a registered system user "
                    "(res.users), not a freelancer-only contact. "
                    "Reassign or create a user account first."
                ))

    @api.constrains("user_id", "partner_id")
    def _check_user_partner_match(self):
        """When both user_id and partner_id are set, they must agree —
        a user_id implies its own partner_id, so allowing them to
        diverge invites silent data drift.
        """
        for rec in self:
            if rec.user_id and rec.partner_id:
                if rec.user_id.partner_id != rec.partner_id:
                    raise ValidationError(_(
                        "Crew Contact and Crew User Account must "
                        "refer to the same person. %(user)s is linked "
                        "to contact %(user_partner)s, but the Crew "
                        "Contact is set to %(partner)s."
                    ) % {
                        "user": rec.user_id.name,
                        "user_partner": rec.user_id.partner_id.name,
                        "partner": rec.partner_id.name,
                    })

    @api.onchange("user_id")
    def _onchange_user_id(self):
        """UX nicety — when the user picks a Crew User Account, snap
        Crew Contact to that user's partner_id automatically. The
        user can override afterwards but the default is right.
        """
        if self.user_id and self.user_id.partner_id:
            self.partner_id = self.user_id.partner_id

    def name_get(self):
        result = []
        for rec in self:
            # Prefer partner_id.name (always set post-P5.M1); fall
            # back to user_id.name for any straggler rows in flight.
            who = rec.partner_id.name or (
                rec.user_id.name if rec.user_id else _("(unnamed)"))
            display = f"{who} ({dict(self._fields['role'].selection).get(rec.role, '')})"
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
        # P5.M1 — programmatic create() callers that only pass
        # user_id (the pre-Q18 API) get partner_id auto-filled
        # from user.partner_id. The @api.onchange covers the form
        # UI; this covers programmatic paths and existing fixtures.
        Users = self.env["res.users"]
        for vals in vals_list:
            if not vals.get("partner_id") and vals.get("user_id"):
                user = Users.browse(vals["user_id"])
                if user.partner_id:
                    vals["partner_id"] = user.partner_id.id
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
