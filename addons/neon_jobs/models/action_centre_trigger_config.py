# -*- coding: utf-8 -*-
"""P4.M2 — Director-editable trigger configuration.

One record per trigger type (10 seeded). Each record carries the
runtime knobs the Action Centre mixin reads when spawning items:
enable/disable, target role, priority, escalation timing, threshold
values, and the auto-close-when-cleared flag for alerts.

Seed data lives in data/action_centre_trigger_config_data.xml with
noupdate="1" so director edits survive module upgrades — mirrors
the P3.M5 checklist template pattern.

Trigger logic itself (the Python conditions that fire each trigger)
lives in the source modules (commercial_event_job, commercial_job,
etc.) via the action.centre.mixin helpers. This config table is
just the knobs.
"""
from odoo import _, api, fields, models


# Mirrors the Selection on action.centre.item.trigger_type. Kept in
# one place here; the item model imports this list to stay in sync.
TRIGGER_TYPE_SELECTION = [
    ("capacity_gate", "Capacity Gate Review"),
    ("lost", "Lost Lead Follow-up"),
    ("event_created", "New Event Job Created"),
    ("readiness_50", "Readiness At Risk (<50)"),
    ("readiness_70", "Readiness Below Threshold (<70)"),
    ("scope_change", "Scope Change for Review"),
    ("closeout_overdue", "Closeout Overdue"),
    ("sla_passed", "Closeout SLA Passed"),
    ("feedback_followup", "Feedback Follow-up Required"),
    ("manual", "Manual"),
]


class ActionCentreTriggerConfig(models.Model):
    _name = "action.centre.trigger.config"
    _description = "Action Centre Trigger Configuration"
    _inherit = ["mail.thread"]
    _order = "trigger_type"
    _rec_name = "name"

    name = fields.Char(
        compute="_compute_name", store=True,
    )
    trigger_type = fields.Selection(
        TRIGGER_TYPE_SELECTION, required=True, index=True,
    )
    is_enabled = fields.Boolean(default=True, tracking=True)

    item_type = fields.Selection(
        [("task", "Task"), ("alert", "Alert")],
        required=True, default="task",
    )
    primary_role = fields.Selection(
        [("lead_tech", "Lead Tech"),
         ("manager", "Manager"),
         ("sales", "Sales"),
         ("crew_chief", "Crew Chief")],
    )
    priority = fields.Selection(
        [("low", "Low"), ("medium", "Medium"),
         ("high", "High"), ("urgent", "Urgent")],
        required=True, default="medium",
    )
    escalation_minutes = fields.Integer(
        default=0,
        help="Minutes before this item escalates to "
        "escalated_to_role. 0 means no escalation.",
    )
    escalated_to_role = fields.Selection(
        [("lead_tech", "Lead Tech"),
         ("manager", "Manager"),
         ("sales", "Sales"),
         ("crew_chief", "Crew Chief")],
    )

    threshold_value = fields.Float(
        help="Numeric threshold used by triggers that compare a "
        "source field against a number (readiness, SLA days, "
        "etc.). Triggers without a numeric condition leave this "
        "at 0.",
    )
    threshold_field = fields.Char(
        readonly=True,
        help="Human description of what the threshold compares.",
    )

    auto_close_when_condition_clears = fields.Boolean(
        default=False,
        help="Alerts with this enabled auto-close when the source "
        "condition clears (e.g. readiness climbs back above 70). "
        "Tasks usually require manual completion.",
    )

    description = fields.Text(
        readonly=True,
        help="Internal explanation shown in the Configuration UI.",
    )

    _sql_constraints = [
        (
            "trigger_type_uniq",
            "unique(trigger_type)",
            "Only one configuration per trigger type is allowed.",
        ),
    ]

    @api.depends("trigger_type")
    def _compute_name(self):
        labels = dict(TRIGGER_TYPE_SELECTION)
        for rec in self:
            rec.name = labels.get(rec.trigger_type) or _("Unknown")
