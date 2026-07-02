# -*- coding: utf-8 -*-
"""PART 2 (quote form) -- draft-only quote-LINE delete.

Amendment to the append-only audit discipline, approved 2026-07-02 by
Robin (director): a DRAFT is not yet an approved financial record, so a
rep who mistypes a line must be able to delete it. Quote-level deletion
and everything post-draft stay append-only/immutable.

The CSV ACL flip (perm_unlink 0 -> 1 on the three quote.line rows) and
the NEW global rule ``quote_line_rule_unlink_draft_only`` land via plain
-u. But the perm_unlink=True flips on the three EXISTING quote.line
group rules live in security/ir_rule.xml under noupdate="1", so -u will
NOT propagate them to an existing install -- the standing pattern
(CLAUDE.md "Security records with noupdate=1") is this migration script
plus the manifest bump. Idempotent: write() of an already-True value is
a no-op; missing xmlids are skipped defensively.
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in (
        "neon_finance.quote_line_rule_sales_own_only",
        "neon_finance.quote_line_rule_bookkeeper_all",
        "neon_finance.quote_line_rule_approver_all",
    ):
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.write({"perm_unlink": True})
