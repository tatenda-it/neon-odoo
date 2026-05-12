# -*- coding: utf-8 -*-
{
    "name": "Neon Jobs",
    "version": "17.0.1.9.2",
    "summary": "Phase 2 — Commercial Job Record + Calendar / Capacity",
    "description": """
Neon Events Elements — Phase 2 — P2.M1 Schema

The Commercial Job is the central operational record connecting CRM, Finance,
Calendar, Operations, Workshop, and Training. This module defines the schema:

* commercial_job_master — Optional parent for multi-event corporate contracts
  (e.g. C Suite, Kuyana, Boxing, Lusitania).
* commercial_job — The central record. Two-state lifecycle (pending → active),
  three parallel status tracks (commercial / finance / operational).
* commercial_job_crew — Crew assignment with confirm/decline workflow.
* venue.room — Room granularity within venues for calendar conflict detection.

Extensions:
* res.partner — is_venue flag and room_ids.
* crm.lead — commercial_job_ids reverse pointer.
* sale.order — commercial_job_ids reverse pointer.

Status: P2.M1 (schema + base form views). State machines, CRM linkage,
capacity gate, calendar UI, and capacity warnings come in P2.M2-M9.
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Operations",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "sale",
        "crm",
        "contacts",
        "account",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_sequence_data.xml",
        "data/res_partner_data.xml",
        "data/crm_stage_data.xml",
        "data/ir_cron_data.xml",
        "data/cross_module_menu_security.xml",
        "data/operations_submenu_security.xml",
        "views/venue_room_views.xml",
        "views/res_partner_views.xml",
        "views/commercial_job_views.xml",
        "views/commercial_job_for_crew_views.xml",
        "views/commercial_job_master_views.xml",
        "views/commercial_job_crew_views.xml",
        "views/commercial_job_calendar_view.xml",
        "views/commercial_job_loss_wizard_views.xml",
        "views/commercial_job_gate_override_wizard_views.xml",
        "views/commercial_job_soft_hold_extend_wizard_views.xml",
        "views/commercial_job_crew_decline_wizard_views.xml",
        "views/commercial_job_dashboard_views.xml",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "_post_init_hook",
}
