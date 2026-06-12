# -*- coding: utf-8 -*-
"""WA-13 — make Kudzai's Finance/Approver membership DURABLE.

Kudzaiishe (login ``admin@neonhiring.co.zw`` — a real finance staffer; reads
like, but is NOT, the Odoo superuser) was added to
``neon_finance.group_neon_finance_approver`` via the UI on 2026-06-12, so she
can GENERATE invoices from quotes (WA-13 Face 2 / the model's
``action_trigger_now`` approver gate). A UI add lives only in the DB, not in any
data file, so a fresh ``-i``/rebuild would drop it. This migration re-asserts
the grant with an idempotent ORM ``(4, id)`` write so it survives a rebuild.

NOT a fresh add — prod membership is already {2, 6, 7, 10, 21}. On the current
DB this is a no-op. The ORM write (NOT a raw ``res_groups_users_rel`` INSERT) is
deliberate: the raw INSERT skips the ``implied_ids`` cascade hook
([tag:implied_ids-orm-vs-sql]).

Fail-loud: if the login does not resolve to exactly one user, raise — a silent
no-op here would hide a renamed/missing login and leave Kudzai unable to
generate after a rebuild.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_KUDZAI_LOGIN = "admin@neonhiring.co.zw"
_GROUP_XMLID = "neon_finance.group_neon_finance_approver"


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref(_GROUP_XMLID, raise_if_not_found=False)
    if not group:
        raise ValueError(
            "WA-13 migration: approver group %s not found — cannot assert "
            "Kudzai's membership." % _GROUP_XMLID)
    user = env["res.users"].with_context(active_test=False).search(
        [("login", "=", _KUDZAI_LOGIN)], limit=1)
    if not user:
        raise ValueError(
            "WA-13 migration: no user with login %r — Kudzai must exist before "
            "the Finance/Approver grant can be made durable. Resolve the login "
            "(it may have been renamed) and re-run." % _KUDZAI_LOGIN)
    if user in group.users:
        _logger.info(
            "WA-13 migration: %s (uid %s) already in %s — no-op.",
            _KUDZAI_LOGIN, user.id, _GROUP_XMLID)
        return
    # ORM (4, id) so the implied_ids cascade fires ([tag:implied_ids-orm-vs-sql]).
    group.sudo().write({"users": [(4, user.id)]})
    _logger.info(
        "WA-13 migration: added %s (uid %s) to %s (now durable across "
        "rebuilds).", _KUDZAI_LOGIN, user.id, _GROUP_XMLID)
