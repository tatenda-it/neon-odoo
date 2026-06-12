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
    'version': '17.0.7.10.8',
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
