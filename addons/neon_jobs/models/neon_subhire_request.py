# -*- coding: utf-8 -*-
"""P-B4 -- Sub-hire request header.

Lifecycle: draft → generated → reviewed → approved → sent.
`superseded` is a branch state set when a newer revision replaces
this one (mirror B3-D7 single-active-with-revision-supersedes).

⚠️ DECISION (B4, D1): new model neon.subhire.request in
neon_jobs. perm_unlink=0 (audit). Mirror B3-D7 supersede pattern.

⚠️ DECISION (B4, D6): the "Approve + Create PO Draft" action
creates a purchase.order in state='draft'. B4 NEVER confirms or
sends the PO -- that lives in Odoo's standard Purchase Orders
menu for separation of concerns. The "Mark Sent" action on the
subhire.request is metadata-only -- it records that the user
took the action OUTSIDE the system; it does NOT touch the PO
state. Issuing a PO is spend (RED) -- the system stops at draft.

⚠️ DECISION (B4, D7): supplier_partner_id is required for
approval but NEVER auto-assigned. The form gives the user a
filtered dropdown (supplier_rank>0) and an empty-state amber
banner if no candidates exist.

⚠️ DECISION (B4, D9): neon_jobs depends on `purchase` (added at
B4) so the standard purchase.order + purchase.order.line models
are available. `-u neon_jobs` triggers `-i purchase` if not yet
installed.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


_REQUEST_STATUSES = [
    ("draft", "Draft"),
    ("generated", "Generated"),
    ("reviewed", "Reviewed"),
    ("approved", "Approved"),
    ("sent", "Sent"),
    ("superseded", "Superseded"),
]


class NeonSubhireRequest(models.Model):
    _name = "neon.subhire.request"
    _description = "Sub-hire request (B4)"
    _inherit = ["mail.thread"]
    _order = "event_job_id, revision desc, id desc"

    # === Identity ===
    name = fields.Char(
        compute="_compute_name", store=True, readonly=True,
        index=True,
    )
    event_job_id = fields.Many2one(
        "commercial.event.job", required=True, index=True,
        ondelete="cascade", tracking=True,
    )
    revision = fields.Integer(
        required=True, default=1, readonly=True, tracking=True,
        help="Auto-incremented on regenerate. revision=1 is the "
             "first; next regen creates revision=2 and the prior "
             "moves to 'superseded'.",
    )

    # === Lifecycle ===
    status = fields.Selection(
        _REQUEST_STATUSES, required=True, default="draft",
        readonly=True, tracking=True, index=True,
    )

    # === Audit timestamps + actors ===
    generated_at = fields.Datetime(readonly=True, tracking=True)
    generated_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    reviewed_at = fields.Datetime(readonly=True, tracking=True)
    reviewed_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    approved_at = fields.Datetime(readonly=True, tracking=True)
    approved_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    sent_at = fields.Datetime(readonly=True, tracking=True)
    sent_by_id = fields.Many2one(
        "res.users", readonly=True, tracking=True)
    superseded_at = fields.Datetime(readonly=True, tracking=True)
    superseded_by_request_id = fields.Many2one(
        "neon.subhire.request", readonly=True, ondelete="set null",
        help="The newer request that superseded this one.",
    )

    # === Snapshot of the B2 conflict the request was generated from ===
    source_conflict_id = fields.Many2one(
        "neon.equipment.conflict", readonly=True,
        ondelete="set null",
        help="The B2 conflict run consumed at generation. Snapshot "
             "pointer; facts are frozen in draft_json.",
    )
    source_conflict_window_start = fields.Datetime(readonly=True)
    source_conflict_window_end = fields.Datetime(readonly=True)

    # === Generated content ===
    draft_json = fields.Text(
        readonly=True,
        help="Strict-JSON Claude output, validated against the "
             "fact-gather. Stored verbatim.",
    )
    draft_summary_html = fields.Html(
        compute="_compute_draft_summary_html",
        store=True, readonly=True, sanitize=False,
        help="Rendered HTML view of draft_json (on-screen).",
    )
    enquiry_subject = fields.Char(
        compute="_compute_enquiry_fields", store=True, readonly=True,
        help="Subject line extracted from draft_json for the "
             "supplier enquiry email/message.",
    )
    enquiry_body = fields.Text(
        compute="_compute_enquiry_fields", store=True, readonly=True,
        help="Body extracted from draft_json -- this is what the "
             "user copy-pastes to the supplier or attaches to the "
             "PO when sending.",
    )
    data_quality_note = fields.Text(
        readonly=True,
        help="Carried verbatim from B2 when load-in/out is imprecise.",
    )

    # === Supplier + PO link (B4-D7 + D6) ===
    supplier_partner_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        domain="[('supplier_rank', '>', 0)]",
        tracking=True,
        help="MUST be chosen by a human before approving. The "
             "form filters to partners with supplier_rank > 0 "
             "(Vendor=True). If none exist, the form shows an "
             "amber banner -- add a Vendor partner first.",
    )
    has_supplier_candidates = fields.Boolean(
        compute="_compute_has_supplier_candidates", store=False,
        help="True when at least one res.partner has "
             "supplier_rank > 0. Drives the empty-state banner "
             "on the form.",
    )
    po_draft_id = fields.Many2one(
        "purchase.order",
        string="PO Draft",
        readonly=True, ondelete="set null", tracking=True,
        help="The purchase.order created in state='draft' by the "
             "Approve action. Confirming/sending the PO happens "
             "via Odoo's standard Purchase Orders menu -- B4 "
             "never auto-confirms.",
    )

    # === B13 usage snapshot ===
    model_used = fields.Char(readonly=True)
    prompt_tokens = fields.Integer(readonly=True)
    completion_tokens = fields.Integer(readonly=True)
    latency_ms = fields.Integer(readonly=True)

    # === Error / quarantine state ===
    error_message = fields.Text(readonly=True)
    quarantine_json = fields.Text(
        readonly=True,
        help="On SubhireValidationError after retry, the Claude "
             "output that contradicted the facts is parked here. "
             "Never rendered to users.",
    )

    # === Helpers / display ===
    line_ids = fields.One2many(
        "neon.subhire.request.line", "request_id",
        string="Sub-hire lines",
    )
    line_count = fields.Integer(
        compute="_compute_line_counts", store=True, readonly=True)
    is_active = fields.Boolean(
        compute="_compute_is_active", store=True, readonly=True,
        index=True,
    )

    _sql_constraints = [
        ("revision_positive",
         "CHECK (revision > 0)",
         "Sub-hire request revision must be a positive integer."),
        ("event_revision_unique",
         "UNIQUE (event_job_id, revision)",
         "A given event_job cannot have two sub-hire requests "
         "with the same revision number."),
    ]

    # ============================================================
    # Computed
    # ============================================================
    @api.depends("event_job_id.name", "revision")
    def _compute_name(self):
        for rec in self:
            ev_name = rec.event_job_id.name or "?"
            rec.name = "SUBHIRE-{ev}-r{rev}".format(
                ev=ev_name, rev=rec.revision or 0)

    @api.depends("status")
    def _compute_is_active(self):
        for rec in self:
            rec.is_active = rec.status not in ("superseded", "draft")

    @api.depends("line_ids")
    def _compute_line_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends("draft_json")
    def _compute_enquiry_fields(self):
        import json as _json
        for rec in self:
            subject = body = ""
            if rec.draft_json:
                try:
                    payload = _json.loads(rec.draft_json) or {}
                    subject = payload.get("enquiry_subject") or ""
                    body = payload.get("enquiry_body") or ""
                except (ValueError, TypeError):
                    pass
            rec.enquiry_subject = subject
            rec.enquiry_body = body

    @api.depends("draft_json", "data_quality_note", "status",
                 "supplier_partner_id", "po_draft_id")
    def _compute_draft_summary_html(self):
        from .subhire_request_renderer import (
            render_subhire_summary_html,
        )
        for rec in self:
            rec.draft_summary_html = render_subhire_summary_html(
                rec.draft_json,
                rec.data_quality_note,
                rec.status,
                rec.supplier_partner_id.name
                if rec.supplier_partner_id else "",
                rec.po_draft_id.name if rec.po_draft_id else "",
            )

    def _compute_has_supplier_candidates(self):
        Partner = self.env["res.partner"].sudo()
        n = Partner.search_count([("supplier_rank", ">", 0)])
        for rec in self:
            rec.has_supplier_candidates = n > 0

    # ============================================================
    # State-machine action buttons
    # ============================================================
    def action_mark_reviewed(self):
        """generated -> reviewed."""
        for rec in self:
            if rec.status != "generated":
                raise UserError(_(
                    "Request must be in 'Generated' state to mark "
                    "as reviewed. Current status: %(s)s"
                ) % {"s": rec.status})
            rec.sudo().write({
                "status": "reviewed",
                "reviewed_at": fields.Datetime.now(),
                "reviewed_by_id": self.env.uid,
            })
        return True

    def action_approve_and_create_po(self):
        """reviewed -> approved. Creates a purchase.order in
        state='draft' (B4-D6). Requires supplier_partner_id set
        (B4-D7). Refuses if no supplier or if a PO already exists
        for this request."""
        for rec in self:
            if rec.status != "reviewed":
                raise UserError(_(
                    "Request must be in 'Reviewed' state to "
                    "approve. Current: %(s)s") % {"s": rec.status})
            if not rec.supplier_partner_id:
                raise UserError(_(
                    "Pick a supplier (Vendor partner) before "
                    "approving. The form's dropdown filters to "
                    "partners with supplier_rank > 0; if empty, "
                    "add one via Contacts -> New Vendor first."))
            if rec.po_draft_id:
                raise UserError(_(
                    "A PO draft already exists for this request "
                    "(%(po)s). Regenerate the request if you need "
                    "a different supplier."
                ) % {"po": rec.po_draft_id.name})
            from .subhire_po_draft_builder import (
                SubhirePoDraftBuilder,
            )
            po = SubhirePoDraftBuilder(self.env).build(rec)
            rec.sudo().write({
                "status": "approved",
                "approved_at": fields.Datetime.now(),
                "approved_by_id": self.env.uid,
                "po_draft_id": po.id,
            })
        return True

    def action_mark_sent(self):
        """approved -> sent. METADATA ONLY -- does NOT confirm
        the PO. B4-D6 holds: PO confirmation is the user's
        explicit click in Odoo's standard Purchase Orders menu."""
        for rec in self:
            if rec.status != "approved":
                raise UserError(_(
                    "Request must be in 'Approved' state to mark "
                    "as sent. Current: %(s)s") % {"s": rec.status})
            rec.sudo().write({
                "status": "sent",
                "sent_at": fields.Datetime.now(),
                "sent_by_id": self.env.uid,
            })
        return True

    def action_regenerate(self):
        """Spawn a new revision + supersede this one. Blocked on
        'sent' (un-send via manager action first)."""
        self.ensure_one()
        if self.status == "sent":
            raise UserError(_(
                "Un-send this request first (manager-only action) "
                "before regenerating. Sent requests are locked."))
        from .subhire_request_generator import (
            SubhireRequestGenerator,
        )
        new_req = SubhireRequestGenerator(
            self.env).generate_for_event(
                self.event_job_id, replaces=self)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.subhire.request",
            "res_id": new_req.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_unsend(self):
        """sent -> approved. Manager-only override (form view's
        groups_id gates the button)."""
        for rec in self:
            if rec.status != "sent":
                raise UserError(_(
                    "Request must be 'Sent' to un-send. Current: "
                    "%(s)s") % {"s": rec.status})
            rec.sudo().write({
                "status": "approved",
                "sent_at": False,
                "sent_by_id": False,
            })
        return True

    @api.model
    def action_generate_for_event(self, event_job_id):
        """Smart-button entry point from the event_job form."""
        EvJ = self.env["commercial.event.job"]
        ev = EvJ.browse(int(event_job_id)).exists()
        if not ev:
            raise UserError(_(
                "Event job not found (id=%(i)s).") % {
                    "i": event_job_id})
        existing = self.search([
            ("event_job_id", "=", ev.id),
            ("status", "not in", ("superseded", "draft")),
        ], order="revision desc", limit=1)
        if existing:
            return {
                "type": "ir.actions.act_window",
                "res_model": "neon.subhire.request",
                "res_id": existing.id,
                "view_mode": "form",
                "target": "current",
            }
        from .subhire_request_generator import (
            SubhireRequestGenerator,
        )
        new_req = SubhireRequestGenerator(self.env).generate_for_event(
            ev)
        return {
            "type": "ir.actions.act_window",
            "res_model": "neon.subhire.request",
            "res_id": new_req.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_open_po_draft(self):
        """Open the linked draft PO in the standard Purchase form."""
        self.ensure_one()
        if not self.po_draft_id:
            raise UserError(_("No PO draft linked yet."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "res_id": self.po_draft_id.id,
            "view_mode": "form",
            "target": "current",
        }
