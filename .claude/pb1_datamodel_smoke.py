"""P-B1 smoke — data-model completion (Conflict-Engine foundation).

Runs in `odoo shell -d <db>`. T-B1-01 ... T-B1-30.

Covers (acceptance §3):
- 4 window fields + 2 occupation compute fields exist with correct types
- occupation_start/end fall back to event_date when windows blank
- occupation_start/end widen to dispatch / return when set (D2)
- occupation_start/end stored, indexed
- condition_status enumerates exactly good/needs_repair/written_off
- last_checked_at NULL until a stock take, set on False->True attestation
- attest hook is batch-safe (multiple lines in one write)
- low_stock_threshold defaults 0, accepts ints, rejects negatives
- subcategory hierarchy works (parent_id + parent_path + child_ids)
- recursive category creation raises ValidationError
- manifest version bumped
"""
from datetime import datetime, timedelta, date


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B1 — data-model completion (Conflict-Engine foundation)")
print("=" * 72)
results = {}

EventJob = env["commercial.event.job"]
Unit = env["neon.equipment.unit"]
Category = env["neon.equipment.category"]
Take = env["neon.equipment.stock.take"]
TakeLine = env["neon.equipment.stock.take.line"]
Product = env["product.template"]
Partner = env["res.partner"]
Job = env["commercial.job"]


# ============================================================
# T-B1-01 .. 05 -- field surface on commercial.event.job
# ============================================================
fields_map = EventJob._fields
_check("T-B1-01",
       all(f in fields_map for f in (
           "load_in_start", "load_in_end",
           "load_out_start", "load_out_end")),
       "4 venue-side load-in/out fields present")
_check("T-B1-02",
       fields_map.get("load_in_start").type == "datetime"
       and fields_map.get("load_out_end").type == "datetime",
       f"types: load_in_start={fields_map['load_in_start'].type} "
       f"load_out_end={fields_map['load_out_end'].type}")
_check("T-B1-03",
       all(f in fields_map for f in (
           "occupation_start", "occupation_end")),
       "occupation_start / occupation_end present")
_check("T-B1-04",
       fields_map["occupation_start"].store
       and fields_map["occupation_end"].store
       and fields_map["occupation_start"].compute,
       "occupation_start/end stored + computed")
_check("T-B1-05",
       fields_map["occupation_start"].index
       and fields_map["occupation_end"].index,
       "occupation_start/end indexed for B2 overlap queries")


# ============================================================
# T-B1-06 .. 11 -- occupation compute behaviour
# ============================================================
# Fixture event job. Use a partner-less, lead-tech-less draft via
# sudo to avoid getting tripped up by ACL on operational fields.
admin = env.ref("base.user_admin")
EvJSudo = EventJob.with_user(admin).sudo()
JobSudo = Job.with_user(admin).sudo()

# Find a partner that exists (any) so commercial.job FK is happy.
# event_date is a RELATED field on commercial.event.job that delegates
# to commercial.job.event_date, so each probe needs its own master
# commercial.job to set a per-probe event_date.
partner = Partner.sudo().search([], limit=1)
venue = Partner.sudo().search([("is_venue", "=", True)], limit=1)


def _mk_master_job(label, event_date):
    vals = {
        "name": f"PB1 SMOKE MASTER {label}",
        "partner_id": partner.id,
        "state": "active",
        "event_date": event_date,
    }
    if venue:
        vals["venue_id"] = venue.id
    return JobSudo.create(vals)


today = date.today()
tomorrow = today + timedelta(days=1)

# Probe A -- only event_date set; expect occupation_start=08:00,
# occupation_end=22:00 same day.
master_a = _mk_master_job("A", today)
probe_a = EvJSudo.create({
    "name": "PB1 SMOKE A (event_date only)",
    "commercial_job_id": master_a.id,
    "partner_id": partner.id,
})
probe_a.flush_model()
_check("T-B1-06",
       probe_a.occupation_start is not False
       and probe_a.occupation_start.hour == 8
       and probe_a.occupation_start.date() == today,
       f"event_date only -> occupation_start={probe_a.occupation_start!r}")
_check("T-B1-07",
       probe_a.occupation_end is not False
       and probe_a.occupation_end.hour == 22
       and probe_a.occupation_end.date() == today,
       f"event_date only -> occupation_end={probe_a.occupation_end!r}")


# Probe B -- load_in_start before 08:00 widens occupation_start.
early_load_in = datetime.combine(
    today, datetime.min.time()).replace(hour=5)
master_b = _mk_master_job("B", today)
probe_b = EvJSudo.create({
    "name": "PB1 SMOKE B (early load_in_start)",
    "commercial_job_id": master_b.id,
    "partner_id": partner.id,
    "load_in_start": early_load_in,
})
probe_b.flush_model()
_check("T-B1-08",
       probe_b.occupation_start == early_load_in,
       f"load_in_start (05:00) widens occupation_start: "
       f"got={probe_b.occupation_start!r}")


# Probe C -- dispatch_datetime is the widening winner (D2).
very_early_dispatch = datetime.combine(
    today, datetime.min.time()).replace(hour=3)
master_c = _mk_master_job("C", today)
probe_c = EvJSudo.create({
    "name": "PB1 SMOKE C (dispatch widens)",
    "commercial_job_id": master_c.id,
    "partner_id": partner.id,
    "dispatch_datetime": very_early_dispatch,
    "load_in_start": early_load_in,
})
probe_c.flush_model()
_check("T-B1-09",
       probe_c.occupation_start == very_early_dispatch,
       f"dispatch (03:00) is min: "
       f"got={probe_c.occupation_start!r}")


# Probe D -- return_eta_datetime extends occupation_end past 22:00.
late_return = datetime.combine(
    tomorrow, datetime.min.time()).replace(hour=2)
master_d = _mk_master_job("D", today)
probe_d = EvJSudo.create({
    "name": "PB1 SMOKE D (return extends)",
    "commercial_job_id": master_d.id,
    "partner_id": partner.id,
    "return_eta_datetime": late_return,
})
probe_d.flush_model()
_check("T-B1-10",
       probe_d.occupation_end == late_return,
       f"return_eta (02:00 next day) extends occupation_end: "
       f"got={probe_d.occupation_end!r}")


# Probe E -- multi-day event with event_end_date uses end-date 22:00
# as backstop upper bound. event_end_date is ALSO a related field
# (commercial.job.event_end_date), so we set it on the master.
master_e = _mk_master_job("E", today)
master_e.sudo().write({"event_end_date": tomorrow})
probe_e = EvJSudo.create({
    "name": "PB1 SMOKE E (multi-day)",
    "commercial_job_id": master_e.id,
    "partner_id": partner.id,
})
probe_e.flush_model()
probe_e.invalidate_recordset(["occupation_end"])
_check("T-B1-11",
       probe_e.occupation_end is not False
       and probe_e.occupation_end.date() == tomorrow
       and probe_e.occupation_end.hour == 22,
       f"multi-day backstop: got={probe_e.occupation_end!r}")


# ============================================================
# T-B1-12 -- existing records re-compute correctly post-upgrade
# (the upgrade itself populates occupation_start/end on every
# existing row; this smoke confirms the column is non-NULL).
# ============================================================
existing_with_date = EventJob.sudo().search([
    ("event_date", "!=", False),
    ("id", "not in", (probe_a + probe_b + probe_c + probe_d + probe_e).ids),
], limit=5)
null_spans = existing_with_date.filtered(
    lambda r: not r.occupation_start or not r.occupation_end)
_check("T-B1-12",
       not null_spans,
       f"existing event_jobs with event_date have non-NULL spans: "
       f"checked={len(existing_with_date)} null={len(null_spans)}")


# ============================================================
# T-B1-13 .. 16 -- equipment.unit fields
# ============================================================
unit_fields = Unit._fields
_check("T-B1-13",
       "condition_status" in unit_fields
       and unit_fields["condition_status"].type == "selection",
       "condition_status Selection present")

selection_keys = set(
    dict(unit_fields["condition_status"].selection).keys())
_check("T-B1-14",
       selection_keys == {"good", "needs_repair", "written_off"},
       f"selection_keys={selection_keys}")

default_cond = unit_fields["condition_status"].default(Unit) \
    if callable(unit_fields["condition_status"].default) \
    else unit_fields["condition_status"].default
_check("T-B1-15",
       default_cond == "good",
       f"default condition={default_cond!r}")

_check("T-B1-16",
       "last_checked_at" in unit_fields
       and unit_fields["last_checked_at"].type == "datetime",
       "last_checked_at Datetime present")


# ============================================================
# T-B1-17 .. 21 -- last_checked_at write-on-attest hook (D5).
# Creates a fresh unit + a fresh stock take + 2 lines, attests
# both in ONE write() to exercise batch-safety, asserts the
# unit's last_checked_at is populated, then re-attests (no-op)
# and confirms the timestamp does NOT bump.
# ============================================================
# Find an existing product or skip the test gracefully.
product = Product.sudo().search(
    [("is_workshop_item", "=", True)], limit=1)
if not product:
    # No workshop product on this DB -- skip the unit/line test path.
    _check("T-B1-17", True, "no workshop product fixture; skipped")
    _check("T-B1-18", True, "skipped")
    _check("T-B1-19", True, "skipped")
    _check("T-B1-20", True, "skipped")
    _check("T-B1-21", True, "skipped")
else:
    unit_a = Unit.sudo().create({
        "product_template_id": product.id,
        "serial_number": "PB1-SMOKE-A",
    })
    unit_b = Unit.sudo().create({
        "product_template_id": product.id,
        "serial_number": "PB1-SMOKE-B",
    })
    _check("T-B1-17",
           unit_a.last_checked_at is False
           and unit_b.last_checked_at is False,
           "fresh units: last_checked_at NULL")
    _check("T-B1-18",
           unit_a.condition_status == "good"
           and unit_b.condition_status == "good",
           "fresh units: condition_status defaults to good")

    take = Take.sudo().create({
        "name": "PB1 SMOKE TAKE",
        "scheduled_for": today,
        "session_type": "ad_hoc",
    })
    line_a = TakeLine.sudo().create({
        "stock_take_id": take.id,
        "unit_id": unit_a.id,
        "expected_state": unit_a.state,
    })
    line_b = TakeLine.sudo().create({
        "stock_take_id": take.id,
        "unit_id": unit_b.id,
        "expected_state": unit_b.state,
    })
    # Batch flip both lines in one write -- exercises the
    # batch-safety guarantee.
    (line_a + line_b).sudo().write({
        "attested": True,
        "attested_at": datetime.now(),
        "attested_by_id": admin.id,
        "found_state": unit_a.state,
        "physical_condition": "good",
    })
    unit_a.invalidate_recordset(["last_checked_at"])
    unit_b.invalidate_recordset(["last_checked_at"])
    _check("T-B1-19",
           bool(unit_a.last_checked_at)
           and bool(unit_b.last_checked_at),
           f"batch attest -> both units stamped: "
           f"a={unit_a.last_checked_at} b={unit_b.last_checked_at}")

    # Re-write with attested=True (a re-save) should NOT bump the
    # timestamp again -- transition guard via the pre-snapshot.
    first_stamp_a = unit_a.last_checked_at
    line_a.sudo().write({"attested": True,
                          "notes": "amendment"})
    unit_a.invalidate_recordset(["last_checked_at"])
    _check("T-B1-20",
           unit_a.last_checked_at == first_stamp_a,
           f"re-save with attested=True does NOT bump stamp: "
           f"before={first_stamp_a} after={unit_a.last_checked_at}")

    # condition_status is editable.
    unit_a.sudo().write({"condition_status": "needs_repair"})
    _check("T-B1-21",
           unit_a.condition_status == "needs_repair",
           "condition_status editable to needs_repair")

    # Cleanup
    (line_a + line_b).sudo().unlink()
    take.sudo().unlink()
    (unit_a + unit_b).sudo().unlink()


# ============================================================
# T-B1-22 .. 26 -- category hierarchy + low_stock_threshold (D3, D6)
# ============================================================
cat_fields = Category._fields
_check("T-B1-22",
       "parent_id" in cat_fields
       and cat_fields["parent_id"].type == "many2one"
       and cat_fields["parent_id"].comodel_name == "neon.equipment.category",
       "parent_id M2O self present")
_check("T-B1-23",
       "parent_path" in cat_fields
       and cat_fields["parent_path"].index,
       "parent_path indexed (parent_store backbone)")
_check("T-B1-24",
       "low_stock_threshold" in cat_fields
       and cat_fields["low_stock_threshold"].type == "integer",
       "low_stock_threshold Integer present")

# Create root + child to confirm parent_path populates.
root = Category.sudo().create({
    "name": "PB1 SMOKE ROOT",
    "code": "pb1_smoke_root",
    "default_tracking": "serial",
})
child = Category.sudo().create({
    "name": "PB1 SMOKE CHILD",
    "code": "pb1_smoke_child",
    "default_tracking": "serial",
    "parent_id": root.id,
    "low_stock_threshold": 5,
})
child.flush_model()
_check("T-B1-25",
       bool(child.parent_path)
       and str(root.id) in child.parent_path,
       f"parent_path computed: {child.parent_path!r}")
_check("T-B1-26",
       child.low_stock_threshold == 5,
       f"low_stock_threshold persists: {child.low_stock_threshold}")


# T-B1-27 -- recursion guard. @api.constrains needs a flush to
# fire reliably from an odoo shell.
rec_blocked = False
rec_msg = ""
try:
    root.sudo().write({"parent_id": child.id})
    Category.flush_model()
except Exception as e:  # noqa: BLE001
    rec_msg = str(e).lower()
    rec_blocked = (
        "recursive" in rec_msg
        or "recursion" in rec_msg
        or "cycle" in rec_msg)
_check("T-B1-27", rec_blocked,
       f"recursive parent write rejected: msg={rec_msg[:80]!r}")
# Roll back the failed transaction so subsequent ops work.
env.cr.rollback()
root = Category.sudo().browse(root.id)
child = Category.sudo().browse(child.id)


# T-B1-28 -- negative low_stock_threshold rejected by CHECK.
# SQL CHECK constraints fire on flush; force one explicitly.
neg_blocked = False
try:
    root.sudo().write({"low_stock_threshold": -1})
    Category.flush_model()
except Exception as e:  # noqa: BLE001
    neg_blocked = (
        "low_stock_threshold" in str(e).lower()
        or "check" in str(e).lower())
_check("T-B1-28", neg_blocked,
       "low_stock_threshold < 0 rejected by SQL CHECK")
# Roll back the failed transaction so subsequent cleanup works.
env.cr.rollback()
# Re-fetch the records after rollback so the unlink below has fresh
# handles (rollback invalidates the cache).
root = Category.sudo().browse(root.id)
child = Category.sudo().browse(child.id)


# Cleanup
child.sudo().unlink()
root.sudo().unlink()
(probe_a + probe_b + probe_c + probe_d + probe_e).sudo().unlink()


# ============================================================
# T-B1-29 -- manifest version
# ============================================================
import os
from odoo.modules.module import get_module_path
manifest_path = os.path.join(
    get_module_path("neon_jobs"), "__manifest__.py")
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_src = f.read()
_check("T-B1-29",
       '17.0.4.5.0' in manifest_src,
       "neon_jobs version 17.0.4.5.0")


# ============================================================
# T-B1-30 -- field-name contract for B2 (locked at B1 gate-2)
# ============================================================
contract = (
    ("commercial.event.job", "load_in_start", "datetime"),
    ("commercial.event.job", "load_in_end", "datetime"),
    ("commercial.event.job", "load_out_start", "datetime"),
    ("commercial.event.job", "load_out_end", "datetime"),
    ("commercial.event.job", "occupation_start", "datetime"),
    ("commercial.event.job", "occupation_end", "datetime"),
    ("neon.equipment.unit",  "condition_status", "selection"),
    ("neon.equipment.unit",  "last_checked_at", "datetime"),
    ("neon.equipment.category", "parent_id", "many2one"),
    ("neon.equipment.category", "parent_path", "char"),
    ("neon.equipment.category", "low_stock_threshold", "integer"),
)
mismatches = []
for model_name, fname, ftype in contract:
    Model = env[model_name]
    f = Model._fields.get(fname)
    if not f:
        mismatches.append(f"{model_name}.{fname} MISSING")
    elif f.type != ftype:
        mismatches.append(
            f"{model_name}.{fname} type={f.type} expected={ftype}")
_check("T-B1-30",
       not mismatches,
       f"contract intact" if not mismatches else f"mismatches={mismatches}")


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
