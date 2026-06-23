"""QUOTE-UX-4 smoke -- NL per-line days + explicit amount via the LLM translator.

The per-line handlers (days <item> <n>, price <item> <amount>) and the engine
line discount-only rule ALREADY exist; the build only (a) adds per-line
'days <item> <n>' to the _wa12_llm_translate_edit allowed-commands prompt so NL
routes to it, and (b) rewords the engine-line price-markup rejection to a clear
rep-facing message. This proves: the prompt now lists the per-line days command
(+ keeps global days); a stubbed NL -> the canonical command round-trips; the
existing per-line days + price handlers apply (deterministic, re-run through
_wa12_try_edit); and the new markup message is clear (names item + rate +
custom-line advice) without changing the reject behaviour.

WA sends are patched (captured, never sent). All writes roll back.
"""
import re
from unittest.mock import patch

from odoo import fields

M = env["neon.whatsapp.message"].sudo()
USD = env.ref("base.USD")
rep = env["res.users"].search([("login", "=", "p2m75_sales")], limit=1)
FROM = "+263779126099"

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


_WIRE = []


def _cap_reply(self, raw_from, from_e164, text):
    _WIRE.append(text or "")
    return True


def _cap_btn(self, raw_from, from_e164, body, buttons):
    _WIRE.append(body or "")
    return True


def _cap_list(self, raw_from, from_e164, body, button_text, rows):
    _WIRE.append(body or "")
    return True


def mk_quote():
    partner = env["res.partner"].create(
        {"name": "[TEST-QUX4] Client", "is_company": True})
    venue = env["res.partner"].create(
        {"name": "[TEST-QUX4] Venue", "is_company": True})
    job = env["commercial.job"].create({
        "partner_id": partner.id, "venue_id": venue.id,
        "event_date": fields.Date.today(), "currency_id": USD.id})
    ej = env["commercial.event.job"].create({"commercial_job_id": job.id})
    q = env["neon.finance.quote"].create({
        "event_job_id": ej.id, "currency_id": USD.id,
        "salesperson_id": rep.id})
    L = env["neon.finance.quote.line"]
    # line 1: non-custom priced line (rate 250/day, 2 days)
    l1 = L.create({"quote_id": q.id, "line_type": "equipment", "name": "RIG",
                   "quantity": 1.0, "duration_days": 2, "unit_rate": 250.0,
                   "pricing_status": "manual"})
    # line 2: custom line (100/day, 2 days)
    l2 = L.create({"quote_id": q.id, "line_type": "custom", "name": "LOGISTICS",
                   "quantity": 1.0, "duration_days": 2, "unit_rate": 100.0,
                   "pricing_status": "manual"})
    return q, l1, l2


_PS = [patch.object(type(M), "_wa6_reply", _cap_reply),
       patch.object(type(M), "_wa6_send_buttons", _cap_btn),
       patch.object(type(M), "_wa6_send_list", _cap_list),
       patch("odoo.addons.mail.models.mail_mail.MailMail.send",
             lambda self, *a, **k: True)]
for p in _PS:
    p.start()

try:
    # 1. TRANSLATOR PROMPT now lists per-line 'days <item> <n>' (+ keeps global)
    cap = {}

    def _cap_chat(self, msgs):
        cap["sys"] = msgs[0]["content"] if msgs else ""
        return "days 2 1"

    q, l1, l2 = mk_quote()
    with patch.object(type(M), "_wa12_llm_chat", _cap_chat):
        out = M._wa12_llm_translate_edit("item 2 is 1 day hire", q)
    chk("translator prompt lists per-line 'days <item> <n>'",
        "days <item> <n>" in cap.get("sys", ""))
    chk("translator prompt still lists global 'days <n>'",
        "days <n>" in cap.get("sys", ""))
    chk("translator still lists 'price <item> <amount>'",
        "price <item> <amount>" in cap.get("sys", ""))
    chk("stubbed NL 'item 2 is 1 day hire' -> translate returns 'days 2 1'",
        out == "days 2 1")
    env.cr.rollback()

    # 2. per-line days handler applies (days 2 1) + subtotal recomputes
    q, l1, l2 = mk_quote()
    base2 = l2.line_subtotal
    M._wa12_try_edit(q, "days 2 1", FROM, FROM)
    chk("days 2 1 -> line2 duration_days == 1 (line1 untouched)",
        l2.duration_days == 1 and l1.duration_days == 2)
    chk("line2 subtotal recomputed to the 1-day value",
        abs(l2.line_subtotal - base2 / 2.0) < 0.01)
    env.cr.rollback()

    # 3. explicit amount on a CUSTOM line (price 2 150) -> unit_rate set
    q, l1, l2 = mk_quote()
    M._wa12_try_edit(q, "price 2 150", FROM, FROM)
    chk("price 2 150 (custom) -> unit_rate 150", abs(l2.unit_rate - 150.0) < 0.01)
    env.cr.rollback()

    # 4. explicit amount on a non-custom line BELOW base (price 1 150) -> discount
    q, l1, l2 = mk_quote()
    M._wa12_try_edit(q, "price 1 150", FROM, FROM)   # base 250, 150 < 250
    chk("price 1 150 (engine, <base) -> discount to 150/day (rate kept 250)",
        l1.unit_rate == 250.0 and abs(l1.discount_amount - 100.0) < 0.01)
    env.cr.rollback()

    # 5. explicit amount on a non-custom line ABOVE base -> CLEAR markup message
    q, l1, l2 = mk_quote()
    _WIRE.clear()
    M._wa12_try_edit(q, "price 1 300", FROM, FROM)   # 300 > 250
    msg = " ".join(_WIRE)
    chk("price 1 300 (engine, >base) -> clear markup msg (item + rate + custom)",
        "RIG" in msg and "catalogue rate" in msg and "custom line" in msg.lower())
    chk("the rejected markup did NOT change the line",
        l1.unit_rate == 250.0 and l1.discount_amount == 0.0)
    env.cr.rollback()

    # 6. explicit-amount NL routes to the existing 'price <item> <amount>'
    q, l1, l2 = mk_quote()
    with patch.object(type(M), "_wa12_llm_chat",
                      lambda self, msgs: "price 2 150"):
        out = M._wa12_llm_translate_edit("logistics is 150", q)
    chk("stubbed NL 'logistics is 150' -> translate returns 'price 2 150'",
        out == "price 2 150")
    env.cr.rollback()
finally:
    for p in _PS:
        try:
            p.stop()
        except Exception:
            pass
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
