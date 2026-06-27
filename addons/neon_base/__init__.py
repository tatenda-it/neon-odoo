# -*- coding: utf-8 -*-
# neon_base has no Python models -- it exists only to pre-declare
# neon_core.group_neon_superuser early in the install graph (via the hook
# below) so neon_jobs / neon_finance references resolve on a cold install,
# before neon_core (which depends on them) can define it.


def _post_init_hook(env):
    """Pre-declare neon_core.group_neon_superuser as a bare shell group.

    neon_jobs and neon_finance reference ``neon_core.group_neon_superuser`` in
    their data files, but neon_core DEFINES that group and DEPENDS ON
    neon_jobs + neon_finance -- so on a cold install the xmlid does not yet
    exist when they load ("External ID not found"). On a warm DB it already
    exists, so the cycle is masked; only a fresh install exposes it.

    neon_base loads first (neon_jobs depends on it) and creates the xmlid here
    via the ORM. It is done in Python, not XML, because Odoo forbids a module
    declaring an xmlid in another, not-yet-installed module's namespace -- and
    neon_base must NOT depend on neon_core or the cycle returns.

    neon_core later UPDATES this same record (noupdate=0) with its full
    implied_ids / category / comment, so the end state is identical to a
    standalone neon_core install. Idempotent: no-op if the xmlid already
    exists.
    """
    imd = env["ir.model.data"]
    if imd.search([("module", "=", "neon_core"),
                   ("name", "=", "group_neon_superuser")], limit=1):
        return
    group = env["res.groups"].create({"name": "Neon Superuser"})
    imd.create({
        "module": "neon_core",
        "name": "group_neon_superuser",
        "model": "res.groups",
        "res_id": group.id,
        "noupdate": False,
    })
