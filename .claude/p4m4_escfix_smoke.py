"""Escalation manager-gate fix (Option A).

The cron-escalation path runs as base.user_root (.sudo() in
_resolve_escalation) + sets _force_escalated_flag. base.user_root is NOT
a jobs-manager on prod, so write()'s reassign gate raised UserError on
every escalation -> feature 100% broken. Fix: skip the manager gate ONLY
when _force_escalated_flag is set; normal reassign still manager-only.

Why p4m4 T195 missed it: it runs as base.user_root, which IS a jobs-
manager on DEV (verified) but NOT on prod -> the gate passed on dev. So
the discriminating test below uses p2m75_lead (crew_leader = a NON-manager
WITH action.centre.item write-ACL) so it catches the bug regardless of
base.user_root's group on the host DB.

TA  flag bypasses the manager gate for a NON-manager (the fix; old code
    raises 'Only Manager')
TB  gate STILL blocks a non-manager reassign WITHOUT the flag
TC  full cron path: _resolve_escalation escalates cleanly
    (level++, escalated_to_id, escalated_at, history 'escalated')

Fully rollback-clean: no commits; env.cr.rollback() at the end.
"""
from odoo import fields
from odoo.exceptions import UserError

results = {}


def check(name, cond, detail=""):
    results[name] = bool(cond)
    line = ("PASS" if cond else "FAIL") + " " + name
    if detail and not cond:
        line += " :: " + str(detail)
    print(line)


mgr = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
lead = env["res.users"].search([("login", "=", "p2m75_lead")], limit=1)
sales = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
cfg = env.ref("neon_jobs.trigger_config_capacity_gate")  # esc->manager, 240m


def make(title, assignee):
    return env["action.centre.item"].sudo().create({
        "title": "ESCFIX " + title,
        "priority": "high",
        "trigger_type": "capacity_gate",
        "trigger_config_id": cfg.id,
        "is_manual": False,
        "primary_assignee_id": assignee.id,
    })


try:
    # --- TA: flag bypasses the manager gate for a NON-manager (THE FIX) ---
    ia = make("TA", lead)            # owned by crew_leader -> accessible
    ia.invalidate_recordset()
    gate_blocked = None
    try:
        ia.with_user(lead).with_context(
            _force_escalated_flag=True).write({"primary_assignee_id": mgr.id})
        gate_blocked = False
    except UserError as e:
        gate_blocked = "Only Manager" in str(e)
    except Exception:  # noqa: BLE001  any non-gate error still != gate block
        gate_blocked = False
    check("TA flag bypasses manager gate for non-manager (fix)",
          gate_blocked is False, "gate raised 'Only Manager' despite flag")

    # --- TB: gate STILL blocks a non-manager reassign WITHOUT the flag ---
    ib = make("TB", lead)
    ib.invalidate_recordset()
    raised = False
    try:
        ib.with_user(lead).write({"primary_assignee_id": sales.id})
    except UserError as e:
        raised = "Only Manager" in str(e)
    except Exception:  # noqa: BLE001
        raised = False
    check("TB manager gate STILL blocks non-manager (no flag)",
          raised, "expected 'Only Manager' UserError")

    # --- TC: full cron path escalates cleanly ---
    ic = make("TC", sales)           # non-manager assignee -> esc to a mgr
    ic.invalidate_recordset()
    env.cr.execute(
        "UPDATE action_centre_item SET create_date = %s WHERE id = %s",
        (fields.Datetime.subtract(fields.Datetime.now(), hours=5), ic.id))
    ic.invalidate_recordset()
    pre_level = ic.escalation_level
    pre_assignee = ic.primary_assignee_id
    ic._resolve_escalation()         # cron path: sudo(root) + flag
    ic.invalidate_recordset()
    esc_rows = ic.history_ids.filtered(lambda h: h.event_type == "escalated")
    check("TC cron escalation succeeds (level 0 -> 1)",
          pre_level == 0 and ic.escalation_level == 1,
          "level=%s" % ic.escalation_level)
    check("TC escalated_to_id + escalated_at stamped",
          bool(ic.escalated_to_id) and bool(ic.escalated_at))
    check("TC primary_assignee reassigned",
          ic.primary_assignee_id != pre_assignee)
    check("TC history logs 'escalated' (system actor)",
          len(esc_rows) >= 1 and esc_rows[:1].actor_is_system is True,
          "rows=%d" % len(esc_rows))
finally:
    env.cr.rollback()

p = sum(1 for v in results.values() if v)
print("\nTotal: %d/%d passed" % (p, len(results)))
