{
    "name": "Neon CRM Extensions",
    "version": "17.0.1.0.0",
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
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}