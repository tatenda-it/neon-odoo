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

    # ============================================================
    # P7a.M9 -- tier-1 gate fire hooks (create + write per DP6)
    # ============================================================
    # Event-job states that should NOT receive a fresh tier-1
    # log entry. The event has finished or been called off; a
    # late re-assignment to a closed event is an admin
    # reconciliation, not an active gate decision. Matches the
    # filter pattern used by the closeout-queue search in
    # neon_jobs/views/commercial_event_job_views.xml.
    _M9_TERMINAL_EVENT_STATES = (
        "completed", "closed", "cancelled", "released",
    )

    def _evaluate_assignment_gate(self):
        """Read M8's computed fields on self and return the
        evaluation snapshot used by _create_tier_1_gate_log
        _and_toast. Pure function -- no side effects, no writes,
        no chatter. Callable from both create() and write()
        hooks (DP6) plus future M10 / M11 helpers.

        Returns a dict shaped:
          {
            'status':        gate_status value,
            'missing_ids':   list of cert_type ids,
            'softening_ids': list of cross_competency ids,
            'softening_used': bool,
          }

        Caller decides whether to log + toast based on the
        returned status. Tier-1 fires when status is in
        ('unqualified', 'needs_cross_competency'); 'qualified'
        and 'pending' fire nothing (no noise on clean
        assignments or empty slots).
        """
        self.ensure_one()
        return {
            "status":        self.gate_status,
            "missing_ids":   self.gate_missing_certification_ids.ids,
            "softening_ids":
                self.gate_softening_cross_competency_ids.ids,
            "softening_used": bool(self.gate_softening_used),
        }

    def _m9_eligible_event_jobs(self):
        """Return the event_jobs under this crew's parent job
        that are still active enough to receive a tier-1 log
        entry. Filters out terminal states per the M9 design
        directive (DP7 implementation note).

        Returns a recordset (possibly empty). Empty result means
        no log entries are written, even when status is
        unqualified -- the assignment is a back-fill on a
        closed event, no live decision to flag.
        """
        self.ensure_one()
        if not self.job_id:
            return self.env["commercial.event.job"]
        return self.job_id.event_job_ids.filtered(
            lambda ej: ej.state
            not in self._M9_TERMINAL_EVENT_STATES
        )

    def _create_tier_1_gate_log_and_toast(self, evaluation,
                                          aggregated_toast_buffer):
        """Write one neon.training.assignment_gate_log record per
        eligible event_job (DP7) and append a per-crew summary to
        the aggregated toast buffer. The caller is responsible
        for emitting the final bus.bus toast after iterating all
        affected crew records (DP3).

        Idempotency: this helper is called only when
        _evaluate_assignment_gate returns a status that warrants
        a fire. Caller checks status precondition; we don't
        re-check here.

        Args:
          evaluation: dict from _evaluate_assignment_gate.
          aggregated_toast_buffer: a list mutated in place with
            entries shaped (crew, evaluation, log_ids,
            event_jobs).

        Returns: the created gate_log recordset.
        """
        self.ensure_one()
        GateLog = self.env["neon.training.assignment_gate_log"]
        event_jobs = self._m9_eligible_event_jobs()
        if not event_jobs:
            # No live event to anchor the log; skip silently.
            # Sales rep still sees the gate_status badge on the
            # crew form via M8's compute -- M9's audit just has
            # nothing to record.
            return GateLog

        missing_ids = evaluation["missing_ids"]
        softening_ids = evaluation["softening_ids"]
        status = evaluation["status"]
        triggering_user = self.env.user
        now = fields.Datetime.now()

        log_vals_list = []
        for ej in event_jobs:
            log_vals_list.append({
                "event_job_id": ej.id,
                "crew_id":      self.id,
                "user_id":      self.user_id.id,
                "gate_tier":    "tier_1_assignment",
                "gate_status_at_fire":       status,
                "missing_certification_type_ids":
                    [(6, 0, missing_ids)],
                "softening_cross_competency_ids":
                    [(6, 0, softening_ids)],
                "fired_at":         now,
                "triggered_by_id":  triggering_user.id,
            })
        # Sudo for the create: training_user tier sales reps don't
        # carry training_admin (which has create perm on the log).
        # The hook fires regardless of who's doing the assignment;
        # the audit record must land.
        logs = GateLog.sudo().create(log_vals_list)

        aggregated_toast_buffer.append({
            "crew":       self,
            "evaluation": evaluation,
            "log_ids":    logs.ids,
            "event_jobs": event_jobs,
        })
        return logs

    def _m9_emit_aggregated_toast(self, aggregated_toast_buffer,
                                  target_partner):
        """Emit the bus.bus notification(s) for an entire write
        or create cycle (DP3). When the buffer has one entry, a
        single per-crew toast fires; when multiple entries, a
        summary toast fires instead.

        Routing: target_partner is the triggering user's
        partner_id (DP1=a). Caller captures this BEFORE any
        sudo escalation so the toast lands on the actual
        sales rep, not SUPERUSER.
        """
        if not aggregated_toast_buffer:
            return
        Bus = self.env["bus.bus"]
        if len(aggregated_toast_buffer) == 1:
            entry = aggregated_toast_buffer[0]
            payload = self._m9_build_toast_payload(
                entry["crew"], entry["evaluation"])
        else:
            payload = self._m9_build_summary_toast_payload(
                aggregated_toast_buffer)
        Bus._sendone(target_partner, "simple_notification", payload)

    def _m9_build_toast_payload(self, crew, evaluation):
        """Single-crew toast copy. DP4: inline softener detail
        when <= 2 softeners, summary phrasing otherwise.
        """
        status = evaluation["status"]
        user_name = (crew.user_id.name
                     or crew.partner_id.name
                     or _("(unnamed assignee)"))
        missing_types = self.env[
            "neon.training.certification.type"].browse(
            evaluation["missing_ids"])
        missing_names = ", ".join(missing_types.mapped("name")) or _(
            "(none)")
        if status == "unqualified":
            return {
                "type":    "warning",
                "title":   _("Qualification check"),
                "message": _(
                    "%(user)s is missing %(n)d required cert(s): "
                    "%(missing)s. Assignment saved."
                ) % {
                    "user":    user_name,
                    "n":       len(missing_types),
                    "missing": missing_names,
                },
                "sticky":  False,
            }
        # status == 'needs_cross_competency'
        softeners = self.env[
            "neon.training.cross_competency"].browse(
            evaluation["softening_ids"])
        if len(softeners) <= 2 and softeners:
            soft_phrases = []
            for cc in softeners:
                ej = cc.demonstrated_through_event_id
                soft_phrases.append(
                    _("demonstrated on %(event)s (%(date)s)") % {
                        "event": ej.display_name,
                        "date": fields.Date.to_string(
                            cc.demonstrated_at),
                    })
            softener_detail = "; ".join(soft_phrases)
        else:
            softener_detail = _(
                "softened by %d cross-competency observations; "
                "see gate log for detail") % len(softeners)
        return {
            "type":    "info",
            "title":   _("Cross-competency softens this assignment"),
            "message": _(
                "%(user)s lacks formal cert for %(missing)s but "
                "%(softener)s. Assignment saved."
            ) % {
                "user":     user_name,
                "missing":  missing_names,
                "softener": softener_detail,
            },
            "sticky":  False,
        }

    def _m9_build_summary_toast_payload(self, buffer):
        """Multi-crew summary toast copy (DP3)."""
        unqualified = sum(
            1 for e in buffer
            if e["evaluation"]["status"] == "unqualified")
        needs_cc = sum(
            1 for e in buffer
            if e["evaluation"]["status"] == "needs_cross_competency")
        return {
            "type":    "warning" if unqualified else "info",
            "title":   _("Qualification warnings"),
            "message": _(
                "Gate fired on %(total)d crew assignment(s): "
                "%(unq)d unqualified, %(ncc)d softened by cross-"
                "competency. See event job gate log for detail."
            ) % {
                "total": len(buffer),
                "unq":   unqualified,
                "ncc":   needs_cc,
            },
            "sticky":  False,
        }

    # ============================================================
    # Phase 7b M5 -- probationary role restriction hook.
    #
    # When a crew row's user_id matches an onboarding candidate
    # in probationary state, the crew row's role must be 'runner'
    # (or null). Non-runner assignments fire a tier_3 (block)
    # gate_log entry with fire_reason='probationary_role_
    # restriction'. The block surfaces via the existing M11
    # event-start gate; M5 doesn't add a separate UI surface.
    #
    # Defensive env.get() pattern: neon_onboarding may not be
    # installed (the M5 hook degrades to no-op in that case).
    # ============================================================
    def _m5_probationary_violation_for_user(self, user_id, role):
        """Return a violation dict if the user is in
        probationary onboarding and role is non-runner;
        otherwise None.

        Safe to call when neon_onboarding is not installed --
        env.get returns None and we exit cleanly.
        """
        if not user_id:
            return None
        Candidate = self.env.get(
            "neon.onboarding.candidate")
        if Candidate is None:
            return None
        candidate = self.env["neon.onboarding.candidate"].sudo().search([
            ("user_id", "=", user_id),
            ("state", "=", "probationary"),
        ], limit=1)
        if not candidate:
            return None
        if role == "runner" or not role:
            return None
        return {
            "candidate_id": candidate.id,
            "candidate_name": candidate.display_name,
            "role": role,
        }

    def _m5_create_probationary_gate_log(self, violation):
        """Write a tier_3 gate_log entry for the M5 probationary
        block. fire_reason='probationary_role_restriction' so
        downstream filtering distinguishes M5 fires from M9/
        M10/M11 fires.

        M12 extension: after creating gate_log entries, fire
        the candidate's _notify_probationary_gate_block hook
        (defensive -- only when neon_onboarding installed AND
        the candidate has the method, i.e. 17.0.1.10.0+).
        """
        self.ensure_one()
        GateLog = self.env["neon.training.assignment_gate_log"]
        event_jobs = self._m9_eligible_event_jobs()
        if not event_jobs:
            return GateLog
        triggering_user = self.env.user
        now = fields.Datetime.now()
        log_vals_list = []
        for ej in event_jobs:
            log_vals_list.append({
                "event_job_id": ej.id,
                "crew_id": self.id,
                "user_id": self.user_id.id,
                "gate_tier": "tier_3_event_start",
                "gate_status_at_fire": "unqualified",
                "fire_reason": "probationary_role_restriction",
                "fired_at": now,
                "triggered_by_id": triggering_user.id,
            })
        logs = GateLog.sudo().create(log_vals_list)
        # M12 notification stub. Defensive: neon_onboarding
        # may not be installed; candidate may not exist or
        # the method may be from an older version.
        Candidate = self.env.get("neon.onboarding.candidate")
        if Candidate is not None and violation.get("candidate_id"):
            candidate = Candidate.sudo().browse(
                violation["candidate_id"])
            if candidate.exists() and hasattr(
                    candidate, "_notify_probationary_gate_block"):
                for ej in event_jobs:
                    candidate.sudo()._notify_probationary_gate_block(
                        ej, violation.get("role") or "non-runner")
        return logs

    @api.model_create_multi
    def create(self, vals_list):
        """DP6: create() is the dominant assignment moment. A
        sales rep adding a crew row with user_id from the start
        hits create(), not write(). Without this hook, M9 only
        catches re-assignments.

        Sudo scope: the gate evaluation reads M8's computes,
        which dereference neon.training.certification.type
        records. Crew Leaders (group_neon_jobs_crew_leader)
        carry no training-tier ACL; without sudo() the gate
        read hits AccessError. The hook escalates JUST the
        gate read + log create; the underlying create() and
        the original env.user identity stay intact for the
        actual crew row.
        """
        records = super().create(vals_list)
        buffer = []
        for rec in records:
            if not rec.user_id:
                continue
            rec_su = rec.sudo()
            evaluation = rec_su._evaluate_assignment_gate()
            if evaluation["status"] in (
                    "unqualified", "needs_cross_competency"):
                rec_su._create_tier_1_gate_log_and_toast(
                    evaluation, buffer)
            # P7b M5 -- probationary role check fires alongside
            # the M9 cert check. Independent gate_log entry per
            # event_job; no toast (M5 doesn't replicate M9's UI
            # surface -- the M11 block flow already covers
            # crew-on-event UX).
            violation = rec._m5_probationary_violation_for_user(
                rec.user_id.id, rec.role)
            if violation:
                rec_su._m5_create_probationary_gate_log(violation)
        if buffer:
            # Capture the real user partner BEFORE sudo so the
            # toast lands on the sales rep, not SUPERUSER.
            self.sudo()._m9_emit_aggregated_toast(
                buffer, self.env.user.partner_id)
        return records

    def write(self, vals):
        """DP6: write() override fires the tier-1 hook on
        re-assignment (user_id transition new != old, new is
        truthy per DP2). DP5 idempotency: a save that doesn't
        change user_id does NOT re-fire the toast even if the
        gate_status would still be unqualified.

        Same sudo scope as create() -- gate read needs cert-
        type ACL bypass for operational-tier writers.
        """
        new_user_id = vals.get("user_id", False) if "user_id" in vals else None
        if new_user_id is None:
            # user_id not in vals at all -- no assignment moment.
            return super().write(vals)

        # Capture old user_ids per record BEFORE super applies.
        old_user_ids = {rec.id: rec.user_id.id for rec in self}
        result = super().write(vals)

        buffer = []
        for rec in self:
            old_uid = old_user_ids.get(rec.id)
            cur_uid = rec.user_id.id
            # Skip non-transitions (DP5 idempotency) and clears
            # (DP2 -- no gate fire on user_id removal).
            if not cur_uid:
                continue
            if cur_uid == old_uid:
                continue
            rec_su = rec.sudo()
            evaluation = rec_su._evaluate_assignment_gate()
            if evaluation["status"] in (
                    "unqualified", "needs_cross_competency"):
                rec_su._create_tier_1_gate_log_and_toast(
                    evaluation, buffer)
            # P7b M5 -- probationary check on re-assignment.
            violation = rec._m5_probationary_violation_for_user(
                rec.user_id.id, rec.role)
            if violation:
                rec_su._m5_create_probationary_gate_log(violation)
        if buffer:
            self.sudo()._m9_emit_aggregated_toast(
                buffer, self.env.user.partner_id)
        return result
