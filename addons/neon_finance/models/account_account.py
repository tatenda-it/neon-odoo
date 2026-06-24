# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountAccount(models.Model):
    """Origin tag on the chart of accounts.

    P-A / BUILD-1 — "Odoo accounting as-is": Odoo's existing generic chart
    (the 47 accounts the invoice engine posts to) stays untouched. This
    module ADDS a starter set of operating-expense accounts the generic
    chart lacks, and tags every account it seeds with ``neon_source`` so the
    Neon-seeded accounts are distinguishable from:
      - Odoo's generic 47 (``neon_source`` empty), and
      - any future Zoho-reconciled accounts (a different ``neon_source``).

    The tag is informational only — it gates no behaviour. The bookkeeper
    may add/rename/reparent accounts freely in the UI; the seed records are
    ``noupdate="1`` so those edits are never clobbered by a later ``-u``.
    """

    _inherit = 'account.account'

    neon_source = fields.Char(
        string="Neon Origin",
        copy=False,
        help="Origin tag for accounts seeded by Neon config-as-data "
             "(e.g. 'seed_accounting'). Empty on Odoo's generic chart. "
             "Distinguishes Neon-seeded accounts from the generic chart and "
             "from future Zoho-reconciled accounts. Informational only.",
    )
