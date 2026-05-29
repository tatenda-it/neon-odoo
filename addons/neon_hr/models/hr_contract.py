# -*- coding: utf-8 -*-
"""Neon HR — hr.contract extension + contract templates.

Adds, on top of the native hr.contract (which already provides
``date_start`` / ``date_end`` / ``wage`` / ``state`` / ``trial_date_end``):

* per-contract pay fields (per-job amount, commission %) — ⚠️ these
  vary by person/grade (Q5) so they are per-contract, NOT global;
* a configurable, legal-flaggable notice period (Q/S6);
* a renewal state machine (Q7-9) with validated transitions;
* the contract-expiry Action Centre wiring (reuses neon_jobs
  action.centre.mixin — see models/action_centre_ext.py).

Plus a small ``neon.hr.contract.template`` model (3 seeded) that
carries starting defaults; applying a template copies its values into
the contract, where they remain editable (per-contract authority).
"""
import logging
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# The 7 confirmed category/contract-type codes. Selection here mirrors
# the neon.hr.category seed codes so a contract's type aligns with its
# employee's category vocabulary.
NEON_CONTRACT_TYPE_SELECTION = [
    ("permanent", "Permanent"),
    ("fixed_term", "Fixed Term"),
    ("employed_technician", "Employed Technician"),
    ("freelance_technician", "Freelance Technician"),
    ("casual_crew", "Casual Crew"),
    ("contractor", "Contractor"),
    ("driver", "Driver"),
]

# Renewal state machine (Q7-9). Keys are source states; values are the
# set of states reachable from them. Anything not listed is blocked.
RENEWAL_TRANSITIONS = {
    "not_reviewed": ["renewal_under_review"],
    "renewal_under_review": ["renew", "do_not_renew"],
    "renew": ["renewal_letter_issued"],
    "do_not_renew": ["non_renewal_notice_issued"],
    "renewal_letter_issued": ["new_contract_signed", "expired"],
    "non_renewal_notice_issued": ["expired"],
    "new_contract_signed": [],
    "expired": [],
}


class NeonHrContractTemplate(models.Model):
    _name = "neon.hr.contract.template"
    _description = "Neon HR Contract Template"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    neon_contract_type = fields.Selection(
        NEON_CONTRACT_TYPE_SELECTION, required=True,
    )
    category_id = fields.Many2one("neon.hr.category")
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id.id,
    )
    default_wage = fields.Monetary(
        currency_field="currency_id",
        help="Starting monthly salary; copied into the contract wage "
        "where it remains editable per person/grade (Q5).",
    )
    default_per_job_amount = fields.Monetary(currency_field="currency_id")
    default_commission_percent = fields.Float(string="Default Commission %")
    # ⚠️ Notice default: permanent template = 30 days. Non-permanent
    # templates leave this flagged for legal sign-off rather than
    # inventing a 3-month value (Q/S6).
    default_notice_days = fields.Integer(default=30)
    notice_flagged = fields.Boolean(
        string="Notice Pending Legal Sign-off")
    description = fields.Text()


class HrContract(models.Model):
    # ⚠️ DECISION: multi-_inherit — extend the existing hr.contract AND
    # mix in neon_jobs' action.centre.mixin so a contract can raise its
    # own Action Centre items. hr.contract already brings mail.thread.
    # NOTE: when _inherit is a LIST that mixes an existing model with a
    # mixin, _name MUST be set to the target model — otherwise Odoo
    # treats the class name as a (new, invalid) model name.
    _name = "hr.contract"
    _inherit = ["hr.contract", "action.centre.mixin"]

    neon_contract_type = fields.Selection(
        NEON_CONTRACT_TYPE_SELECTION, string="Neon Contract Type",
        tracking=True,
    )
    template_id = fields.Many2one(
        "neon.hr.contract.template", string="Template",
        help="Applying a template copies its starting defaults into "
        "this contract; the values remain editable here.",
    )

    # ----- Per-contract pay (Q5 — NOT global constants) -------------
    per_job_amount = fields.Monetary(
        currency_field="currency_id",
        help="Per-job / per-event amount. Varies by person and grade "
        "— stored on the contract, never as a global constant.",
    )
    commission_percent = fields.Float(string="Commission %")

    # ----- Notice period (Q/S6) -------------------------------------
    notice_period_days = fields.Integer(
        string="Notice Period (days)",
        help="Permanent = 30 (legally settled). Other categories are "
        "configurable and flagged for legal sign-off — NOT defaulted "
        "to 3 months.",
    )
    notice_period_flagged_for_legal = fields.Boolean(
        string="Notice Pending Legal Sign-off",
        help="⚠️ Set for every non-permanent contract, and for any "
        "contract with a trial (probation) period — the notice value "
        "is a placeholder awaiting legal confirmation. NOTE the "
        "probation-on-probation contradiction: a notice period during "
        "an already-probationary term cannot sensibly equal the "
        "3-month probation itself; legal must resolve this.",
    )

    # ----- Renewal state machine (Q7-9) -----------------------------
    renewal_state = fields.Selection(
        [("not_reviewed", "Not Reviewed"),
         ("renewal_under_review", "Renewal Under Review"),
         ("renew", "Decision: Renew"),
         ("do_not_renew", "Decision: Do Not Renew"),
         ("renewal_letter_issued", "Renewal Letter Issued"),
         ("non_renewal_notice_issued", "Non-Renewal Notice Issued"),
         ("new_contract_signed", "New Contract Signed"),
         ("expired", "Expired")],
        default="not_reviewed", tracking=True, required=True,
        string="Renewal Stage",
    )
    renewal_owner_id = fields.Many2one(
        "res.users", string="Renewal Owner", tracking=True,
    )
    # Open item (Q10/S5): structured per-role criteria are deferred;
    # for now a free-text recommendation + evidence field.
    renewal_recommendation = fields.Text(
        string="Renewal Recommendation & Evidence",
        help="Free-text recommendation and supporting evidence. "
        "Structured per-role criteria are deferred to a later "
        "release (Q10/S5 unanswered).",
    )

    # ----- Expiry surfacing -----------------------------------------
    neon_expiry_state = fields.Selection(
        [("no_end", "No End Date"),
         ("future", "Future"),
         ("expiring", "Expiring (≤30d)"),
         ("expired_active", "Expired but Active")],
        compute="_compute_neon_expiry_state", store=True,
        string="Expiry State",
    )

    # ----------------------------------------------------------------
    @api.depends("date_end", "state")
    def _compute_neon_expiry_state(self):
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=30)
        for rec in self:
            if not rec.date_end:
                rec.neon_expiry_state = "no_end"
            elif rec.state == "open" and rec.date_end < today:
                rec.neon_expiry_state = "expired_active"
            elif rec.date_end <= horizon:
                rec.neon_expiry_state = "expiring"
            else:
                rec.neon_expiry_state = "future"

    @api.onchange("template_id")
    def _onchange_template_id(self):
        tpl = self.template_id
        if not tpl:
            return
        self.neon_contract_type = tpl.neon_contract_type
        if tpl.default_wage:
            self.wage = tpl.default_wage
        self.per_job_amount = tpl.default_per_job_amount
        self.commission_percent = tpl.default_commission_percent
        self.notice_period_days = tpl.default_notice_days
        self.notice_period_flagged_for_legal = tpl.notice_flagged

    @api.onchange("neon_contract_type", "trial_date_end")
    def _onchange_notice_flag(self):
        """Permanent with no probation = settled (not flagged).
        Everything else is flagged for legal sign-off — including any
        contract carrying a trial period (probation contradiction)."""
        if self.neon_contract_type == "permanent" and not self.trial_date_end:
            self.notice_period_flagged_for_legal = False
            if not self.notice_period_days:
                self.notice_period_days = 30
        else:
            self.notice_period_flagged_for_legal = True

    # ----- Renewal transitions --------------------------------------
    def _set_renewal_state(self, target):
        for rec in self:
            allowed = RENEWAL_TRANSITIONS.get(rec.renewal_state, [])
            if target not in allowed:
                raise UserError(_(
                    "Invalid renewal transition: %(src)s → %(dst)s. "
                    "Allowed from %(src)s: %(allowed)s."
                ) % {
                    "src": rec.renewal_state,
                    "dst": target,
                    "allowed": ", ".join(allowed) or _("(none — terminal)"),
                })
            rec.renewal_state = target
            rec.message_post(body=_(
                "Renewal stage moved to %(stage)s by %(user)s."
            ) % {"stage": target, "user": self.env.user.name})
            # Courtesy: when the renewal resolves, clear the open
            # expiry task so HR's Action Centre doesn't keep nagging.
            if target in ("new_contract_signed", "expired"):
                rec._action_centre_close_items(
                    "contract_expiry_30days", force=True)
        return True

    def action_renewal_start_review(self):
        return self._set_renewal_state("renewal_under_review")

    def action_renewal_decide_renew(self):
        return self._set_renewal_state("renew")

    def action_renewal_decide_not_renew(self):
        return self._set_renewal_state("do_not_renew")

    def action_renewal_issue_letter(self):
        return self._set_renewal_state("renewal_letter_issued")

    def action_renewal_issue_non_renewal(self):
        return self._set_renewal_state("non_renewal_notice_issued")

    def action_renewal_new_contract_signed(self):
        return self._set_renewal_state("new_contract_signed")

    def action_renewal_mark_expired(self):
        return self._set_renewal_state("expired")

    # ----- Contract-expiry Action Centre cron (Q7-9) ----------------
    @api.model
    def _neon_hr_alert_assignee(self):
        """Resolve the single Admin/HR person for explicit assignment.
        Falls back to empty (then the trigger config's primary_role =
        'manager' surfaces the item to OD/MD)."""
        grp = self.env.ref(
            "neon_hr.group_neon_hr_admin", raise_if_not_found=False)
        if not grp:
            return self.env["res.users"]
        root = self.env.ref("base.user_root", raise_if_not_found=False)
        domain = [("groups_id", "in", grp.id), ("active", "=", True)]
        if root:
            domain.append(("id", "!=", root.id))
        return self.env["res.users"].sudo().search(
            domain, order="id asc", limit=1)

    @api.model
    def _cron_contract_expiry_scan(self):
        """Daily — raise/refresh a contract_expiry_30days Action Centre
        item for every OPEN contract whose end date is within 30 days,
        AND for contracts already past their end date but still Active
        (expired-but-Active). Idempotent: the mixin won't duplicate an
        open item for the same (trigger, contract).

        Also nudges document expiry states so they stay fresh."""
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=30)
        Config = self.env["action.centre.trigger.config"].sudo()
        cfg = Config.search(
            [("trigger_type", "=", "contract_expiry_30days")], limit=1)
        created = 0
        if cfg and cfg.is_enabled:
            contracts = self.sudo().search([
                ("state", "=", "open"),
                ("date_end", "!=", False),
                ("date_end", "<=", horizon),
            ])
            hr_user = self._neon_hr_alert_assignee()
            for c in contracts:
                days = (c.date_end - today).days
                emp = c.employee_id.name or c.name
                if days < 0:
                    title = _(
                        "EXPIRED %(d)s days ago & still Active: "
                        "%(emp)s contract (ended %(end)s)"
                    ) % {"d": abs(days), "emp": emp, "end": c.date_end}
                    priority = "urgent"
                else:
                    title = _(
                        "Contract expires in %(d)s days: %(emp)s "
                        "(ends %(end)s)"
                    ) % {"d": days, "emp": emp, "end": c.date_end}
                    priority = "high"
                kwargs = {
                    "title": title,
                    "priority": priority,
                    "due_date": datetime.combine(c.date_end, time()),
                }
                if hr_user:
                    kwargs["primary_assignee_id"] = hr_user.id
                try:
                    item = c._action_centre_create_item(
                        "contract_expiry_30days", **kwargs)
                    if item:
                        created += 1
                except Exception as e:
                    _logger.warning(
                        "neon_hr contract_expiry trigger failed for "
                        "%s: %s", c.name, e)
            _logger.info(
                "neon_hr contract_expiry: %d contracts in window, "
                "%d items created/refreshed.", len(contracts), created)

        # Refresh document expiry states in the same daily pass.
        self.env["neon.hr.document"].sudo()._cron_refresh_document_states()
        return True
