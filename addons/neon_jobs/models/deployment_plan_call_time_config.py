# -*- coding: utf-8 -*-
"""P-B3 -- Call-time policy config.

⚠️ DECISION (B3, gate-1 (c)): crew call-time offsets are
configurable -- defaults are sensible but Lisa (Operations) signs
off on the policy. Flagged for ops review on first deploy.

Defaults (per gate-1 (c) recommendation):
  - crew_chief:  max(prep_start, dispatch_datetime) - 30 min
  - lead_tech:   same anchor, - 60 min  (i.e. 30 min before
                  crew_chief)
  - rest:        dispatch_datetime - 15 min

Anchor field selects the timestamp the offset is computed from.
Default 'dispatch_for_chief_and_lead_max_anchor' uses the wider of
(prep_start, dispatch) for chief + lead, and dispatch alone for
rest. Direct 'dispatch' anchors all three from dispatch_datetime
unconditionally.

The config is a singleton (one row only -- enforced by
_sql_constraint). Lisa edits via Settings menu.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


_ANCHOR_CHOICES = [
    ("max_prep_dispatch",
     "Max of (prep_start, dispatch) for chief+lead; "
     "dispatch only for rest"),
    ("dispatch",
     "Dispatch only (uniform anchor)"),
]


class NeonDeploymentPlanCallTimeConfig(models.Model):
    _name = "neon.deployment.plan.call.time.config"
    _description = "Deployment Plan Call-Time Policy"
    _inherit = ["mail.thread"]
    _rec_name = "display_name"

    display_name = fields.Char(
        compute="_compute_display_name", store=False)

    crew_chief_offset_minutes = fields.Integer(
        required=True, default=30, tracking=True,
        help="Minutes BEFORE the anchor that the crew chief is "
             "called. Default 30. Negative values would mean AFTER "
             "the anchor (rejected by CHECK constraint).",
    )
    lead_tech_offset_minutes = fields.Integer(
        required=True, default=60, tracking=True,
        help="Minutes BEFORE the anchor for the lead tech. Default "
             "60 (i.e. 30 min before the crew chief).",
    )
    rest_offset_minutes = fields.Integer(
        required=True, default=15, tracking=True,
        help="Minutes BEFORE dispatch_datetime for the rest of the "
             "crew. Default 15.",
    )
    anchor_policy = fields.Selection(
        _ANCHOR_CHOICES, required=True,
        default="max_prep_dispatch", tracking=True,
        help="Anchor selection for chief + lead. 'rest' always "
             "anchors on dispatch regardless of this choice "
             "(rest_offset_minutes is small + dispatch is the right "
             "single point for the convoy).",
    )

    is_ops_signed_off = fields.Boolean(
        default=False, tracking=True,
        string="Ops signed off",
        help="Lisa (Operations) ticks this once the policy has "
             "been reviewed. Until then, the deployment plan form "
             "renders an amber banner: 'Call-time policy not yet "
             "signed off by Operations'.",
    )

    _sql_constraints = [
        ("offsets_non_negative",
         "CHECK (crew_chief_offset_minutes >= 0 "
         "  AND lead_tech_offset_minutes >= 0 "
         "  AND rest_offset_minutes >= 0)",
         "Call-time offsets cannot be negative (they're BEFORE the "
         "anchor; negative would mean after, which is nonsense)."),
    ]

    @api.depends("crew_chief_offset_minutes",
                 "lead_tech_offset_minutes",
                 "rest_offset_minutes",
                 "is_ops_signed_off")
    def _compute_display_name(self):
        for rec in self:
            sign = "✓ ops-signed" if rec.is_ops_signed_off else \
                   "⚠ pending ops sign-off"
            rec.display_name = (
                "Call-time policy ("
                "chief −{c}m / lead −{l}m / rest −{r}m -- {s})"
            ).format(c=rec.crew_chief_offset_minutes,
                     l=rec.lead_tech_offset_minutes,
                     r=rec.rest_offset_minutes,
                     s=sign)

    @api.constrains()
    def _check_singleton(self):
        # Singleton: only one config row allowed. Caller hits the
        # form via Settings menu which lazy-creates via
        # get_singleton().
        if self.search_count([]) > 1:
            raise ValidationError(_(
                "Only one Call-Time Policy config can exist. Edit "
                "the existing row instead of creating a new one."))

    @api.model
    def get_singleton(self):
        """Lazy-create + return the singleton config row. Called
        from the fact gatherer + the Settings menu action."""
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({})
        return rec
