"""P-WA-12.5 WIRE smoke — assert the BOT'S ACTUAL MESSAGES, not internal state.

⚠️ SUPERSEDED (WA-12.6 cutover) by .claude/pwa12_6_structured_smoke.py. W1/W3/
W5/W8 here exercised the OLD combined-extract -> q_items stepper flow, which the
structured spine REPLACED (client -> qs_event -> qs_item, one item at a time).
Those legs now fail by design; only the matcher-scope legs (W6/W7) still hold.
NOT in the regression runner. The wire-level guarantee (incl. the no-command-
syntax sweep, W4) is re-proven by pwa12_6 S1-S11. Kept for history only; safe
to delete once WA-12.6 is fully bedded in on prod.

The lesson from WA-12.4: pwa12 was 68/68 green while the live conversation was
broken (a 5-item brief produced "confirm 1 item"; a question removed a line).
Internal-state tests prove the units; they do NOT prove the conversation. This
suite REPLAYS the real wire briefs through `_wa12_maybe_intercept` /
`_wa12_llm_intake_maybe` and asserts the bot's OUTBOUND messages (body + button
titles + list rows), captured by patching the send primitives.

Runs in `odoo shell -d neon_crm`. Self-contained [TEST-WA125] fixtures; torn
down at the end. The LLM is stubbed deterministically per case (extraction is
non-deterministic on the wire -- the stub fixes the extraction so the test
proves the STEPPER + matcher behaviour given a known extraction; a dedicated
case stubs a MERGED/DROPPED extraction to prove the deterministic item-drop net).

W1  5-item brief -> 5 stepper steps (counter "① of 5"), one item per message
W2  "3 x 2 screen" on the wire -> a card naming 3M X 2M LED SCREEN (NOT 6x2)
W3  a QUESTION mid-flow -> a plain HELP reply, never a mutation, never a new line
W4  NO bot message contains command syntax ("<", "e.g. `", "qty <", "price <")
W5  item-drop NET: a MERGED LLM extraction still yields all items as steps
"""
from unittest.mock import patch

from odoo.exceptions import AccessError  # noqa: F401

M = env["neon.whatsapp.message"].sudo()
PT = env["product.template"].sudo()
P = env["res.partner"].sudo()
Users = env["res.users"].sudo()
ECat = env["neon.equipment.category"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Bracket = env["neon.finance.pricing.bracket"].sudo()
PTerm = env["neon.finance.payment.term"].sudo()
USD = env.ref("base.USD")

results = {}


def _check(name, ok, detail=""):
    print("%s:" % name, "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-WA-12.5 — WIRE smoke (assert the bot's actual messages)")
print("=" * 72)

PHONE = "+263779125001"

# ---------------------------------------------------------------- the capture
# An ordered transcript of what the bot SENT. Each entry: dict(kind, body,
# options=[titles]) where kind in text|buttons|list. Patched onto the send
# primitives so we read the RENDERED conversation, not message_body alone.
_WIRE = []


def _cap_reply(self, raw_from, from_e164, text):
    _WIRE.append({"kind": "text", "body": text or "", "options": []})
    return True


def _cap_buttons(self, raw_from, from_e164, body, buttons):
    _WIRE.append({"kind": "buttons", "body": body or "",
                  "options": [b.get("title") or "" for b in buttons]})
    return True


def _cap_list(self, raw_from, from_e164, body, button_text, rows):
    _WIRE.append({"kind": "list", "body": body or "",
                  "options": [r.get("title") or "" for r in rows],
                  "descs": [r.get("description") or "" for r in rows]})
    return True


_P_REPLY = patch.object(type(M), "_wa6_reply", _cap_reply)
_P_BTN = patch.object(type(M), "_wa6_send_buttons", _cap_buttons)
_P_LIST = patch.object(type(M), "_wa6_send_list", _cap_list)
_P_REPLY.start(); _P_BTN.start(); _P_LIST.start()
# mute SMTP (a finalize would email)
_P_MAIL = patch("odoo.addons.mail.models.mail_mail.MailMail.send",
                lambda self, *a, **k: True)
_P_MAIL.start()


def _wire_clear():
    _WIRE.clear()


def _wire_text():
    return "\n----\n".join(e["body"] for e in _WIRE)


def _wire_all():
    """body + every option title + description, joined (for syntax scanning)."""
    out = []
    for e in _WIRE:
        out.append(e["body"])
        out.extend(e.get("options") or [])
        out.extend(e.get("descs") or [])
    return "\n".join(out)


def _clear_sess(ph):
    s = env["neon.wa.equip.session"].sudo().with_context(
        active_test=False).search([("phone_number", "=", ph)])
    if s:
        s.unlink()


def _txt(ph, body):
    return {"from": ph, "type": "text", "text": {"body": body},
            "id": "w125-%s" % (body or "")[:8]}

# ---------------------------------------------------------------- fixtures
def _purge_test_terms_and_partners():
    """neon.finance.payment.term is APPEND-ONLY (perm_unlink=0), so it can't be
    ORM-unlinked and it FK-blocks deleting the test client. For [TEST-WA125]
    fixture teardown ONLY, raw-SQL the terms (by name OR by a [TEST-WA125]
    partner), then ORM-unlink the partners. Test-fixture cleanup, [TEST-*] only."""
    parts = P.with_context(active_test=False).search(
        [("name", "like", "[TEST-WA125]")])
    # %s is the only psycopg2 placeholder; the LIKE pattern is a bound param so
    # its literal % is not mis-read.
    env.cr.execute(
        "DELETE FROM neon_finance_payment_term "
        "WHERE name LIKE %s OR partner_id IN %s",
        ("%[TEST-WA125]%", tuple(parts.ids) or (0,)))
    parts.exists().unlink()


_clear_sess(PHONE)
PT.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).unlink()
_purge_test_terms_and_partners()


def _cat(code, name):
    c = ECat.search([("code", "=", code)], limit=1)
    return c or ECat.create({"code": code, "name": name})


cat_vis, cat_lig, cat_stg = _cat("visual", "Visual"), _cat("lighting", "Lighting"), _cat("staging", "Staging")
cat_tru, cat_eff = _cat("trussing", "Trussing"), _cat("effects", "Effects")
# pre-wipe any [TEST-WA125] rules + category left by a crashed prior run, then
# create a $50-rule category so the lines price (echo != $0).
Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).mapped("bracket_ids").unlink()
Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).unlink()
ECat.with_context(active_test=False).search([("code", "=", "TW125")]).unlink()
twcat = ECat.create({"name": "[TEST-WA125] Cat", "code": "TW125"})
trule = Rule.create({"name": "[TEST-WA125] Rule", "category_id": twcat.id,
                     "currency_id": USD.id, "base_rate": 50.0,
                     "effective_date": "2020-01-01", "active": True})
Bracket.create({"rule_id": trule.id, "sequence": 1, "day_from": 1,
                "day_to": -1, "multiplier": 1.0})


def _p(name, cat, rate_cat=True):
    return PT.create({"name": name, "workshop_name": name.lower(),
                      "is_workshop_item": True, "list_price": 10.0,
                      "equipment_category_id": (twcat if rate_cat else cat).id})


# screens: 3x2 AND 6x2 (defect-2 discrimination). Priced via twcat.
scr32 = _p("[TEST-WA125] 3M X 2M LED SCREEN", cat_vis)
scr62 = _p("[TEST-WA125] 6M X 2M LED SCREEN", cat_vis)
can = _p("[TEST-WA125] RGBWAUV 18X18 ZOOM INDOOR LED CAN", cat_lig)
mole1 = _p("[TEST-WA125] 2X100W INDOOR MOLEFAYS", cat_lig)
mole2 = _p("[TEST-WA125] 4x100W INDOOR MOLEFAYS", cat_lig)
totem = _p("[TEST-WA125] 2M PIN TRUSS TOTEM WITH BASE", cat_tru)
stage = _p("[TEST-WA125] 3.6M X 6M STAGE", cat_stg)
smoke = _p("[TEST-WA125] VERTICAL SMOKE MACHINES", cat_eff)
client = P.create({"name": "[TEST-WA125] Acme Events Co"})
PTerm.create({"name": "[TEST-WA125] Terms", "partner_id": client.id})
env.company.sudo().write({"email": env.company.email or "noreply@neon.test"})
client.write({"email": "acme125@neon.test"})

# a sales-capable bot user mapping for PHONE.
_lg = "pwa125_sales"
ex = Users.with_context(active_test=False).search([("login", "=", _lg)], limit=1)
g_sales = env.ref("neon_core.group_neon_sales_rep")   # the _wa12_can_quote gate
if not ex:
    ex = Users.with_context(no_reset_password=True).create({
        "name": "PWA125 Sales", "login": _lg, "password": "test123",
        "groups_id": [(4, env.ref("base.group_user").id), (4, g_sales.id)]})
else:
    ex.write({"groups_id": [(4, g_sales.id)]})
u_sales = ex
# map the phone -> user via the WA-6 resolver's store (neon.bot.user).
_BotModel = env["neon.bot.user"].sudo()
_BotModel.with_context(active_test=False).search(
    [("phone_number", "=", PHONE)]).unlink()
_BotModel.create({"name": "[TEST-WA125] bot", "phone_number": PHONE,
                  "user_id": u_sales.id})
env.cr.commit()

D = M.with_user(u_sales)


def _quote_brief(items_list, client_name="[TEST-WA125] Acme Events Co",
                 date="2026-11-20"):
    """A deterministic LLM extraction stub returning items_list verbatim."""
    its = ", ".join('{"name": "%s", "qty": %d, "stated_price": null}'
                    % (n, q) for n, q in items_list)
    return ('{"intent":"quote","client":"%s","items":[%s],"date":"%s",'
            '"phone":null,"email":null,"contact_person":null,"address":null,'
            '"event_name":null}' % (client_name, its, date))


# ============================================================ W1: 5 items -> 5 steps
_wire_clear(); _clear_sess(PHONE)
_brief5 = _quote_brief([
    ("6m x 2m screen", 1), ("RGBWAUV zoom can", 24),
    ("4x100 molefay", 4), ("2m truss totem", 2), ("smoke machine", 1)])
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _brief5):
    D._wa12_llm_intake_maybe(_txt(
        PHONE, "quote acme: 6m x 2m screen, 24 rgbwauv zoom cans, "
        "4x100 molefays, 2 totems, a smoke machine, for the 20th"))
# the bot should present item ① ONLY, with a counter "of 5".
intro = _WIRE[0]["body"] if _WIRE else ""
first_card = _WIRE[1] if len(_WIRE) > 1 else {"body": ""}
sess = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
buf = sess._get_buffer() if sess else {}
n_lines = len(buf.get("lines") or [])
w1 = {
    "five_lines": n_lines == 5,
    "intro_says_5": "5 item" in intro.lower(),
    "first_is_step1": ("① of 5" in first_card["body"] or "1 of 5" in first_card["body"]),
    "only_one_item_shown": first_card["body"].count("✅") <= 1,
}
_check("W1-5items-5steps", all(w1.values()),
       "%s  (lines=%d, intro=%r)" % (w1, n_lines, intro[:40]))

# ============================================================ W2: 3x2 -> 3M X 2M
# walk to item ① then, if it's a screen card, assert it names 3M X 2M when the
# brief item is "3 x 2 screen". Replay a 1-item brief with the exact dims.
_wire_clear(); _clear_sess(PHONE)
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: _quote_brief([("3 x 2 screen", 1)])):
    D._wa12_llm_intake_maybe(_txt(PHONE, "quote acme a 3 x 2 screen for the 20th"))
card2 = " ".join(e["body"] for e in _WIRE)
w2 = {
    "names_3x2": "3M X 2M LED SCREEN" in card2,
    "not_6x2": "6M X 2M LED SCREEN" not in card2,
}
_check("W2-3x2-not-6x2", all(w2.values()),
       "card=%r" % card2[card2.find("✅"):card2.find("✅") + 50])

# ============================================================ W3: question -> HELP
# At a confident card, a QUESTION must get HELP, never bind/advance/mutate.
_wire_clear(); _clear_sess(PHONE)
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: _quote_brief([("6m x 2m screen", 1)])):
    D._wa12_llm_intake_maybe(_txt(PHONE, "quote acme a 6m x 2m screen, 20th"))
sess3 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
buf3a = sess3._get_buffer() if sess3 else {}
n_before = len(buf3a.get("lines") or [])
_wire_clear()
D._wa12_maybe_intercept(_txt(PHONE, "where do I tap?"))
sess3 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
buf3b = sess3._get_buffer() if sess3 else {}
help_reply = _wire_text().lower()
w3 = {
    "no_phantom_line": len(buf3b.get("lines") or []) == n_before,
    "still_step1": (buf3b.get("cur") == buf3a.get("cur") and buf3b.get("focus")),
    "gave_help": ("tap" in help_reply and "?" not in _WIRE[0]["body"][:1]),
    "not_matched": "not sure" not in help_reply,
}
_check("W3-question-is-help", all(w3.values()), "%s" % w3)

# ============================================================ W4: no command syntax
# Scan EVERY message sent across W1-W3 + a fresh draft for command grammar.
_BANNED = ("<", "e.g. `", "qty <", "price <", "remove <", "2 = ", "client <name>")
# replay W1 again to refill the wire, then walk to a draft + edit prompt.
_wire_clear(); _clear_sess(PHONE)
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: _quote_brief([("6m x 2m screen", 1)])):
    D._wa12_llm_intake_maybe(_txt(PHONE, "quote acme a 6m x 2m screen, 20th"))
# confirm the one item via the real tap so we reach the draft screen.
sessW4 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
from odoo.addons.neon_channels.models import wa_payload as _wp
_sec = env["ir.config_parameter"].sudo().get_param("database.secret") or ""
bW4 = sessW4._get_buffer(); pW4 = bW4.get("pending") or {}
if pW4.get("kind") == "confirm":
    okid = _wp.encode(_sec, "wa12_ok", sessW4.id, "b%d" % pW4["lid"], pW4.get("seq"))
    D._wa12_maybe_intercept({"from": PHONE, "type": "interactive",
                             "interactive": {"button_reply": {"id": okid}},
                             "id": "w4ok"})
scan = _wire_all()
hits = [b for b in _BANNED if b in scan]
_check("W4-no-command-syntax", not hits, "banned tokens present: %s" % hits)

# ============================================================ W5: item-drop NET
# A MERGED LLM extraction (the wire failure: items collapsed into one name)
# must STILL yield every item as a step via the deterministic re-split.
_wire_clear(); _clear_sess(PHONE)
_merged = _quote_brief([
    ("6m x 2m screen, RGBWAUV zoom can, smoke machine", 1)])  # 3 merged into 1
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _merged):
    D._wa12_llm_intake_maybe(_txt(PHONE, "quote acme screen can and smoke, 20th"))
sess5 = env["neon.wa.equip.session"].sudo()._active_for_phone(PHONE)
buf5 = sess5._get_buffer() if sess5 else {}
w5 = {"net_recovered_3": len(buf5.get("lines") or []) == 3}
_check("W5-item-drop-net", all(w5.values()),
       "merged-extraction recovered to %d lines" % len(buf5.get("lines") or []))

# ============================================================ W6: list scope
# The candidate-list builders must EXCLUDE Packages + cross-category noise
# (wire 675-707: "smoke" listed 3 DJ/WEDDING packages; "3M X 2M" listed a
# goalpost truss + packages). _wa12_suggestion_ids must never return a PACKAGE
# whose long name embeds the typed phrase.
def _pname(i):
    return PT.browse(i).name


def _is_pkg(i):
    return "PACKAGE" in (_pname(i) or "").upper()


sug_ids = M._wa12_suggestion_ids(["3M X 2M SCREEN", "3M X 2M LED SCREEN"])
w6 = {
    "suggestion_ids_no_package": not any(_is_pkg(i) for i in sug_ids),
    # family_names (the discovery pick-list) excludes packages.
    "family_names_no_package": not any(
        "PACKAGE" in (n or "").upper()
        for n in (M._wa12_family_names("effects") or [])),
    # family candidate ids stay in-category (no cross-family leak).
    "visual_cands_all_visual": all(
        PT.browse(i).equipment_category_id.code == "visual"
        for i in M._wa12_family_candidate_ids("visual")),
}
_check("W6-list-scope-no-packages", all(w6.values()),
       "%s (sug_ids=%s)" % (w6, [(_pname(i))[:24] for i in sug_ids]))

# ============================================================ W7: smoke -> single
# the confirmed 'smoke' alias resolves to ONE product -> a confident card, NOT
# a fuzzy list of packages (wire defect: smoke listed 3 packages).
_wire_clear(); _clear_sess(PHONE)
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: _quote_brief([("smoke machine", 1)])):
    D._wa12_llm_intake_maybe(_txt(PHONE, "quote acme a smoke machine for the 20th"))
allmsg7 = _wire_all()
w7 = {
    "names_smoke_machine": "VERTICAL SMOKE MACHINES" in allmsg7,
    "no_package": "PACKAGE" not in allmsg7.upper(),
    "confident_card": any(e["kind"] == "buttons" and "✅" in e["body"]
                          for e in _WIRE),
}
_check("W7-smoke-single-not-list", all(w7.values()), "%s" % w7)

# ============================================================ W8: family-hint retype
# a bare-dimension correction on a SCREEN line scopes to Visual -> 3M X 2M LED
# SCREEN, never a 3M X 2M GOALPOST TRUSS (wire defect 7). Drive the focused
# retype: seed a screen line at the cursor, type "3 x 2".
_wire_clear(); _clear_sess(PHONE)
_bufW8 = {"v": 4, "next_lid": 2, "pending": None, "cur": 1, "focus": True,
          "seq": 0, "client_txt": "[TEST-WA125] Acme Events Co",
          "partner_id": client.id, "date_txt": "", "days": 1, "prefills": {},
          "lines": [{"lid": 1, "kind": "matched", "state": "pending",
                     "product_id": scr62.id, "product_name": scr62.name,
                     "qty": 1, "rep_price": None, "stated_price": None,
                     "family": "visual"}]}
sessW8 = env["neon.wa.equip.session"].sudo()._start_quote(
    PHONE, u_sales, "q_items", _bufW8)
M._wa12_present_item(sessW8, sessW8._get_buffer(), _bufW8["lines"][0],
                     PHONE, PHONE)
_wire_clear()
D._wa12_maybe_intercept(_txt(PHONE, "3 x 2"))   # correct the screen
bW8 = sessW8._get_buffer()
ln8 = M._wa12_line_by_lid(bW8, 1) or {}
allmsg8 = _wire_all()
w8 = {
    "bound_3x2_screen": (ln8.get("product_id") == scr32.id
                         or "3M X 2M LED SCREEN" in allmsg8),
    "not_goalpost": "GOALPOST" not in allmsg8.upper(),
}
_check("W8-dim-retype-family-scope", all(w8.values()),
       "%s (line now=%r)" % (w8, (ln8.get("product_name") or "")[:30]))

# ---------------------------------------------------------------- teardown
_clear_sess(PHONE)
_tq = env["neon.finance.quote"].sudo().with_context(active_test=False).search(
    [("partner_id", "=", client.id)])
_tej = _tq.mapped("event_job_id")
_tcj = _tej.mapped("commercial_job_id")
# quote FK-references the event_job -> drop the quote FIRST, then the chain.
env["neon.finance.approval"].sudo().search(
    [("quote_id", "in", _tq.ids)]).unlink()
env["neon.finance.invoice.schedule"].sudo().search(
    [("quote_id", "in", _tq.ids)]).unlink()
_tq.unlink()
_tej.exists().unlink()
_tcj.exists().unlink()
Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).mapped("bracket_ids").unlink()
Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).unlink()
PT.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).unlink()
ECat.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA125]")]).unlink()
# append-only payment terms + the test client (raw-SQL the terms, [TEST-*] only).
_purge_test_terms_and_partners()
_BotModel.with_context(active_test=False).search(
    [("phone_number", "=", PHONE)]).unlink()
u_sales.write({"active": False})
env.cr.commit()
_P_REPLY.stop(); _P_BTN.stop(); _P_LIST.stop(); _P_MAIL.stop()

print("=" * 72)
_passed = sum(1 for v in results.values() if v)
print("WIRE Total: %d/%d passed" % (_passed, len(results)))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 72)
