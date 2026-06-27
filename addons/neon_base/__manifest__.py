# -*- coding: utf-8 -*-
{
    "name": "Neon Base",
    "version": "17.0.1.0.0",
    "summary": "Cold-install dependency shim -- pre-declares "
               "group_neon_superuser so neon_jobs / neon_finance "
               "references resolve before neon_core loads.",
    "description": """
Neon Base
=========

A minimal foundation module that exists to break a cold-install circular
dependency.

The problem
-----------
neon_jobs and neon_finance reference ``neon_core.group_neon_superuser`` in
their data files (ACL rows, action ``groups_id``, menu ``groups=``). But
neon_core DEFINES that group and DEPENDS ON neon_jobs + neon_finance, so on a
cold install neon_jobs/neon_finance load first and the xmlid does not yet
exist -> "External ID not found". On a warm DB the group already exists, so
the cycle is masked; only a fresh install exposes it.

The fix (Option 3)
------------------
neon_base loads before neon_jobs (neon_jobs depends on it) and pre-declares
the group under its real xmlid (``neon_core.group_neon_superuser``) via a
post_init_hook. The existing references then resolve. When neon_core later
installs it UPDATES this same record (noupdate=0) with its full implied_ids /
category / comment, so the end state is byte-for-byte identical to a
standalone neon_core install. No existing access-control reference is changed.

The xmlid is created in Python (the hook), not XML: Odoo forbids a module
declaring an xmlid in another, not-yet-installed module's namespace, and
neon_base must not depend on neon_core or the cycle returns.

Status: LOCAL build. Prod deploy is a separate later step pending review +
intra-file load-order audit + on-prod browser smoke.
""",
    "author": "Neon Events Elements",
    "category": "Neon/Core",
    "license": "LGPL-3",
    "depends": ["base"],
    "post_init_hook": "_post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
