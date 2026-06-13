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
def _purge():
    parts = P.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")])
    env.cr.execute("DELETE FROM neon_finance_payment_term WHERE name LIKE %s "
                   "OR partner_id IN %s", ("%[TEST-WA126]%", tuple(parts.ids) or (0,)))
    _tq = Q.with_context(active_test=False).search([("partner_id", "in", parts.ids)])
    env["neon.finance.approval"].sudo().search([("quote_id", "in", _tq.ids)]).unlink()
    env["neon.finance.invoice.schedule"].sudo().search([("quote_id", "in", _tq.ids)]).unlink()
    _ej = _tq.mapped("event_job_id"); _cj = _ej.mapped("commercial_job_id")
    _tq.unlink(); _ej.exists().unlink(); _cj.exists().unlink()
    parts.exists().unlink()


_clear_sess()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
Rule.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).mapped("bracket_ids").unlink()
Rule.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
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

# ============================================================ S3: range -> 5 days
_clear()
D._wa12_maybe_intercept(_txt("7 to 11 August 2026"))
s3 = _sess(); b3 = s3._get_buffer() if s3 else {}
s3ok = {"at_item_step": bool(s3) and s3.step == "qs_item",
        "days_5": b3.get("days") == 5,
        "echoed_5day": "5-day" in _alltext().lower() or "5 day" in _alltext().lower()}
_check("S3-range-5-days-inclusive", all(s3ok.values()),
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

# ---- teardown
_clear_sess()
_purge()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
Rule.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).mapped("bracket_ids").unlink()
Rule.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
ECat.with_context(active_test=False).search([("name", "like", "[TEST-WA126]")]).unlink()
Bot.with_context(active_test=False).search([("phone_number", "=", PHONE)]).unlink()
u_sales.write({"active": False})
env.cr.commit()
for p in _PS:
    p.stop()
print("=" * 72)
_passed = sum(1 for v in results.values() if v)
print("STRUCTURED WIRE Total: %d/%d passed" % (_passed, len(results)))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 72)
