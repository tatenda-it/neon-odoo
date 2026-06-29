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
    (2, "crm.crm_menu_root", None),                        # CRM Pipeline (screen TBD)
    (3, "neon_screens.menu_operations_calendar_root", "Operations Calendar"),  # screen #2 (built)
    # slot 4 Event Jobs — no distinct top-level menu yet; claims its slot when built
    (5, "neon_screens.menu_equipment_screen_root", "Equipment & Inventory"),
    (6, "hr.menu_hr_root", None),                          # Crew & People (TBD)
    (7, "account.menu_finance", None),                     # Finance Control (TBD)
    (8, "neon_commercial_intel.menu_neon_ci_root", None),  # AI Planner (TBD)
    # slot 9 Field App — no menu; PWA-vs-WhatsApp decision pending
]

# Menus to DEMOTE out of the business cluster back to their neon_menu_order
# department home. Screen #1 placed the raw Operations app at slot 3 as a
# placeholder; Operations Calendar (screen #2) now owns slot 3, so the raw app
# drops to its 40s home (still fully visible — NO hiding).
RAIL_V0_DEMOTE = {
    "neon_jobs.menu_operations_root": 40,
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
