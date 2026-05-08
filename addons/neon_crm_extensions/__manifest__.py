{
    "name": "Neon CRM Extensions",
    "version": "17.0.1.5.0",
    "summary": "Neon-specific custom fields and workflow extensions for CRM",
    "description": """
Neon CRM Extensions
===================

Adds Phase 1 custom fields to crm.lead:

* Brand (Hiring vs Events)
* GDPR consent flag
* SLA tracking (first response time, breached flag)
* Auto-computed lead score (1-5)
* Equipment required (Phase 3 forward hook)
* Annual event month (for annual client re-engagement)

Day 11 — Payment confirmation lifecycle:

* payment_claim_status field (none / claimed / verified)
* "Payment Pending Verification" pipeline stage
* Confirm Payment Received wizard for sales users
* Finance Manager group; only members can mark a claim Verified
* OpenClaw WhatsApp notification to Munashe on submit

Module is the foundation for Sections 4-6 of the M1 Action Plan
(SLA hook, deduplication, automation rules).
""",
    "author": "Neon Events Elements",
    "website": "https://neonhiring.com",
    "category": "Sales/CRM",
    "license": "LGPL-3",
    "depends": [
        "crm",
        "sale_management",
        "phone_validation",
        "mail",
        "account",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/cron_jobs.xml",
        "data/crm_stages.xml",
        "data/system_parameters.xml",
        "wizards/payment_confirm_wizard_views.xml",
        "views/crm_lead_views.xml",
        "views/res_partner_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
