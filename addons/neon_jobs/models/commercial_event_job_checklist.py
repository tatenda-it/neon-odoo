# -*- coding: utf-8 -*-
"""
P3.M5 — Checklist Library (instance side).

Each commercial.event.job carries 9 commercial.event.job.checklist
records (one per type), auto-created when the event_job is created.
Items are snapshotted from the matching template at creation time
so later template edits don't retroactively change in-flight events.

Authority on item check is enforced via a write override that
resolves ownership_role on the parent instance against the calling
user. The role was captured at instance create time so the rules
don't shift mid-event even if the type→role map is reconfigured.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .commercial_checklist_template import (
    CHECKLIST_TYPES,
    OWNERSHIP_ROLES,
)


CHECKLIST_STATES = [
    ("not_started", "Not Started"),
    ("in_progress", "In Progress"),
    ("completed",   "Completed"),
    ("na",          "Not Applicable"),
]
_NA = "na"
_DONE = "completed"
_IN_PROGRESS = "in_progress"
_NOT_STARTED = "not_started"


class CommercialEventJobChecklist(models.Model):
    _name = "commercial.event.job.checklist"
    _description = "Event Job Checklist Instance"
    _inherit = ["mail.thread"]
    _order = "event_job_id, sequence, id"

    event_job_id = fields.Many2one(
        "commercial.event.job",
        string="Event Job",
        required=True,
        ondelete="cascade",
        index=True,
    )
    type = fields.Selection(
        CHECKLIST_TYPES,
        string="Type",
        required=True,
        readonly=True,
    )
    template_id = fields.Many2one(
        "commercial.checklist.template",
        string="Source Template",
        readonly=True,
        help="Template the items were snapshotted from. Edits to "
        "the template do NOT propagate to this instance.",
    )
    ownership_role = fields.Selection(
        OWNERSHIP_ROLES,
        string="Ownership Role",
        required=True,
        readonly=True,
        help="Captured at instance create time. Determines who is "
        "authorised to tick items on this checklist.",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    state = fields.Selection(
        CHECKLIST_STATES,
        string="State",
        default=_NOT_STARTED,
        required=True,
        tracking=True,
    )
    na_reason = fields.Text(
        string="N/A Reason",
        tracking=True,
        help="Why this checklist doesn't apply to this event. "
        "Required when state='na'.",
    )
    item_ids = fields.One2many(
        "commercial.event.job.checklist.item",
        "checklist_id",
        string="Items",
    )
    total_count = fields.Integer(
        string="Total Items",
        compute="_compute_counts",
        store=True,
    )
    completed_count = fields.Integer(
        string="Completed Items",
        compute="_compute_counts",
        store=True,
        help="Counts items that are either is_checked=True OR "
        "is_na=True (with reason).",
    )
    completion_ratio = fields.Float(
        string="Completion Ratio",
        compute="_compute_counts",
        store=True,
        help="(checked + n/a) / total. 0.0 when no items.",
    )
    completion_pct = fields.Float(
        string="Completion %",
        compute="_compute_counts",
        store=True,
    )
    completed_at = fields.Datetime(string="Completed At", readonly=True)
    completed_by = fields.Many2one("res.users", string="Completed By", readonly=True)

    @api.depends("item_ids", "item_ids.is_checked", "item_ids.is_na")
    def _compute_counts(self):
        for rec in self:
            total = len(rec.item_ids)
            done = len(rec.item_ids.filtered(lambda i: i.is_checked or i.is_na))
            rec.total_count = total
            rec.completed_count = done
            rec.completion_ratio = (done / total) if total else 0.0
            rec.completion_pct = rec.completion_ratio * 100.0

    @api.constrains("state", "na_reason")
    def _check_na_reason(self):
        for rec in self:
            if rec.state == _NA and not (rec.na_reason and rec.na_reason.strip()):
                raise ValidationError(_(
                    "An N/A checklist must record a reason. "
                    "Provide one before marking '%s' as Not Applicable."
                ) % (dict(CHECKLIST_TYPES).get(rec.type) or rec.type))

    def _user_in_any_group(self, group_keys):
        from .commercial_event_job import _GROUP_XMLIDS
        return any(
            self.env.user.has_group(_GROUP_XMLIDS[k]) for k in group_keys
        )

    def _is_event_crew_chief(self):
        self.ensure_one()
        chief = self.event_job_id.crew_chief_id
        return bool(chief and chief.id == self.env.uid)

    def _check_item_authority(self):
        """Authority gate for ticking / un-ticking items on this
        checklist. Raises UserError on fail. Manager always passes.
        Crew Leader passes for all owned roles. Crew Chief passes
        only for crew_chief-owned checklists where they are the
        crew_chief on the underlying event_job.
        """
        self.ensure_one()
        if self._user_in_any_group(("manager", "crew_leader")):
            return True
        if self.ownership_role == "crew_chief" and self._is_event_crew_chief():
            return True
        role_label = dict(OWNERSHIP_ROLES).get(self.ownership_role) or self.ownership_role
        raise UserError(_(
            "You are not authorised to tick items on this checklist "
            "(ownership role: %(role)s). Required: %(req)s."
        ) % {
            "role": role_label,
            "req": "Manager or Crew Leader" if self.ownership_role != "crew_chief"
                   else "Crew Chief on this event, or Manager / Crew Leader",
        })

    def _refresh_state_from_items(self):
        """Auto-transition state based on item progress. Locked when
        state='na' — only an explicit action can move out of N/A.

        Elevated with sudo() because crew tier (who can legitimately
        tick items on crew_chief-owned checklists via the item-side
        authority gate) lacks direct write ACL on the parent
        checklist instance. The item write hook is a system-driven
        side effect, not direct user mutation; chatter attribution
        keeps the real user via author_id implicitly.
        """
        for rec in self:
            if rec.state == _NA:
                continue
            total = rec.total_count
            done = rec.completed_count
            if total == 0 or done == 0:
                new_state = _NOT_STARTED
            elif done < total:
                new_state = _IN_PROGRESS
            else:
                new_state = _DONE
            if new_state != rec.state:
                vals = {"state": new_state}
                if new_state == _DONE:
                    vals.update({
                        "completed_at": fields.Datetime.now(),
                        "completed_by": self.env.user.id,
                    })
                elif rec.state == _DONE:
                    vals.update({"completed_at": False, "completed_by": False})
                rec.sudo().write(vals)

    def action_mark_na(self, reason=None):
        """Manager / Crew Leader marks a checklist Not Applicable
        for this event. Requires a written reason which lands in
        chatter."""
        if reason is None:
            reason = self.env.context.get("default_na_reason")
        if not reason or not str(reason).strip():
            raise UserError(_(
                "An N/A reason is required to mark a checklist as "
                "Not Applicable. Open the wizard or pass a reason."
            ))
        if not self._user_in_any_group(("manager", "crew_leader")):
            raise UserError(_(
                "Only Manager or Crew Leader can mark a checklist "
                "Not Applicable."
            ))
        reason = str(reason).strip()
        for rec in self:
            rec.write({"state": _NA, "na_reason": reason})
            rec.message_post(body=_(
                "Checklist marked Not Applicable by %(user)s. "
                "Reason: %(reason)s"
            ) % {"user": self.env.user.name, "reason": reason})
        return True

    def action_unmark_na(self):
        """Pull a checklist back out of N/A. Authority same as
        mark_na. Resets state to derived value from item progress."""
        if not self._user_in_any_group(("manager", "crew_leader")):
            raise UserError(_(
                "Only Manager or Crew Leader can clear an N/A "
                "checklist."
            ))
        for rec in self:
            rec.write({"state": _NOT_STARTED, "na_reason": False})
            rec.message_post(
                body=_("Checklist N/A cleared by %s.") % self.env.user.name
            )
            rec._refresh_state_from_items()
        return True


class CommercialEventJobChecklistItem(models.Model):
    _name = "commercial.event.job.checklist.item"
    _description = "Event Job Checklist Item"
    _order = "checklist_id, sequence, id"

    checklist_id = fields.Many2one(
        "commercial.event.job.checklist",
        string="Checklist",
        required=True,
        ondelete="cascade",
        index=True,
    )
    template_item_id = fields.Many2one(
        "commercial.checklist.template.item",
        string="Template Item",
        readonly=True,
        ondelete="set null",
        help="Lineage pointer back to the template row this item "
        "was snapshotted from. Edits to the template item do NOT "
        "propagate to this instance row.",
    )
    sequence = fields.Integer(string="Sequence", default=10)
    name = fields.Char(string="Step", required=True, readonly=True)
    photo_required = fields.Boolean(
        string="Photo Required",
        readonly=True,
    )
    is_checked = fields.Boolean(string="Done", default=False)
    is_na = fields.Boolean(string="N/A", default=False)
    na_reason = fields.Char(string="N/A Reason")
    photo_attachment_ids = fields.Many2many(
        "ir.attachment",
        "event_checklist_item_attachment_rel",
        "item_id",
        "attachment_id",
        string="Photo Attachments",
    )
    checked_by = fields.Many2one("res.users", string="Checked By", readonly=True)
    checked_at = fields.Datetime(string="Checked At", readonly=True)
    notes = fields.Text(string="Notes")

    @api.constrains("is_na", "na_reason")
    def _check_na_reason(self):
        for rec in self:
            if rec.is_na and not (rec.na_reason and rec.na_reason.strip()):
                raise ValidationError(_(
                    "Item '%s' is marked N/A — please record why."
                ) % (rec.name or _("(unnamed)")))

    @api.constrains("is_checked", "photo_required", "photo_attachment_ids")
    def _check_photo_required(self):
        for rec in self:
            if (
                rec.is_checked
                and rec.photo_required
                and not rec.photo_attachment_ids
            ):
                raise ValidationError(_(
                    "Item '%s' requires photo proof before it can "
                    "be marked done. Attach a photo and try again."
                ) % (rec.name or _("(unnamed)")))

    @api.constrains("is_checked", "is_na")
    def _check_not_both(self):
        for rec in self:
            if rec.is_checked and rec.is_na:
                raise ValidationError(_(
                    "Item '%s' cannot be both Done and N/A — pick one."
                ) % (rec.name or _("(unnamed)")))

    def write(self, vals):
        check_authority = bool({"is_checked", "is_na", "na_reason"} & set(vals))
        if check_authority:
            for rec in self:
                if rec.checklist_id.state == _NA:
                    raise UserError(_(
                        "Cannot edit items on a checklist that is "
                        "marked Not Applicable. Clear N/A first."
                    ))
                rec.checklist_id._check_item_authority()
        if vals.get("is_checked") and not vals.get("checked_by"):
            vals = dict(vals,
                        checked_by=self.env.user.id,
                        checked_at=fields.Datetime.now())
        if "is_checked" in vals and vals["is_checked"] is False:
            vals = dict(vals, checked_by=False, checked_at=False)
        res = super().write(vals)
        if {"is_checked", "is_na"} & set(vals):
            self.mapped("checklist_id")._refresh_state_from_items()
        return res
