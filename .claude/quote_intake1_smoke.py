"""WA-INTAKE-1 smoke -- ambiguous client in the one-shot quote template now
opens the qc_pick pick-list (reusing the structured lane's flow) instead of the
"send the template again" dead-end, holding the parsed draft so nothing is
re-typed on resume.

Proves: ambiguous -> pick-list (not dead-end) + a qc_pick session buffering the
parsed draft (template=True, extras, matched); pick a number -> the quote
resumes via _wa12_quote_from_slots with the SAME items/date/event/venue and the
chosen client; an EXACT match still resolves directly (no pick-list); and the
buffer extension is additive (a no-template caller defaults template=False /
extras={}, so the structured lane is unchanged).

WA sends + audit patched (captured, never sent). All writes roll back (the flow
does not commit).
"""
from unittest.mock import patch

from odoo import fields

M = env["neon.whatsapp.message"].sudo()
Sess = env["neon.wa.equip.session"].sudo()
USD = env.ref("base.USD")
# NB: the qc_pick CAPTURE re-checks _wa12_can_quote(sess.user_id); in the real
# flow the sender is always can-quote (gated upstream in _wa12_maybe_intercept
# before process_template runs), so the rep MUST be a can-quote user here.
rep = env["res.users"].search([("login", "=", "p2m75_mgr")], limit=1)
FROM = "+263779126055"     # ambiguous flow
FROM2 = "+263779126056"    # exact-match flow
FROM3 = "+263779126057"    # additive-buffer parity

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


_WIRE = []


def _cap(self, raw_from, from_e164, *a, **k):
    # _wa6_reply(text) / _wa6_send_buttons(body, buttons) / _wa6_send_list(body,..)
    _WIRE.append(a[0] if a else "")
    return True


BODY = ("Client: [TEST-WAI1] Econet\nEvent: Test Event\nVenue: Test Venue\n"
        "Date: 2026-08-01\nDays: 2\nItems:\n- WAI1TESTRIG")

_PS = [patch.object(type(M), "_wa6_reply", _cap),
       patch.object(type(M), "_wa6_send_buttons", _cap),
       patch.object(type(M), "_wa6_send_list", _cap),
       patch.object(type(M), "_wa6_audit_in", lambda self, *a, **k: None),
       patch("odoo.addons.mail.models.mail_mail.MailMail.send",
             lambda self, *a, **k: True)]
for p in _PS:
    p.start()

try:
    # fixtures (no commit -> single transaction, rolled back at the end)
    cat = env["neon.equipment.category"].create(
        {"name": "[TEST-WAI1] Cat", "code": "TWAI1"})
    prod = env["product.template"].create(
        {"name": "WAI1TESTRIG", "is_workshop_item": True,
         "equipment_category_id": cat.id, "type": "consu"})
    rule = env["neon.finance.pricing.rule"].create(
        {"product_template_id": prod.id, "currency_id": USD.id,
         "base_rate": 200.0, "effective_date": "2020-01-01"})
    env["neon.finance.pricing.bracket"].create(
        {"rule_id": rule.id, "sequence": 1, "day_from": 1, "day_to": -1,
         "multiplier": 1.0})
    p1 = env["res.partner"].create(
        {"name": "[TEST-WAI1] Econet Holdings Zig", "is_company": True})
    p2 = env["res.partner"].create(
        {"name": "[TEST-WAI1] Econet Holdings Zimbabwe", "is_company": True})
    for ph in (FROM, FROM2, FROM3):
        s = Sess._active_for_phone(ph)
        if s:
            s.sudo().write({"active": False})

    # 1. AMBIGUOUS -> pick-list (not the dead-end), draft buffered
    _WIRE.clear()
    M._wa12_process_template_filled(rep, BODY, FROM, FROM, M)
    reply = " | ".join(_WIRE)
    chk("ambiguous -> NOT the 'send the template again' dead-end",
        "Send the template again" not in reply)
    chk("ambiguous -> pick-list names both candidates",
        "Econet Holdings Zig" in reply and "Econet Holdings Zimbabwe" in reply)
    sess = Sess._active_for_phone(FROM)
    buf = sess._get_buffer() if sess else {}
    chk("qc_pick session opened with template=True",
        bool(sess) and sess.step == "qc_pick" and buf.get("template") is True)
    chk("buffer carries the parsed extras (event + venue)",
        (buf.get("extras") or {}).get("event_name") == "Test Event"
        and (buf.get("extras") or {}).get("venue") == "Test Venue")
    chk("buffer carries the matched item(s)", len(buf.get("matched") or []) >= 1)

    # 2. PICK "1" -> resume -> quote built with the picked client + draft
    cand_ids = buf.get("candidate_ids") or []
    picked = env["res.partner"].browse(cand_ids[0]) if cand_ids else env["res.partner"]
    _WIRE.clear()
    M._wa12_handle_capture(sess, "1", FROM, FROM)
    q = env["neon.finance.quote"].search(
        [("partner_id", "=", picked.id)], order="id desc", limit=1)
    chk("pick 1 -> quote built for the picked client (nothing re-typed)",
        bool(q) and q.partner_id == picked)
    chk("resumed quote kept the item line", bool(q) and len(q.line_ids) >= 1)
    cj = q.event_job_id.commercial_job_id if q else env["commercial.job"]
    chk("resumed quote kept the date", bool(cj) and bool(cj.event_date))
    # F5/Part A: event subject + venue land on the EVENT job's client_notes
    notes = (q.event_job_id.client_notes or "") if q else ""
    chk("resumed quote kept the event + venue extras",
        "Test Event" in notes and "Test Venue" in notes)

    # 3. EXACT match -> direct resolve, NO pick-list
    body_exact = BODY.replace("Client: [TEST-WAI1] Econet\n",
                              "Client: [TEST-WAI1] Econet Holdings Zig\n")
    _WIRE.clear()
    M._wa12_process_template_filled(rep, body_exact, FROM2, FROM2, M)
    s2 = Sess._active_for_phone(FROM2)
    qx = env["neon.finance.quote"].search(
        [("partner_id", "=", p1.id)], order="id desc", limit=1)
    chk("exact match -> quote built directly, no qc_pick session",
        bool(qx) and not (s2 and s2.step == "qc_pick"))

    # 4. additive buffer: a no-template caller defaults template=False/extras={}
    M._wa12_start_client_intake(rep, "[TEST-WAI1] Econet", (p1 | p2), [], "", 1,
                                FROM3, FROM3)
    s3 = Sess._active_for_phone(FROM3)
    b3 = s3._get_buffer() if s3 else {}
    chk("structured/no-template caller -> template defaults False (parity)",
        bool(s3) and b3.get("template") is False and (b3.get("extras") or {}) == {})
finally:
    for p in _PS:
        try:
            p.stop()
        except Exception:
            pass
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
