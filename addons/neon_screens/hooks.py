# -*- coding: utf-8 -*-
"""Rail v0 (skeleton) — curated 9-slot nav order at the top of the rail.

Reuses neon_menu_order's force-write-sequence approach (resolve each menu by
external id, skip if absent, write sequence). Loaded AFTER neon_menu_order
(manifest dependency) so these slot sequences are the final word for the 9
business entries; every OTHER top-level menu keeps its neon_menu_order
sequence (10+) and therefore appears BELOW the business cluster.

LABELS are set ONLY for entries whose curated screen exists today:
  - "My Landing"            = the live neon_dashboard role-lens landing
  - "Equipment & Inventory" = this build's screen
Other business entries move to their slot but KEEP their current label (their
curated screen is not built yet — relabelling a broader menu would mislead).

NO hiding of the raw app list. NO role-switcher card. Both are Rail v1
(end-stage). Fully reversible.
"""
import logging

_logger = logging.getLogger(__name__)

# (slot sequence, top-level menu external id, business label or None)
RAIL_V0_SLOTS = [
    (1, "neon_dashboard.menu_neon_dashboard_root", "My Landing"),
    (2, "neon_screens.menu_crm_pipeline_root", "CRM Pipeline"),  # screen #5 (built)
    (3, "neon_screens.menu_operations_calendar_root", "Operations Calendar"),  # screen #2 (built)
    (4, "neon_screens.menu_event_jobs_root", "Event Jobs"),  # screen #3 (built)
    (5, "neon_screens.menu_equipment_screen_root", "Equipment & Inventory"),
    (6, "neon_screens.menu_crew_people_root", "Crew & People"),  # screen #6 (built: directory v1)
    (7, "neon_screens.menu_finance_control_root", "Finance Control"),  # screen #4 (built)
    (8, "neon_commercial_intel.menu_neon_ci_root", None),  # AI Planner (TBD)
    # slot 9 Field App — no menu; PWA-vs-WhatsApp decision pending
]

# Menus to DEMOTE out of the business cluster back to their neon_menu_order
# department home. Screen #1 placed the raw Operations app at slot 3 as a
# placeholder; Operations Calendar (screen #2) now owns slot 3, so the raw app
# drops to its 40s home (still fully visible — NO hiding).
RAIL_V0_DEMOTE = {
    "neon_jobs.menu_operations_root": 40,
    # Finance Control (screen #4) owns slot 7; the raw Accounting app drops to
    # its 40s home (still fully visible -- NO hiding).
    "account.menu_finance": 41,
    # CRM Pipeline (screen #5) owns slot 2; the raw CRM app drops to its 40s
    # home (still fully visible -- NO hiding, NO crm.stage change).
    "crm.crm_menu_root": 42,
    # Crew & People (screen #6) owns slot 6; the raw Employees/HR app drops to
    # its 40s home (still fully visible -- NO hiding).
    "hr.menu_hr_root": 43,
}


def _apply_rail_v0(env):
    applied, skipped = [], []
    for slot, xmlid, label in RAIL_V0_SLOTS:
        menu = env.ref(xmlid, raise_if_not_found=False)
        if not menu:
            skipped.append(xmlid)
            continue
        vals = {"sequence": slot}
        if label:
            vals["name"] = label
        menu.sudo().write(vals)
        applied.append(xmlid)
    demoted = []
    for xmlid, seq in RAIL_V0_DEMOTE.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if menu:
            menu.sudo().write({"sequence": seq})
            demoted.append(xmlid)
    _logger.info(
        "neon_screens Rail v0: slotted %d, demoted %d, skipped %d (%s)",
        len(applied), len(demoted), len(skipped), ", ".join(skipped) or "none")
    return applied, skipped


def post_init_hook(env):
    _apply_rail_v0(env)
