# -*- coding: utf-8 -*-
"""
Migration to 17.0.1.6.1 — clear old ir.actions.act_window records for
operations_dashboard_action and my_schedule_action so they can be
re-created as ir.actions.server.

P2.M7 originally landed these as plain act_window. The browser smoke
showed they opened unsaved forms with empty defaults (Bug 1: computed
counters and M2M previews never fired). The fix converts them to
server actions that create a persisted record server-side and return
an act_window targeting it by res_id.

Odoo refuses to change the model of an existing external id, so we
clear the old records (data + xml_id) before the XML loader inserts
the new server action records.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'neon_jobs'
           AND name IN ('operations_dashboard_action', 'my_schedule_action')
           AND model = 'ir.actions.act_window'
    """)
    act_ids = [row[0] for row in cr.fetchall()]
    if act_ids:
        cr.execute("DELETE FROM ir_act_window WHERE id IN %s", (tuple(act_ids),))
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = 'neon_jobs'
           AND name IN ('operations_dashboard_action', 'my_schedule_action')
           AND model = 'ir.actions.act_window'
    """)
