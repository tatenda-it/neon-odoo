# -*- coding: utf-8 -*-
{
    "name": "Neon HR",
    "version": "17.0.5.0.0",
    "summary": "People R1a/R1b/R2/R3a — employee master, contracts, docs, "
               "leave, payroll, wages, loans, accidents, discipline, "
               "TOIL, handbook, driver licences + competency gating",
    "description": """
Neon HR — Release 1a (Employee Foundation)
===========================================

Extends Odoo hr.employee / hr.contract with the Neon-specific
employee master: 7 employee categories, a document-compliance
checklist, a contract renewal state machine, configurable notice
periods, and 30-day contract-expiry alerts raised through the
existing neon_jobs Action Centre.

R1b (separate release) bolts leave / payroll / event-wage /
freelance-rate / staff-loan / crew-availability models onto this
foundation — see the model/field names reported in the R1a
Gate-2 summary.
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Human Resources",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "hr",
        "hr_contract",
        "hr_holidays",
        "neon_core",
        "neon_jobs",
    ],
    "data": [
        "security/neon_hr_groups.xml",
        "security/ir.model.access.csv",
        "security/neon_hr_record_rules.xml",
        "security/neon_hr_payroll_rules.xml",
        "security/neon_hr_r2_rules.xml",
        "security/neon_hr_r3_rules.xml",
        "data/neon_hr_document_type_data.xml",
        "data/neon_hr_category_data.xml",
        "data/contract_templates.xml",
        "data/action_centre_trigger_config_data.xml",
        "data/ir_cron_contract_expiry.xml",
        "data/neon_hr_leave_types.xml",
        "data/neon_hr_payroll_config.xml",
        "data/neon_hr_r2_data.xml",
        "data/ir_cron_accident_nssa.xml",
        "data/neon_hr_r3_data.xml",
        "data/ir_cron_licence_expiry.xml",
        "views/neon_hr_category_views.xml",
        "views/neon_hr_document_views.xml",
        "views/hr_employee_views.xml",
        "views/hr_contract_views.xml",
        "views/neon_hr_leave_views.xml",
        "views/neon_hr_payroll_views.xml",
        "views/neon_hr_r2_views.xml",
        "views/neon_hr_r3_views.xml",
        "views/neon_hr_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
}
