# -*- coding: utf-8 -*-
{
    "name": "Neon Onboarding",
    "version": "17.0.1.1.0",
    "summary": "Phase 7b -- crew onboarding state machine. "
               "M1 ships the neon.onboarding.candidate model, "
               "4-state machine (candidate / cert_collection / "
               "probationary / active), append-only audit log, "
               "and Skip Onboarding admin override wizard. "
               "Subsequent milestones add requirement templates "
               "(M2), full UX (M3), required cert integration "
               "(M4), probationary gating (M5), activation flow "
               "(M6), and portal stream (M8-M10).",
    "description": """
Neon Onboarding
===============

Phase 7b -- crew onboarding state machine. Foundation milestone
M1 establishes the candidate record + state machine + admin
override path. Designed for the existing-crew bulk-import case
(skip wizard) AND the new-hire happy path (state advances).

M1 scope:
* neon.onboarding.candidate model with full field set per
  schema sketch section 4.1
* 4-state machine: candidate -> cert_collection -> probationary
  -> active (admin override jump to active via Skip wizard)
* neon.onboarding.audit.log model (append-only, mirrors M9's
  assignment_gate_log H3=A pattern from Phase 7a)
* ACLs across 5 neon_core tiers (superuser / bookkeeper /
  sales_rep / lead_tech / crew)
* Skip Onboarding wizard visible to superuser tier only per
  Tatenda's design call (Robin + Munashe verify certs; admin
  override for existing crew is superuser-only)
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Onboarding",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "neon_core",
        "neon_jobs",
        "neon_training",
    ],
    "data": [
        "security/neon_onboarding_security.xml",
        "security/ir.model.access.csv",
        # Skip wizard views BEFORE candidate views -- the
        # candidate form's Skip Onboarding button references
        # action_neon_onboarding_skip_wizard via %()d lookup.
        "views/neon_onboarding_skip_wizard_views.xml",
        "views/neon_onboarding_candidate_views.xml",
        # M2 -- requirement template views (load after candidate
        # views so the parent menu menu_neon_onboarding_root is
        # in the registry when Configuration submenu attaches).
        "views/neon_onboarding_requirement_template_views.xml",
        # M2 seed templates: load AFTER views so any admin
        # exploration of the model has a UI ready. Templates
        # reference neon_training cert type xmlids -- those are
        # loaded earlier via the depends order.
        "data/neon_onboarding_templates.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "_post_init_hook",
}
