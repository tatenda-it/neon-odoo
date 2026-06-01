# -*- coding: utf-8 -*-
"""Neon HR R3a — competency / licence gate on crew assignment.

Extends ``commercial.job.crew`` (neon_jobs) FROM neon_hr. neon_hr
depends on neon_jobs and shares no FILES with it (same discipline as
action_centre_ext.py). We do NOT rebuild crew assignment — we add a
computed gate signal + an OD/MD override, and enforce on create/write.

⚠️ DECISION (Gate 1 — SPLIT severity):
* DRIVER LICENCE — a crew member assigned role='driver' whose mapped
  employee holds NO valid licence is a HARD BLOCK (UserError), NOT
  override-able (overriding would authorise an illegal act; driving
  unlicensed is illegal in Zimbabwe — legal/safety, not operational).
* COMPETENCY — a missing/expired required competency WARNS by default
  (chatter + computed signal) with an OD/MD override; under
  ``neon_hr.competency_gate_mode = 'block'`` it raises UserError unless
  overridden. The licence block ignores both the mode and the override.
* FREELANCER / NO EMPLOYEE RECORD — a crew member with no resolvable
  hr.employee yields a WARNING ("no employee record — cannot verify"),
  never a silent pass and never a block: absence of data is not proof
  of an absent licence.

⚠️ DECISION: ``neon_gate_state``/``neon_gate_message`` are a STORED
compute for DISPLAY. The block decision (warn vs block) is read LIVE
from the config parameter inside _neon_enforce_gate at create/write —
config params don't fire recomputes, so the stored state is a hint, the
enforcement is authoritative.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

GATE_MODE_PARAM = "neon_hr.competency_gate_mode"


class CommercialJobCrew(models.Model):
    _inherit = "commercial.job.crew"

    neon_employee_id = fields.Many2one(
        "hr.employee", compute="_compute_neon_employee_id", store=True,
        string="Mapped Employee",
        help="The hr.employee this crew member maps to (via user or "
        "contact). Empty for freelancers with no employee record.")
    neon_gate_state = fields.Selection(
        [("ok", "OK"),
         ("no_employee", "No Employee Record"),
         ("competency_warning", "Competency Gap"),
         ("licence_block", "Licence Block"),
         ("overridden", "Overridden (OD/MD)")],
        compute="_compute_neon_gate", store=True, string="Assignment Gate")
    neon_gate_message = fields.Char(compute="_compute_neon_gate", store=True)
    neon_competency_override = fields.Boolean(
        string="Competency Gate Overridden", tracking=True,
        help="OD/MD-only bypass of the COMPETENCY gate (never the "
        "licence block).")

    @api.depends("user_id", "partner_id")
    def _compute_neon_employee_id(self):
        Emp = self.env["hr.employee"].sudo()
        for rec in self:
            emp = Emp.browse()
            if rec.user_id:
                emp = Emp.search([("user_id", "=", rec.user_id.id)], limit=1)
            if not emp and rec.partner_id:
                emp = Emp.search([
                    "|",
                    ("work_contact_id", "=", rec.partner_id.id),
                    ("user_id.partner_id", "=", rec.partner_id.id),
                ], limit=1)
            rec.neon_employee_id = emp

    def _neon_required_competencies(self):
        self.ensure_one()
        req = self.env["neon.hr.role.competency"].sudo().search(
            [("crew_role", "=", self.role), ("active", "=", True)], limit=1)
        return req.competency_ids

    def _neon_gate_eval(self):
        """Pure evaluation -> dict(state, message, block). Shared by the
        stored compute (display) and create/write enforcement."""
        self.ensure_one()
        emp = self.neon_employee_id
        role_req = self._neon_required_competencies()
        needs_licence = self.role == "driver"
        # Freelancer / no employee — cannot verify; warn, never block.
        if (needs_licence or role_req) and not emp:
            return {
                "state": "no_employee",
                "message": _(
                    "No employee record for %s — licence / competency "
                    "cannot be verified.") % (
                    self.partner_id.name or _("crew member")),
                "block": False}
        # Driver licence — HARD block, not override-able.
        if needs_licence and emp and not emp._has_valid_licence():
            return {
                "state": "licence_block",
                "message": _(
                    "%s has no valid driver licence on file — cannot be "
                    "assigned as Driver (legal/safety).") % emp.name,
                "block": True}
        # Competency gap (config-driven warn/block, override-able).
        if role_req and emp:
            missing = emp._missing_competencies(role_req)
            if missing:
                names = ", ".join(missing.mapped("name"))
                if self.neon_competency_override:
                    return {
                        "state": "overridden",
                        "message": _(
                            "Competency gap overridden by OD/MD: %s")
                        % names,
                        "block": False}
                mode = self.env["ir.config_parameter"].sudo().get_param(
                    GATE_MODE_PARAM, "warn")
                return {
                    "state": "competency_warning",
                    "message": _(
                        "%(emp)s is missing required competencies: %(c)s")
                    % {"emp": emp.name, "c": names},
                    "block": mode == "block"}
        return {"state": "ok", "message": _("Assignment cleared."),
                "block": False}

    @api.depends("role", "neon_competency_override", "neon_employee_id",
                 "neon_employee_id.is_driver",
                 "neon_employee_id.licence_ids.state",
                 "neon_employee_id.employee_competency_ids.state")
    def _compute_neon_gate(self):
        for rec in self:
            res = rec._neon_gate_eval()
            rec.neon_gate_state = res["state"]
            rec.neon_gate_message = res["message"]

    def _neon_enforce_gate(self):
        """Raise for the non-override-able licence block and for a
        competency gap in block mode (unless overridden); post a chatter
        warning otherwise. The licence block is unconditional."""
        for rec in self:
            res = rec._neon_gate_eval()
            if res["state"] == "licence_block":
                raise UserError(res["message"])
            if res["block"]:  # competency, block mode, not overridden
                raise UserError(_(
                    "%(msg)s  An OD/MD override is required to proceed.")
                    % {"msg": res["message"]})
            if res["state"] in ("competency_warning", "no_employee"):
                rec.message_post(
                    body=_("⚠️ Assignment gate: %s") % res["message"])
        return True

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._neon_enforce_gate()
        return recs

    def write(self, vals):
        res = super().write(vals)
        if {"role", "user_id", "partner_id",
                "neon_competency_override"} & set(vals):
            self._neon_enforce_gate()
        return res

    def action_neon_override_competency(self):
        """OD/MD-only override of the COMPETENCY gate (never licence)."""
        self.ensure_one()
        if not self.env.user.has_group("neon_core.group_neon_superuser"):
            raise UserError(_(
                "Only OD/MD (Neon Superuser) may override the competency "
                "gate."))
        self.neon_competency_override = True
        self.message_post(
            body=_("Competency gate overridden by %s.") % self.env.user.name)
        return True
