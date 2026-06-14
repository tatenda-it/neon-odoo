"""P-WA-12.6 WIRE smoke — the STRUCTURED one-at-a-time collection spine.

Asserts the BOT'S ACTUAL MESSAGES through the deterministic FSM (client -> event
-> items one-by-one -> review). The architecture makes item-drop / wrong-client
/ mis-parse structurally impossible; these wire cases prove it on the real
dispatch (_wa12_maybe_intercept), not internal state. LLM stubbed where a quote-
intent gate / pre-fill read is needed (the spine itself is deterministic).

S1  a one-message DUMP -> bot resets to step-1 CLIENT (does NOT bulk-parse;
    buffer holds zero items)
S2  client resolved -> EVENT step (date asked)
S3  event "7 to 11 August 2026" -> 5-day hire (inclusive) -> item step
S4  items added ONE BY ONE -> N items -> N draft lines (the item-drop fix)
S5  MONEY: every drafted line carries duration_days = 5 (the duration fix)
S6  "smoke" in the item step -> a card/list with ONLY smoke machines (no PACKAGE)
S7  CLIENT-LOCK: at the item step a client name does NOT switch the client
"""
from unittest.mock import patch

M = env["neon.whatsapp.message"].sudo()
PT = env["product.template"].sudo()
P = env["res.partner"].sudo()
Users = env["res.users"].sudo()
ECat = env["neon.equipment.category"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Bracket = env["neon.finance.pricing.bracket"].sudo()
PTerm = env["neon.finance.payment.term"].sudo()
Q = env["neon.finance.quote"].sudo()
USD = env.ref("base.USD")
results = {}


def _check(n, ok, d=""):
    print("%s:" % n, "PASS" if ok else "FAIL", d)
    results[n] = ok


print("=" * 72)
print("P-WA-12.6 — STRUCTURED collection WIRE smoke")
print("=" * 72)
PHONE = "+263779126001"
_WIRE = []
_ALLWIRE = []   # never cleared: every bot message across S1-S10 for the S11 sweep


def _cap_reply(self, raw_from, from_e164, text):
    _WIRE.append({"kind": "text", "body": text or "", "opts": []}); return True


def _cap_btn(self, raw_from, from_e164, body, buttons):
    _WIRE.append({"kind": "buttons", "body": body or "",
                  "opts": [b.get("title") or "" for b in buttons],
                  "ids": [b.get("id") for b in buttons]}); return True


def _cap_list(self, raw_from, from_e164, body, button_text, rows):
    _WIRE.append({"kind": "list", "body": body or "",
                  "opts": [r.get("title") or "" for r in rows],
                  "ids": [r.get("id") for r in rows],
                  "descs": [r.get("description") or "" for r in rows]}); return True


_PS = [patch.object(type(M), "_wa6_reply", _cap_reply),
       patch.object(type(M), "_wa6_send_buttons", _cap_btn),
       patch.object(type(M), "_wa6_send_list", _cap_list),
       patch("odoo.addons.mail.models.mail_mail.MailMail.send",
             lambda self, *a, **k: True)]
for p in _PS:
    p.start()


def _clear():
    _ALLWIRE.extend(_WIRE)   # archive for the cumulative no-syntax sweep (S11)
    _WIRE.clear()


def _alltext():
    out = []
    for e in _WIRE:
        out.append(e["body"]); out += e.get("opts") or []; out += e.get("descs") or []
    return "\n".join(out)


def _sess():
    return env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)


def _clear_sess():
    s = env["neon.wa.equip.session"].sudo().with_context(
        active_test=False).search([("phone_number", "=", PHONE)])
    if s:
        s.unlink()


def _txt(b):
    return {"from": PHONE, "type": "text", "text": {"body": b}, "id": "w126"}


def _tap(pid_id, lst=False):
    k = "list_reply" if lst else "button_reply"
    return {"from": PHONE, "type": "interactive",
            "interactive": {k: {"id": pid_id, "title": "x"}}, "id": "w126t"}

# ---- fixtures
def _purge_rules():
    """neon.finance.pricing.rule + bracket are APPEND-ONLY (perm_unlink=0) -> raw
    SQL for [TEST-WA126] fixtures (brackets FK the rule -> brackets first)."""
    env.cr.execute(
        "DELETE FROM neon_finance_pricing_bracket WHERE rule_id IN "
        "(SELECT id FROM neon_finance_pricing_rule WHERE name LIKE %s)",
        ("%[TEST-WA126]%",))
    env.cr.execute(
        "DELETE FROM neon_finance_pricing_rule WHERE name LIKE %s",
        ("%[TEST-WA126]%",))


def _purge():
    parts = P.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")])
    env.cr.execute("DELETE FROM neon_finance_payment_term WHERE name LIKE %s "
                   "OR partner_id IN %s", ("%[TEST-WA126]%", tuple(parts.ids) or (0,)))
    _tq = Q.with_context(active_test=False).search([("partner_id", "in", parts.ids)])
    env["neon.finance.approval"].sudo().search([("quote_id", "in", _tq.ids)]).unlink()
    env["neon.finance.invoice.schedule"].sudo().search([("quote_id", "in", _tq.ids)]).unlink()
    _ej = _tq.mapped("event_job_id"); _cj = _ej.mapped("commercial_job_id")
    _tq.unlink(); _ej.exists().unlink(); _cj.exists().unlink()
    _purge_rules()  # product-scoped rules FK the products -> drop before them
    parts.exists().unlink()


_clear_sess()
_purge_rules()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
ECat.with_context(active_test=False).search([("code", "=", "TW126")]).unlink()
_purge()


def _cat(code, name):
    c = ECat.search([("code", "=", code)], limit=1)
    return c or ECat.create({"code": code, "name": name})


cat_vis, cat_lig, cat_eff = _cat("visual", "Visual"), _cat("lighting", "Lighting"), _cat("effects", "Effects")
cat_pkg = _cat("packages", "Packages")
twcat = ECat.create({"name": "[TEST-WA126] Cat", "code": "TW126"})
trule = Rule.create({"name": "[TEST-WA126] Rule", "category_id": twcat.id,
                     "currency_id": USD.id, "base_rate": 100.0,
                     "effective_date": "2020-01-01", "active": True})
Bracket.create({"rule_id": trule.id, "sequence": 1, "day_from": 1, "day_to": -1, "multiplier": 1.0})


def _p(name, cat):
    """A product in its REAL family (so family enumeration + scope work) WITH a
    product-scoped $100 rule (so it prices regardless of category)."""
    p = PT.create({"name": name, "workshop_name": name.lower(),
                   "is_workshop_item": True, "list_price": 10.0,
                   "equipment_category_id": cat.id})
    pr = Rule.create({"name": "[TEST-WA126] R-%d" % p.id,
                      "product_template_id": p.id, "currency_id": USD.id,
                      "base_rate": 100.0, "effective_date": "2020-01-01"})
    Bracket.create({"rule_id": pr.id, "sequence": 1, "day_from": 1,
                    "day_to": -1, "multiplier": 1.0})
    return p


# distinct, real-family products (so "smoke" enumerates in Effects, etc.)
scr = _p("[TEST-WA126] 6M X 2M LED SCREEN", cat_vis)
can = _p("[TEST-WA126] RGBWAUV 18X18 ZOOM INDOOR LED CAN", cat_lig)
mole = _p("[TEST-WA126] 4x100W INDOOR MOLEFAYS", cat_lig)
stage = _p("[TEST-WA126] 3.6M X 6M STAGE", _cat("staging", "Staging"))
smoke = _p("[TEST-WA126] VERTICAL SMOKE MACHINES", cat_eff)
# a package that embeds 'SMOKE MACHINE' (the pollution the scope fix excludes)
pkg = PT.create({"name": "[TEST-WA126] BASIC DJ PACKAGE - PA, 12 CANS, SMOKE MACHINE",
                 "workshop_name": "basic dj package", "is_workshop_item": True,
                 "list_price": 450.0, "equipment_category_id": cat_pkg.id})
client = P.create({"name": "[TEST-WA126] Acme Events Co"})
other = P.create({"name": "[TEST-WA126] Beta Corp"})
env.company.sudo().write({"email": env.company.email or "noreply@neon.test"})
client.write({"email": "acme126@neon.test"})

_lg = "pwa126_sales"
ex = Users.with_context(active_test=False).search([("login", "=", _lg)], limit=1)
g_sales = env.ref("neon_core.group_neon_sales_rep")
if not ex:
    ex = Users.with_context(no_reset_password=True).create({
        "name": "PWA126 Sales", "login": _lg, "password": "test123",
        "groups_id": [(4, env.ref("base.group_user").id), (4, g_sales.id)]})
else:
    ex.write({"groups_id": [(4, g_sales.id)], "active": True})
u_sales = ex
Bot = env["neon.bot.user"].sudo()
Bot.with_context(active_test=False).search([("phone_number", "=", PHONE)]).unlink()
Bot.create({"name": "[TEST-WA126] bot", "phone_number": PHONE, "user_id": u_sales.id})
env.cr.commit()
D = M.with_user(u_sales)

# LLM stub: a quote-intent read (so the conversational entry claims) + a client
# pre-fill suggestion. Items are NEVER read from the dump (the whole point).
_LLM = ('{"intent":"quote","client":"[TEST-WA126] Acme Events Co","items":[],'
        '"date":null,"phone":null,"email":null,"contact_person":null,'
        '"address":null,"event_name":null}')

# ============================================================ S1: dump -> step-1
_clear(); _clear_sess()
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _LLM):
    D._wa12_llm_intake_maybe(_txt(
        "quote acme: 6m x 2m screen, 24 cans, 4 molefays, a stage and smoke, "
        "7 to 11 august"))
s1 = _sess(); b1 = s1._get_buffer() if s1 else {}
intro = _WIRE[0]["body"] if _WIRE else ""
s1ok = {
    "at_client_step": bool(s1) and s1.step == "q_client",
    "one_step_intro": "one step at a time" in intro.lower(),
    "no_items_bulk_parsed": len(b1.get("items") or []) == 0,
}
_check("S1-dump-resets-to-client", all(s1ok.values()),
       "%s intro=%r" % (s1ok, intro[:45]))

# ============================================================ S2: client -> event
_clear()
D._wa12_maybe_intercept(_txt("[TEST-WA126] Acme Events Co"))
s2 = _sess(); b2 = s2._get_buffer() if s2 else {}
s2ok = {"at_event_step": bool(s2) and s2.step == "qs_event",
        "client_logged": b2.get("partner_id") == client.id,
        "asks_date": "date" in _alltext().lower()}
_check("S2-client-to-event", all(s2ok.values()), "%s" % s2ok)

# ============================================================ S3: range -> ASK days
# Robin's convention: a RANGE never auto-assumes -> the bot ASKS "how many
# chargeable days?" (offers the inclusive count as a hint); the rep types it.
_clear()
D._wa12_maybe_intercept(_txt("7 to 11 August 2026"))
s3a = _sess(); b3a = s3a._get_buffer() if s3a else {}
asked = "how many" in _alltext().lower()
hinted = "5" in _alltext()           # inclusive hint shown
await_set = bool(b3a.get("await_days")) and s3a.step == "qs_event"
_clear()
D._wa12_maybe_intercept(_txt("5"))   # the rep states 5 chargeable days
s3 = _sess(); b3 = s3._get_buffer() if s3 else {}
s3ok = {"asked_days": asked, "offered_hint": hinted, "await_flag": await_set,
        "at_item_step": bool(s3) and s3.step == "qs_item",
        "days_5_from_rep": b3.get("days") == 5}
_check("S3-range-asks-rep-for-days", all(s3ok.values()),
       "%s (days=%s)" % (s3ok, b3.get("days")))

# ============================================================ S4+S5: 5 items one-by-one
def _add_item(name):
    """Name an item -> confident card -> tap ✓ -> qty 1 -> next."""
    _clear()
    D._wa12_maybe_intercept(_txt(name))
    # the last sent message should be a ✓/✗ card (confident) or a list.
    last = _WIRE[-1] if _WIRE else {}
    okid = (last.get("ids") or [None])[0]
    if okid:
        D._wa12_maybe_intercept(_tap(okid, lst=(last.get("kind") == "list")))
        D._wa12_maybe_intercept(_txt("1"))   # qty


for nm in ["6m x 2m screen", "rgbwauv zoom can", "4x100 molefay",
           "stage", "smoke machine"]:
    _add_item(nm)
s4 = _sess(); b4 = s4._get_buffer() if s4 else {}
n_items = len(b4.get("items") or [])
_clear()
D._wa12_maybe_intercept(_txt("done"))
s5 = _sess()
q = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
durs = set(q.line_ids.mapped("duration_days")) if q else set()
_check("S4-five-items-one-by-one", n_items == 5 and q and len(q.line_ids) == 5,
       "collected=%d lines=%d" % (n_items, len(q.line_ids) if q else 0))
_check("S5-MONEY-duration-5-on-every-line", bool(q) and durs == {5},
       "line durations=%s (want {5})" % durs)

# ============================================================ S8: REVIEW money surface
# At the q_confirm draft (from S4 'done'), the review MUST apply discount + VAT
# toggle correctly. This is the money surface that must not deploy unvalidated.
# The session s5 is now q_confirm; commands route via _wa12_try_edit (typed
# fallback -- the rep normally taps, but the underlying math is what we assert).
s8 = _sess()
review_ok = {}
if s8 and s8.step == "q_confirm" and q:
    tax_before = q.amount_tax or 0.0
    total_before = q.amount_total or 0.0
    # VAT off -> tax row clears.
    _clear(); D._wa12_maybe_intercept(_txt("no tax"))
    q.invalidate_recordset()
    review_ok["vat_off_zeroes_tax"] = (q.amount_tax or 0.0) == 0.0
    # VAT back on -> tax returns at ~15% of the untaxed base (the real rate, not
    # just "non-zero" -- this is the money surface).
    _clear(); D._wa12_maybe_intercept(_txt("with tax"))
    q.invalidate_recordset()
    review_ok["vat_on_restores_tax"] = (q.amount_tax or 0.0) > 0.0
    review_ok["vat_rate_is_15pct"] = bool(q.amount_untaxed) and abs(
        (q.amount_tax / q.amount_untaxed) - 0.15) < 0.01
    # a 10% discount on line 1 -> its subtotal is EXACTLY rate×qty×days×0.9 (the
    # actual edit math, not merely "it dropped").
    l1 = q.line_ids[:1]
    sub_before = l1.line_subtotal if l1 else 0.0
    _clear(); D._wa12_maybe_intercept(_txt("discount 1 10%"))
    q.invalidate_recordset()
    l1 = q.line_ids[:1]
    want = round((l1.unit_rate or 0) * (l1.quantity or 0)
                 * (l1.duration_days or 0) * 0.9, 2) if l1 else -1
    review_ok["discount_drops_subtotal"] = bool(l1) and (
        l1.line_subtotal < sub_before)
    review_ok["discount_math_exact"] = bool(l1) and abs(
        (l1.line_subtotal or 0) - want) < 0.02
    review_ok["still_q_confirm"] = _sess() and _sess().step == "q_confirm"
else:
    review_ok["reached_review"] = False
_check("S8-REVIEW-money-discount-vat", bool(review_ok) and all(review_ok.values()),
       "%s" % review_ok)

# ============================================================ S12-S17: WA-12.6 review polish
# (B) review fall-through carries NO command syntax; (C) whole-quote discount /
# target-total (incl-VAT default + ex-VAT override) lands EXACTLY + labels the
# basis + clears the stale note on a per-line edit; (A) the "Quote a client" tap
# routes into begin_structured. All on the live q_confirm session `q`/s8.
from odoo.addons.neon_channels.models import wa_payload as _wp  # noqa
_SECRET = env["ir.config_parameter"].sudo().get_param("database.secret") or ""


def _clean_base():
    """Clear all line discounts + the note, recalc -> the undiscounted base."""
    q.line_ids.with_context().write({"discount_pct": 0.0, "discount_amount": 0.0})
    q.write({"wa12_discount_note": False})
    q.action_recalculate_pricing()
    q.invalidate_recordset()


if s8 and s8.step == "q_confirm" and q:
    # S12: an UNRECOGNISED edit at the review -> the fall-through help, which
    # must be PLAIN language (no command-syntax cheat sheet). LLM forced down so
    # the deterministic fall-through fires (not an LLM translation).
    _clear()
    with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: None):
        D._wa12_maybe_intercept(_txt("zxqw mmm pls"))
    fall = _alltext()
    _bad = [t for t in ("<", "`", "price <", "discount <", "qty <", "e.g. `")
            if t in fall]
    _check("S12-review-fallthrough-no-command-syntax",
           bool(fall) and not _bad, "offenders=%s reply=%r" % (_bad, fall[:90]))

    # S13: whole-quote discount, DEFAULT (VAT-INCLUSIVE) -> the displayed Total
    # drops by EXACTLY 179; the note labels "(incl. VAT)".
    _clean_base()
    base_total = q.amount_total
    _clear(); D._wa12_maybe_intercept(_txt("discount 179"))
    q.invalidate_recordset()
    _drop13 = base_total - q.amount_total
    _check("S13-whole-quote-discount-incl-total-minus-179",
           abs(_drop13 - 179.0) < 0.5
           # the note TIES OUT with the achieved drop on the PDF (review fix):
           and ("%.2f" % _drop13) in (q.wa12_discount_note or "")
           and "incl" in (q.wa12_discount_note or "").lower(),
           "base=%.2f now=%.2f drop=%.2f note=%r"
           % (base_total, q.amount_total, _drop13, q.wa12_discount_note))

    # S14: EX-VAT override -> the GOODS (untaxed) drop by 179; the Total drops by
    # MORE (VAT comes off too); the note labels "(ex VAT)".
    _clean_base()
    base_untaxed, base_total2 = q.amount_untaxed, q.amount_total
    _clear(); D._wa12_maybe_intercept(_txt("discount 179 ex vat"))
    q.invalidate_recordset()
    _goods14 = base_untaxed - q.amount_untaxed
    _check("S14-whole-quote-discount-ex-vat-goods-minus-179",
           abs(_goods14 - 179.0) < 0.5
           and (base_total2 - q.amount_total) > 179.5
           # note ties out with the achieved GOODS drop (ex-VAT basis):
           and ("%.2f" % _goods14) in (q.wa12_discount_note or "")
           and "ex vat" in (q.wa12_discount_note or "").lower(),
           "goods drop=%.2f total drop=%.2f note=%r"
           % (_goods14, base_total2 - q.amount_total, q.wa12_discount_note))

    # S15: target-total (incl-VAT default) -> the displayed Total lands on 500.
    _clean_base()
    _clear(); D._wa12_maybe_intercept(_txt("total should be 500"))
    q.invalidate_recordset()
    _check("S15-target-total-lands-exactly",
           abs(q.amount_total - 500.0) < 0.5,
           "total now=%.2f (want 500)" % q.amount_total)

    # S16: the whole-quote note is CLEARED on a subsequent per-line edit (never a
    # stale label on the PDF the approver reads).
    _clean_base()
    _clear(); D._wa12_maybe_intercept(_txt("discount 179"))
    q.invalidate_recordset(); _had = bool(q.wa12_discount_note)
    _clear(); D._wa12_maybe_intercept(_txt("no tax"))
    q.invalidate_recordset()
    _check("S16-note-cleared-on-per-line-edit",
           _had and not q.wa12_discount_note,
           "had=%s after=%r" % (_had, q.wa12_discount_note))
else:
    for _n in ("S12-review-fallthrough-no-command-syntax",
               "S13-whole-quote-discount-incl-total-minus-179",
               "S14-whole-quote-discount-ex-vat-goods-minus-179",
               "S15-target-total-lands-exactly",
               "S16-note-cleared-on-per-line-edit"):
        _check(_n, False, "review session not reached")

# S17: WA-12.6 Part A -- the menu "Quote a client" tap now sends the COPY-FILL
# TEMPLATE skeleton (template is the PRIMARY collection); the stepper is the
# fallback (proven by pwa12_7 T9). (Was: tap -> q_client stepper.)
_clear(); _clear_sess()
_tapid = _wp.encode(_SECRET, "wa12_start", u_sales.id)
D._wa12_maybe_intercept({"from": PHONE, "type": "interactive",
                         "interactive": {"button_reply": {"id": _tapid,
                                                          "title": "Quote a client"}},
                         "id": "wa12start"})
_s17txt = _WIRE[-1]["body"] if _WIRE else ""
_check("S17-quote-a-client-tap-sends-template-skeleton",
       "Quote:" in _s17txt and "Items:" in _s17txt and "Copy this" in _s17txt
       and not _sess(),
       "reply=%r session=%s" % (_s17txt[:60], bool(_sess())))
_clear_sess()

# ============================================================ S6: smoke -> only smoke
_clear(); _clear_sess()
# jump a session straight to the item step to test the item search in isolation.
env["neon.wa.equip.session"].sudo()._start_quote(
    PHONE, u_sales, "qs_item",
    {"v": 5, "structured": True, "client_txt": client.name,
     "partner_id": client.id, "date_txt": "2026-08-07", "days": 5, "venue": "",
     "note": "", "prefills": {}, "items": [], "pending_item": None,
     "qty_for": False})
D._wa12_maybe_intercept(_txt("smoke"))
smoke_msg = _alltext().upper()
_check("S6-smoke-only-smoke-machines",
       "VERTICAL SMOKE MACHINES" in smoke_msg and "PACKAGE" not in smoke_msg,
       "msg has package=%s" % ("PACKAGE" in smoke_msg))

# ============================================================ S7: client-lock
_clear()
# at the item step, typing another client NAME must NOT switch the client.
D._wa12_maybe_intercept(_txt("[TEST-WA126] Beta Corp"))
s7 = _sess(); b7 = s7._get_buffer() if s7 else {}
_check("S7-client-locked", b7.get("partner_id") == client.id,
       "client still=%s (not Beta=%s)" % (b7.get("partner_id"), other.id))

# ============================================================ S9: NEW-client intake -> event
# A client the bot doesn't know -> guided intake -> on completion RESUME into the
# EVENT step (not a dead-end). Robin's briefs are often new clients.
_clear(); _clear_sess()
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: '{"intent":"quote","client":"[TEST-WA126] '
                  'Zêta New Co","items":[],"date":null,"phone":null,'
                  '"email":null,"contact_person":null,"address":null,'
                  '"event_name":null}'):
    D._wa12_llm_intake_maybe(_txt("quote for Zeta New Co"))
D._wa12_maybe_intercept(_txt("[TEST-WA126] Zêta New Co"))   # unknown -> intake
D._wa12_maybe_intercept(_txt("new"))
D._wa12_maybe_intercept(_txt("individual"))
D._wa12_maybe_intercept(_txt("ok"))            # qc_name -> reuse typed name
D._wa12_maybe_intercept(_txt("+263779126777"))  # qc_phone
_clear()
D._wa12_maybe_intercept(_txt("skip"))          # qc_email -> create + resume
s9 = _sess()
newp = P.search([("name", "=", "[TEST-WA126] Zêta New Co")], limit=1)
_check("S9-newclient-intake-to-event",
       bool(newp) and bool(s9) and s9.step == "qs_event"
       and "date" in _alltext().lower(),
       "created=%s resumed=%s" % (bool(newp), s9.step if s9 else None))

# ============================================================ S10: 3-day brief -> dur 3
# the user's money must-pass: a "for 3 days" brief -> every line duration_days=3.
_clear(); _clear_sess()
_q10_before = Q.search([("partner_id", "=", client.id)], order="id desc",
                       limit=1).id
env["neon.wa.equip.session"].sudo()._start_quote(
    PHONE, u_sales, "qs_event",
    {"v": 5, "structured": True, "client_txt": client.name,
     "partner_id": client.id, "date_txt": "", "venue": "", "note": "",
     "prefills": {}, "items": [], "pending_item": None, "qty_for": False,
     "await_days": False})
D._wa12_maybe_intercept(_txt("25 September 2026 for 3 days"))
s10 = _sess(); b10 = s10._get_buffer() if s10 else {}
# add one confident item then done.
_clear(); D._wa12_maybe_intercept(_txt("6m x 2m screen"))
last10 = _WIRE[-1] if _WIRE else {}
oid = (last10.get("ids") or [None])[0]
if oid:
    D._wa12_maybe_intercept(_tap(oid, lst=(last10.get("kind") == "list")))
    D._wa12_maybe_intercept(_txt("2"))   # qty 2
D._wa12_maybe_intercept(_txt("done"))
q10 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
l10 = q10.line_ids[:1] if q10 else None
dur_ok = bool(q10) and set(q10.line_ids.mapped("duration_days")) == {3}
sub_ok = bool(l10) and abs(
    (l10.unit_rate or 0) * (l10.quantity or 0) * (l10.duration_days or 0)
    - (l10.line_subtotal or 0)) < 0.5
_check("S10-MONEY-3day-brief", b10.get("days") == 3 and dur_ok and sub_ok,
       "days=%s durs=%s subtotal=rate×qty×3=%s" % (
           b10.get("days"),
           set(q10.line_ids.mapped("duration_days")) if q10 else set(), sub_ok))

# ============================================================ S11: NO COMMAND SYNTAX
# User directive: every user-facing message is PLAIN language -- no internal
# command grammar (angle-bracket placeholders like "price <item>", backtick
# command templates like "e.g. `add screen`"). Sweep EVERY bot message captured
# across S1-S10 (text bodies + button/list titles + row descriptions). A plain-
# language example like "(e.g. *bespoke arch 250*)" or a date "(e.g. 25/09/2026)"
# is allowed; only command-shaped syntax is forbidden.
_allmsgs = _ALLWIRE + _WIRE
_sweep_parts = []
for e in _allmsgs:
    _sweep_parts.append(e.get("body") or "")
    _sweep_parts += e.get("opts") or []
    _sweep_parts += e.get("descs") or []
_sweep = "\n".join(_sweep_parts)
# The copy-fill TEMPLATE skeleton legitimately shows the custom-line FORMAT
# "<qty> x <description> @ $<price>" (the user-approved exception) -> strip those
# placeholder tokens before the sweep. The forbidden patterns are COMMAND
# templates ("price <item>", "qty <item>", a backtick cheat sheet), NOT a data
# format -- those are still caught.
for _ph in ("<qty>", "<description>", "<desc>", "<price>", "<amt>"):
    _sweep = _sweep.replace(_ph, "")
_FORBIDDEN = ["`", "price <", "add <", "replace <", "qty <", "discount <",
              "e.g. `", "<item>"]
_offenders = sorted({tok for tok in _FORBIDDEN if tok in _sweep})
_check("S11-no-command-syntax",
       len(_allmsgs) >= 10 and not _offenders,
       "swept %d messages; offending tokens=%s" % (len(_allmsgs), _offenders))

# ---- teardown
_clear_sess()
_purge()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
ECat.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
Bot.with_context(active_test=False).search([("phone_number", "=", PHONE)]).unlink()
u_sales.write({"active": False})
env.cr.commit()
for p in _PS:
    p.stop()
print("=" * 72)
_passed = sum(1 for v in results.values() if v)
print("STRUCTURED WIRE Total: %d/%d passed" % (_passed, len(results)))
# plain summary line so run_regression.sh (greps ^Total:) picks this suite up.
print("Total: %d/%d passed" % (_passed, len(results)))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 72)
