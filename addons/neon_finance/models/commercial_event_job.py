# -*- coding: utf-8 -*-
"""P6.M5 -- commercial.event.job extension (Schema Sketch §6.3).

Adds the cost side to the existing event_job model: cost_line_ids
reverse o2m, per-currency cost totals (USD + ZWG kept separate per
the cross-currency H1 design-pause decision), initial + quoted
budget tracking, margin compute, budget variance, and the rendered
P&L mini-statement HTML.

⚠️ DECISION (P6.M5, pre-approved): the P&L is computed as an HTML
string and surfaced via a Char field with widget="html" readonly=True
on the form. QWeb templates would be more flexible long-term but the
HTML-compute is simpler, easier to test, and reads cleanly across
the USD/ZWG currency split.

⚠️ DECISION (P6.M5, pre-approved): cross-currency cost handling is
explicit, not silent. cost_total_usd and cost_total_zig are
separate stored sums. The headline margin (margin_gross / margin_pct)
is computed in the quote's currency; cross-currency contributions
appear as labelled rows in the P&L view so finance can see what got
billed in which currency without invisible FX conversion.
"""
from odoo import _, api, fields, models


class CommercialEventJob(models.Model):
    _inherit = "commercial.event.job"

    # ============================================================
    # === Cost line linkage + per-currency aggregates
    # ============================================================
    cost_line_ids = fields.One2many(
        "neon.finance.cost.line",
        "event_job_id",
        string="Cost Lines",
    )
    cost_total_usd = fields.Monetary(
        compute="_compute_cost_totals",
        store=True,
        currency_field="_usd_currency_id",
        help="Sum of cost.line.amount where currency_id == USD. "
        "Per-currency separation chosen over silent FX conversion -- "
        "finance can see what got billed in which currency.",
    )
    cost_total_zig = fields.Monetary(
        compute="_compute_cost_totals",
        store=True,
        currency_field="_zig_currency_id",
        help="Sum of cost.line.amount where currency_id == ZWG. "
        "Companion to cost_total_usd.",
    )

    # Helper currency m2o for the Monetary widgets above. These are
    # bare Many2one fields (no store) computed at access time. Without
    # them the per-currency Monetary widgets have no currency context.
    _usd_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_helper_currencies",
        help="Resolves to base.USD; backs cost_total_usd's widget.",
    )
    _zig_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_helper_currencies",
        help="Resolves to ZWG; backs cost_total_zig's widget.",
    )

    # ============================================================
    # === Budgets (initial entered by salesperson + quoted from quote)
    # ============================================================
    initial_budget = fields.Monetary(
        currency_field="initial_budget_currency_id",
        help="Rough cost+margin target entered by the salesperson at "
        "event_job creation, before quoting. Used to compute "
        "budget_variance_initial alongside the actual quoted_budget.",
    )
    initial_budget_currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.ref(
            "base.USD", raise_if_not_found=False),
        string="Initial Budget Currency",
    )
    quoted_budget = fields.Monetary(
        currency_field="quoted_budget_currency_id",
        readonly=True,
        copy=False,
        help="Auto-stamped from quote.amount_total when the quote "
        "transitions to 'accepted' (see quote.action_accept). Null "
        "until then. Multi-quote events: the latest accept wins.",
    )
    quoted_budget_currency_id = fields.Many2one(
        "res.currency",
        readonly=True,
        copy=False,
        string="Quoted Budget Currency",
    )

    # ============================================================
    # === Margin + variance (all monetary fields in quoted_budget's
    # === currency for the headline; cross-currency contributions
    # === show up in the P&L view body)
    # ============================================================
    margin_gross = fields.Monetary(
        compute="_compute_margin",
        store=True,
        currency_field="quoted_budget_currency_id",
        help="Revenue (quoted_budget) minus same-currency cost total. "
        "Cross-currency cost contributions DO NOT enter this headline "
        "figure -- see the P&L view for the full breakdown.",
    )
    margin_pct = fields.Float(
        compute="_compute_margin",
        store=True,
        digits=(5, 2),
    )
    budget_variance_initial = fields.Monetary(
        compute="_compute_variance",
        store=True,
        currency_field="initial_budget_currency_id",
        help="Same-currency-cost minus initial_budget. Negative means "
        "actual costs were under the rough target.",
    )
    budget_variance_quoted = fields.Monetary(
        compute="_compute_variance",
        store=True,
        currency_field="quoted_budget_currency_id",
        help="Same-currency-cost minus quoted_budget. Negative means "
        "actual costs were under the quoted figure (margin upside).",
    )

    pnl_html = fields.Html(
        string="Financial Summary",
        compute="_compute_pnl_html",
        sanitize=False,
        help="Rendered HTML mini-statement showing revenue lines, "
        "cost lines, and margin/variance figures. Computed at access "
        "time -- always reflects current cost_line_ids state.",
    )

    # ============================================================
    # === P6.M6 budget alert tracking
    # ============================================================
    budget_alert_level = fields.Selection(
        [
            ("ok", "On Budget"),
            ("warn", "Warning"),
            ("breach", "Over Budget"),
            ("severe", "Severely Over Budget"),
        ],
        compute="_compute_budget_alert_level",
        store=True,
        readonly=True,
        copy=False,
        index=True,
        default="ok",
        help="Derived from cost_total vs quoted_budget. Thresholds "
        "are configured via Settings > Budget Alerts (Neon): warn / "
        "breach / severe pct defaults 80 / 100 / 120. 'ok' when "
        "quoted_budget is null (no accepted quote to compare against).",
    )
    last_alert_dispatched_at = fields.Datetime(
        readonly=True,
        copy=False,
        help="Timestamp of the last mail.activity dispatched for this "
        "event_job's budget level. Used by the write() override to "
        "implement a 1-hour idempotency window -- prevents alert "
        "storms during bulk cost imports at the same level.",
    )
    suggest_reapproval = fields.Boolean(
        default=False,
        copy=False,
        help="Set to True automatically when budget_alert_level "
        "reaches 'severe'. Surfaces as a banner on the event_job "
        "form prompting Robin / Munashe to consider re-quote and "
        "re-approval. Manually flippable by approvers; cleared by "
        "the Acknowledge over-budget button.",
    )

    # ============================================================
    # === Computes
    # ============================================================
    @api.depends()
    def _compute_helper_currencies(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        for rec in self:
            rec._usd_currency_id = usd
            rec._zig_currency_id = zwg

    @api.depends("cost_line_ids.amount", "cost_line_ids.currency_id")
    def _compute_cost_totals(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        for rec in self:
            usd_sum = sum(
                rec.cost_line_ids.filtered(
                    lambda l: l.currency_id == usd
                ).mapped("amount")
            )
            zig_sum = sum(
                rec.cost_line_ids.filtered(
                    lambda l: l.currency_id == zwg
                ).mapped("amount")
            )
            rec.cost_total_usd = usd_sum
            rec.cost_total_zig = zig_sum

    @api.depends("cost_total_usd", "cost_total_zig",
                 "quoted_budget", "quoted_budget_currency_id")
    def _compute_margin(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        for rec in self:
            # Same-currency margin only; cross-currency contributions
            # are surfaced separately in the P&L view body.
            if rec.quoted_budget_currency_id == usd:
                same_currency_cost = rec.cost_total_usd
            elif rec.quoted_budget_currency_id == zwg:
                same_currency_cost = rec.cost_total_zig
            else:
                same_currency_cost = 0.0
            rec.margin_gross = rec.quoted_budget - same_currency_cost
            if rec.quoted_budget:
                rec.margin_pct = (
                    rec.margin_gross / rec.quoted_budget * 100.0)
            else:
                rec.margin_pct = 0.0

    @api.depends("cost_total_usd", "cost_total_zig",
                 "initial_budget", "initial_budget_currency_id",
                 "quoted_budget", "quoted_budget_currency_id")
    def _compute_variance(self):
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        for rec in self:
            # variance_initial uses the initial budget's currency
            if rec.initial_budget_currency_id == usd:
                rec.budget_variance_initial = (
                    rec.cost_total_usd - rec.initial_budget)
            elif rec.initial_budget_currency_id == zwg:
                rec.budget_variance_initial = (
                    rec.cost_total_zig - rec.initial_budget)
            else:
                rec.budget_variance_initial = 0.0
            # variance_quoted uses the quoted budget's currency
            if rec.quoted_budget_currency_id == usd:
                rec.budget_variance_quoted = (
                    rec.cost_total_usd - rec.quoted_budget)
            elif rec.quoted_budget_currency_id == zwg:
                rec.budget_variance_quoted = (
                    rec.cost_total_zig - rec.quoted_budget)
            else:
                rec.budget_variance_quoted = 0.0

    @api.depends("cost_line_ids", "cost_line_ids.amount",
                 "cost_line_ids.currency_id", "cost_line_ids.cost_type",
                 "cost_total_usd", "cost_total_zig",
                 "quoted_budget", "quoted_budget_currency_id",
                 "initial_budget", "margin_gross", "margin_pct",
                 "budget_variance_initial", "budget_variance_quoted")
    def _compute_pnl_html(self):
        """Render the P&L mini-statement per Schema Sketch §6.2. Pure
        HTML string; no QWeb template indirection. Three blocks:
        REVENUE (from related quote(s)), COST (per cost_type x
        currency), and MARGIN (headline + variance).
        """
        # ⚠️ DECISION (P6.M6 follow-up to M5 P&L): the pnl_html compute
        # reads neon.finance.quote, but users with event_job access via
        # operational groups (Lead Tech / Manager / Crew) don't have R
        # on neon.finance.quote at the ACL layer. The P&L view is a
        # derived financial summary that anyone with event_job read
        # should see, so we sudo() the quote search. requesting user's
        # identity is preserved for the compute itself.
        Quote = self.env["neon.finance.quote"].sudo()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        # Cache the cost_type label dict outside the loop.
        cost_type_labels = dict(
            self.env["neon.finance.cost.line"]
                ._fields["cost_type"].selection)
        for rec in self:
            # Headline currency for the revenue + margin block --
            # pick the quoted_budget_currency_id, fall back to the
            # event_job's own currency_id (related from commercial_job),
            # else USD.
            head_currency = (
                rec.quoted_budget_currency_id
                or rec.currency_id
                or usd
            )
            sym = head_currency.symbol or head_currency.name
            # Locate the active (non-rejected, non-cancelled,
            # non-expired) quote on this event_job. Latest by create
            # date.
            quote = Quote.search([
                ("event_job_id", "=", rec.id),
                ("state", "not in",
                 ("rejected", "expired", "cancelled")),
            ], order="create_date desc", limit=1)

            parts = []
            parts.append("<div class='o_pnl_mini_statement'>")

            # --- REVENUE block (driven by quote) ----------
            parts.append(
                "<h4 style='margin-bottom:6px;'>Revenue (%s)</h4>"
                % head_currency.name)
            if quote:
                parts.append("<table style='width:100%; max-width:560px; "
                             "margin-left:0;'>")
                line_type_labels = dict(
                    self.env["neon.finance.quote.line"]
                        ._fields["line_type"].selection)
                for lt in ("equipment", "crew", "sub_rental",
                           "consumable", "other"):
                    subtotal = sum(quote.line_ids.filtered(
                        lambda l: l.line_type == lt
                    ).mapped("line_subtotal"))
                    if subtotal:
                        parts.append(
                            "<tr><td style='padding-left:18px;'>%s "
                            "subtotal</td>"
                            "<td style='text-align:right;'>%s%.2f</td>"
                            "</tr>"
                            % (line_type_labels.get(lt, lt),
                               sym, subtotal))
                parts.append(
                    "<tr><td style='padding-left:18px; "
                    "border-top:1px solid #ccc;'>"
                    "Untaxed subtotal</td>"
                    "<td style='text-align:right; "
                    "border-top:1px solid #ccc;'>%s%.2f</td></tr>"
                    % (sym, quote.amount_untaxed))
                parts.append(
                    "<tr><td style='padding-left:18px;'>VAT 15.5%%</td>"
                    "<td style='text-align:right;'>%s%.2f</td></tr>"
                    % (sym, quote.amount_tax))
                parts.append(
                    "<tr><td style='padding-left:18px; font-weight:bold; "
                    "border-top:2px solid #444;'>REVENUE TOTAL</td>"
                    "<td style='text-align:right; font-weight:bold; "
                    "border-top:2px solid #444;'>%s%.2f</td></tr>"
                    % (sym, quote.amount_total))
                parts.append("</table>")
            else:
                parts.append("<p style='color:#888;'>"
                             "No quote yet -- revenue figures will "
                             "populate once a quote is created and "
                             "submitted.</p>")

            # --- COST block (per cost_type per currency) ----------
            parts.append("<h4 style='margin-top:14px; "
                         "margin-bottom:6px;'>Cost</h4>")
            parts.append("<table style='width:100%; max-width:560px; "
                         "margin-left:0;'>")
            usd_sum_per_type = {}
            zig_sum_per_type = {}
            for line in rec.cost_line_ids:
                if line.currency_id == usd:
                    usd_sum_per_type[line.cost_type] = (
                        usd_sum_per_type.get(line.cost_type, 0.0)
                        + line.amount)
                elif line.currency_id == zwg:
                    zig_sum_per_type[line.cost_type] = (
                        zig_sum_per_type.get(line.cost_type, 0.0)
                        + line.amount)
            for ct in ("crew", "sub_rental", "consumable",
                       "transport", "venue", "write_off", "other"):
                usd_amt = usd_sum_per_type.get(ct, 0.0)
                zig_amt = zig_sum_per_type.get(ct, 0.0)
                if not usd_amt and not zig_amt:
                    continue
                pieces = []
                if usd_amt:
                    pieces.append("$%.2f" % usd_amt)
                if zig_amt:
                    pieces.append("ZiG %.2f" % zig_amt)
                parts.append(
                    "<tr><td style='padding-left:18px;'>%s</td>"
                    "<td style='text-align:right;'>%s</td></tr>"
                    % (cost_type_labels.get(ct, ct),
                       " &nbsp;+&nbsp; ".join(pieces)))
            # Totals row -- show both currencies if both have costs
            total_pieces = []
            if rec.cost_total_usd:
                total_pieces.append("$%.2f" % rec.cost_total_usd)
            if rec.cost_total_zig:
                total_pieces.append("ZiG %.2f" % rec.cost_total_zig)
            parts.append(
                "<tr><td style='padding-left:18px; font-weight:bold; "
                "border-top:2px solid #444;'>COST TOTAL</td>"
                "<td style='text-align:right; font-weight:bold; "
                "border-top:2px solid #444;'>%s</td></tr>"
                % (" &nbsp;+&nbsp; ".join(total_pieces) or "%s0.00" % sym))
            parts.append("</table>")

            # --- MARGIN + variance ----------
            parts.append("<h4 style='margin-top:14px; "
                         "margin-bottom:6px;'>Margin</h4>")
            parts.append("<table style='width:100%; max-width:560px; "
                         "margin-left:0;'>")
            parts.append(
                "<tr><td style='padding-left:18px;'>Gross margin "
                "(%s)</td>"
                "<td style='text-align:right;'>%s%.2f</td></tr>"
                % (head_currency.name, sym, rec.margin_gross))
            parts.append(
                "<tr><td style='padding-left:18px;'>Gross margin %%</td>"
                "<td style='text-align:right;'>%.2f%%</td></tr>"
                % rec.margin_pct)
            if rec.initial_budget:
                parts.append(
                    "<tr><td style='padding-left:18px;'>Variance vs "
                    "initial budget</td>"
                    "<td style='text-align:right;'>%s%.2f</td></tr>"
                    % (rec.initial_budget_currency_id.symbol or "",
                       rec.budget_variance_initial))
            if rec.quoted_budget:
                parts.append(
                    "<tr><td style='padding-left:18px;'>Variance vs "
                    "quoted budget</td>"
                    "<td style='text-align:right;'>%s%.2f</td></tr>"
                    % (sym, rec.budget_variance_quoted))
            parts.append("</table>")
            parts.append("</div>")
            rec.pnl_html = "".join(parts)

    # ============================================================
    # === P6.M6 budget alert: compute level + write() dispatch
    # ============================================================
    # ⚠️ DECISION (P6.M6): 1-hour idempotency window is hardcoded as
    # a module-level constant rather than a 4th config_parameter. The
    # value is a UX-rate-limit tied to human review cadence, not a
    # tunable business policy -- adding a knob would be over-
    # engineering for a value nobody is going to change.
    _ALERT_IDEMPOTENCY_MINUTES = 60

    _LEVEL_ORDER = {"ok": 0, "warn": 1, "breach": 2, "severe": 3}

    @api.depends("cost_total_usd", "cost_total_zig",
                 "quoted_budget", "quoted_budget_currency_id")
    def _compute_budget_alert_level(self):
        """Derive budget_alert_level from same-currency cost vs.
        quoted_budget. Reads three thresholds from ir.config_parameter
        (warn/breach/severe pct, defaults 80/100/120). Returns 'ok'
        when quoted_budget is null (no accepted quote to compare).

        ⚠️ DECISION (P6.M6): same-currency-only comparison carries the
        M5 margin_gross invariant forward. Cross-currency cost
        contributions appear in the P&L view but don't escalate the
        alert level -- finance reviewers see what they need without
        invisible FX conversion in the alert path.

        ⚠️ DECISION (P6.M6): dispatch fires INSIDE the compute, not
        from a separate write() override. Stored-computed-field
        updates bypass model.write() entirely, so a write()-based
        trigger wouldn't fire on cost.line.create -> cost_total
        recompute -> budget_alert_level recompute. The compute reads
        the previous stored value via direct SQL (bypasses ORM cache
        + recursion) so old/new comparison is reliable.
        """
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        ICP = self.env["ir.config_parameter"].sudo()
        warn_pct = float(ICP.get_param(
            "neon_finance.budget_warn_pct", "80"))
        breach_pct = float(ICP.get_param(
            "neon_finance.budget_breach_pct", "100"))
        severe_pct = float(ICP.get_param(
            "neon_finance.budget_severe_pct", "120"))
        suppress = self.env.context.get("skip_finance_notification")

        for rec in self:
            # Read prior stored value via SQL so we can detect
            # escalation/de-escalation. ORM cache reads would either
            # return the just-being-computed value or recurse.
            old_level = "ok"
            if rec.id:
                self.env.cr.execute(
                    "SELECT budget_alert_level FROM commercial_event_job"
                    " WHERE id = %s", (rec.id,))
                row = self.env.cr.fetchone()
                if row and row[0]:
                    old_level = row[0]

            if not rec.quoted_budget:
                new_level = "ok"
            elif rec.quoted_budget_currency_id == usd:
                pct = (rec.cost_total_usd / rec.quoted_budget) * 100.0
                new_level = self._level_for_pct(
                    pct, warn_pct, breach_pct, severe_pct)
            elif rec.quoted_budget_currency_id == zwg:
                pct = (rec.cost_total_zig / rec.quoted_budget) * 100.0
                new_level = self._level_for_pct(
                    pct, warn_pct, breach_pct, severe_pct)
            else:
                new_level = "ok"

            rec.budget_alert_level = new_level

            if suppress:
                continue

            old_rank = self._LEVEL_ORDER.get(old_level, 0)
            new_rank = self._LEVEL_ORDER.get(new_level, 0)
            if new_rank > old_rank:
                rec._dispatch_budget_alert(old_level, new_level)
            elif new_rank < old_rank and old_level == "severe":
                # De-escalation out of severe -- clear the flag, no
                # activity dispatch (silent good news).
                if rec.suggest_reapproval:
                    rec.sudo().write({"suggest_reapproval": False})
                    rec.sudo().message_post(body=_(
                        "Budget level dropped from %s to %s; "
                        "suggest_reapproval auto-cleared."
                    ) % (old_level, new_level))

    @staticmethod
    def _level_for_pct(pct, warn_pct, breach_pct, severe_pct):
        """Pure helper -- map percent to level using the configured
        thresholds. Order matters: check severe first."""
        if pct >= severe_pct:
            return "severe"
        if pct >= breach_pct:
            return "breach"
        if pct >= warn_pct:
            return "warn"
        return "ok"

    def _dispatch_budget_alert(self, old_level, new_level):
        """Schedule mail.activity TODO for every Approver + Bookkeeper
        when budget_alert_level escalates. Idempotency: skip if
        last_alert_dispatched_at is within 60 min AND the new level
        is the same as the level that triggered the previous alert.
        Escalation beyond the previous level breaks the idempotency.

        Sets suggest_reapproval=True when new_level='severe'.
        Activities are scheduled on the event_job record itself --
        matches the M4 (approval) + M5 (cost.line) pattern; future
        dismiss-on-acknowledge logic stays scoped.
        """
        self.ensure_one()
        # Idempotency: if we dispatched recently at this same level,
        # skip. Escalation to a higher level bypasses the check.
        now = fields.Datetime.now()
        if self.last_alert_dispatched_at:
            elapsed = (now - self.last_alert_dispatched_at).total_seconds()
            if (elapsed < self._ALERT_IDEMPOTENCY_MINUTES * 60
                    and self._LEVEL_ORDER.get(new_level, 0)
                    <= self._LEVEL_ORDER.get(old_level, 0)):
                # No escalation AND within window -- skip.
                return

        approvers = self.env.ref(
            "neon_finance.group_neon_finance_approver",
            raise_if_not_found=False,
        )
        bookkeepers = self.env.ref(
            "neon_finance.group_neon_finance_bookkeeper",
            raise_if_not_found=False,
        )
        recipients = self.env["res.users"]
        if approvers:
            recipients |= approvers.users
        if bookkeepers:
            recipients |= bookkeepers.users

        level_labels = dict(self._fields["budget_alert_level"].selection)
        summary = _(
            "Budget alert on %s: %s (%.0f%% of quoted budget)"
        ) % (
            self.name,
            level_labels.get(new_level, new_level),
            (self._same_currency_cost() / self.quoted_budget * 100.0)
            if self.quoted_budget else 0.0,
        )
        note = _(
            "Event %(name)s budget level escalated from %(old)s to "
            "%(new)s.\nQuoted budget: %(qb)s %(cur)s\nCost so far: "
            "%(cost)s %(cur)s\nReview the Financial Summary tab."
        ) % {
            "name": self.name,
            "old": level_labels.get(old_level, old_level),
            "new": level_labels.get(new_level, new_level),
            "qb": self.quoted_budget,
            "cur": (self.quoted_budget_currency_id.name
                    if self.quoted_budget_currency_id else "?"),
            "cost": self._same_currency_cost(),
        }
        for user in recipients:
            self.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=user.id,
                summary=summary,
                note=note,
            )

        # Chatter post on breach + severe; warn is activity-only.
        if new_level in ("breach", "severe"):
            self.sudo().message_post(body=_(
                "Budget alert: %s is now %s (escalated from %s)."
            ) % (
                self.name,
                level_labels.get(new_level, new_level),
                level_labels.get(old_level, old_level),
            ))

        # severe additionally flips the suggest_reapproval flag.
        if new_level == "severe":
            self.sudo().write({"suggest_reapproval": True})

        self.sudo().write({"last_alert_dispatched_at": now})

    def _same_currency_cost(self):
        """Return the cost_total in quoted_budget_currency_id (the
        same-currency value used in margin + alert level)."""
        self.ensure_one()
        usd = self.env.ref("base.USD", raise_if_not_found=False)
        zwg = self.env.ref(
            "neon_finance.currency_zwg", raise_if_not_found=False)
        if self.quoted_budget_currency_id == usd:
            return self.cost_total_usd
        if self.quoted_budget_currency_id == zwg:
            return self.cost_total_zig
        return 0.0

    def action_acknowledge_over_budget(self):
        """Approver button on the event_job form. Clears
        suggest_reapproval (the action-required flag) but leaves
        budget_alert_level untouched -- the level is data-derived
        and cost data hasn't changed. Posts chatter for audit.
        """
        for rec in self:
            if not rec.suggest_reapproval:
                # Idempotent no-op for users clicking twice.
                continue
            rec.sudo().write({"suggest_reapproval": False})
            rec.sudo().message_post(body=_(
                "Over-budget acknowledged by %s. Budget level "
                "remains %s; suggest_reapproval cleared. Cost "
                "data is unchanged."
            ) % (
                self.env.user.name,
                dict(self._fields["budget_alert_level"].selection).get(
                    rec.budget_alert_level, rec.budget_alert_level),
            ))
        return True
