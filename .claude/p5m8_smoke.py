"""P5.M8 smoke — weekly stock take flow.

T360 _cron_create_weekly_session spawns a 'scheduled' session
T361 cron is idempotent (second call returns existing session)
T362 ad-hoc wizard with category filter creates a narrow session
T363 attest with found == expected → no discrepancy
T364 attest with found_state != expected_state → discrepancy
T365 attest with found_location != expected_location → discrepancy
T366 attest with physical_condition='damaged' → discrepancy
T367 is_high_impact compute: Sound True, Trussing False
T368 high-impact discrepancy fires Action Centre item
T369 standard-category discrepancy does NOT fire Action Centre item
T370 marking line.resolved=True auto-closes the high-impact item
T371 'Attest All As Expected' bulk-attests every unattested line
T372 state machine: pending → in_progress → completed; complete
     with unattested lines raises
"""
from datetime import date

from odoo.exceptions import UserError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

StockTake = env["neon.equipment.stock.take"]
StockLine = env["neon.equipment.stock.take.line"]
Wizard = env["neon.equipment.stock.take.wizard"]
Category = env["neon.equipment.category"]
Unit = env["neon.equipment.unit"]
Item = env["action.centre.item"]

manager = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)

# Resolve the seeded high-impact categories — the migration script
# should have flipped these to True on the version bump. Verify and
# log; in fresh test DBs the smoke can self-seed if needed.
sound_cat = env.ref("neon_jobs.equipment_category_sound")
trussing_cat = env.ref("neon_jobs.equipment_category_trussing")
if not sound_cat.is_high_impact:
    sound_cat.sudo().write({"is_high_impact": True})
    print("WARN: Sound category was not high-impact; smoke applied "
          "is_high_impact=True for testing.")
if trussing_cat.is_high_impact:
    trussing_cat.sudo().write({"is_high_impact": False})
print("Sound.is_high_impact:", sound_cat.is_high_impact,
      " Trussing.is_high_impact:", trussing_cat.is_high_impact)

# Clean any prior P5M8 sessions left by aborted smoke iterations
StockTake.sudo().search([
    ("session_type", "=", "scheduled"),
    ("scheduled_for", "=", date.today()),
]).unlink()
env.cr.commit()


# ============================================================
print()
print("=" * 72)
print("T360 - cron creates a scheduled session with workshop-floor lines")
print("=" * 72)
existing = StockTake.sudo().search([
    ("session_type", "=", "scheduled"),
    ("scheduled_for", "=", date.today()),
])
existing.unlink()  # ensure fresh state
session360 = StockTake.sudo()._cron_create_weekly_session()
ok = (
    bool(session360)
    and session360.session_type == "scheduled"
    and session360.state == "pending"
    and session360.line_count > 0
    and all(
        l.expected_state in ("active", "reserved", "maintenance",
                             "returned", "damaged")
        for l in session360.line_ids[:10])  # sample first 10
)
print("  session:", session360.name)
print("  state:", session360.state, " session_type:", session360.session_type)
print("  line_count:", session360.line_count, "(want > 0)")
print("T360:", "PASS" if ok else "FAIL")
results["T360"] = ok


# ============================================================
print()
print("=" * 72)
print("T361 - cron is idempotent")
print("=" * 72)
session361 = StockTake.sudo()._cron_create_weekly_session()
count_after = StockTake.sudo().search_count([
    ("session_type", "=", "scheduled"),
    ("scheduled_for", "=", date.today()),
    ("state", "in", ("pending", "in_progress")),
])
ok = session361.id == session360.id and count_after == 1
print("  same session returned?", session361.id == session360.id)
print("  total active scheduled sessions today:",
      count_after, "(want 1)")
print("T361:", "PASS" if ok else "FAIL")
results["T361"] = ok


# ============================================================
print()
print("=" * 72)
print("T362 - ad-hoc wizard with category filter")
print("=" * 72)
wiz362 = Wizard.with_user(manager).create({
    "category_ids": [(6, 0, [sound_cat.id])],
})
result362 = wiz362.action_confirm()
session362 = StockTake.sudo().browse(result362.get("res_id"))
ok = (
    bool(session362)
    and session362.session_type == "ad_hoc"
    and session362.line_count > 0
    and all(l.category_id == sound_cat
            for l in session362.line_ids)
)
print("  session:", session362.name, " type:", session362.session_type)
print("  lines:", session362.line_count,
      " all-Sound?",
      all(l.category_id == sound_cat for l in session362.line_ids))
print("T362:", "PASS" if ok else "FAIL")
results["T362"] = ok


# ============================================================
# Build a focused 3-unit ad-hoc session for the attestation tests.
# Sound category has multiple products with active units; the
# session will contain just Sound units, plenty to slice.
attest_session = StockTake.sudo()._create_session(
    session_type="ad_hoc",
    category_ids=Category.browse(sound_cat.id),
)
attest_lines = attest_session.line_ids
assert len(attest_lines) >= 6, (
    "Need ≥6 Sound-category lines for T363-T370; got %d. "
    "Re-seed the testing kit." % len(attest_lines))
print("Attestation session built:", attest_session.name,
      " lines:", len(attest_lines))


# ============================================================
print()
print("=" * 72)
print("T363 - attest with found == expected → no discrepancy")
print("=" * 72)
line363 = attest_lines[0]
line363.action_attest(
    found_state=line363.expected_state,
    found_location=line363.expected_location,
    physical_condition="good",
)
line363.invalidate_recordset()
ok = line363.attested is True and line363.has_discrepancy is False
print("  attested:", line363.attested,
      " has_discrepancy:", line363.has_discrepancy)
print("T363:", "PASS" if ok else "FAIL")
results["T363"] = ok


# ============================================================
print()
print("=" * 72)
print("T364 - attest with found_state != expected_state → discrepancy")
print("=" * 72)
line364 = attest_lines[1]
# Pick any state that differs from expected
mismatch_state = "maintenance" if line364.expected_state != "maintenance" else "damaged"
line364.action_attest(
    found_state=mismatch_state,
    physical_condition="good",
)
line364.invalidate_recordset()
ok = line364.attested is True and line364.has_discrepancy is True
print("  expected:", line364.expected_state,
      " found:", line364.found_state)
print("  has_discrepancy:", line364.has_discrepancy)
print("T364:", "PASS" if ok else "FAIL")
results["T364"] = ok


# ============================================================
print()
print("=" * 72)
print("T365 - attest with found_location != expected → discrepancy")
print("=" * 72)
line365 = attest_lines[2]
line365.action_attest(
    found_state=line365.expected_state,
    found_location="Workshop B — Shelf Z (relocated)",
    physical_condition="good",
)
line365.invalidate_recordset()
ok = line365.attested is True and line365.has_discrepancy is True
print("  expected_loc:", repr(line365.expected_location))
print("  found_loc:", repr(line365.found_location))
print("  has_discrepancy:", line365.has_discrepancy)
print("T365:", "PASS" if ok else "FAIL")
results["T365"] = ok


# ============================================================
print()
print("=" * 72)
print("T366 - attest with physical_condition='damaged' → discrepancy")
print("=" * 72)
line366 = attest_lines[3]
line366.action_attest(
    found_state=line366.expected_state,
    physical_condition="damaged",
)
line366.invalidate_recordset()
ok = line366.attested is True and line366.has_discrepancy is True
print("  physical_condition:", line366.physical_condition)
print("  has_discrepancy:", line366.has_discrepancy)
print("T366:", "PASS" if ok else "FAIL")
results["T366"] = ok


# ============================================================
print()
print("=" * 72)
print("T367 - is_high_impact compute: Sound True, Trussing False")
print("=" * 72)
# Build a tiny session containing both Sound + Trussing units
trussing_session = StockTake.sudo()._create_session(
    session_type="ad_hoc",
    category_ids=Category.browse([sound_cat.id, trussing_cat.id]),
)
sound_line = trussing_session.line_ids.filtered(
    lambda l: l.category_id == sound_cat)[:1]
trussing_line = trussing_session.line_ids.filtered(
    lambda l: l.category_id == trussing_cat)[:1]
ok = (
    bool(sound_line) and bool(trussing_line)
    and sound_line.is_high_impact is True
    and trussing_line.is_high_impact is False
)
print("  sound is_high_impact:",
      sound_line.is_high_impact if sound_line else None)
print("  trussing is_high_impact:",
      trussing_line.is_high_impact if trussing_line else None)
print("T367:", "PASS" if ok else "FAIL")
results["T367"] = ok


# ============================================================
print()
print("=" * 72)
print("T368 - high-impact discrepancy fires Action Centre item")
print("=" * 72)
line368 = attest_lines[4]  # Sound category
line368.action_attest(
    found_state="maintenance" if line368.expected_state != "maintenance"
    else "damaged",
)
line368.invalidate_recordset()
source_model = env["ir.model"].sudo()._get(
    "neon.equipment.stock.take.line")
items368 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_high_impact"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", line368.id),
])
ok = (
    line368.has_discrepancy is True
    and line368.is_high_impact is True
    and bool(items368)
)
print("  has_discrepancy:", line368.has_discrepancy,
      " is_high_impact:", line368.is_high_impact)
print("  action items spawned:", len(items368),
      "(want >=1)")
if items368:
    print("  sample title:", items368[0].title)
print("T368:", "PASS" if ok else "FAIL")
results["T368"] = ok


# ============================================================
print()
print("=" * 72)
print("T369 - standard-category discrepancy does NOT fire item")
print("=" * 72)
line369 = trussing_line[0]  # Trussing (standard)
line369.action_attest(
    found_state="maintenance" if line369.expected_state != "maintenance"
    else "damaged",
)
line369.invalidate_recordset()
items369 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_high_impact"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", line369.id),
])
ok = (
    line369.has_discrepancy is True
    and line369.is_high_impact is False
    and not items369
)
print("  has_discrepancy:", line369.has_discrepancy,
      " is_high_impact:", line369.is_high_impact)
print("  action items spawned:", len(items369), "(want 0)")
print("T369:", "PASS" if ok else "FAIL")
results["T369"] = ok


# ============================================================
print()
print("=" * 72)
print("T370 - marking line.resolved=True auto-closes the item")
print("=" * 72)
line368.action_resolve(notes="Reconciled with movement log")
line368.invalidate_recordset()
open_items_370 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_high_impact"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", line368.id),
    ("state", "in", ("open", "in_progress")),
])
closed_items_370 = Item.sudo().search([
    ("trigger_type", "=", "stock_take_high_impact"),
    ("source_model_id", "=", source_model.id),
    ("source_id", "=", line368.id),
    ("state", "=", "cancelled"),
])
ok = (
    line368.resolved is True
    and not open_items_370
    and bool(closed_items_370)
)
print("  resolved:", line368.resolved)
print("  open items after resolve:", len(open_items_370), "(want 0)")
print("  closed items after resolve:",
      len(closed_items_370), "(want >=1)")
print("T370:", "PASS" if ok else "FAIL")
results["T370"] = ok


# ============================================================
print()
print("=" * 72)
print("T371 - 'Attest All As Expected' bulk-attests all unattested lines")
print("=" * 72)
bulk_session = StockTake.sudo()._create_session(
    session_type="ad_hoc",
    category_ids=Category.browse([trussing_cat.id]),  # standard, no escalation
)
# Take a slice — limit to 5 lines via the linked recordset (cancel
# the rest by hand to keep the test focused).
keep = bulk_session.line_ids[:5]
to_drop = bulk_session.line_ids - keep
to_drop.unlink()
bulk_session.invalidate_recordset()
assert len(bulk_session.line_ids) == 5
unattested_before = len(
    bulk_session.line_ids.filtered(lambda l: not l.attested))
bulk_session.with_user(manager).action_attest_all_as_expected()
bulk_session.invalidate_recordset()
attested_after = len(
    bulk_session.line_ids.filtered(lambda l: l.attested))
discrepancies = len(
    bulk_session.line_ids.filtered(lambda l: l.has_discrepancy))
ok = (
    unattested_before == 5
    and attested_after == 5
    and discrepancies == 0
)
print("  unattested before:", unattested_before, " attested after:",
      attested_after, "(want 5/5)")
print("  discrepancies:", discrepancies, "(want 0)")
print("T371:", "PASS" if ok else "FAIL")
results["T371"] = ok


# ============================================================
print()
print("=" * 72)
print("T372 - state machine pending → in_progress → completed")
print("=" * 72)
sm_session = StockTake.sudo()._create_session(
    session_type="ad_hoc",
    category_ids=Category.browse([trussing_cat.id]),
)
sm_session.line_ids[3:].unlink()  # keep 3 lines for speed
sm_session.invalidate_recordset()
sm_session.action_start()
assert sm_session.state == "in_progress"
# Try to complete with unattested lines → expect raise
err1, _v = _try(lambda: sm_session.action_complete())
assert isinstance(err1, UserError)
# Attest everything and re-try
sm_session.action_attest_all_as_expected()
sm_session.action_complete()
sm_session.invalidate_recordset()
# Final: terminal — illegal further transitions
err2, _v = _try(lambda: sm_session.action_start())
ok = (
    sm_session.state == "completed"
    and isinstance(err1, UserError)
    and "unattested" in str(err1).lower()
    and isinstance(err2, UserError)
)
print("  final state:", sm_session.state, "(want completed)")
print("  complete-with-unattested raised:",
      type(err1).__name__ if err1 else None)
print("  re-start from completed raised:",
      type(err2).__name__ if err2 else None)
print("T372:", "PASS" if ok else "FAIL")
results["T372"] = ok


# ============================================================
print()
print("=" * 72)
print("FULL SUMMARY")
print("=" * 72)
order = ["T360", "T361", "T362", "T363", "T364", "T365", "T366",
         "T367", "T368", "T369", "T370", "T371", "T372"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print("Total: {}/{} passed".format(passed, len(order)))

env.cr.rollback()
