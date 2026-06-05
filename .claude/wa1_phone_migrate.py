# -*- coding: utf-8 -*-
"""WA-1 one-shot migration -- canonicalise neon.whatsapp.message.phone_number
to E.164 ('+263...') via the single-source phone_utils.to_e164.

MANUAL, approval-gated. NOT in any manifest, NOT a pre/post-migrate hook,
NOT a cron, NOT imported by the addon __init__. Run by hand on a target DB:

    docker compose exec -T odoo \
        odoo shell -d <DB> --no-http --stop-after-init < .claude/wa1_phone_migrate.py

Properties (the locked design):
  * IN-PLACE update -> row count is preserved (no create, no unlink).
  * IDEMPOTENT -> to_e164 of an already-canonical value == itself, so a
    second run changes 0 rows.
  * BEFORE/AFTER counts printed (MIG ... lines) for the staging/prod report.
  * COMMITS once at the end (real data change). Snapshot-anchored: take a
    DB snapshot before running on prod.
"""
from odoo.addons.neon_channels.models.phone_utils import to_e164

M = env["neon.whatsapp.message"].sudo()  # noqa: F821  (odoo shell global)

rows = M.search([])
before_total = len(rows)
before_canon = M.search_count([("phone_number", "=like", "+%")])
print("MIG BEFORE  total=%d  canonical(+)=%d  need-normalize=%d"
      % (before_total, before_canon, before_total - before_canon))

changed = 0
samples = []
for r in rows:
    cur = r.phone_number or ""
    new = to_e164(cur)
    if new and new != cur:
        if len(samples) < 8:
            samples.append("%s -> %s" % (cur, new))
        r.phone_number = new
        changed += 1

env.cr.commit()  # noqa: F821

after = M.search([])
after_total = len(after)
after_canon = M.search_count([("phone_number", "=like", "+%")])
print("MIG AFTER   total=%d  canonical(+)=%d  changed=%d"
      % (after_total, after_canon, changed))
print("MIG ASSERT  count_preserved=%s  all_canonical=%s"
      % (after_total == before_total, after_canon == after_total))
for s in samples:
    print("MIG CHANGED %s" % s)
print("MIG DONE")
