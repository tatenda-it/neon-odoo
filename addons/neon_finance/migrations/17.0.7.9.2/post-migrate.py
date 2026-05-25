# -*- coding: utf-8 -*-
"""P8A hotfix (delivered via neon_finance migration) -- reap two
P6-era orphans from any DB that still has them.

Both orphans exist on prod (`crm.neonhiring.com`) but not on dev:

1. ir.rule with xmlid ``neon_finance.event_job_rule_sales_own_quotes``
   -- domain ``[('quote_ids.salesperson_id', '=', user.id)]`` references
   a field that no longer exists on commercial.event.job. Created
   manually on prod at some point (UI / out-of-band SQL), against the
   P6.M5 design pause which intentionally OMITS sales-tier scoping on
   event_job (see addons/neon_finance/security/ir_rule.xml lines
   136-141 for the documented intent).

2. ir.model.fields with xmlid
   ``neon_finance.field_commercial_event_job__quote_ids`` -- one2many
   metadata row whose Python declaration was removed from
   commercial_event_job.py during the same P6.M5 cleanup. The DB row
   survived (Odoo's -u doesn't auto-reap orphan field metadata).

Symptom: any Sales-tier read of commercial.event.job raises
``ValueError: Invalid field commercial.event.job.quote_ids in leaf
('quote_ids.salesperson_id', '=', NN)``. Surfaced during P8A.M1-M3
browser walkthrough when Robin (uid 21, manually granted finance_sales)
clicked the Jobs-block empty-state CTA.

This migration deletes both orphan rows (record + ir_model_data
pointer) by xmlid lookup. Idempotent -- safe to re-run on a DB that
already lacks them.

Side effect: sales-tier users now see all commercial.event.job rows
in the list view (this is the intended P6.M5 design state; the P&L
mini-statement gating in the form view is unaffected).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # ---------------------------------------------------------------
    # 1. Orphan rule.
    # ---------------------------------------------------------------
    cr.execute("""
        SELECT res_id
          FROM ir_model_data
         WHERE model = 'ir.rule'
           AND module = 'neon_finance'
           AND name = 'event_job_rule_sales_own_quotes'
    """)
    rule_rows = cr.fetchall()
    if rule_rows:
        rule_ids = tuple(r[0] for r in rule_rows)
        cr.execute(
            "DELETE FROM rule_group_rel WHERE rule_group_id IN %s",
            (rule_ids,),
        )
        cr.execute(
            "DELETE FROM ir_rule WHERE id IN %s",
            (rule_ids,),
        )
        cr.execute("""
            DELETE FROM ir_model_data
             WHERE model = 'ir.rule'
               AND module = 'neon_finance'
               AND name = 'event_job_rule_sales_own_quotes'
        """)
        _logger.info(
            "P8A hotfix: deleted orphan ir.rule "
            "event_job_rule_sales_own_quotes (rule ids: %s)",
            rule_ids,
        )
    else:
        _logger.info(
            "P8A hotfix: orphan ir.rule "
            "event_job_rule_sales_own_quotes already absent.")

    # ---------------------------------------------------------------
    # 2. Orphan field metadata.
    # ---------------------------------------------------------------
    cr.execute("""
        SELECT res_id
          FROM ir_model_data
         WHERE model = 'ir.model.fields'
           AND module = 'neon_finance'
           AND name = 'field_commercial_event_job__quote_ids'
    """)
    field_rows = cr.fetchall()
    if field_rows:
        field_ids = tuple(r[0] for r in field_rows)
        # Defensive: also clean ir.model.fields.selection rows that
        # might point at the orphan field (not expected for o2m, but
        # cheap to be thorough).
        cr.execute(
            "DELETE FROM ir_model_fields_selection "
            "WHERE field_id IN %s",
            (field_ids,),
        )
        cr.execute(
            "DELETE FROM ir_model_fields WHERE id IN %s",
            (field_ids,),
        )
        cr.execute("""
            DELETE FROM ir_model_data
             WHERE model = 'ir.model.fields'
               AND module = 'neon_finance'
               AND name = 'field_commercial_event_job__quote_ids'
        """)
        _logger.info(
            "P8A hotfix: deleted orphan ir.model.fields "
            "field_commercial_event_job__quote_ids (field ids: %s)",
            field_ids,
        )
    else:
        _logger.info(
            "P8A hotfix: orphan ir.model.fields "
            "field_commercial_event_job__quote_ids already absent.")
