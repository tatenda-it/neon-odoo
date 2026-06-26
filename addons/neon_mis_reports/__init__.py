# -*- coding: utf-8 -*-
from . import wizards  # noqa: F401

# Multi-currency: give each report a single TARGET currency so no figure is a
# ZWG+USD blend. The three existing instances become the USD-target variants;
# a ZWG-target sibling is created for each (6 reports total). All stay
# DRAFT-marked until Robin/the bookkeeper sign off mappings + currency behaviour
# against real data (the 1 July opening-balance cutover).
#
# Applied via post_init_hook (not data records) so it also covers the noupdate
# OCA Cash Flow instance and runs on a fresh prod -i. Idempotent.
_DRAFT_PREFIX = "DRAFT (not final) - "

# base instance external id -> clean (un-prefixed, un-suffixed) report name
_BASE_INSTANCES = {
    "mis_builder_cash_flow.mis_instance_cash_flow": "Cash Flow",
    "neon_mis_reports.mis_instance_pl": "Profit & Loss",
    "neon_mis_reports.mis_instance_bs": "Balance Sheet",
}


def _apply_currency_variants(env):
    Instance = env["mis.report.instance"]
    usd = env.ref("base.USD", raise_if_not_found=False) or env.company.currency_id
    zwg = env["res.currency"].with_context(active_test=False).search(
        [("name", "=", "ZWG")], limit=1)
    for xmlid, base_name in _BASE_INSTANCES.items():
        base = env.ref(xmlid, raise_if_not_found=False)
        if not base:
            continue
        # existing instance -> USD-target variant
        base.write({
            "currency_id": usd.id,
            "name": "%s%s (USD)" % (_DRAFT_PREFIX, base_name),
        })
        if not zwg:
            continue
        # ensure exactly one ZWG-target sibling for THIS report. Key idempotency
        # on (report_id, currency) -- NOT on name -- because mis.report.instance
        # .copy() forces a "(copy)" suffix and ignores a name passed in default,
        # so the name must be set AFTER the copy.
        zwg_name = "%s%s (ZWG)" % (_DRAFT_PREFIX, base_name)
        sibling = Instance.search(
            [("report_id", "=", base.report_id.id), ("currency_id", "=", zwg.id)], limit=1)
        if sibling:
            if sibling.name != zwg_name:
                sibling.name = zwg_name
        else:
            base.copy().write({"currency_id": zwg.id, "name": zwg_name})


def post_init_hook(env):
    _apply_currency_variants(env)
