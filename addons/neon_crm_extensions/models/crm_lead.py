# -*- coding: utf-8 -*-
"""
Neon CRM Extensions — crm.lead inheritance.

Adds Phase 1 custom fields to leads/opportunities. Field names are
prefixed `x_` so they are easy to identify as custom and won't collide
with future Odoo upstream fields.
"""

from datetime import timedelta
from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = "crm.lead"

    # ────────────────────────────────────────────────────────────────
    # Round A — Simple stored fields (no computation)
    # ────────────────────────────────────────────────────────────────

    x_brand = fields.Selection(
        selection=[
            ("neonhiring", "Neon Hiring (equipment hire)"),
            ("neonevents", "Neon Events (full production)"),
        ],
        string="Brand",
        tracking=True,
        help="Which Neon brand this lead belongs to. Set during qualifying.",
    )

    x_consent_given = fields.Boolean(
        string="Marketing Consent (GDPR)",
        default=False,
        tracking=True,
        help="Has the contact given explicit consent for marketing communications?",
    )

    x_equipment_required = fields.Text(
        string="Equipment Required",
        help=(
            "Free-text list of equipment the client is asking about. "
            "Phase 1 hook for Phase 3's structured equipment allocation."
        ),
    )

    x_annual_event_month = fields.Selection(
        selection=[
            ("01", "January"),  ("02", "February"), ("03", "March"),
            ("04", "April"),    ("05", "May"),      ("06", "June"),
            ("07", "July"),     ("08", "August"),   ("09", "September"),
            ("10", "October"),  ("11", "November"), ("12", "December"),
        ],
        string="Annual Event Month",
        help=(
            "For Annual Client tagged contacts — the month their event "
            "typically happens. Drives the 9-month re-engagement check."
        ),
    )
    # ────────────────────────────────────────────────────────────────
    # Round F — Deduplication flag (set by daily scheduled action in §5)
    # ────────────────────────────────────────────────────────────────

    x_duplicate_flag = fields.Boolean(
        string="Possible Duplicate",
        default=False,
        copy=False,
        help=(
            "True when the daily deduplication check found another active lead "
            "with matching phone or email. Set by scheduled action — do not edit "
            "manually. Lead remains flagged until the underlying duplicate is "
            "merged or one record is archived/lost."
        ),
    )
    # ────────────────────────────────────────────────────────────────
    # Round B — SLA tracking datetime (set by message_post hook in §4)
    # ────────────────────────────────────────────────────────────────

    x_first_response_time = fields.Datetime(
        string="First Response Time",
        readonly=True,
        copy=False,
        help=(
            "Timestamp of the first outbound message from a Neon team member "
            "after the lead was created. Used by SLA breach computation."
        ),
    )
    # ────────────────────────────────────────────────────────────────
    # Round C — Computed fields (auto-derived, never set manually)
    # ────────────────────────────────────────────────────────────────

    x_sla_breached = fields.Boolean(
        string="SLA Breached",
        compute="_compute_sla_breached",
        store=True,
        help=(
            "True when the first response took longer than 2 hours after "
            "the lead was created. Auto-computed; do not set manually."
        ),
    )

    x_lead_score = fields.Integer(
        string="Lead Score",
        compute="_compute_lead_score",
        store=True,
        help=(
            "1-5 score auto-computed from expected_revenue x probability. "
            "Higher = more probable, higher value lead. Tune thresholds "
            "in the _compute_lead_score method when real data is available."
        ),
    )

    # ────────────────────────────────────────────────────────────────
    # Compute methods for Round C
    # ────────────────────────────────────────────────────────────────

    @api.depends("create_date", "x_first_response_time")
    def _compute_sla_breached(self):
        """Flag the lead as breaching SLA if first response > 2 hours."""
        sla_window = timedelta(hours=2)
        for lead in self:
            if lead.create_date and lead.x_first_response_time:
                elapsed = lead.x_first_response_time - lead.create_date
                lead.x_sla_breached = elapsed > sla_window
            else:
                lead.x_sla_breached = False

    @api.depends("expected_revenue", "probability")
    def _compute_lead_score(self):
        """Map probable revenue (revenue x probability) to a 1-5 score."""
        for lead in self:
            revenue = lead.expected_revenue or 0.0
            prob = lead.probability or 0.0
            probable_value = revenue * prob / 100.0
            if probable_value >= 10000:
                lead.x_lead_score = 5
            elif probable_value >= 5000:
                lead.x_lead_score = 4
            elif probable_value >= 2000:
                lead.x_lead_score = 3
            elif probable_value >= 500:
                lead.x_lead_score = 2
            else:
                lead.x_lead_score = 1
    
    # ────────────────────────────────────────────────────────────────
    # Combined alert ribbon (Round H+) — priority-aware ribbon driver
    # ────────────────────────────────────────────────────────────────

    x_alert_label = fields.Char(
        string="Alert Label",
        compute="_compute_alert",
        store=True,
        help="Display text for the unified alert ribbon. Auto-computed.",
    )

    x_alert_color = fields.Selection(
        selection=[
            ("none", "None"),
            ("warning", "Warning (yellow)"),
            ("danger", "Danger (red)"),
        ],
        string="Alert Color",
        compute="_compute_alert",
        store=True,
        default="none",
        help="Background colour of the unified alert ribbon. Auto-computed.",
    )

    @api.depends("x_sla_breached", "x_duplicate_flag")
    def _compute_alert(self):
        """Combine the two ribbon-worthy flags into a single label/color
        so they can share one web_ribbon slot. SLA dominates duplicate
        when both are true."""
        for lead in self:
            if lead.x_sla_breached and lead.x_duplicate_flag:
                lead.x_alert_label = "SLA + DUPLICATE"
                lead.x_alert_color = "danger"
            elif lead.x_sla_breached:
                lead.x_alert_label = "SLA Breached"
                lead.x_alert_color = "danger"
            elif lead.x_duplicate_flag:
                lead.x_alert_label = "Possible Duplicate"
                lead.x_alert_color = "warning"
            else:
                lead.x_alert_label = False
                lead.x_alert_color = "none"
    # ────────────────────────────────────────────────────────────────
    # SLA Tracking Hook (Section 4)
    # ────────────────────────────────────────────────────────────────

    def message_post(self, **kwargs):
        """Stamp x_first_response_time the first time an internal user
        posts a real message on this lead. The x_sla_breached compute
        recalculates automatically once the timestamp is set.
        """
        # Always call super first so the message actually gets posted
        message = super().message_post(**kwargs)

        # Only stamp on the first qualifying response
        for lead in self:
            if lead.x_first_response_time:
                continue
            if self.env.user.share:
                continue
            if not kwargs.get("body"):
                continue
            lead.x_first_response_time = fields.Datetime.now()

        return message
    # ────────────────────────────────────────────────────────────────
    # Deduplication detection (Section 5)
    # ────────────────────────────────────────────────────────────────

    @api.model
    def _neon_run_dedup_check(self):
        """Daily scheduled action — flag leads that share a phone or email
        with another active lead.

        Strategy:
        1. Fetch all active leads with at least a phone or email
        2. Build two lookup maps: normalised phone -> lead IDs, lowered email -> lead IDs
        3. Any phone or email mapping to 2+ leads marks all those leads as duplicates
        4. Leads that no longer match anything get their flag cleared
        """
        # 1. Fetch candidates
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            "|", ("phone", "!=", False), ("email_from", "!=", False),
        ])

        # 2. Build lookup maps
        phone_map = {}    # normalised phone -> set of lead IDs
        email_map = {}    # lowered email -> set of lead IDs

        for lead in leads:
            if lead.phone:
                normalised = self._neon_normalise_phone(lead.phone)
                if normalised:
                    phone_map.setdefault(normalised, set()).add(lead.id)
            if lead.email_from:
                lowered = lead.email_from.strip().lower()
                if lowered:
                    email_map.setdefault(lowered, set()).add(lead.id)

        # 3. Collect all duplicate IDs
        flagged_ids = set()
        for ids in phone_map.values():
            if len(ids) >= 2:
                flagged_ids.update(ids)
        for ids in email_map.values():
            if len(ids) >= 2:
                flagged_ids.update(ids)

        # 4. Update flags. Use sudo() to bypass any record rules; this is a
        # system-level scan that must see all leads regardless of ownership.
        all_active = self.search([("active", "=", True), ("type", "=", "opportunity")])
        to_flag = all_active.filtered(lambda r: r.id in flagged_ids)
        to_unflag = all_active.filtered(
            lambda r: r.id not in flagged_ids and r.x_duplicate_flag
        )
        if to_flag:
            to_flag.write({"x_duplicate_flag": True})
        if to_unflag:
            to_unflag.write({"x_duplicate_flag": False})

        return {
            "scanned": len(leads),
            "flagged": len(to_flag),
            "unflagged": len(to_unflag),
        }

    @api.model
    def _neon_normalise_phone(self, phone):
        """Strip non-digits, drop a leading 0 if present, drop a leading
        country code 263 if present. Used only for duplicate matching;
        does not modify the stored phone value."""
        if not phone:
            return ""
        # Keep only digits
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not digits:
            return ""
        # Drop leading country code 263 (Zimbabwe)
        if digits.startswith("263"):
            digits = digits[3:]
        # Drop leading 0
        if digits.startswith("0"):
            digits = digits[1:]
        return digits
    # ════════════════════════════════════════════════════════════════
    # Automation Rules (Section 6 — first wave, no WhatsApp dependency)
    # ════════════════════════════════════════════════════════════════
    #
    # Each rule is a private method that:
    #   - searches for matching crm.lead records
    #   - creates a mail.activity for each match (Round J)
    #   - skips records that already have an active activity of the same kind
    #   - logs a summary line at the end
    #
    # Activity duplication is prevented via summary-prefix matching: if a
    # lead already has an open activity whose summary starts with
    # "[Neon Rule N]" then we don't create another one. This is the
    # idempotency guard — daily reruns won't spam users.

    @api.model
    def _neon_recent_message_cutoff(self, days):
        """Return a datetime that is `days` ago from now."""
        return fields.Datetime.now() - timedelta(days=days)

    @api.model
    def _neon_last_message_before(self, lead, cutoff):
        """Return True if the lead's most recent mail.message is older
        than the cutoff datetime, OR if the lead has no messages at all
        (then we use create_date as a stand-in)."""
        last_message = self.env["mail.message"].search(
            [
                ("model", "=", "crm.lead"),
                ("res_id", "=", lead.id),
                ("message_type", "in", ("comment", "email")),
            ],
            order="date desc",
            limit=1,
        )
        if last_message:
            return last_message.date <= cutoff
        return lead.create_date and lead.create_date <= cutoff

    @api.model
    def _neon_has_open_activity(self, lead, summary_prefix):
        """Return True if the lead already has an open mail.activity whose
        summary starts with `summary_prefix`. Used to prevent duplicate
        activities when a rule re-fires."""
        existing = self.env["mail.activity"].search_count([
            ("res_model", "=", "crm.lead"),
            ("res_id", "=", lead.id),
            ("summary", "=like", summary_prefix + "%"),
        ])
        return existing > 0

    @api.model
    def _neon_create_activity(self, lead, summary, note, user_id, deadline_days=1):
        """Create a mail.activity on a lead record. Uses the generic
        'Mark Done' (TODO) activity type from mail.mail_activity_data_todo.
        Returns the created activity record."""
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not todo_type:
            return self.env["mail.activity"]
        return self.env["mail.activity"].create({
            "res_model_id": self.env.ref("crm.model_crm_lead").id,
            "res_id": lead.id,
            "activity_type_id": todo_type.id,
            "summary": summary,
            "note": note,
            "user_id": user_id,
            "date_deadline": fields.Date.today() + timedelta(days=deadline_days),
        })

    @api.model
    def _neon_md_user_id(self):
        """Return Munashe's user id for escalations. Falls back to the
        admin user if Munashe's account is not found (defensive)."""
        munashe = self.env["res.users"].search([("login", "=", "munashe@neonhiring.co.zw")], limit=1)
        if munashe:
            return munashe.id
        return self.env.ref("base.user_admin").id

    # --- Rule 3 -----------------------------------------------------

    @api.model
    def _neon_rule3_quote_followup_d3(self):
        """Rule 3 — leads at Quote Sent stage with no chatter for 3+ days.
        Creates a TODO activity for the assigned salesperson asking them
        to chase the client."""
        cutoff = self._neon_recent_message_cutoff(3)
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            ("stage_id.name", "=", "Quote Sent"),
            ("write_date", "<=", cutoff),
        ])
        matched = leads.filtered(lambda l: self._neon_last_message_before(l, cutoff))
        prefix = "[Neon Rule 3]"
        created = 0
        for lead in matched:
            if self._neon_has_open_activity(lead, prefix):
                continue
            self._neon_create_activity(
                lead=lead,
                summary=f"{prefix} Chase quote — Day 3",
                note=(
                    "<p>The quote you sent has had no client activity for 3 days. "
                    "Follow up with a friendly chase message.</p>"
                ),
                user_id=lead.user_id.id or self._neon_md_user_id(),
                deadline_days=1,
            )
            created += 1
        import logging
        logging.getLogger(__name__).info(
            "[Neon Rule 3] Quote followup D3: scanned %d, %d matched, %d activities created",
            len(leads), len(matched), created,
        )
        return matched

    # --- Rule 4 -----------------------------------------------------

    @api.model
    def _neon_rule4_quote_followup_d7(self):
        """Rule 4 — leads at Quote Sent with no chatter for 7+ days.
        Escalates to Munashe (MD), not the assigned salesperson."""
        cutoff = self._neon_recent_message_cutoff(7)
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            ("stage_id.name", "=", "Quote Sent"),
            ("write_date", "<=", cutoff),
        ])
        matched = leads.filtered(lambda l: self._neon_last_message_before(l, cutoff))
        prefix = "[Neon Rule 4]"
        created = 0
        md_id = self._neon_md_user_id()
        for lead in matched:
            if self._neon_has_open_activity(lead, prefix):
                continue
            self._neon_create_activity(
                lead=lead,
                summary=f"{prefix} Quote ESCALATION — Day 7",
                note=(
                    "<p><strong>Escalation:</strong> Quote has had no activity "
                    "for 7 days. Salesperson reminder fired at Day 3 and was "
                    "not actioned. Personal review recommended.</p>"
                ),
                user_id=md_id,
                deadline_days=1,
            )
            created += 1
        import logging
        logging.getLogger(__name__).info(
            "[Neon Rule 4] Quote followup D7 escalation: scanned %d, %d matched, %d activities created",
            len(leads), len(matched), created,
        )
        return matched

    # --- Rule 5 -----------------------------------------------------

    @api.model
    def _neon_rule5_stuck_deal(self):
        """Rule 5 — any active lead in any non-terminal stage with 7+ days
        of no chatter. Surfaced on Munashe's dashboard via activity."""
        cutoff = self._neon_recent_message_cutoff(7)
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            ("stage_id.name", "!=", "Confirmed"),
            ("probability", ">", 0),
            ("write_date", "<=", cutoff),
        ])
        matched = leads.filtered(lambda l: self._neon_last_message_before(l, cutoff))
        prefix = "[Neon Rule 5]"
        created = 0
        md_id = self._neon_md_user_id()
        for lead in matched:
            if self._neon_has_open_activity(lead, prefix):
                continue
            self._neon_create_activity(
                lead=lead,
                summary=f"{prefix} Stuck deal — review",
                note=(
                    "<p>This deal has had no activity for 7+ days and is still "
                    "open. Decide whether to push it forward or mark as Lost.</p>"
                ),
                user_id=md_id,
                deadline_days=2,
            )
            created += 1
        import logging
        logging.getLogger(__name__).info(
            "[Neon Rule 5] Stuck deal scan: scanned %d, %d matched, %d activities created",
            len(leads), len(matched), created,
        )
        return matched

    # --- Rule 8 -----------------------------------------------------

    @api.model
    def _neon_rule8_annual_client(self):
        """Rule 8 — leads tagged 'Annual Client' with no activity for
        9+ months (~270 days). Triggers a personal-outreach reminder
        for the original salesperson."""
        cutoff = self._neon_recent_message_cutoff(9 * 30)
        tag = self.env["crm.tag"].search([("name", "=", "Annual Client")], limit=1)
        if not tag:
            import logging
            logging.getLogger(__name__).warning(
                "[Neon Rule 8] No 'Annual Client' tag found — skipping run"
            )
            return self.browse()
        leads = self.search([
            ("type", "=", "opportunity"),
            ("tag_ids", "in", tag.id),
            ("write_date", "<=", cutoff),
        ])
        matched = leads.filtered(lambda l: self._neon_last_message_before(l, cutoff))
        prefix = "[Neon Rule 8]"
        created = 0
        for lead in matched:
            if self._neon_has_open_activity(lead, prefix):
                continue
            self._neon_create_activity(
                lead=lead,
                summary=f"{prefix} Annual client check-in",
                note=(
                    "<p>Annual client check-in due. Send a personal WhatsApp "
                    "or call — do <strong>not</strong> send a mass email.</p>"
                    "<p>Suggested message: 'Hi [Name], hope all is well — "
                    "your annual [event] should be coming up. Can we assist "
                    "with production this year?'</p>"
                ),
                user_id=lead.user_id.id or self._neon_md_user_id(),
                deadline_days=3,
            )
            created += 1
        import logging
        logging.getLogger(__name__).info(
            "[Neon Rule 8] Annual client re-engagement: scanned %d, %d matched, %d activities created",
            len(leads), len(matched), created,
        )
        return matched

    # --- Rule 9 -----------------------------------------------------

    @api.model
    def _neon_rule9_duplicate_warning(self):
        """Rule 9 — leads currently flagged as duplicates by Section 5's
        scheduled check. Creates a TODO activity asking the salesperson
        to investigate and merge or dismiss."""
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            ("x_duplicate_flag", "=", True),
        ])
        prefix = "[Neon Rule 9]"
        created = 0
        for lead in leads:
            if self._neon_has_open_activity(lead, prefix):
                continue
            self._neon_create_activity(
                lead=lead,
                summary=f"{prefix} Possible duplicate — review",
                note=(
                    "<p>This lead shares a phone or email with another active "
                    "lead. Open both records and decide whether to merge "
                    "(via the Action menu) or dismiss the warning.</p>"
                ),
                user_id=lead.user_id.id or self._neon_md_user_id(),
                deadline_days=1,
            )
            created += 1
        import logging
        logging.getLogger(__name__).info(
            "[Neon Rule 9] Duplicate warning: %d flagged leads, %d activities created",
            len(leads), created,
        )
        return leads