# -*- coding: utf-8 -*-
"""
P7a.M9 -- neon.training.assignment_gate_log.

Schema Sketch section 2.5 deferred from M1; M9 owns creation. One
record per (crew, event_job) pair when a gate fires. Tier 1 records
(severity='info') are written by the commercial.job.crew create
and write hooks in this module; M10 will add tier_2 records on
quote acceptance; M11 will add tier_3 records on event start.

H3=A audit discipline: perm_unlink=0 on every group, including
admin. Corrections via new records (a later fire supersedes an
earlier one, but the earlier record stays for audit).
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


_GATE_TIERS = [
    ("tier_1_assignment",   "Tier 1 -- Assignment"),
    ("tier_2_quote_accept", "Tier 2 -- Quote Acceptance"),
    ("tier_3_event_start",  "Tier 3 -- Event Start"),
]

# Severity is computed from gate_tier per the layered-gating
# design: M9 info, M10 warn, M11 block. Centralised here so the
# tier-to-severity mapping has a single source of truth.
_TIER_SEVERITY = {
    "tier_1_assignment":   "info",
    "tier_2_quote_accept": "warn",
    "tier_3_event_start":  "block",
}

# Gate status values mirror commercial.job.crew.gate_status from
# M8. Re-declared as a local Selection so the audit record stands
# alone even if the M8 enum drifts (audit captures the verdict at
# fire time; we don't want a M8 enum change to silently rewrite
# history).
_GATE_STATUS = [
    ("pending",                "Pending"),
    ("qualified",              "Qualified"),
    ("needs_cross_competency", "Needs Cross-Competency"),
    ("unqualified",            "Unqualified"),
]


class NeonTrainingAssignmentGateLog(models.Model):
    _name = "neon.training.assignment_gate_log"
    _description = "Training Assignment Gate Log"
    _inherit = ["mail.thread"]
    _order = "fired_at desc, id desc"

    # ============================================================
    # Binding fields (the gate fire is anchored to a crew + event)
    # ============================================================
    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
        help="Event the gate fired against. One gate_log per "
        "(crew, event_job) pair (DP7); a crew assignment on a "
        "commercial.job with multiple event_jobs writes one "
        "record per event_job. ondelete='cascade': when the "
        "event_job is deleted the audit goes with it. The "
        "audit shape says 'this fire was about THIS event'; "
        "if the event is gone, the binding is gone. H3=A no-"
        "delete discipline applies to USER actions on the gate "
        "log, not cascade-from-parent.",
    )
    crew_id = fields.Many2one(
        "commercial.job.crew",
        string="Crew Assignment",
        ondelete="set null",
        index=True,
        tracking=True,
        help="The crew row whose user_id transition triggered "
        "this fire. The hook sets this at fire time; if the crew "
        "row is later deleted (commercial.job.crew has perm_"
        "unlink=1 for ops users), this field becomes NULL but "
        "the audit record persists with user_id + event_job_id "
        "+ missing-cert snapshot intact. Audit shape: the gate "
        "fired against this user on this event, regardless of "
        "subsequent crew-row deletions.",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Assignee",
        required=True,
        ondelete="restrict",
        tracking=True,
        help="The crew member at fire time. Snapshot field "
        "(not related to crew_id.user_id) so the audit survives "
        "later reassignment.",
    )

    # ============================================================
    # Tier + severity
    # ============================================================
    gate_tier = fields.Selection(
        _GATE_TIERS,
        string="Gate Tier",
        required=True,
        default="tier_1_assignment",
        tracking=True,
    )
    severity = fields.Selection(
        [("info", "Info"), ("warn", "Warning"), ("block", "Block")],
        string="Severity",
        compute="_compute_severity",
        store=True,
        help="Derived from gate_tier per the layered-gating "
        "design (tier_1=info, tier_2=warn, tier_3=block). "
        "Stored so list view can filter + group cheaply.",
    )

    # ============================================================
    # Snapshot of the gate state at fire time
    # ============================================================
    gate_status_at_fire = fields.Selection(
        _GATE_STATUS,
        string="Gate Status (at fire)",
        required=True,
        tracking=True,
        help="The commercial.job.crew.gate_status value at the "
        "moment the gate fired. Audit snapshot -- does not "
        "track later gate_status changes.",
    )
    missing_certification_type_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_training_gatelog_missing_cert_rel",
        "log_id",
        "cert_type_id",
        string="Missing Certifications (at fire)",
        help="Cert types the assignee lacked at fire time. "
        "Audit snapshot.",
    )
    softening_cross_competency_ids = fields.Many2many(
        "neon.training.cross_competency",
        "neon_training_gatelog_softening_cc_rel",
        "log_id",
        "cc_id",
        string="Softening Cross-Competencies (at fire)",
        help="Cross-competency observations that softened the "
        "gate at fire time. Empty when severity='block' would "
        "have applied without softener.",
    )

    # ============================================================
    # Override (M10 / M11 populate; M9 leaves nullable)
    # ============================================================
    override_reason = fields.Text(
        string="Override Reason",
        help="Required when M10/M11 use this record to bypass a "
        "warn/block tier. Tier-1 (M9 info) never needs override; "
        "field stays nullable for tier-1 records.",
    )
    overridden_by_id = fields.Many2one(
        "res.users",
        string="Overridden By",
        ondelete="restrict",
        help="The user who approved the override. M10 (warn-"
        "tier) and M11 (block-tier) require this be a finance-"
        "approver or operations manager; M9 tier-1 never "
        "populates this.",
    )
    overridden_at = fields.Datetime(
        string="Overridden At",
    )

    # ============================================================
    # Provenance
    # ============================================================
    fired_at = fields.Datetime(
        string="Fired At",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        help="When the gate fired. Set by create() default; "
        "M9 hooks populate explicitly so the timestamp matches "
        "the assignment moment.",
    )
    triggered_by_id = fields.Many2one(
        "res.users",
        string="Triggered By",
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.user.id,
        tracking=True,
        help="The user whose action fired the gate. For tier-1 "
        "(M9) this is the sales rep / event organiser writing "
        "the crew assignment. ir.rule scopes training_user "
        "tier to their own triggered_by_id records.",
    )

    # ============================================================
    # Computes
    # ============================================================
    @api.depends("gate_tier")
    def _compute_severity(self):
        for rec in self:
            rec.severity = _TIER_SEVERITY.get(rec.gate_tier, "info")

    # ============================================================
    # Audit defence
    # ============================================================
    def unlink(self):
        """Belt-and-braces unlink block. The ACL CSV already sets
        perm_unlink=0 for every group, but a SUPERUSER bypass via
        sudo() could otherwise slip a deletion. Explicit raise
        here makes the audit guarantee robust to future changes
        in how sudo() interacts with model-level ACLs.

        H3=A audit discipline -- corrections via new records,
        never via delete. M10 / M11 override mechanics layer
        on top by writing the override fields, not by replacing
        the record.
        """
        raise UserError(_(
            "Training gate log records are append-only (audit "
            "discipline H3=A). Corrections via a new record "
            "with later fired_at, not via delete. Contact admin "
            "if you believe this record is genuinely wrong; "
            "the resolution is a corrective entry, not a delete."
        ))

    def name_get(self):
        result = []
        for rec in self:
            tier_label = dict(self._fields["gate_tier"].selection).get(
                rec.gate_tier, rec.gate_tier)
            event_label = (rec.event_job_id.display_name
                           or _("(no event)"))
            user_label = rec.user_id.name or _("(no user)")
            result.append((
                rec.id,
                "%s: %s on %s" % (tier_label, user_label, event_label),
            ))
        return result
