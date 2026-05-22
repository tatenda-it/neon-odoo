# -*- coding: utf-8 -*-
"""neon.lms.practical.scenario + neon.lms.scenario.completion.

Phase 7e M5. Practical scenarios are real-world judgement
calls reviewed by a signoff authority (Robin/Munashe, lead
tech, or external). Completion records hold per-learner
signoff state.

Signoff routing imports Phase 7a M7's _CERT_VERIFIER_LOGINS
constant at runtime to keep the managerial-signoff list
single-sourced (no duplication of the Robin+Munashe
hardcoding).
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


_SIGNOFF_AUTHORITIES = [
    ("superuser", "Managerial Superuser (Robin / Munashe)"),
    ("lead_tech", "Lead Tech"),
    ("external", "External (out-of-band)"),
]


class NeonLMSPracticalScenario(models.Model):
    _name = "neon.lms.practical.scenario"
    _description = "Neon LMS Practical Scenario"
    _order = "module_id, sequence asc, id asc"

    module_id = fields.Many2one(
        "neon.lms.module",
        string="Module",
        required=True,
        ondelete="restrict",
        index=True,
    )
    sequence = fields.Integer(default=10)
    title = fields.Char(
        required=True,
        translate=True,
    )
    description = fields.Text(
        required=True,
        translate=True,
        help="The scenario setup -- what the learner is "
             "asked to do or judge.",
    )
    expected_actions = fields.Text(
        translate=True,
        help="What the learner should do or say. Reviewed "
             "by signoff authority during evaluation.",
    )
    evaluation_criteria = fields.Text(
        translate=True,
        help="What the signoff authority should look for. "
             "Drives the pass/fail decision.",
    )
    signoff_authority = fields.Selection(
        _SIGNOFF_AUTHORITIES,
        string="Signoff Authority",
        required=True,
        default="superuser",
        help="Who can sign off this scenario. 'superuser' "
             "routes to Phase 7a M7's managerial verifier "
             "list (Robin + Munashe). 'lead_tech' routes "
             "to neon_core.group_neon_lead_tech members. "
             "'external' is out-of-band (no in-system "
             "verifier).",
    )
    active = fields.Boolean(default=True)

    def _get_signoff_partners(self):
        """Return res.partner recordset of users who can
        sign off this scenario. Phase 9 wiring (notifications)
        consumes this list.

        For 'superuser': delegates to Phase 7a M7's
        _CERT_VERIFIER_LOGINS constant -- single source of
        truth for managerial signoff routing across phases.
        """
        self.ensure_one()
        Partner = self.env["res.partner"]
        if self.signoff_authority == "superuser":
            # Import at runtime to avoid load-order coupling.
            from odoo.addons.neon_training.models import (
                neon_training_certification as ntc)
            users = self.env["res.users"].sudo().search([
                ("login", "in",
                 list(ntc._CERT_VERIFIER_LOGINS)),
                ("active", "=", True),
            ])
            return users.mapped("partner_id")
        if self.signoff_authority == "lead_tech":
            grp = self.env.ref(
                "neon_core.group_neon_lead_tech",
                raise_if_not_found=False)
            if not grp:
                return Partner
            return grp.users.mapped("partner_id")
        # external -- out-of-band
        return Partner


class NeonLMSScenarioCompletion(models.Model):
    _name = "neon.lms.scenario.completion"
    _description = "Neon LMS Scenario Completion"
    _order = "learner_id, scenario_id"

    learner_id = fields.Many2one(
        "res.users",
        string="Learner",
        required=True,
        ondelete="restrict",
        index=True,
    )
    scenario_id = fields.Many2one(
        "neon.lms.practical.scenario",
        string="Scenario",
        required=True,
        ondelete="restrict",
        index=True,
    )
    signed_off_by_id = fields.Many2one(
        "res.users",
        string="Signed Off By",
        ondelete="restrict",
        help="The user who reviewed + signed off this "
             "completion. Must match scenario.signoff_"
             "authority routing.",
    )
    signoff_date = fields.Datetime()
    notes = fields.Text(
        help="Reviewer notes -- visible to the learner.",
    )
    passed = fields.Boolean(
        default=False,
        help="True only when signed_off_by_id is set + the "
             "reviewer marked the scenario as passed.",
    )

    _sql_constraints = [
        ("scenario_completion_unique",
         "UNIQUE(learner_id, scenario_id)",
         "A learner can have at most one completion record "
         "per scenario."),
    ]

    def write(self, vals):
        """M8 workflow trigger: when passed flips True, find
        the learner's module.completion for the scenario's
        module and fire _check_and_advance_to_completed.

        sudo() on every cross-model read: signoff authorities
        (lead_tech, training_admin) writing the completion
        don't necessarily have ACL on neon.lms.module or
        slide.channel.partner. The hook is workflow logic;
        run with elevated ACL throughout.
        """
        res = super().write(vals)
        if vals.get("passed"):
            ModuleComp = self.env.get(
                "neon.lms.module.completion")
            if ModuleComp is None:
                return res
            for rec in self.filtered(lambda c: c.passed):
                rec_su = rec.sudo()
                partner = rec_su.learner_id.partner_id
                Enrollment = self.env[
                    "slide.channel.partner"]
                enrollment = Enrollment.sudo().search([
                    ("partner_id", "=", partner.id),
                    ("channel_id", "=",
                     rec_su.scenario_id.module_id.channel_id.id),
                ], limit=1)
                if not enrollment:
                    continue
                mc = ModuleComp.sudo().search([
                    ("enrollment_id", "=", enrollment.id),
                    ("module_id", "=",
                     rec_su.scenario_id.module_id.id),
                ], limit=1)
                if mc:
                    mc._check_and_advance_to_completed()
        return res
