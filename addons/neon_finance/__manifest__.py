# -*- coding: utf-8 -*-
{
    'name': 'Neon Finance',
    # 17.0.7.10.0 = B11/WA-12 quote-by-WhatsApp finance layer: a new
    # neon_finance_quote_wa12 model layer (_wa12_provision_chain draft booking
    # chain + lifecycle hooks: graduate-on-accept / archive-on-dead-quote), the
    # DRAFT-stamped quote QWeb report (action_report_neon_quote), and the TBC
    # placeholder-venue data record. New layer (not a fix round) -> minor bump.
    # 17.0.7.10.1 = WA-12 pricing-engine fix (review): the pricing engine now
    # resolves a reservation-less line's category via
    # product_template_id.equipment_category_id (the documented hook) and prices
    # it through the rule/bracket/day-multiplier -- so a WA-12 line is engine-
    # priced (or 'no_rule'), never list_price-driven. create() keys engine-vs-
    # manual on `not unit_rate`; recalc keys on `pricing_status != 'manual'` so
    # an engine-priced reservation-less line re-prices instead of flipping to
    # manual, while a hand-set 'manual' line is preserved. Reservation-backed
    # lines are byte-unchanged (equipment_line_id short-circuit).
    # 17.0.7.11.0 = WA-12.2 F1 (proof #2, MONEY-PATH): the create() and
    # recalculate engine gates key on the PRODUCT, not equipment_category_id --
    # per-product rules (WA-12.1 PRIMARY) resolve without a category (the
    # catalogue-load CREATE products carry none), so the category gate made the
    # confirm echo show the rule rate while the drafted line stayed $0.00
    # 'not_yet' (the display-vs-provision divergence). No rule at all ->
    # 'no_rule' -> blocked, never a silent $0. + F8 REP-PRICED badge on the
    # quote PDF line (manual rate, no rule, no reservation -- as loud as
    # CUSTOM). Engine wiring -> minor bump.
    # 17.0.7.10.8 = WA-12 addendum (user-ratified 12 Jun 2026): the MD/OD tier
    # (neon_core.group_neon_superuser) MAY self-approve their own quotes -- the
    # ratified WA-12/WA-13 "MD/OD self-approval principle" supersedes the
    # blanket P6.predeploy SoD check for that tier ONLY (a plain approver who is
    # also the salesperson stays SoD-blocked). ⚠️ DECISION marker inline in
    # action_approve.
    # 17.0.7.10.7 = WA-13 — make Kudzai's Finance/Approver membership durable
    # across a fresh -i/rebuild (migration 17.0.7.10.7 idempotent (4, id) ORM
    # re-assert of the UI-added grant; no-op on the current prod DB). WA-13 adds
    # no finance model/engine -- it is a WhatsApp face on the existing P6.M7
    # invoice.schedule machinery (lives in neon_crew_comms).
    # 17.0.7.11.1 = WA-12.6 review polish: a DISPLAY-ONLY wa12_discount_note Char
    # on neon.finance.quote (a human label for a whole-quote WhatsApp discount,
    # e.g. "Discount USD 179.00 (incl. VAT)") + a conditional row on the quote
    # PDF totals block. Display only -- the discount itself lives in the per-line
    # discount_pct, so _compute_amounts is byte-unchanged. New nullable field ->
    # no migration; the note is set/cleared by the neon_crew_comms review edit.
    # 17.0.7.12.1 = WA-12.6 custom-line final: the CLIENT quote PDF no longer
    # badges a custom line ("CUSTOM" purple span removed) -- a custom line prints
    # as a normal item (name + rate). The custom marker stays INTERNAL (WhatsApp
    # draft ✍️ + the approval summary + the backend line_type). REP-PRICED badge
    # (manual equipment, distinct from line_type=custom) is unchanged.
    # 17.0.7.13.0 = FIX-S1 (rep-facing quote surface): the neon.finance.quote
    # FORM gains a product_template_id catalogue picker on the inline line tree
    # + an _onchange_product_template_id that fires the pricing engine live
    # (sets line_type='equipment', stamps unit_rate from rule x bracket x day-
    # multiplier) -- so a rep building a quote in Odoo gets engine pricing,
    # parity with the WA-12 path (previously the form had no product column, so
    # only WhatsApp produced engine-priced quotes). + a SUBMIT GUARD in
    # action_submit_for_approval that blocks any line with unit_rate<=0 (no
    # engine rate AND no rep rate) -- the safety check against the silent $0/$1
    # class the stock sale.order door produced. _find_pricing_rule falls back
    # to the related currency_id for onchange-safety. New feature/wiring->minor.
    # 17.0.7.14.0 = QUOTE-UX-1 (C + D-Odoo): (C) a "Preview" button on the draft
    # quote form (action_preview_quote) that prints the existing quote PDF so a
    # rep reviews the full quote before submitting. (D-Odoo) the Approval Queue
    # FORM now shows the LIVE quote line items + untaxed/VAT/total (related,
    # read-only quote_line_ids/quote_amount_* on neon.finance.approval) so the
    # approver sees the full quote on the record they action -- no click-through;
    # + the submit activity NOTE is enriched with an itemised text summary
    # (_neon_quote_itemised_text). neon_finance stays WhatsApp-agnostic (the WA
    # ping fires from neon_crew_comms' override of action_submit_for_approval).
    # New feature -> minor bump.
    # 17.0.7.14.1 = QUOTE-UX-1 post-deploy fix: action_preview_quote calls
    # report_action(config=False) so the Preview button returns the PDF for
    # ALL tiers -- with the default config=True an admin/superuser (the
    # directors) got the 'Configure Document Layout' wizard instead of the PDF
    # because prod has no company.external_report_layout_id (Neon uses a custom
    # QWeb external layout). Surfaced in post-deploy verify. Patch.
    # 17.0.7.14.2 = QUOTE-UX-1b: the quote-form Preview button is now
    # PERSISTENT across every active pipeline stage (draft / pending_approval
    # / approved / sent / accepted), not draft-only -- mirroring the stock
    # sale.order always-visible btn-secondary Preview adjacent to the action
    # cluster, so the rep can eyeball the state-correct PDF (DRAFT-stamped
    # while draft/pending, final document once approved/sent/accepted) one
    # click left of the stage's primary action before sending. View-only:
    # reuses action_preview_quote unchanged (config=False inherited). Hidden
    # only in terminal states. No model/schema/RBAC change. Patch.
    # 17.0.7.14.3 = QUOTE-UX-3: surface the ENGINE line discount on the Odoo
    # quote form. discount_pct + discount_amount added as default-visible
    # (optional="show") columns on the editable line tree adjacent to unit_rate,
    # + wa12_discount_note read-only in the totals footer. View-only: the
    # fields, mutual-exclusion constraint/onchanges, and _compute_subtotal ->
    # totals chain already exist (used by the WA flow + PDF). No model/compute/
    # onchange change. Patch.
    # 17.0.7.15.0 = QUOTE-UX-3b: whole-quote discount on the Odoo form. New
    # shared neon.finance.quote.apply_whole_quote_discount (extracted from the
    # WA _wa12_whole_quote_discount: clear -> recalc -> base -> validate (raise
    # UserError) -> uniform per-line discount_pct -> recalc -> wa12_discount_note
    # = achieved drop) + a TransientModel wizard + a draft-only form button. The
    # WA path now calls the shared method. New wizard layer -> minor bump.
    # 17.0.7.15.1 = REP-PRICED-PDF-FIX: the internal REP-PRICED rep-vs-engine
    # provenance tag on the quote report is now state-gated to draft /
    # pending_approval (working states) and HIDDEN on the client-facing faces
    # (approved / sent / accepted), mirroring the DRAFT-banner gating. Report
    # template display-only -- no model / flag / compute change. Patch.
    # 17.0.7.16.0 = P-A/BUILD-1 (accounting as-is): seed the operating-expense
    # accounts Odoo's generic 47-account chart lacks. ADDS 13 new
    # account_type='expense' records in the gap-filled 6xxxxx band
    # (account_account_seed_data.xml, noupdate=1) -- the existing 47 (which the
    # invoice engine posts to) are untouched, and the already-present
    # 611000/612000/620000/630000 are reused, not recreated. New
    # account.account.neon_source Char origin-tag field (models/
    # account_account.py) stamps every seeded account 'seed_accounting' so the
    # Neon-seeded set is distinguishable from the generic chart and from future
    # Zoho-reconciled accounts. No opening balances / no posting / no engine
    # change. Config-as-data layer -> minor bump. (Additive nullable column +
    # additive data rows; no existing-row migration.)
    'version': '17.0.7.17.3',
    'summary': 'Zimbabwe finance configuration + Phase 6 pricing engine '
               '(rule lookup + bracket compute + day multipliers) + quote '
               'model + OD/MD approval workflow + cost lines + per-event '
               'P&L + budget variance tracking + multi-stage invoicing '
               'schedule for Neon Events Elements',
    'description': """
Neon Finance
============
Phase 1: ZWG currency ownership, ZIMRA VAT tax records (15.5%
standard, 0% zero-rated), tax groups, partner-bank tweaks.

Phase 6 (this milestone, P6.M1): pricing rule + bracket + day-type
multiplier + USD/ZiG conversion rate schema, plus the four finance
role groups (user / sales / bookkeeper / approver). Extends
neon.equipment.category with a cost_strategy field driving quote
and cost-line behaviour downstream.
""",
    'author': 'Neon Events Elements Pvt Ltd',
    'website': 'https://neonhiring.com',
    'category': 'Accounting/Localizations',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'account',
        # P6.M1 — extends neon.equipment.category with cost_strategy
        # and auto-spawns day_multiplier rows for new categories.
        # Cycle check (pre-build): neon_jobs has no reverse deps
        # onto neon_finance or neon_sales.
        'neon_jobs',
    ],
    'data': [
        # security must load first so groups exist before ACL CSV
        # references them.
        'security/security.xml',
        'security/ir.model.access.csv',
        # P6.M2 — record rules for the quote model (must load AFTER
        # the CSV so the model exists in the registry).
        'security/ir_rule.xml',
        # Phase 1 data unchanged.
        'data/res_currency_data.xml',
        'data/account_tax_data.xml',
        'data/res_company_profile.xml',
        # WA-12 -- the single TBC placeholder venue for phone-quote
        # provisional booking chains (binding a; functional default, not seed
        # corpus). res.partner is_venue=True; needs neon_jobs (the field).
        'data/wa12_tbc_venue.xml',
        'data/res_company_logo.xml',
        'data/res_company_banks.xml',
        'data/account_journal_data.xml',
        # P-A/BUILD-1 — operating-expense chart seed (13 account_type=expense
        # records, neon_source-tagged, noupdate=1). No ref deps beyond
        # base.main_company; the neon_source field is registered at model load
        # so ordering among data files is free. Grouped with the account.*
        # config data above.
        'data/account_account_seed_data.xml',
        # BANKING-SETUP -- after the account seed + res_company_banks (refs the
        # CABS ZWG bank account) + security (refs the finance groups).
        'data/banking_setup_data.xml',
        # P6.M1 sequences must load before the pricing-rule seed
        # data so the default `next_by_code` lookup succeeds when
        # each rule is created. P6.M2 adds two more sequences (QUO-
        # USD-, QUO-ZIG-) into the same file.
        'data/ir_sequence_data.xml',
        'data/pricing_rule_seed_data.xml',
        # P6.M2 — daily cron for quote expiry.
        'data/ir_cron_data.xml',
        # P6.M4 — approval-feature-flag + reserved threshold params.
        'data/ir_config_parameter.xml',
        # Views.
        'views/res_partner_bank_views.xml',
        'views/neon_finance_pricing_rule_views.xml',
        'views/neon_finance_day_multiplier_views.xml',
        'views/neon_finance_conversion_rate_views.xml',
        'views/neon_equipment_category_views.xml',
        # P6.M2 — quote stack views.
        'views/neon_finance_payment_term_views.xml',
        'views/neon_finance_quote_line_views.xml',
        'views/neon_finance_quote_views.xml',
        # WA-12 — quote PDF report (DRAFT-stamped) for the WhatsApp loop.
        'report/neon_finance_quote_report.xml',
        # WA-12 design alignment — bigger company logo on the shared letterhead.
        'report/external_layout_neon.xml',
        # P6.M4 — approval views + Finance Approval settings section.
        'views/neon_finance_approval_views.xml',
        'views/res_config_settings_views.xml',
        # P6.M5 — cost line views + event_job extension (Cost Lines +
        # Financial Summary tabs).
        'views/neon_finance_cost_line_views.xml',
        'views/commercial_event_job_views.xml',
        # P6.M7 — multi-stage invoicing schedule + per-client templates.
        'views/neon_finance_invoice_schedule_views.xml',
        'views/neon_finance_invoice_schedule_template_views.xml',
        'wizard/neon_finance_payment_term_wizard_views.xml',
        # P6.M11 -- cost recovery wizard (TransientModel + form view).
        'wizard/neon_finance_cost_recovery_wizard_views.xml',
        # QUOTE-UX-3b -- whole-quote discount wizard (form face of the shared
        # apply_whole_quote_discount, the same method WhatsApp uses).
        'wizard/neon_finance_whole_quote_discount_wizard_views.xml',
        # P6.M9 -- res.partner credit hold flag + clear action button.
        # Bookkeeper/Approver groups gate visibility in the form view.
        'views/res_partner_views.xml',
        # P6.M8 -- invoice PDF template (inherits account.report_invoice_document
        # with ZIMRA strip + multi-stage indicator + payment terms summary +
        # currency-matched banking + T&Cs footer). Mirrors the neon_sales
        # QUOTE PDF override; the patterns are proven in production for
        # quotes (Phase 1) so M8 ports the same approach to invoices.
        'report/account_move_report_views.xml',
        # P6.M10 -- Cash Flow Dashboard. Six tiles + drill-through act_window
        # records + server-action wrapper + virtual model RPC. Mirrors the
        # P5.M10 Workshop Dashboard pattern (inline-return server-action,
        # no persisted ir.actions.client record, groups_id on wrapper).
        'views/neon_finance_dashboard_views.xml',
        # Menus load last so action ref()s resolve.
        'views/neon_finance_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # P6.M10 -- Cash Flow Dashboard OWL client action.
            'neon_finance/static/src/js/cash_flow_dashboard/cash_flow_dashboard.js',
            'neon_finance/static/src/js/cash_flow_dashboard/cash_flow_dashboard.xml',
            'neon_finance/static/src/js/cash_flow_dashboard/cash_flow_dashboard.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
