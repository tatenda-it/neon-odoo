# -*- coding: utf-8 -*-
"""P6.M7 -- invoice schedule template (Schema Sketch §7.2).

Per-partner default schedule template. Sales rep saves a multi-stage
schedule against a client; subsequent quotes for that client auto-
instantiate the schedule on quote acceptance. Falls back to a single-
stage 100% on-acceptance default when no template exists.

Append-only audit trail: no perm_unlink for any group. To retire a
template, set active=False; corrections via a new template.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_STAGES = [
    ("deposit", "Deposit"),
    ("progress", "Progress Payment"),
    ("final", "Final Balance"),
    ("retention", "Retention Hold"),
]

_TRIGGERS = [
    ("on_acceptance", "On Quote Acceptance"),
    ("on_date", "On Specific Date / Offset"),
    ("on_event_state", "On Event State Change"),
    ("manual", "Manual Trigger Only"),
]

_EVENT_STATES = [
    ("ready_for_dispatch", "Pre-Dispatch"),
    ("in_progress", "Event In Progress"),
    ("completed", "Event Completed"),
]


class NeonFinanceInvoiceScheduleTemplate(models.Model):
    _name = "neon.finance.invoice.schedule.template"
    _description = "Invoice Schedule Template"
    _order = "partner_id, name"
    _rec_name = "name"

    name = fields.Char(required=True, index=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Client",
        required=True,
        ondelete="restrict",
        index=True,
        help="One template per (partner, name). The partner's most "
        "recent active template wins on quote acceptance when "
        "multiple exist.",
    )
    line_ids = fields.One2many(
        "neon.finance.invoice.schedule.template.line",
        "template_id",
        string="Stages",
    )
    active = fields.Boolean(default=True, index=True)
    notes = fields.Text()

    @api.constrains("line_ids")
    def _check_percentage_sum(self):
        for rec in self:
            if not rec.line_ids:
                continue
            total = sum(rec.line_ids.mapped("percentage"))
            if abs(total - 100.0) > 0.01:
                raise ValidationError(_(
                    "Template '%(name)s' stage percentages must sum "
                    "to 100 (got %(total).2f). Adjust stages before "
                    "saving."
                ) % {"name": rec.name, "total": total})


class NeonFinanceInvoiceScheduleTemplateLine(models.Model):
    _name = "neon.finance.invoice.schedule.template.line"
    _description = "Invoice Schedule Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "neon.finance.invoice.schedule.template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(default=10)
    stage = fields.Selection(_STAGES, required=True, default="final")
    trigger = fields.Selection(
        _TRIGGERS, required=True, default="on_acceptance")
    trigger_offset_days = fields.Integer(
        default=0,
        help="For trigger='on_date': days from quote acceptance. "
        "0 means same-day; negative means before; positive after. "
        "Ignored for other trigger types.",
    )
    trigger_event_state = fields.Selection(
        _EVENT_STATES,
        help="For trigger='on_event_state': which event_job state "
        "fires this stage's invoice.",
    )
    percentage = fields.Float(required=True, default=100.0)
    notes = fields.Text()

    _sql_constraints = [
        ("check_percentage_range",
         "CHECK (percentage >= 0 AND percentage <= 100)",
         "Stage percentage must be between 0 and 100."),
    ]

    @api.constrains("trigger", "trigger_event_state")
    def _check_trigger_event_state_required(self):
        for rec in self:
            if rec.trigger == "on_event_state" and not rec.trigger_event_state:
                raise ValidationError(_(
                    "Template line stage '%s' uses trigger "
                    "'on_event_state' but no event state is set."
                ) % dict(_STAGES).get(rec.stage, rec.stage))
