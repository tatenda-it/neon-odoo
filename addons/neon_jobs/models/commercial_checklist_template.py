# -*- coding: utf-8 -*-
"""
P3.M5 — Checklist Library (template side).

9 templates (one per v4.1 §20 checklist type) define the default
items that get snapshotted onto every newly-created event_job's
9 checklist instances. Managers edit templates via Configuration
→ Operations → Checklist Templates; edits propagate to NEW
event_jobs only — existing instances retain their snapshot.

Ownership role map (Q9) drives who can later check items on the
instance side. Map lives in this file as the canonical source;
the instance model snapshots a role at creation time so a future
map change can't retroactively shift authority on in-flight events.
"""
from odoo import _, api, fields, models


CHECKLIST_TYPES = [
    ("capacity_acceptance", "Capacity Acceptance"),
    ("job_readiness",       "Job Readiness"),
    ("gear_prep",           "Gear Preparation"),
    ("dispatch",            "Dispatch"),
    ("site_setup",          "Site Setup"),
    ("client_handover",     "Client Handover"),
    ("strike",              "Strike Down"),
    ("returned",            "Equipment Return"),
    ("closeout",            "Event Closeout"),
]

OWNERSHIP_ROLES = [
    ("lead_tech",         "Lead Tech"),
    ("crew_chief",        "Crew Chief"),
    ("lead_tech_finance", "Lead Tech + Finance"),
]

# Spec D4 — type → ownership role mapping. Pre-event Lead Tech;
# live (on-site) Crew Chief; post-event Lead Tech + Finance.
CHECKLIST_TYPE_TO_ROLE = {
    "capacity_acceptance": "lead_tech",
    "job_readiness":       "lead_tech",
    "gear_prep":           "lead_tech",
    "dispatch":            "lead_tech",
    "site_setup":          "crew_chief",
    "client_handover":     "crew_chief",
    "strike":              "crew_chief",
    "returned":            "lead_tech_finance",
    "closeout":            "lead_tech_finance",
}

# Spec D1 lifecycle order used for sub-tab display + sequence seeding.
CHECKLIST_TYPE_ORDER = [t[0] for t in CHECKLIST_TYPES]


class CommercialChecklistTemplate(models.Model):
    _name = "commercial.checklist.template"
    _description = "Checklist Template (one per v4.1 type)"
    _order = "sequence, id"

    type = fields.Selection(
        CHECKLIST_TYPES,
        string="Checklist Type",
        required=True,
        copy=False,
        help="Each of the 9 v4.1 §20 checklist types is represented "
        "by exactly one active template.",
    )
    name = fields.Char(
        string="Template Name",
        compute="_compute_name",
        store=True,
    )
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True)
    ownership_role = fields.Selection(
        OWNERSHIP_ROLES,
        string="Default Ownership Role",
        compute="_compute_ownership_role",
        store=True,
        help="Who is authorised to tick items in instances of this "
        "checklist. Derived from type — Lead Tech for pre-event, "
        "Crew Chief for live, Lead Tech + Finance for post-event.",
    )
    item_ids = fields.One2many(
        "commercial.checklist.template.item",
        "template_id",
        string="Items",
        copy=True,
    )
    item_count = fields.Integer(
        string="Item Count",
        compute="_compute_item_count",
    )

    _sql_constraints = [
        (
            "unique_type",
            "UNIQUE (type)",
            "Only one active checklist template per type is allowed.",
        ),
    ]

    @api.depends("type")
    def _compute_name(self):
        type_dict = dict(CHECKLIST_TYPES)
        for rec in self:
            rec.name = "%s Template" % (type_dict.get(rec.type) or _("Unknown"))

    @api.depends("type")
    def _compute_ownership_role(self):
        for rec in self:
            rec.ownership_role = CHECKLIST_TYPE_TO_ROLE.get(rec.type, "lead_tech")

    @api.depends("item_ids")
    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)


class CommercialChecklistTemplateItem(models.Model):
    _name = "commercial.checklist.template.item"
    _description = "Checklist Template Item"
    _order = "template_id, sequence, id"

    template_id = fields.Many2one(
        "commercial.checklist.template",
        string="Template",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Step", required=True)
    description = fields.Text(string="Description")
    photo_required = fields.Boolean(
        string="Photo Required",
        default=False,
        help="When True, instance items derived from this template "
        "row require a photo attachment before they can be ticked. "
        "Per Q10 — opt-in per item, NOT default.",
    )
    active = fields.Boolean(default=True)
