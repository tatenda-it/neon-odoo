# -*- coding: utf-8 -*-
"""P5.M11 — quantity-aware reservation engine smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < p5m11_quantity_reservation_smoke.py

Quantity-tracked products reserve by COUNT against quantity_on_hand
(unit-less); serial products keep per-unit binding (byte-unchanged).
Rolls back -- never commits.

T1  quantity line qty 4 (qoh 440) -> ONE confirmed COUNT reservation
    quantity=4 (not "3 short"), product set, unit-less, avail 440->436
T2  reserve beyond qoh -> short, reason "only N in inventory"
T3  overlap: qoh 10, A reserves 7 -> B reserves 5 -> short, "committed"
T4  non-overlapping windows -> both reserve full
T5  serial product -> binds actual units (unchanged); beyond -> short
T6  conflict engine + reservation path agree on supply
T7  checkout quantity -> fulfilled + ONE unit-less movement (qty, actor)
T8  check-in quantity damaged -> stock_adjust + qoh decrement (actor)
T9  no product-less reservation rows ever created
T10 migration cleanup collapses N-soft_hold quantity line -> one COUNT row
"""
import traceback

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


try:
    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True,
                           mail_notify_force_send=False))
    EventJob = env["commercial.event.job"].sudo()
    Line = env["commercial.event.job.equipment.line"].sudo()
    Res = env["neon.equipment.reservation"].sudo()
    Unit = env["neon.equipment.unit"].sudo()
    Movement = env["neon.equipment.movement"].sudo()
    Product = env["product.template"].sudo()
    Wizard = env["neon.equipment.checkin.wizard"]
    from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
        ConflictEngine,
    )

    cat_truss = env.ref("neon_jobs.equipment_category_trussing")
    cat_sound = env.ref("neon_jobs.equipment_category_sound")
    mgr = env["res.users"].sudo().search([("login", "=", "p2m75_mgr")],
                                          limit=1)
    check("fixtures: trussing/sound cats + p2m75_mgr", bool(cat_truss)
          and bool(cat_sound) and bool(mgr))
    parent = env["commercial.job"].sudo().search([], limit=1, order="id")
    check("fixtures: a parent commercial.job exists", bool(parent))

    def mk_qty_product(name, qoh):
        return Product.create({
            "name": name, "workshop_name": name, "is_workshop_item": True,
            "equipment_category_id": cat_truss.id,
            "tracking_mode": "quantity", "quantity_on_hand": qoh})

    def mk_serial_product(name, n_units):
        p = Product.create({
            "name": name, "workshop_name": name, "is_workshop_item": True,
            "equipment_category_id": cat_sound.id, "tracking_mode": "serial"})
        Unit.create([{
            "product_template_id": p.id, "serial_number": "%s-%03d" % (name, i),
            "state": "active"} for i in range(n_units)])
        return p

    p_pins = mk_qty_product("P5M11 Truss Pins", 440)
    p_ten = mk_qty_product("P5M11 Ten Pack", 10)
    p_serial = mk_serial_product("P5M11 Serial Mic", 3)

    def mk_ej(efrom, eto, edate):
        ej = EventJob.create({
            "commercial_job_id": parent.id, "lead_tech_id": mgr.id,
            "event_date": edate, "prep_start_datetime": efrom,
            "return_eta_datetime": eto})
        ej.invalidate_recordset()
        return ej

    W1 = ("2026-12-15 06:00:00", "2026-12-16 20:00:00", "2026-12-15")
    W2 = ("2027-01-15 06:00:00", "2027-01-16 20:00:00", "2027-01-15")
    ej_q = mk_ej(*W1)

    def add_line(ej, product, qty):
        ln = Line.create({"event_job_id": ej.id,
                          "product_template_id": product.id,
                          "quantity_planned": qty})
        ln.invalidate_recordset()
        return ln

    # ---------------------------------------------------------------
    # T1 — quantity line qty 4 -> ONE COUNT reservation, reserve full
    l1 = add_line(ej_q, p_pins, 4)
    r1 = l1.reservation_ids
    check("T1: ONE COUNT soft_hold (not 4 rows), unit-less, product set, "
          "quantity=4",
          len(r1) == 1 and r1.state == "soft_hold" and not r1.unit_id
          and r1.quantity == 4 and r1.product_template_id.id == p_pins.id,
          (len(r1), r1.quantity, bool(r1.unit_id)))
    res1 = l1.action_allocate()
    r1.invalidate_recordset()
    check("T1: action_allocate reserves the full 4 (NOT '3 short')",
          res1.get("ok") and res1.get("allocated") == 4
          and r1.state == "confirmed" and r1.quantity == 4, res1)
    # availability seen by ANOTHER request on the same product+window =
    # supply - total committed (l1's own window-helper excludes itself by
    # design, so check the committed total drives 440 -> 436 for others).
    committed = Res._committed_qty_for_product(
        p_pins.id, r1.reserve_from, r1.reserve_to)
    check("T1: the commit reduces availability for others 440 -> 436",
          committed == 4 and (l1._qty_supply() - committed) == 436,
          (committed, l1._qty_supply()))

    # ---------------------------------------------------------------
    # T2 — reserve beyond qoh -> "only N in inventory"
    ej_q2 = mk_ej(*W2)
    l2 = add_line(ej_q2, p_pins, 500)
    res2 = l2.action_allocate()
    check("T2: qty 500 vs qoh 440 -> short, reason 'only 440 in inventory'",
          not res2.get("ok") and "only 440 in inventory" in res2.get("reason", ""),
          res2)

    # ---------------------------------------------------------------
    # T3 — overlap commitment (qoh 10): A reserves 7, B short by 2
    ej_a = mk_ej(*W1)
    ej_b = mk_ej(*W1)   # SAME window -> overlaps ej_a
    la = add_line(ej_a, p_ten, 7)
    ra = la.action_allocate()
    lb = add_line(ej_b, p_ten, 5)
    rb = lb.action_allocate()
    check("T3: A reserves 7 of 10 (ok)", ra.get("ok") and ra.get("allocated") == 7, ra)
    check("T3: B (overlap) short -> avail 3, reason 'committed on these dates'",
          not rb.get("ok") and rb.get("available") == 3
          and "committed on these dates" in rb.get("reason", ""), rb)

    # ---------------------------------------------------------------
    # T4 — non-overlapping window reserves full (no false short)
    ej_c = mk_ej(*W2)   # different dates from ej_a
    lc = add_line(ej_c, p_ten, 5)
    rc = lc.action_allocate()
    check("T4: non-overlapping window reserves the full 5 (no false short)",
          rc.get("ok") and rc.get("allocated") == 5, rc)

    # ---------------------------------------------------------------
    # T5 — serial path unchanged (binds real units)
    ej_s = mk_ej(*W1)
    ls = add_line(ej_s, p_serial, 2)
    rs = ls.action_allocate()
    ls.invalidate_recordset()
    bound = ls.reservation_ids.filtered(
        lambda r: r.state == "confirmed" and r.unit_id)
    check("T5: serial line binds 2 ACTUAL units (per-unit, unchanged)",
          rs.get("ok") and rs.get("allocated") == 2 and len(bound) == 2
          and all(r.quantity == 1 for r in bound), (rs, len(bound)))
    ej_s2 = mk_ej(*W2)
    ls2 = add_line(ej_s2, p_serial, 5)   # only ~1 unit free now
    rs2 = ls2.action_allocate()
    check("T5: serial beyond available units -> short", not rs2.get("ok"), rs2)

    # ---------------------------------------------------------------
    # T6 — conflict engine + reservation path agree on supply
    ce = ConflictEngine(env)
    check("T6: line._qty_supply() == ConflictEngine._available_for_product",
          l1._qty_supply() == ce._available_for_product(p_pins.id), l1._qty_supply())

    # ---------------------------------------------------------------
    # T7 — checkout quantity -> fulfilled + ONE unit-less movement (actor)
    mv_before = Movement.search_count([("event_job_id", "=", ej_q.id)])
    l1.with_user(mgr.id).action_checkout()
    l1.invalidate_recordset(); r1.invalidate_recordset()
    mv = Movement.search([("event_job_id", "=", ej_q.id),
                          ("movement_type", "=", "checkout")])
    check("T7: quantity checkout -> reservation fulfilled + ONE unit-less "
          "movement (quantity=4, product set, actor=mgr)",
          r1.state == "fulfilled" and len(mv) == 1 and not mv.unit_id
          and mv.quantity == 4 and mv.product_template_id.id == p_pins.id
          and mv.actor_id.id == mgr.id,
          (r1.state, len(mv), mv.quantity if mv else None))

    # ---------------------------------------------------------------
    # T8 — check-in quantity damaged -> stock_adjust + qoh decrement (actor)
    qoh_before = p_pins.quantity_on_hand
    wiz = Wizard.with_user(mgr.id).with_context(
        default_event_job_id=ej_q.id)
    wvals = wiz.default_get(["event_job_id", "checkin_line_ids",
                            "to_location_text"])
    w = wiz.create(wvals)
    check("T8: check-in wizard built ONE unit-less quantity line (qty 4)",
          len(w.checkin_line_ids) == 1 and not w.checkin_line_ids.unit_id
          and w.checkin_line_ids.quantity == 4
          and w.checkin_line_ids.product_template_id.id == p_pins.id,
          len(w.checkin_line_ids))
    # damaged condition requires a photo (audit rule, fires for quantity
    # lines too) -- supply a 1x1 PNG.
    _PNG_1X1 = (b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE"
                b"QVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    w.checkin_line_ids.write({"condition_at_event": "damaged",
                              "damaged_qty": 2, "photo": _PNG_1X1})
    w.action_confirm()
    p_pins.invalidate_recordset()
    sa = Movement.search([("event_job_id", "=", ej_q.id),
                          ("movement_type", "=", "stock_adjust")])
    check("T8: damaged 2 -> stock_adjust movement (qty 2, actor=mgr) + "
          "quantity_on_hand %d -> %d" % (qoh_before, qoh_before - 2),
          len(sa) == 1 and sa.quantity == 2 and sa.actor_id.id == mgr.id
          and p_pins.quantity_on_hand == qoh_before - 2,
          (len(sa), p_pins.quantity_on_hand))

    # ---------------------------------------------------------------
    # T9 — no product-less reservation rows created by the engine
    test_ejs = (ej_q | ej_q2 | ej_a | ej_b | ej_c | ej_s | ej_s2)
    productless = Res.search([("event_job_id", "in", test_ejs.ids),
                              ("product_template_id", "=", False)])
    check("T9: ZERO product-less reservation rows across the test event jobs",
          len(productless) == 0, productless.ids)

    # ---------------------------------------------------------------
    # T10 — migration cleanup collapses a crafted N-soft_hold quantity line
    ej_m = mk_ej(*W1)
    lm = add_line(ej_m, p_pins, 3)     # auto-spawn -> ONE count row
    # craft the pre-M11 mess: add 2 extra unit-less soft_holds
    ej_m._spawn_one_reservation_for_line(lm, quantity=1)
    ej_m._spawn_one_reservation_for_line(lm, quantity=1)
    lm.invalidate_recordset()
    before = lm.reservation_ids.filtered(lambda r: r.state == "soft_hold")
    plan = Res._p5m11_reservation_cleanup(dry_run=True)
    check("T10: dry-run reports the crafted line for collapse (3 soft_holds)",
          len(before) == 3
          and any(c["line"] == lm.id for c in plan["collapse"]), plan["collapse"])
    Res._p5m11_reservation_cleanup(dry_run=False)
    lm.invalidate_recordset()
    after = lm.reservation_ids.filtered(lambda r: r.state == "soft_hold")
    cancelled = lm.reservation_ids.filtered(lambda r: r.state == "cancelled")
    check("T10: after cleanup -> ONE COUNT soft_hold (quantity=3), extras "
          "cancelled",
          len(after) == 1 and after.quantity == 3 and not after.unit_id
          and len(cancelled) == 3,
          (len(after), after.quantity if after else None, len(cancelled)))

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    try:
        env.cr.rollback()
    except Exception:  # noqa: BLE001
        pass

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))
