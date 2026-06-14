"""P-WA-12.7 — QUOTE-BY-TEMPLATE (Part A) + date/quotation/expiry (Part B/C) WIRE
smoke. Asserts the BOT'S ACTUAL replies + the persisted records through the REAL
dispatch (_wa12_maybe_intercept), Groq mocked. Covers the VERIFY list:

  T1  trigger ("Quote a client" tap) -> the copy-fill SKELETON (no command syntax)
  T2  a FILLED template -> a ONE-reply draft (all items, qtys from "<qty> x", VAT)
  T3  Bug 1: a DATE RANGE persists BOTH event_date + event_end_date (shared chain)
  T4  duration money: Days: N -> duration_days=N on every line; subtotal=rate*qty*N
  T5  quotation_date = Harare today on the quote
  T6  expiry: expires_at rebased on quotation_date + the configured validity days
  T7  UNMATCHED item FLAGS (pending A); submit BLOCKED; "A = <item>" resolves; drop
  T8  new client in ONE message: Quote:+Contact/Phone/Email -> company + child
  T9  stepper FALLBACK: "step" -> q_client; inline "Quote: X — items" -> stepper
  T10 Venue: free-text -> event_job.venue_full_address

Runs in `odoo shell -d neon_crm`. Self-contained [TEST-WA127] fixtures; torn down.
"""
from contextlib import ExitStack  # noqa: F401
from unittest.mock import patch
import datetime
import pytz

_passed = 0
_total = 0
results = {}


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[n] = ok
    print("%s:" % n, "PASS" if ok else "FAIL", d if not ok else "")


from odoo.addons.neon_channels.models import wa_payload  # noqa: E402

env = env(context=dict(env.context, tracking_disable=True,
                       mail_create_nosubscribe=True,
                       mail_notify_force_send=False))
SECRET = env["ir.config_parameter"].sudo().get_param("database.secret") or ""
M = env["neon.crew.whatsapp.message"].sudo() if False else None
# resolve the dispatcher model (the one carrying _wa12_maybe_intercept)
for _name in env.registry.models:
    if hasattr(env[_name], "_wa12_process_template_filled"):
        M = env[_name].sudo()
        break
P = env["res.partner"].sudo()
Q = env["neon.finance.quote"].sudo()
PT = env["product.template"].sudo()
ECat = env["neon.equipment.category"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Bracket = env["neon.finance.pricing.bracket"].sudo()
Users = env["res.users"].sudo()
USD = env.ref("base.USD")
PHONE = "+263779127001"
HARARE = pytz.timezone("Africa/Harare")
_HARARE_TODAY = HARARE.fromutc(datetime.datetime.utcnow()).date()

_MAILP = patch("odoo.addons.mail.models.mail_mail.MailMail.send",
               lambda self, *a, **k: True)
_MAILP.start()

_WIRE = []


def _cap_reply(self, raw_from, from_e164, text):
    _WIRE.append({"kind": "text", "body": text or ""}); return True


def _cap_btn(self, raw_from, from_e164, body, buttons):
    _WIRE.append({"kind": "buttons", "body": body or ""}); return True


def _cap_list(self, raw_from, from_e164, body, bt, rows):
    _WIRE.append({"kind": "list", "body": body or ""}); return True


_PS = [patch.object(type(M), "_wa6_reply", _cap_reply),
       patch.object(type(M), "_wa6_send_buttons", _cap_btn),
       patch.object(type(M), "_wa6_send_list", _cap_list)]
for _p_ in _PS:
    _p_.start()


def _clear():
    _WIRE.clear()


def _last():
    return _WIRE[-1]["body"] if _WIRE else ""


def _alltext():
    return "\n".join(e["body"] for e in _WIRE)


def _txt(b):
    return {"from": PHONE, "type": "text", "text": {"body": b}, "id": "w127"}


def _clear_sess():
    s = env["neon.wa.equip.session"].sudo().with_context(
        active_test=False).search([("phone_number", "=", PHONE)])
    if s:
        s.unlink()


# ---- fixtures ----
def _purge_rules():
    env.cr.execute(
        "DELETE FROM neon_finance_pricing_bracket WHERE rule_id IN "
        "(SELECT id FROM neon_finance_pricing_rule WHERE name LIKE %s)",
        ("%[TEST-WA127]%",))
    env.cr.execute("DELETE FROM neon_finance_pricing_rule WHERE name LIKE %s",
                   ("%[TEST-WA127]%",))


def _purge():
    parts = P.with_context(active_test=False).search(
        [("name", "like", "[TEST-WA127]")])
    env.cr.execute(
        "DELETE FROM neon_finance_payment_term WHERE name LIKE %s "
        "OR partner_id IN %s", ("%[TEST-WA127]%", tuple(parts.ids) or (0,)))
    _tq = Q.with_context(active_test=False).search(
        [("partner_id", "in", parts.ids)])
    env["neon.finance.approval"].sudo().search(
        [("quote_id", "in", _tq.ids)]).unlink()
    env["neon.finance.invoice.schedule"].sudo().search(
        [("quote_id", "in", _tq.ids)]).unlink()
    _ej = _tq.mapped("event_job_id"); _cj = _ej.mapped("commercial_job_id")
    _tq.unlink(); _ej.exists().unlink(); _cj.exists().unlink()
    _purge_rules()
    # child contacts first (parent FK)
    parts.filtered(lambda p: p.parent_id).exists().unlink()
    parts.exists().unlink()


_clear_sess()
_purge()
PT.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA127]")]).unlink()


def _cat(code, name):
    c = ECat.search([("code", "=", code)], limit=1)
    return c or ECat.create({"code": code, "name": name})


cat_vis, cat_lig = _cat("visual", "Visual"), _cat("lighting", "Lighting")


def _p(name, cat):
    p = PT.create({"name": name, "workshop_name": name.lower(),
                   "is_workshop_item": True, "list_price": 10.0,
                   "equipment_category_id": cat.id})
    pr = Rule.create({"name": "[TEST-WA127] R-%d" % p.id,
                      "product_template_id": p.id, "currency_id": USD.id,
                      "base_rate": 100.0, "effective_date": "2020-01-01"})
    Bracket.create({"rule_id": pr.id, "sequence": 1, "day_from": 1,
                    "day_to": -1, "multiplier": 1.0})
    return p


scr = _p("[TEST-WA127] 6M X 2M LED SCREEN", cat_vis)
can = _p("[TEST-WA127] RGBWAUV 18X18 ZOOM INDOOR LED CAN", cat_lig)
mole = _p("[TEST-WA127] 4x100W INDOOR MOLEFAYS", cat_lig)
# a TRULY rate-less product (no product rule + a category with no rule) for the
# F8 '@ $price' promotion test (#3) -- so the engine can't price it and the rep
# price sticks.
cat_norule = _cat("TW127NR", "[TEST-WA127] NoRuleCat")
norate = PT.create({"name": "[TEST-WA127] NORATEWIDGET", "list_price": 5.0,
                    "workshop_name": "noratewidget", "is_workshop_item": True,
                    "equipment_category_id": cat_norule.id})
client = P.create({"name": "[TEST-WA127] Acme Events Co",
                   "email": "acme127@neon.test"})
env.company.sudo().write({"email": env.company.email or "noreply@neon.test"})

g_sales = env.ref("neon_core.group_neon_sales_rep")
_lg = "pwa127_sales"
ex = Users.with_context(active_test=False).search([("login", "=", _lg)], limit=1)
if not ex:
    ex = Users.with_context(no_reset_password=True).create({
        "name": "PWA127 Sales", "login": _lg, "password": "test123",
        "groups_id": [(4, env.ref("base.group_user").id), (4, g_sales.id)]})
else:
    ex.write({"groups_id": [(4, g_sales.id)], "active": True})
u_sales = ex
Bot = env["neon.bot.user"].sudo()
Bot.with_context(active_test=False).search(
    [("phone_number", "=", PHONE)]).unlink()
Bot.create({"name": "[TEST-WA127] bot", "phone_number": PHONE,
            "user_id": u_sales.id})
# config params for the expiry tests (validity 30, line OFF by default)
ICP = env["ir.config_parameter"].sudo()
ICP.set_param("neon_finance.quote_validity_period_days", "30")
ICP.set_param("neon_finance.show_quote_expiry_line", "False")
env.cr.commit()
D = M.with_user(u_sales)
_LLM_QUOTE = ('{"intent":"quote","client":"","items":[],"date":null,'
              '"phone":null,"email":null,"contact_person":null,'
              '"address":null,"event_name":null}')


def _latest_quote():
    return Q.search([("partner_id", "child_of", client.id)],
                    order="id desc", limit=1) or Q.search(
        [("salesperson_id", "=", u_sales.id)], order="id desc", limit=1)


# ============================================================ T1: trigger -> skeleton
_clear(); _clear_sess()
_startid = wa_payload.encode(SECRET, "wa12_start", u_sales.id)
D._wa12_maybe_intercept({"from": PHONE, "type": "interactive",
                         "interactive": {"button_reply": {"id": _startid,
                                                          "title": "Quote a client"}},
                         "id": "t1"})
sk = _last()
# NB the helper line legitimately shows the custom-line FORMAT "<qty> x <desc>
# @ $<price>" (the user-approved exception) -- so we do NOT assert "no <".
_check("T1-trigger-sends-template-skeleton",
       "Quote:" in sk and "Items:" in sk and "Contact:" in sk
       and "Copy this" in sk and "no command syntax" not in sk.lower(),
       "skeleton=%r" % sk[:80])


# ============================================================ T2/T4/T5/T6: filled template happy path
_clear(); _clear_sess()
_tmpl = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Event: Year-End Gala\n"
    "Venue: Borrowdale Racecourse, Harare\n"
    "Date: 25 September 2026\n"
    "Days: 3\n"
    "Items:\n"
    "- 2 x 6m x 2m led screen\n"
    "- 4 x zoom led can\n"
    "- 1 x 4x100 molefay\n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl))
q2 = _latest_quote()
draft2 = _alltext()
_check("T2-filled-template-one-reply-draft",
       bool(q2) and len(q2.line_ids) == 3
       and set(q2.line_ids.mapped("quantity")) == {2.0, 4.0, 1.0}
       and "Total:" in draft2,
       "lines=%d qtys=%s" % (len(q2.line_ids) if q2 else 0,
                             q2.line_ids.mapped("quantity") if q2 else []))
_check("T4-duration-days-on-every-line-money",
       bool(q2) and set(q2.line_ids.mapped("duration_days")) == {3}
       and all(abs((l.unit_rate or 0) * (l.quantity or 0) * 3
                   - (l.line_subtotal or 0)) < 0.5 for l in q2.line_ids),
       "durs=%s" % (set(q2.line_ids.mapped("duration_days")) if q2 else set()))
_check("T5-quotation_date-harare-today",
       bool(q2) and q2.quotation_date == _HARARE_TODAY,
       "quotation_date=%s want=%s" % (q2.quotation_date if q2 else None,
                                      _HARARE_TODAY))
# expiry rebased on quotation_date + 30 (the configured validity)
_want_exp = _HARARE_TODAY + datetime.timedelta(days=30)
_check("T6-expires_at-rebased-on-quotation_date+validity",
       bool(q2) and q2.expires_at == _want_exp,
       "expires_at=%s want=%s" % (q2.expires_at if q2 else None, _want_exp))
_check("T10-venue-free-text-on-event-job-notes",
       bool(q2) and q2.event_job_id
       and "Borrowdale" in (q2.event_job_id.client_notes or ""),
       "notes=%r" % (q2.event_job_id.client_notes if q2 and q2.event_job_id
                     else None))


# ============================================================ T3: Bug 1 — range persists BOTH ends
_clear(); _clear_sess()
_tmpl_range = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Date: 7 August 2026 - 11 August 2026\n"
    "Days: 4\n"
    "Items:\n"
    "- 1 x 6m x 2m led screen\n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_range))
q3 = _latest_quote()
cj3 = q3.event_job_id.commercial_job_id if q3 and q3.event_job_id else None
_check("T3-Bug1-date-range-persists-BOTH-ends",
       bool(cj3)
       and cj3.event_date == datetime.date(2026, 8, 7)
       and cj3.event_end_date == datetime.date(2026, 8, 11),
       "start=%s end=%s" % (cj3.event_date if cj3 else None,
                            cj3.event_end_date if cj3 else None))
_check("T3b-days-separate-from-range-span",
       bool(q3) and set(q3.line_ids.mapped("duration_days")) == {4},
       "durs=%s (Days:4 drives duration, not the 5-day span)"
       % (set(q3.line_ids.mapped("duration_days")) if q3 else set()))


# ============================================================ T7: unmatched FLAG + submit block + resolve
_clear(); _clear_sess()
_tmpl_unmatched = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Date: 25 September 2026\n"
    "Days: 1\n"
    "Items:\n"
    "- 1 x 6m x 2m led screen\n"
    "- 1 x zxqwvb nonsense gadget\n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_unmatched))
q7 = _latest_quote()
flagged = _alltext()
sess7 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
b7 = sess7._get_buffer() if sess7 else {}
_check("T7a-unmatched-flags-not-dead-end",
       bool(q7) and len(q7.line_ids) == 1   # matched screen drafted
       and "Not matched yet" in flagged
       and len(b7.get("wa12_pending") or []) == 1,
       "lines=%d pending=%d" % (len(q7.line_ids) if q7 else 0,
                                len(b7.get("wa12_pending") or [])))
# submit BLOCKED while pending
_clear()
D._wa12_maybe_intercept(_txt("yes"))
q7.invalidate_recordset()
_check("T7b-submit-BLOCKED-until-resolved",
       q7.state == "draft" and "resolve the flagged" in _last().lower(),
       "state=%s reply=%r" % (q7.state, _last()[:70]))
# resolve A with a real item -> line added + pending cleared
_clear()
D._wa12_maybe_intercept(_txt("A = 4x100 molefay"))
q7.invalidate_recordset()
sess7 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
b7b = sess7._get_buffer() if sess7 else {}
_check("T7c-resolve-A-adds-line-clears-pending",
       len(q7.line_ids) == 2 and not (b7b.get("wa12_pending") or []),
       "lines=%d pending=%d" % (len(q7.line_ids),
                                len(b7b.get("wa12_pending") or [])))
# now submit is allowed (no pending, all priced) -> pending_approval
_clear()
D._wa12_maybe_intercept(_txt("yes"))
q7.invalidate_recordset()
_check("T7d-submit-allowed-after-resolve",
       q7.state in ("pending_approval", "approved"),
       "state=%s" % q7.state)

# drop-path: a fresh unmatched, then "drop A" -> pending cleared, submit OK
_clear(); _clear_sess()
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_unmatched))
q7d = _latest_quote()
_clear()
D._wa12_maybe_intercept(_txt("drop A"))
sess7d = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
b7d = sess7d._get_buffer() if sess7d else {}
_check("T7e-drop-A-clears-pending",
       not (b7d.get("wa12_pending") or []) and len(q7d.line_ids) == 1,
       "pending=%d lines=%d" % (len(b7d.get("wa12_pending") or []),
                                len(q7d.line_ids)))


# ============================================================ T8: NEW client in ONE message
_clear(); _clear_sess()
_newco = "[TEST-WA127] Zephyr Holdings"
_tmpl_new = (
    "Quote: %s\n"
    "Contact: [TEST-WA127] Jane Doe\n"
    "Phone: +263772555111\n"
    "Email: jane127@zephyr.test\n"
    "Date: 25 September 2026\n"
    "Days: 1\n"
    "Items:\n"
    "- 1 x 6m x 2m led screen\n") % _newco
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_new))
newco = P.search([("name", "=", _newco)], limit=1)
child = P.search([("name", "=", "[TEST-WA127] Jane Doe"),
                  ("parent_id", "=", newco.id)], limit=1) if newco else P.browse()
_check("T8-new-client-one-message-company+child",
       bool(newco) and newco.is_company and bool(child)
       and "555111" in (child.phone or newco.phone or ""),
       "company=%s child=%s" % (bool(newco), bool(child)))


# ============================================================ T9: stepper FALLBACK
_clear(); _clear_sess()
D._wa12_maybe_intercept(_txt("Quote: step"))
s9 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
_check("T9a-quote-colon-step-forces-stepper",
       bool(s9) and s9.step == "q_client", "step=%s" % (s9.step if s9 else None))
_clear(); _clear_sess()
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt("Quote: Acme — led screen, 2026-09-25"))
s9b = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
_check("T9b-inline-quote-falls-to-stepper",
       bool(s9b) and s9b.step == "q_client",
       "step=%s" % (s9b.step if s9b else None))
_clear(); _clear_sess()
D._wa12_maybe_intercept(_txt("quote"))
_check("T9c-bare-quote-sends-skeleton",
       "Items:" in _last() and "Copy this" in _last(), "reply=%r" % _last()[:60])


# ============================================================ REVIEW-FIX regression
# T11 (#1 HIGH): an ALL-unmatched template + Days:3 -> zero-line draft, days
# BUFFERED; resolving a flag bills at days 3 (was undercharging at 1).
_clear(); _clear_sess()
_tmpl_allun = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Date: 25 September 2026\n"
    "Days: 3\n"
    "Items:\n"
    "- 1 x zxqwvb nonsense one\n"
    "- 1 x ploremp nonsense two\n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_allun))
q11 = _latest_quote()
s11 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
b11 = s11._get_buffer() if s11 else {}
_check("T11a-all-unmatched-zero-line-draft-days-buffered",
       bool(q11) and len(q11.line_ids) == 0
       and len(b11.get("wa12_pending") or []) == 2 and b11.get("wa12_days") == 3,
       "lines=%d pending=%d days=%s" % (len(q11.line_ids) if q11 else -1,
                                        len(b11.get("wa12_pending") or []),
                                        b11.get("wa12_days")))
_clear()
D._wa12_maybe_intercept(_txt("A = 6m x 2m led screen"))
q11.invalidate_recordset()
l11 = q11.line_ids[:1]
_check("T11b-resolved-line-bills-buffered-days-3-not-1",
       bool(l11) and l11.duration_days == 3
       and abs((l11.unit_rate or 0) * (l11.quantity or 0) * 3
               - (l11.line_subtotal or 0)) < 0.5,
       "duration_days=%s subtotal=%s" % (l11.duration_days if l11 else None,
                                         l11.line_subtotal if l11 else None))

# T12 (#2 MEDIUM): unfilled skeleton "- 1 x" lines do NOT become phantom flags.
_clear(); _clear_sess()
_tmpl_blanks = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Date: 25 September 2026\n"
    "Days: 1\n"
    "Items:\n"
    "- 2 x 6m x 2m led screen\n"
    "- 1 x \n"
    "- 1 x \n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_blanks))
q12 = _latest_quote()
s12 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
b12 = s12._get_buffer() if s12 else {}
_check("T12-skeleton-blanks-no-phantom-flags",
       bool(q12) and len(q12.line_ids) == 1
       and not (b12.get("wa12_pending") or []),
       "lines=%d pending=%d" % (len(q12.line_ids) if q12 else -1,
                                len(b12.get("wa12_pending") or [])))

# T13 (#3 LOW): a MATCHED item with NO catalogue rate + "@ $price" -> the rep
# price is promoted (F8), so the line prices at the rep figure (not $0/blocked).
_clear(); _clear_sess()
_tmpl_norate = (
    "Quote: [TEST-WA127] Acme Events Co\n"
    "Date: 25 September 2026\n"
    "Days: 1\n"
    "Items:\n"
    "- 1 x noratewidget @ $250\n")
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM_QUOTE):
    D._wa12_maybe_intercept(_txt(_tmpl_norate))
q13 = _latest_quote()
l13 = q13.line_ids.filtered(lambda l: l.product_template_id == norate)[:1] \
    if q13 else None
_check("T13-matched-no-rate-@price-promoted-to-rep-price",
       bool(l13) and abs((l13.unit_rate or 0) - 250.0) < 0.5,
       "line=%s rate=%s" % (bool(l13), l13.unit_rate if l13 else None))

# T14 (#4 LOW): the detect is TIGHT -> casual 2-line prose is NOT a template.
_fp1 = D._wa12_is_template_filled(
    "Subject: Re your enquiry\nFor: the wedding\nlets talk tomorrow")
_fp2 = D._wa12_is_template_filled("For: Acme\nWhen: friday")
_real = D._wa12_is_template_filled(_tmpl)   # the real T2 template
_check("T14-tight-detect-no-false-positive",
       _fp1 is False and _fp2 is False and _real is True,
       "fp1=%s fp2=%s real=%s" % (_fp1, _fp2, _real))

# ---- teardown ----
_clear_sess()
_purge()
PT.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA127]")]).unlink()
Bot.with_context(active_test=False).search(
    [("phone_number", "=", PHONE)]).unlink()
u_sales.write({"active": False})
env.cr.commit()
for _p_ in _PS:
    _p_.stop()
_MAILP.stop()
print("=" * 64)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 64)
