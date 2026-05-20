# -*- coding: utf-8 -*-
"""
P7a.M8 -- commercial.job.crew extension for training gate inference.

Per Schema Sketch section 3.3, the "role line" concept maps to the
existing commercial.job.crew model (job.crew is the assignment;
the schema's hypothetical event.job.role.line does not exist as
a separate model). G1=B: requirements are INFERRED from
crew.role + the event_job equipment context, not declared by
sales reps.

What M8 ships
=============
Five computed non-stored fields:

  required_certification_type_ids       (M2m to cert type)
  gate_status                            (Selection: qualified /
                                          needs_cross_competency /
                                          unqualified / pending)
  gate_missing_certification_ids        (M2m -- cert types lacking)
  gate_softening_cross_competency_ids   (M2m to cross_competency
                                          records that downgrade
                                          unqualified -> needs_
                                          cross_competency)
  gate_softening_used                   (Boolean -- True when any
                                          softener was applied;
                                          drives the M9-M11 UI hint)

Six methods:

  _compute_required_certifications
  _infer_role_tier_certifications
  _infer_equipment_certifications
  _compute_gate_status
  _compute_gate_missing_certification_ids
  _compute_gate_softening_cross_competency_ids

DATA LAYER ONLY. No state writes. No gate fires. No assignment
_gate_log records. M9-M11 read these fields and own all the
gating UX + logging.

Cross-cutting enumeration discipline
====================================
M8 touches THREE models (commercial.event.job, commercial.job.
crew, res.users). Each touch is declared in the milestone
gate-1 report per the CLAUDE.md amendment from M4.
"""
from odoo import _, api, fields, models


# Map crew.role (existing Selection enum) -> training cert xmlid
# for the role-tier requirement inference. 'other' yields no
# requirement (non-tier roles like 'Catering Coordinator' don't
# carry a formal role-tier cert).
_ROLE_TIER_TO_CERT_XMLID = {
    "lead_tech": "neon_training.cert_type_lead_tech",
    "tech":      "neon_training.cert_type_tech",
    "runner":    "neon_training.cert_type_runner",
    "driver":    "neon_training.cert_type_driver",
    # "other" intentionally absent -> empty result via dict.get
}


class CommercialJobCrew(models.Model):
    _inherit = "commercial.job.crew"

    # ============================================================
    # Inferred requirements
    # ============================================================
    required_certification_type_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_training_crew_required_cert_rel",
        "crew_id",
        "cert_type_id",
        string="Required Certifications",
        compute="_compute_required_certifications",
        store=False,
        help="Inferred from crew.role (role-tier requirement) plus "
        "the event_job equipment context (equipment-based cert "
        "requirements). G1=B: requirements are inferred, not "
        "declared by sales reps. Non-stored to avoid recompute "
        "storm on cert state changes; M12 dashboard may promote "
        "to stored if reporting performance demands.",
    )

    # ============================================================
    # Gate status + diagnostics
    # ============================================================
    gate_status = fields.Selection(
        [
            ("pending",                "Pending (no user assigned)"),
            ("qualified",              "Qualified"),
            ("needs_cross_competency", "Needs Cross-Competency"),
            ("unqualified",            "Unqualified"),
        ],
        string="Training Gate",
        compute="_compute_gate_status",
        store=False,
        help="Per-crew qualification state.\n\n"
        "pending = no user assigned yet (freelancers via partner_"
        "id without user_id also surface as pending; cross-"
        "competency lookup needs an Odoo user).\n\n"
        "qualified = all required certs are active for this user.\n\n"
        "needs_cross_competency = formal cert missing but a cross-"
        "competency observation softens the gap (M6 data softens "
        "the block-tier outcome in M11 layered gating).\n\n"
        "unqualified = formal cert missing AND no softener exists.",
    )
    gate_missing_certification_ids = fields.Many2many(
        "neon.training.certification.type",
        "neon_training_crew_missing_cert_rel",
        "crew_id",
        "cert_type_id",
        string="Missing Certifications",
        compute="_compute_gate_missing_certification_ids",
        store=False,
        help="The actual cert types this crew member lacks vs. the "
        "inferred requirement. Drives the M9-M11 UI display "
        "('Missing: MA3 Console, Work at Heights').",
    )
    gate_softening_cross_competency_ids = fields.Many2many(
        "neon.training.cross_competency",
        "neon_training_crew_softening_cc_rel",
        "crew_id",
        "cc_id",
        string="Softening Cross-Competencies",
        compute="_compute_gate_softening_cross_competency_ids",
        store=False,
        help="Cross-competency observations matching missing cert "
        "types for the assigned user. M11 block-tier gating "
        "downgrades to warn when at least one softener exists.",
    )
    gate_softening_used = fields.Boolean(
        string="Softening Applied",
        compute="_compute_gate_softening_cross_competency_ids",
        store=False,
        help="True when the gate_status was lifted from "
        "'unqualified' to 'needs_cross_competency' by at least "
        "one cross-competency observation. UI hint for M9-M11.",
    )

    # ============================================================
    # Inference helpers
    # ============================================================
    def _infer_role_tier_certifications(self):
        """Resolve crew.role (Selection enum) to the matching
        role-tier cert type via _ROLE_TIER_TO_CERT_XMLID. Returns
        a recordset (single cert type or empty for 'other')."""
        self.ensure_one()
        CertType = self.env["neon.training.certification.type"]
        xmlid = _ROLE_TIER_TO_CERT_XMLID.get(self.role)
        if not xmlid:
            return CertType
        cert_type = self.env.ref(xmlid, raise_if_not_found=False)
        return cert_type or CertType

    def _infer_equipment_certifications(self):
        """Resolve equipment-based cert requirements from the
        event_job equipment context. DP1=a: equipment lives on
        commercial.event.job.equipment_line_ids per event; crew
        sits on the parent commercial.job. M8 takes the UNION of
        equipment across all event_jobs of this crew's parent
        job -- defensive: a crew member must be qualified for any
        equipment that might appear on any event_job of the
        commercial job they're assigned to.

        Equipment-to-cert link: cert_type.equipment_model_id is
        a Many2one to product.template. Iterate the equipment
        line product_templates; for each, find cert types where
        equipment_model_id matches; union the results.

        Pre-deploy reality: M1/M3 seeded cert types with
        equipment_model_id NULL (Ranganai populates via UI post-
        deploy). Until then this method returns empty for all
        crew records, which is code-correct (no equipment certs
        currently required from the system's perspective). Logged
        as Phase 7a pre-deploy task in the project status doc.
        """
        self.ensure_one()
        CertType = self.env["neon.training.certification.type"]
        if not self.job_id:
            return CertType
        # Union of equipment templates across all event_jobs of the
        # parent commercial.job.
        equipment_lines = self.job_id.event_job_ids.equipment_line_ids
        templates = equipment_lines.mapped("product_template_id")
        if not templates:
            return CertType
        # Find cert types pointing at any of these templates.
        return CertType.sudo().search([
            ("equipment_model_id", "in", templates.ids),
            ("active", "=", True),
        ])

    # ============================================================
    # Computes
    # ============================================================
    @api.depends(
        "role",
        "job_id",
        "job_id.event_job_ids",
        "job_id.event_job_ids.equipment_line_ids",
        "job_id.event_job_ids.equipment_line_ids.product_template_id",
    )
    def _compute_required_certifications(self):
        for rec in self:
            required = (rec._infer_role_tier_certifications()
                        | rec._infer_equipment_certifications())
            rec.required_certification_type_ids = required

    @api.depends(
        "user_id",
        "user_id.training_certification_ids.state",
        "user_id.training_certification_ids.type_id",
        "user_id.cross_competency_ids.certification_type_id",
        "required_certification_type_ids",
    )
    def _compute_gate_status(self):
        """Compute the gate verdict per crew. Logic per Schema
        Sketch section 3.3 + M6 cross-competency softening.

        State precedence:
          no user_id -> 'pending'
          required is empty (no role-tier match + no equipment
            with cert) -> 'qualified' (trivially)
          missing is empty -> 'qualified'
          missing fully softened by cross-competency -> 'needs_
            cross_competency'
          missing not fully softened -> 'unqualified'

        Edge case: crew with partner_id only (freelancer, no
        user_id) surfaces as 'pending'. Cross-competency lookup
        needs an Odoo user; the freelance path is out-of-scope
        until 7b portal mechanics.
        """
        for rec in self:
            if not rec.user_id:
                rec.gate_status = "pending"
                continue
            required = rec.required_certification_type_ids
            if not required:
                rec.gate_status = "qualified"
                continue
            active_certs = rec.user_id.training_certification_ids.filtered(
                lambda c: c.state == "active")
            held_types = active_certs.mapped("type_id")
            missing = required - held_types
            if not missing:
                rec.gate_status = "qualified"
                continue
            # Cross-competency softening check.
            softening = rec.user_id.cross_competency_ids.filtered(
                lambda cc: cc.certification_type_id in missing)
            softened_types = softening.mapped("certification_type_id")
            unsoftened_missing = missing - softened_types
            if not unsoftened_missing:
                rec.gate_status = "needs_cross_competency"
            else:
                rec.gate_status = "unqualified"

    @api.depends(
        "user_id",
        "user_id.training_certification_ids.state",
        "user_id.training_certification_ids.type_id",
        "required_certification_type_ids",
    )
    def _compute_gate_missing_certification_ids(self):
        for rec in self:
            if not rec.user_id:
                rec.gate_missing_certification_ids = (
                    rec.required_certification_type_ids)
                continue
            active_certs = rec.user_id.training_certification_ids.filtered(
                lambda c: c.state == "active")
            held_types = active_certs.mapped("type_id")
            rec.gate_missing_certification_ids = (
                rec.required_certification_type_ids - held_types)

    @api.depends(
        "user_id",
        "user_id.cross_competency_ids.certification_type_id",
        "gate_missing_certification_ids",
        "gate_status",
    )
    def _compute_gate_softening_cross_competency_ids(self):
        for rec in self:
            if (not rec.user_id
                    or not rec.gate_missing_certification_ids):
                rec.gate_softening_cross_competency_ids = (
                    self.env["neon.training.cross_competency"])
                rec.gate_softening_used = False
                continue
            softening = rec.user_id.cross_competency_ids.filtered(
                lambda cc: cc.certification_type_id
                           in rec.gate_missing_certification_ids)
            rec.gate_softening_cross_competency_ids = softening
            # gate_softening_used reflects whether the softening
            # actually changed the gate verdict, not just whether
            # any softener exists.
            rec.gate_softening_used = (
                rec.gate_status == "needs_cross_competency")
