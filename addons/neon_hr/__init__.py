# -*- coding: utf-8 -*-
from . import models

import logging

_logger = logging.getLogger(__name__)


def _enforce_hr_confidentiality(env):
    """Q28 confidentiality enforcement — runs on install AND upgrade.

    ⚠️ DECISION (build-time, deploy-critical): installing the stock
    ``hr`` / ``hr_contract`` modules as neon_hr dependencies makes Odoo
    auto-grant hr.group_hr_user + hr.group_hr_manager to ALL existing
    internal users (observed: 118/121 on the dev DB). That would make
    every crew/sales/bookkeeper user an HR Manager and let them read
    every salary and personal field — the exact opposite of Q28.

    This hook:
      1) grants hr management to OD/MD (neon_core.group_neon_superuser),
         which lives in neon_core (loaded first) so cannot reference
         hr.* groups from XML;
      2) STRIPS the auto-granted hr_user/hr_manager from every internal
         user EXCEPT OD/MD, HR Admin, and the system admin/root.

    The employee directory (public fields) stays readable by all
    internal users via Odoo's public-employee rule; only the private
    fields + contracts/salary become confidential — precisely Q28.

    Idempotent: uses ORM (4,id)/(3,id) so re-runs are no-ops.
    """
    superuser = env.ref(
        "neon_core.group_neon_superuser", raise_if_not_found=False)
    hr_admin = env.ref(
        "neon_hr.group_neon_hr_admin", raise_if_not_found=False)

    # 1) Grant HR management to OD/MD. hr.group_hr_manager cascades to
    #    the contract manager via hr_contract; add it + the Time Off
    #    manager (R1b) explicitly. neon_core loads first so its
    #    implied_ids cannot reference hr.* from XML — hence this hook.
    if superuser:
        grant = []
        for xmlid in ("hr.group_hr_manager",
                      "hr_contract.group_hr_contract_manager",
                      "hr_holidays.group_hr_holidays_manager"):
            grp = env.ref(xmlid, raise_if_not_found=False)
            if grp:
                grant.append((4, grp.id))
        if grant:
            superuser.sudo().write({"implied_ids": grant})
            _logger.info(
                "neon_hr: granted %d HR manager group(s) to "
                "neon_core.group_neon_superuser.", len(grant))

    # 2) Strip the auto-granted privileged HR groups from everyone
    #    else. hr_user/hr_manager (Q28 salary/personal confidentiality)
    #    + hr_holidays_manager (R1b: only OD/MD/Admin may override-
    #    approve leave; ordinary leave routes via leave_manager_id).
    #    hr_holidays_user/_responsible are LEFT broad so staff can
    #    request + see their own leave.
    strip_groups = env["res.groups"]
    for xmlid in ("hr.group_hr_user", "hr.group_hr_manager",
                  "hr_holidays.group_hr_holidays_manager"):
        grp = env.ref(xmlid, raise_if_not_found=False)
        if grp:
            strip_groups |= grp
    if not strip_groups:
        _logger.warning(
            "neon_hr: privileged HR groups not found — strip skipped.")
        return
    keep_uids = set()
    for grp in filter(None, (superuser, hr_admin)):
        keep_uids |= set(grp.sudo().users.ids)
    for xmlid in ("base.user_root", "base.user_admin"):
        u = env.ref(xmlid, raise_if_not_found=False)
        if u:
            keep_uids.add(u.id)
    domain = [("share", "=", False), ("id", "not in", list(keep_uids))]
    domain += ["|"] * (len(strip_groups) - 1)
    domain += [("groups_id", "in", g.id) for g in strip_groups]
    strip = env["res.users"].sudo().search(domain)
    if strip:
        strip.write({"groups_id": [(3, g.id) for g in strip_groups]})
        _logger.info(
            "neon_hr: stripped %s from %d non-HR users (Q28 + leave "
            "approval control). Kept %d HR-authorised users.",
            strip_groups.mapped("name"), len(strip), len(keep_uids))


def post_init_hook(env):
    """Fresh-install entry point (prod). Upgrades go through the
    migrations/<version>/post-migrate.py companion."""
    _enforce_hr_confidentiality(env)
