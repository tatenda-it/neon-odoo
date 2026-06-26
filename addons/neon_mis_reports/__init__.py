# -*- coding: utf-8 -*-

# The three financial reports are DRAFT until real opening balances + real
# transactions are keyed and the line-mappings are signed off (Robin's
# instruction). Prefix each instance name so the bookkeeper never mistakes the
# current (test-data) figures for final ones. Applied via post_init_hook so it
# also covers the noupdate OCA Cash Flow instance, and runs on a fresh prod -i.
_DRAFT_PREFIX = "DRAFT (not final) - "
_INSTANCE_XMLIDS = [
    "neon_mis_reports.mis_instance_pl",
    "neon_mis_reports.mis_instance_bs",
    "mis_builder_cash_flow.mis_instance_cash_flow",
]


def post_init_hook(env):
    for xmlid in _INSTANCE_XMLIDS:
        inst = env.ref(xmlid, raise_if_not_found=False)
        if inst and not inst.name.startswith("DRAFT"):
            inst.name = _DRAFT_PREFIX + inst.name
