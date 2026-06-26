# -*- coding: utf-8 -*-
"""Sidebar department grouping -- sequence-only reorder of the top-level app
menus into department clusters (Robin-approved, cosmetic).

Writes ir.ui.menu.sequence ONLY; never groups_id / action / visibility, so each
user keeps exactly their own role-gated subset and only the order changes.

Clusters (ascending blocks; gaps left between clusters to slot future apps):
  10s Sales & CRM | 20s Accounting & Finance | 30s Intelligence & Analytics
  40s Operations  | 50s People               | 60s Training & Knowledge
  70s Comms       | 80s System (technical menus parked at the tail)

Force-write (not data records) because several menu roots are noupdate=1; a
plain record would not re-apply on -u. Each menu is resolved by external id and
SKIPPED if absent, so the hook is safe across environments.
"""
import logging

_logger = logging.getLogger(__name__)

# external id -> sequence. Order within each cluster follows Robin's spec.
MENU_SEQUENCE = {
    # 1. Sales & CRM
    "sale_crm.sale_order_menu_quotations_crm": 10,        # Quotes
    "neon_sales.menu_neon_quotes_toplevel": 11,           # My Quotation
    "crm.crm_menu_root": 12,                              # CRM
    "sale.sale_menu_root": 13,                            # Sales
    "contacts.menu_contacts": 14,                         # Contacts
    # 2. Accounting & Finance
    "neon_banking_labels.menu_neon_statements_root": 20,  # Statements
    "neon_finance.menu_neon_banking_root": 21,            # Reconciliation
    "neon_banking_labels.menu_neon_reporting_root": 22,   # Reporting
    "neon_weekly_budget.menu_weekly_budget_root": 23,     # Weekly Budget
    "neon_migration.menu_collections_root": 24,           # Collections
    "account.menu_finance": 25,                           # Accounting
    # 3. Intelligence & Analytics
    "neon_migration.menu_client_intel_root": 30,          # Client Intelligence
    "neon_migration.menu_demand_root": 31,                # Demand & Seasonality
    "neon_migration.menu_winloss_root": 32,               # Realisation & Win/Loss
    "spreadsheet_dashboard.spreadsheet_dashboard_menu_root": 33,  # Dashboards
    "neon_dashboard.menu_neon_dashboard_root": 34,        # Dashboard (Neon role-lens)
    "neon_insights.menu_neon_insights_root": 35,          # Feedback Insights
    # 4. Operations
    "neon_jobs.menu_operations_root": 40,                 # Operations
    "neon_jobs.menu_workshop_root": 41,                   # Workshop
    "purchase.menu_purchase_root": 42,                    # Purchase
    # 5. People
    "hr.menu_hr_root": 50,                                # Employees
    "hr_holidays.menu_hr_holidays_root": 51,              # Time Off
    "neon_onboarding.menu_neon_onboarding_root": 52,      # Neon Onboarding
    # 6. Training & Knowledge
    "neon_training.menu_neon_training_root": 60,          # Neon Training
    "neon_lms.menu_neon_lms_root": 61,                    # Neon LMS
    "neon_external_training.menu_external_training_root": 62,  # External Training
    "website_slides.website_slides_menu_root": 63,        # eLearning
    "neon_kb.menu_kb_root": 64,                           # Knowledge Base
    "neon_library.menu_library_root": 65,                 # Library
    # 7. Comms
    "mail.menu_root_discuss": 70,                         # Discuss
    "calendar.mail_menu_calendar": 71,                    # Calendar
    # 8. System (+ technical menus parked at the tail)
    "website.menu_website_configuration": 80,            # Website
    "neon_migration.menu_neon_migration_root": 81,        # Zoho Archive
    "utm.menu_link_tracker_root": 82,                     # Link Tracker
    "base.menu_management": 83,                           # Apps
    "base.menu_administration": 84,                       # Settings
    "queue_job.menu_queue_job_root": 88,                  # Job Queue (technical)
    "base.menu_tests": 89,                                # Tests (technical)
}


def apply_menu_order(env):
    """Force-write the configured sequence on every resolvable menu. Idempotent;
    touches sequence only. Returns (applied, skipped)."""
    applied, skipped = 0, []
    for xmlid, seq in MENU_SEQUENCE.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            if menu.sequence != seq:
                menu.sudo().write({"sequence": seq})
            applied += 1
        else:
            skipped.append(xmlid)
    _logger.info(
        "neon_menu_order: sequenced %d top-level menus, skipped %d (%s)",
        applied, len(skipped), ", ".join(skipped) or "none")
    return applied, skipped


def post_init_hook(env):
    apply_menu_order(env)
