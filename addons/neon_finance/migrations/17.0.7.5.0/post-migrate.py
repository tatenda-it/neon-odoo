# -*- coding: utf-8 -*-
"""P6.M7 post-migration -- no data backfill required.

The milestone adds two new models (neon.finance.invoice.schedule +
neon.finance.invoice.schedule.template) plus a quote.invoice_schedule_ids
o2m. Schema additions are handled by Odoo's standard registry init on
-u, and no existing rows need a fixup:

* Quotes accepted prior to 17.0.7.5.0 were never required to carry a
  schedule -- silently materialising one for them retroactively would
  invent invoice obligations the team never agreed to. The contract is
  prospective only.
* The new daily cron + sequence record load via their data XML.
* ACLs and ir.rule records load via their respective security files.

This script exists so the runtime version on existing installs is
stamped to 17.0.7.5.0 (Odoo treats migrations/<ver>/ presence as the
upgrade marker even when migrate() is a no-op). Future P6 milestones
that add data fixups can rely on this no-op step having run.
"""


def migrate(cr, version):
    return
