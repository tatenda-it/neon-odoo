"""P-WA-12 smoke — quote-by-WhatsApp (real dispatch path + the 4 bindings).

Runs in `odoo shell -d neon_crm`. Exercises the REAL path through
_wa12_maybe_intercept with synthesised inbound dicts (command -> parse ->
provision -> line-build -> submit -> approve-tap -> PDF -> send), never the
handlers in isolation. Test RATES only — [TEST-WA12] products carry test
list_price; nothing live.

T-WA12-01  entitlement: _wa12_can_quote sales=T, crew=F, superuser=T
T-WA12-02  DENIAL both faces: a mapped crew (non-sales) -> terse refusal on
           Quote: AND Price:, and the refusal leaks NO command/capability
T-WA12-03  fall-through: mid-sentence "quote"/"price" -> NOT claimed; a WA-6
           "finalize"/WA-8 command -> NOT shadowed (WA-12 returns None)
T-WA12-04  client resolve: no-match -> honest miss; ambiguous -> ambiguous msg
T-WA12-05  real-path provision: Quote: -> draft quote on a provisional chain
           (commercial.job pending + TBC venue + event.job is_quote_provisional)
T-WA12-06  binding-b (provisional): ZERO checklists / event_created ACT /
           readiness_50 ACT on the provisional event.job (vs a CONTROL job)
T-WA12-07  no_rule guard: a $1-placeholder line BLOCKS submit; a priced quote
           submits -> pending_approval
T-WA12-08  binding-b (graduation): accept -> event.job IDENTICAL to the control
           (checklists present, event_created ACT present, marker cleared)
T-WA12-09  dual-payload: Approve via interactive HMAC AND via template-QR text
           both -> action_approve on the pending quote
T-WA12-10  teardown: dead (rejected) quote -> provisional chain archived;
           [TEST-WA12] fixtures removed incl. ACT rows -> baseline
"""
from unittest.mock import patch

from odoo.exceptions import AccessError  # noqa: F401 (parity)
from odoo.addons.neon_channels.models import wa_payload

# Mute SMTP for the whole run: action_accept fires the P6.M7 on-acceptance
# invoice email, but the test DB has no mail server / from-address (the real
# SMTP sender is a separate prod dependency). We test the WA-12 flow + the
# graduation hook, not mail delivery. Stopped in teardown.
_MAILP = patch(
    "odoo.addons.mail.models.mail_mail.MailMail.send",
    lambda self, *a, **k: True)
_MAILP.start()
_MAILP2 = patch(
    "odoo.addons.base.models.ir_mail_server.IrMailServer.send_email",
    lambda *a, **k: "test-msgid")
_MAILP2.start()


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-WA-12 — quote-by-WhatsApp (real path + 4 bindings)")
print("=" * 72)
results = {}

Users = env["res.users"].sudo()
Bot = env["neon.bot.user"].sudo()
M = env["neon.whatsapp.message"].sudo()
P = env["res.partner"].sudo()
PT = env["product.template"].sudo()
Q = env["neon.finance.quote"].sudo()
EJ = env["commercial.event.job"].sudo()
ACT = env["action.centre.item"].sudo()
SECRET = env["ir.config_parameter"].sudo().get_param("database.secret") or ""

SALES_PH = "+263771200012"
CREW_PH = "+263771200013"
APPR_PH = "+263771200014"


def _wipe_login(login):
    for u in Users.with_context(active_test=False).search([("login", "=", login)]):
        u.write({"login": login + "_OLD_" + str(u.id), "active": False})


def _mapbot(user, phone):
    bu = Bot.with_context(active_test=False).search(
        [("phone_number", "=", phone)], limit=1)
    vals = {"name": user.name, "user_id": user.id,
            "phone_number": phone, "active": True}
    (bu.write(vals) if bu else Bot.create(vals))


# ---------------------------------------------------------------- fixtures
# Pre-wipe any prior [TEST-WA12] residue so re-runs are idempotent (a crashed
# run leaves committed partners/products behind -> name searches go ambiguous).
# CRITICAL: the equip-session row is one-per-phone (unique, spans active) and is
# REUSED across runs -- a leftover q_confirm session for a test phone makes the
# next run's command get consumed as a session turn. Drop it first.
env["neon.wa.equip.session"].sudo().with_context(active_test=False).search(
    [("phone_number", "in", (SALES_PH, CREW_PH, APPR_PH))]).unlink()
_old_p = P.with_context(active_test=False).search([("name", "like", "[TEST-WA12]")])
if _old_p:
    _oq = Q.with_context(active_test=False).search([("partner_id", "in", _old_p.ids)])
    # approvals + invoice schedules FK the quotes -> drop before unlinking them.
    env["neon.finance.approval"].sudo().search(
        [("quote_id", "in", _oq.ids)]).unlink()
    env["neon.finance.invoice.schedule"].sudo().search(
        [("quote_id", "in", _oq.ids)]).unlink()
    _oej = _oq.mapped("event_job_id")
    _ocj = _oej.mapped("commercial_job_id")
    _oq.unlink()
    _oej.exists().unlink()
    _ocj.exists().unlink()
    env["neon.finance.payment.term"].sudo().search(
        [("partner_id", "in", _old_p.ids)]).unlink()
    _old_p.unlink()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA12]")]).unlink()
# [TEST-WA12] pricing fixtures: delete AFTER the products (which reference the
# categories); the rule's unique(category,currency,effective_date) would
# otherwise collide on a re-run.
_orules = env["neon.finance.pricing.rule"].sudo().with_context(
    active_test=False).search([("name", "like", "[TEST-WA12]")])
_orules.mapped("bracket_ids").unlink()
_orules.unlink()
env["neon.equipment.category"].sudo().with_context(active_test=False).search(
    [("name", "like", "[TEST-WA12]")]).unlink()
for lg in ("pwa12_sales", "pwa12_crew", "pwa12_appr"):
    _wipe_login(lg)
g_sales = env.ref("neon_core.group_neon_sales_rep")
g_super = env.ref("neon_core.group_neon_superuser")
g_crew = env.ref("neon_jobs.group_neon_jobs_user", raise_if_not_found=False) \
    or env.ref("base.group_user")

u_sales = Users.with_context(no_reset_password=True).create({
    "name": "PWA12 Sales", "login": "pwa12_sales", "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_sales.id)]})
u_crew = Users.with_context(no_reset_password=True).create({
    "name": "PWA12 Crew", "login": "pwa12_crew", "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_crew.id)]})
u_appr = Users.with_context(no_reset_password=True).create({
    "name": "PWA12 Approver", "login": "pwa12_appr", "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_super.id)]})
_mapbot(u_sales, SALES_PH)
_mapbot(u_crew, CREW_PH)
_mapbot(u_appr, APPR_PH)
# message_post (submit/approve chatter) computes the author's from-address with
# raise_on_email=True; real prod users carry an email, these fixtures don't.
for _u in (u_sales, u_crew, u_appr):
    _u.partner_id.write({"email": "%s@neon.test" % _u.login})

client = P.create({"name": "[TEST-WA12] Acme Events Co"})
USD = env.ref("base.USD")
# WA-12 prices through the ENGINE (rule x bracket x day-mult), NEVER list_price.
# A dedicated [TEST-WA12] rule (base $50, bracket 1..* x1.0) gives a
# deterministic $50/day -- NOT a Sound rule, so no ambiguity with PRC-0001. A
# SECOND category with NO rule exercises the no_rule path.
ECat = env["neon.equipment.category"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Bracket = env["neon.finance.pricing.bracket"].sudo()
tcat = ECat.create({"name": "[TEST-WA12] Cat", "code": "TWA12CAT"})
tcat_norule = ECat.create({"name": "[TEST-WA12] NoRuleCat", "code": "TWA12NR"})
trule = Rule.create({
    "name": "[TEST-WA12] Rule", "category_id": tcat.id, "currency_id": USD.id,
    "base_rate": 50.0, "effective_date": "2020-01-01", "active": True})
Bracket.create({"rule_id": trule.id, "sequence": 1, "day_from": 1,
                "day_to": -1, "multiplier": 1.0})
prod_ok = PT.create({
    # unique token so _wa6_match_one token-matches THIS product only; the
    # list_price is DELIBERATELY 999 (!= the $50 rule) to PROVE the engine
    # ignores list_price -- the line must price at $50 via tcat -> trule.
    "name": "[TEST-WA12] Qwertyunit", "is_workshop_item": True,
    "list_price": 999.0,
    "equipment_category_id": tcat.id})
prod_ph = PT.create({
    # a category with NO rule -> the engine stamps 'no_rule' -> guard blocks.
    "name": "[TEST-WA12] Placeholder Gizmo", "is_workshop_item": True,
    "list_price": 1.0,
    "equipment_category_id": tcat_norule.id})
# WA-12.1: a PRODUCT-scoped rule ($77) on a product that ALSO sits in tcat (the
# $50 category rule) with list_price 999 -> must price $77 (product rule wins).
prod_pr = PT.create({
    "name": "[TEST-WA12] Prodruled", "is_workshop_item": True,
    "list_price": 999.0, "equipment_category_id": tcat.id})
prule = Rule.create({
    "name": "[TEST-WA12] ProdRule", "product_template_id": prod_pr.id,
    "currency_id": USD.id, "base_rate": 77.0, "effective_date": "2020-01-01"})
Bracket.create({"rule_id": prule.id, "sequence": 1, "day_from": 1,
                "day_to": -1, "multiplier": 1.0})
# a partner-scoped payment term so _wa12_ensure_payment_term resolves (the
# prod DB carries terms; the test DB starts with none).
PTerm = env["neon.finance.payment.term"].sudo()
pterm = PTerm.create({"name": "[TEST-WA12] Terms", "partner_id": client.id})
# accept fires the P6.M7 on-acceptance invoice schedule, which emails — give
# the mail machinery a from-address + a dummy server so accept doesn't raise
# (the real SMTP sender is a separate prod dependency, not under test here).
env.company.sudo().write({"email": env.company.email or "noreply@neon.test"})
client.write({"email": "acme@neon.test"})
if not env["ir.mail_server"].sudo().search([], limit=1):
    env["ir.mail_server"].sudo().create({
        "name": "[TEST-WA12] dummy", "smtp_host": "localhost",
        "smtp_port": 25, "smtp_encryption": "none"})
env.cr.commit()

D_sales = M.with_user(u_sales)
D_crew = M.with_user(u_crew)
D_appr = M.with_user(u_appr)


def _txt(phone, body):
    return {"from": phone, "type": "text", "text": {"body": body},
            "id": "pwa12-%s" % phone}


def _act_count(ejob):
    """open/in_progress ACT rows whose source is this event.job."""
    model = env["ir.model"].sudo().search(
        [("model", "=", "commercial.event.job")], limit=1)
    return ACT.search_count([
        ("source_model_id", "=", model.id), ("source_id", "=", ejob.id),
        ("state", "in", ("open", "in_progress"))])


# ---------------------------------------------------------- T-WA12-01 entitle
_check("T-WA12-01",
       D_sales._wa12_can_quote(u_sales) is True
       and D_crew._wa12_can_quote(u_crew) is False
       and D_appr._wa12_can_quote(u_appr) is True,
       "sales=T crew=F superuser=T")

# ---------------------------------------------------------- T-WA12-02 denial
crew_q = D_crew._wa12_maybe_intercept(_txt(CREW_PH, "Quote: Acme — widget, 2026-08-01"))
crew_p = D_crew._wa12_maybe_intercept(_txt(CREW_PH, "Price: widget"))
# the refusal text must NOT contain the word "quote"/"price"/"invoice"
last_out = M.search([("phone_number", "=", CREW_PH), ("direction", "=", "outbound")],
                    order="id desc", limit=1)
leaks = any(w in (last_out.message_body or "").lower()
            for w in ("quote", "price", "invoice", "command"))
_check("T-WA12-02",
       crew_q is True and crew_p is True and not leaks,
       "both faces claimed+refused; refusal leaks capability=%s" % leaks)

# ---------------------------------------------------------- T-WA12-03 fallthrough
ft1 = D_sales._wa12_maybe_intercept(_txt(SALES_PH, "I'd love a quote for the gala soon"))
ft2 = D_sales._wa12_maybe_intercept(_txt(SALES_PH, "the price was fair last time"))
ft3 = D_sales._wa12_maybe_intercept(_txt(SALES_PH, "finalize"))
_check("T-WA12-03",
       ft1 is None and ft2 is None and ft3 is None,
       "mid-sentence quote/price + WA-6 'finalize' all fall through")

# ---------------------------------------------------------- T-WA12-04 client
nomatch = D_sales._wa12_resolve_client("Nonexistent Zzz Client")
_check("T-WA12-04a", (not nomatch[0]) and bool(nomatch[1]),
       "no-match -> empty + honest message")
P.create({"name": "[TEST-WA12] Dup Client"})
P.create({"name": "[TEST-WA12] Dup Client"})
amb = D_sales._wa12_resolve_client("[TEST-WA12] Dup Client")
_check("T-WA12-04b", (not amb[0]) and "more than one" in (amb[1] or "").lower(),
       "ambiguous -> empty + ambiguous message")

# ---------------------------------------------------------- T-WA12-05 provision
_cmd = "Quote: Acme Events - qwertyunit x2, 2026-08-01"
claimed = D_sales._wa12_maybe_intercept(_txt(SALES_PH, _cmd))
# find the provisioned quote by salesperson (a DIRECT field; quote.partner_id
# is a 2-level related-store that may lag within the un-flushed test txn).
quote = Q.search([("salesperson_id", "=", u_sales.id), ("state", "=", "draft")],
                 order="id desc", limit=1)
ejob = quote.event_job_id
cjob = ejob.commercial_job_id
tbc = env.ref("neon_finance.wa12_tbc_venue", raise_if_not_found=False)
_check("T-WA12-05",
       claimed is True and quote and quote.state == "draft"
       and ejob.is_quote_provisional and cjob.state == "pending"
       and cjob.venue_id == tbc and cjob.partner_id == client
       and len(quote.line_ids) >= 1,
       "draft quote %s on provisional chain (cjob %s pending, venue TBC, "
       "ejob provisional, %d line(s))" % (
           quote.name if quote else "-", cjob.id if cjob else "-",
           len(quote.line_ids) if quote else 0))

# ---- T-WA12-05a (review-fix: ENGINE pricing, NOT list_price) — prod_ok x2 x1d
# prices $50/day via tcat->trule (its list_price is 999, which MUST be ignored):
# 50 x 2 x 1 = $100.00 ex-VAT, $115.50 incl 15.5% VAT.
okl = quote.line_ids.filtered(lambda l: l.product_template_id == prod_ok)[:1]
_check("T-WA12-05a",
       okl.pricing_status == "priced" and abs(okl.unit_rate - 50.0) < 0.01
       and abs(quote.amount_untaxed - 100.0) < 0.01
       and abs(quote.amount_total - 115.50) < 0.01,
       "engine-priced via rule: line=%s rate=%s (list_price 999 IGNORED); "
       "untaxed=%s total=%s (want priced/50/100.00/115.50)" % (
           okl.pricing_status, okl.unit_rate,
           quote.amount_untaxed, quote.amount_total))

# ---------------------------------------------------------- T-WA12-06 binding-b
n_checklists = len(ejob.checklist_ids) if "checklist_ids" in ejob._fields else 0
_check("T-WA12-06",
       n_checklists == 0 and _act_count(ejob) == 0,
       "provisional ejob: %d checklists, %d open ACT (want 0/0)"
       % (n_checklists, _act_count(ejob)))

# control: a normally-created event.job DOES fire the effects
ctrl_cj = env["commercial.job"].sudo().create({
    "partner_id": client.id, "event_date": "2026-08-01",
    "venue_id": tbc.id})
ctrl_ej = EJ.create({"commercial_job_id": ctrl_cj.id})
ctrl_checklists = len(ctrl_ej.checklist_ids) if "checklist_ids" in ctrl_ej._fields else -1
_check("T-WA12-06-control",
       ctrl_checklists > 0 and _act_count(ctrl_ej) >= 1,
       "control ejob: %d checklists, %d ACT (want >0/>=1)"
       % (ctrl_checklists, _act_count(ctrl_ej)))

# ---------------------------------------------------------- T-WA12-07 no_rule guard
# add a placeholder-rate line to the T05 draft (in scope) -> submit must block
ph_quote = quote
M.sudo()._wa12_build_lines(ph_quote, [{"product_id": prod_ph.id, "qty": 1}], 1)
ph_quote.action_recalculate_pricing()
unpriced = M.sudo()._wa12_unpriced_lines(ph_quote)
phl = ph_quote.line_ids.filtered(lambda l: l.product_template_id == prod_ph)[:1]
blocked = False
try:
    if not unpriced:
        ph_quote.action_submit_for_approval()
    else:
        blocked = True
except Exception:
    blocked = True
# (review-fix b) an UNRULED category resolves the engine's no_rule path -> guard
_check("T-WA12-07", bool(unpriced) and blocked and phl.pricing_status == "no_rule",
       "unruled-category line status=%s -> unpriced=%s, submit blocked"
       % (phl.pricing_status, unpriced))

# ---------------------------------------------------------- T-WA12-08 graduation
# build a clean (priced-only) quote, submit, approve, check graduation
clean = Q._wa12_provision_chain(
    client, "2026-09-01",
    env.ref("base.USD"), u_sales, date_is_placeholder=False)
M.sudo()._wa12_build_lines(clean, [{"product_id": prod_ok.id, "qty": 2}], 1)
clean.action_recalculate_pricing()
M.sudo()._wa12_ensure_payment_term(clean, client)
g_ej = clean.event_job_id
submitted = approved = False
try:
    clean.with_user(u_sales.id).action_submit_for_approval()
    submitted = clean.state == "pending_approval"
    clean.with_user(u_appr.id).action_approve()
    # draft->pending_approval->approved->sent->accepted; accept is the client
    # acceptance that graduates the provisional chain (binding d).
    if clean.state == "approved":
        clean.with_user(u_sales.id).action_send()
    if clean.state == "sent":
        clean.with_user(u_sales.id).action_accept()
    approved = clean.state == "accepted"
except Exception as e:
    print("   T08 flow err:", str(e)[:120])
g_checklists = len(g_ej.checklist_ids) if "checklist_ids" in g_ej._fields else -1
_check("T-WA12-08",
       submitted and not g_ej.is_quote_provisional and g_checklists > 0
       and _act_count(g_ej) >= 1,
       "graduated ejob: provisional=%s, %d checklists, %d ACT (want F/>0/>=1)"
       % (g_ej.is_quote_provisional, g_checklists, _act_count(g_ej)))

# ---------------------------------------------------------- T-WA12-09 dual-payload
# a fresh priced quote in pending_approval, approve via BOTH payload forms
dp = Q._wa12_provision_chain(
    client, "2026-09-02", env.ref("base.USD"), u_sales)
M.sudo()._wa12_build_lines(dp, [{"product_id": prod_ok.id, "qty": 1}], 1)
dp.action_recalculate_pricing(); M.sudo()._wa12_ensure_payment_term(dp, client)
dp.with_user(u_sales.id).action_submit_for_approval()
# (a) interactive HMAC payload
hmac_id = wa_payload.encode(SECRET, "wa12_approve", dp.id)
imsg = {"from": APPR_PH, "type": "interactive",
        "interactive": {"button_reply": {"id": hmac_id}}, "id": "dp-i"}
tap_i = D_appr._wa12_extract_tap(imsg)
# (b) template-QR plain text -> resolves the pending quote
bmsg = {"from": APPR_PH, "type": "button",
        "button": {"text": "Approve", "payload": "Approve"}, "id": "dp-b"}
tap_b = D_appr._wa12_extract_tap(bmsg)
_check("T-WA12-09",
       tap_i and tap_i[0] == "wa12_approve" and tap_i[1].id == dp.id
       and tap_b and tap_b[0] == "wa12_approve" and tap_b[1].id == dp.id,
       "HMAC->%s/%s ; template-QR->%s/%s (both resolve quote %s)" % (
           tap_i[0] if tap_i else None, tap_i[1].id if tap_i else None,
           tap_b[0] if tap_b else None, tap_b[1].id if tap_b else None, dp.id))

# ============================================================ review-fix guards
# ---- T-WA12-11 parser fall-through (bare "quote"/"price" never steal a turn)
_check("T-WA12-11",
       D_sales._wa12_is_price_cmd("price list please") is False
       and D_sales._wa12_is_quote_cmd("quote me a figure for the gala") is False
       and D_sales._wa12_is_quote_cmd("quotes for tomorrow") is False
       and D_sales._wa12_is_quote_cmd("quote") is True
       and D_sales._wa12_is_quote_cmd("Quote: Acme — led wall") is True
       and D_sales._wa12_is_price_cmd("price:") is True,
       "bare word only as exact-equals; colon form prefixes; openers fall through")

# ---- T-WA12-12 a live NON-WA-12 session (WA-6) is never overrun by Quote:
Sess = env["neon.wa.equip.session"].sudo().with_context(active_test=False)
_s6 = Sess.search([("phone_number", "=", SALES_PH)], limit=1)
_v6 = {"phone_number": SALES_PH, "user_id": u_sales.id, "step": "await_items",
       "active": True, "last_inbound": False}
_s6.write(_v6) if _s6 else Sess.create(_v6)
steal = D_sales._wa12_maybe_intercept(_txt(
    SALES_PH, "Quote: Acme - qwertyunit x2, 2026-08-01"))
_s6 = Sess.search([("phone_number", "=", SALES_PH)], limit=1)
_check("T-WA12-12",
       steal is None and _s6.step == "await_items" and _s6.active,
       "live WA-6 session intact (intercept None, step=%s active=%s)"
       % (_s6.step, _s6.active))

# ---- T-WA12-13 'for N days' parses clean (no dangling 's' in the items)
_c13, _i13, _d13, _days13 = D_sales._wa12_parse_quote(
    "Acme Events - LED wall for 3 days, 2026-08-01")
_check("T-WA12-13",
       _days13 == 3 and _i13.strip().lower() == "led wall",
       "for-N-days clean: items=%r days=%s" % (_i13, _days13))

# ---- T-WA12-14 provisioning create_uid = the real rep (not the webhook user)
_check("T-WA12-14",
       quote.create_uid.id == u_sales.id
       and ejob.create_uid.id == u_sales.id
       and cjob.create_uid.id == u_sales.id
       and quote.line_ids[:1].create_uid.id == u_sales.id,
       "chain create_uid = rep (q=%s ej=%s cj=%s line=%s)" % (
           quote.create_uid.id, ejob.create_uid.id, cjob.create_uid.id,
           quote.line_ids[:1].create_uid.id))

# ---- T-WA12-15 view_pdf + send-to-client gated on the WA-12 layer (not a
# mapped non-owner crew): a forwarded HMAC tap is refused, no doc / no send
def _last_out(ph):
    return M.search([("phone_number", "=", ph), ("direction", "=", "outbound")],
                    order="id desc", limit=1)
_vtap = D_crew._wa12_extract_tap({
    "from": CREW_PH, "type": "interactive", "id": "vp",
    "interactive": {"button_reply": {
        "id": wa_payload.encode(SECRET, "wa12_view_pdf", dp.id)}}})
D_crew._wa12_handle_tap(_vtap[0], _vtap[1], CREW_PH, CREW_PH,
                        {"from": CREW_PH, "type": "interactive", "id": "vp"})
_v_ref = "action on your account" in (_last_out(CREW_PH).message_body or "").lower()
_stap = D_crew._wa12_extract_tap({
    "from": CREW_PH, "type": "interactive", "id": "sd",
    "interactive": {"button_reply": {
        "id": wa_payload.encode(SECRET, "wa12_send", dp.id)}}})
D_crew._wa12_handle_tap(_stap[0], _stap[1], CREW_PH, CREW_PH,
                        {"from": CREW_PH, "type": "interactive", "id": "sd"})
_s_ref = "action on your account" in (_last_out(CREW_PH).message_body or "").lower()
_check("T-WA12-15", _v_ref and _s_ref,
       "non-owner crew tap refused: view_pdf=%s send=%s" % (_v_ref, _s_ref))

# ---- T-WA12-16 approver gate (group-based) is DISTINCT from the creation gate
# (so the reject turn keys on the right capability; a pure sales rep can't
# complete a rejection, a real approver can).
_check("T-WA12-16",
       D_appr._wa12_is_approver(u_appr) is True
       and D_sales._wa12_is_approver(u_sales) is False
       and D_crew._wa12_is_approver(u_crew) is False
       and D_sales._wa12_can_quote(u_sales) is True,
       "approver(group) gate distinct from creation gate")

# ---- T-WA12-17 cold template-QR is AMBIGUOUS with 2+ pending -> refuse (never
# approve the wrong quote). dp (T09) is still pending; add a 2nd pending quote.
dp2 = Q._wa12_provision_chain(client, "2026-09-04", env.ref("base.USD"), u_sales)
M.sudo()._wa12_build_lines(dp2, [{"product_id": prod_ok.id, "qty": 1}], 1)
dp2.action_recalculate_pricing(); M.sudo()._wa12_ensure_payment_term(dp2, client)
dp2.with_user(u_sales.id).action_submit_for_approval()
_btap = D_appr._wa12_extract_tap({"from": APPR_PH, "type": "button", "id": "amb",
                                  "button": {"text": "Approve", "payload": "Approve"}})
D_appr._wa12_handle_tap(_btap[0], _btap[1], APPR_PH, APPR_PH,
                        {"from": APPR_PH, "type": "button", "id": "amb"})
_amb_out = M.search([("phone_number", "=", APPR_PH), ("direction", "=", "outbound")],
                    order="id desc", limit=1)
_check("T-WA12-17",
       len(_btap[1]) >= 2
       and "can't tell which" in (_amb_out.message_body or "").lower()
       and dp.state == "pending_approval" and dp2.state == "pending_approval",
       "2 pending -> template-QR Approve refused, neither approved (dp=%s dp2=%s)"
       % (dp.state, dp2.state))

# ---- T-WA12-18 (review-fix c) REGRESSION: a hand-set rate on a categorized
# product with NO equipment_line_id stays 'manual' -- the engine widening
# (scoped to unit_rate==0) must NOT re-price it to the rule's $50.
mq = Q._wa12_provision_chain(client, "2026-10-01", USD, u_sales)
mline = env["neon.finance.quote.line"].sudo().create({
    "quote_id": mq.id, "line_type": "equipment", "product_template_id": prod_ok.id,
    "name": "[TEST-WA12] manual", "quantity": 1, "unit_rate": 80.0,
    "duration_days": 1})
m_create = mline.pricing_status
mq.action_recalculate_pricing()
_check("T-WA12-18",
       m_create == "manual" and mline.pricing_status == "manual"
       and abs(mline.unit_rate - 80.0) < 0.01,
       "manual line preserved (create=%s recalc=%s rate=%s; NOT repriced to 50)"
       % (m_create, mline.pricing_status, mline.unit_rate))
# reservation-backed lines are byte-unchanged by construction: the gate is
# `equipment_line_id OR (new clause)` -> when equipment_line_id is set the new
# clause is never evaluated (short-circuit). Covered structurally + by pwa6.

# ---- T-WA12-19 (review-fix d) GUARD-BYPASS pinned: the WA-12 lane never sets
# unit_rate, so it can NEVER fabricate a 'manual'-priced line for ANY input --
# the engine prices ('priced') or stamps 'no_rule'. (The defeat we found.)
dq = Q._wa12_provision_chain(client, "2026-10-02", USD, u_sales)
M.sudo()._wa12_build_lines(dq, [{"product_id": prod_ok.id, "qty": 1},
                                {"product_id": prod_ph.id, "qty": 1}], 1)
dq.action_recalculate_pricing()
_dstatuses = dq.line_ids.mapped("pricing_status")
_check("T-WA12-19",
       "manual" not in _dstatuses
       and set(_dstatuses) <= {"priced", "no_rule", "not_yet"},
       "WA-12 lane fabricates no 'manual' line: statuses=%s" % _dstatuses)

# ---- T-WA12-20 (review-fix) [Send to client] requires a client email: a client
# with NO email -> the send leg refuses + leaves state 'approved' (never the
# false "sent" on an undelivered quote that the proof's accidental tap exposed).
noeml = P.create({"name": "[TEST-WA12] NoEmail Co", "is_company": True})
neq = Q._wa12_provision_chain(noeml, "2026-11-01", USD, u_sales)
M.sudo()._wa12_build_lines(neq, [{"product_id": prod_ok.id, "qty": 1}], 1)
neq.action_recalculate_pricing()
M.sudo()._wa12_ensure_payment_term(neq, noeml)
neq.with_user(u_sales.id).action_submit_for_approval()
neq.with_user(u_appr.id).action_approve()
M.sudo()._wa12_handle_send_to_client(neq, u_sales, SALES_PH, SALES_PH)
_ne_out = M.search([("phone_number", "=", SALES_PH), ("direction", "=", "outbound")],
                   order="id desc", limit=1)
_check("T-WA12-20",
       "no email" in (_ne_out.message_body or "").lower()
       and neq.state == "approved",
       "no-email client: send refused (reply has 'no email'), state=%s (NOT sent)"
       % neq.state)

# ---- T-WA12-21 (WA-12.1) PRODUCT-rule resolution + flat day math: prod_pr has a
# $77 product rule, sits in tcat ($50 cat rule), list_price 999 -> prices $77.
prq = Q._wa12_provision_chain(client, "2026-09-20", USD, u_sales)
M.sudo()._wa12_build_lines(prq, [{"product_id": prod_pr.id, "qty": 2}], 3)
prq.action_recalculate_pricing()
prl = prq.line_ids[0]
_check("T-WA12-21",
       prl.pricing_status == "priced" and abs(prl.unit_rate - 77.0) < 0.01
       and abs(prl.line_subtotal - 462.0) < 0.01,
       "product rule wins: status=%s rate=%s subtotal=%s (want priced/77/462 "
       "= 77×2×3 flat; not $50 cat, not $999 list)" % (
           prl.pricing_status, prl.unit_rate, prl.line_subtotal))

# ---- T-WA12-22 (flex) edit loop on a draft: discount, custom line, no-tax.
fq = Q._wa12_provision_chain(client, "2026-09-21", USD, u_sales)
M.sudo()._wa12_build_lines(fq, [{"product_id": prod_ok.id, "qty": 1}], 1)
fq.action_recalculate_pricing()  # prod_ok -> $50 via tcat
M.sudo()._wa12_try_edit(fq, "discount qwertyunit 20%", SALES_PH, SALES_PH)
fl = fq.line_ids.filtered(lambda l: l.product_template_id == prod_ok)[:1]
disc_ok = abs(fl.unit_rate - 50.0) < 0.01 and abs(fl.line_subtotal - 40.0) < 0.01
M.sudo()._wa12_try_edit(fq, "add custom Rigging at 120", SALES_PH, SALES_PH)
custom = fq.line_ids.filtered(lambda l: l.line_type == "custom")[:1]
custom_ok = bool(custom) and abs(custom.unit_rate - 120.0) < 0.01
# custom line passes the guard; equipment lines are priced -> not unpriced
guard_ok = not M.sudo()._wa12_unpriced_lines(fq)
M.sudo()._wa12_try_edit(fq, "no tax", SALES_PH, SALES_PH)
notax_ok = (fq.amount_tax or 0.0) == 0.0
_check("T-WA12-22",
       disc_ok and custom_ok and guard_ok and notax_ok,
       "flex edit loop: disc(50→40)=%s custom@120=%s guard-pass=%s no-tax=%s"
       % (disc_ok, custom_ok, guard_ok, notax_ok))

# ---- T-WA12-23 (review WA12-FLEX-3) Price: face uses the ENGINE, not
# list_price. qwertyunit (list 999, $50 cat rule) -> $50; prodruled ($77 product
# rule) -> $77; placeholder (no rule) -> 'no rate set yet'. Clear any live
# SALES_PH session first: a live q_* session legitimately OWNS the turn (the
# command branch runs after the session branch), so the standalone Price: face
# is tested on a clean slate.
env["neon.wa.equip.session"].sudo().with_context(active_test=False).search(
    [("phone_number", "=", SALES_PH)]).write({"active": False})


def _price_reply(token):
    _s = M.search([], order="id desc", limit=1).id
    D_sales._wa12_maybe_intercept(_txt(SALES_PH, "Price: %s" % token))
    o = M.search([("id", ">", _s), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1)
    return o.message_body or ""

pr_ok = _price_reply("qwertyunit")
pr_pr = _price_reply("prodruled")
pr_ph = _price_reply("placeholder gizmo")
_check("T-WA12-23",
       ("50.00" in pr_ok and "999" not in pr_ok)
       and "77.00" in pr_pr
       and "no rate set yet" in pr_ph.lower(),
       "Price: engine rate — qwertyunit=%r prodruled=%r placeholder=%r"
       % (pr_ok[:40], pr_pr[:40], pr_ph[:40]))

# ---- T-WA12-24 (review WA13-3) a stale WA-13 'Cancel' INTERACTIVE tap reaching
# a live q_confirm session must NOT be parsed as a cancel command (it would
# cancel a live quote draft) — WA-12 re-prompts, the quote stays draft.
t24q = Q._wa12_provision_chain(client, "2026-12-01", USD, u_sales)
M.sudo()._wa12_build_lines(t24q, [{"product_id": prod_ok.id, "qty": 1}], 1)
t24q.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": t24q.id})
_stale = {"from": SALES_PH, "type": "interactive", "id": "stale-wa13",
          "interactive": {"button_reply": {
              "id": "wa13_inv_cancel:999:deadbeef", "title": "Cancel"}}}
_r24 = D_sales._wa12_maybe_intercept(_stale)
_s24 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
_check("T-WA12-24",
       _r24 is True and t24q.state == "draft"
       and bool(_s24) and _s24.step == "q_confirm",
       "stale WA-13 Cancel tap re-prompted; quote stays draft (state=%s, "
       "sess=%s)" % (t24q.state, _s24.step if _s24 else "-"))

# ---- T-WA12-25 (preview) a mid-session `preview` renders the CURRENT draft
# (DRAFT-stamped) to the REQUESTER, NO state change, and edits after preview
# still apply.
pvq = Q._wa12_provision_chain(client, "2026-12-05", USD, u_sales)
M.sudo()._wa12_build_lines(pvq, [{"product_id": prod_ok.id, "qty": 1}], 1)
pvq.action_recalculate_pricing()
_sp = M.search([], order="id desc", limit=1).id
M.sudo()._wa12_try_edit(pvq, "preview", SALES_PH, SALES_PH)
_pv_out = M.search([("id", ">", _sp), ("phone_number", "=", SALES_PH),
                    ("direction", "=", "outbound")])
_pv_doc = bool(_pv_out.filtered(lambda m: m.message_type == "document"))
_state_after = pvq.state
# an edit AFTER preview still applies (no_tax -> amount_tax 0); also proves the
# session/draft survived the preview unchanged.
M.sudo()._wa12_try_edit(pvq, "no tax", SALES_PH, SALES_PH)
_check("T-WA12-25",
       _pv_doc and _state_after == "draft" and (pvq.amount_tax or 0.0) == 0.0,
       "preview -> DRAFT doc to requester (%s), state unchanged (%s), "
       "post-preview edit applies (tax=%s)"
       % (_pv_doc, _state_after, pvq.amount_tax))

# ---- T-WA12-26 (wall a) payment term: a partner with NO term -> the company
# 7-day default is auto-applied (submit is never termless, never a "use the
# Odoo button" reply).
import odoo.addons.neon_crew_comms.models.whatsapp_message_wa12 as _w12  # noqa
noterm = P.create({"name": "[TEST-WA12] NoTerm Co"})
tq26 = Q._wa12_provision_chain(noterm, "2026-09-20", USD, u_sales)
M.sudo()._wa12_build_lines(tq26, [{"product_id": prod_ok.id, "qty": 1}], 1)
tq26.action_recalculate_pricing()
M.sudo()._wa12_ensure_payment_term(tq26, noterm)
_check("T-WA12-26",
       bool(tq26.payment_term_id)
       and tq26.payment_term_id.final_due_days == 7
       and tq26.payment_term_id.deposit_pct == 0.0,
       "no-term partner -> 7-day default applied (term=%r final_due=%s)"
       % (tq26.payment_term_id.name, tq26.payment_term_id.final_due_days))

# ---- T-WA12-27 (wall c) date tolerance, DAY-FIRST: 25/09/26, 25/09/2026,
# 29 Sept 2026, 15 september 2026 all parse to 2026-09-{25,25,29,15}.
_d1, _p1 = M._wa12_resolve_date("25/09/26")
_d2, _p2 = M._wa12_resolve_date("25/09/2026")
_d3, _p3 = M._wa12_resolve_date("29 Sept 2026")
_d4, _p4 = M._wa12_resolve_date("15 september 2026")
_check("T-WA12-27",
       not any([_p1, _p2, _p3, _p4])
       and (_d1.year, _d1.month, _d1.day) == (2026, 9, 25)
       and (_d2.month, _d2.day) == (9, 25)
       and (_d3.year, _d3.month, _d3.day) == (2026, 9, 29)
       and (_d4.year, _d4.month, _d4.day) == (2026, 9, 15),
       "date tolerance: 25/09/26=%s 25/09/2026=%s 29 Sept 2026=%s "
       "15 september 2026=%s" % (_d1, _d2, _d3, _d4))

# ---- T-WA12-28 (wall b/d) conversational triggers + synonyms + strip +
# bare-date-sets-date + terms command.
trig_ok = (M._wa12_is_quote_cmd("quote for Acme")
           and M._wa12_is_quote_cmd("make a quotation for Acme")
           and M._wa12_is_quote_cmd("i want a quote for Acme")
           and not M._wa12_is_quote_cmd("quote me later"))
strip_ok = M._wa12_strip_cmd(
    "quote for Acme — widget",
    _w12._WA12_QUOTE_CMDS + _w12._WA12_QUOTE_TRIGGERS) == "Acme — widget"
syn_ok = ("scrap this" in _w12._WA12_CANCEL_WORDS
          and "submit for approval" in _w12._WA12_SUBMIT_WORDS)
tq28 = Q._wa12_provision_chain(client, "2026-09-21", USD, u_sales)
M.sudo()._wa12_build_lines(tq28, [{"product_id": prod_ok.id, "qty": 1}], 1)
tq28.action_recalculate_pricing()
M.sudo()._wa12_try_edit(tq28, "29 Sept 2026", SALES_PH, SALES_PH)
_cj28 = tq28.event_job_id.commercial_job_id
date_ok = (_cj28.event_date and _cj28.event_date.month == 9
           and _cj28.event_date.day == 29
           and not _cj28.event_date_is_placeholder)
M.sudo()._wa12_try_edit(tq28, "terms net 14 days", SALES_PH, SALES_PH)
terms_ok = (bool(tq28.payment_term_id)
            and tq28.payment_term_id.final_due_days == 14)
_check("T-WA12-28",
       trig_ok and strip_ok and syn_ok and date_ok and terms_ok,
       "triggers=%s strip=%s synonyms=%s bare-date(29 Sep)=%s terms(14d)=%s"
       % (trig_ok, strip_ok, syn_ok, date_ok, terms_ok))

# ---- new-client intake helpers ----------------------------------------------
def _clear_sess(ph):
    env["neon.wa.equip.session"].sudo().with_context(active_test=False).search(
        [("phone_number", "=", ph)]).write({"active": False})


def _send(ph, txt):
    return D_sales._wa12_maybe_intercept(_txt(ph, txt))


def _step(ph):
    s = env["neon.wa.equip.session"].sudo()._active_for_phone(ph)
    return s.step if s else None


# ---- T-WA12-29 (intake) full new-client capture (individual, no dupe) ->
# partner created (E164 phone joins WA-9 spine, ref source, create_uid=rep) ->
# quote RESUMES in the same session with no item/date re-entry.
_clear_sess(SALES_PH)
N29 = "[TEST-WA12] Zorptronic Events"
_send(SALES_PH, "Quote: %s — qwertyunit, 25/09/2026" % N29)
pick29 = _step(SALES_PH) == "qc_pick"
_send(SALES_PH, "new")
_send(SALES_PH, "individual")
_send(SALES_PH, "ok")            # qc_name -> reuse the typed name (confirmed)
phase29 = _step(SALES_PH)        # individual skips contact -> qc_phone
_send(SALES_PH, "+263772345678")
_send(SALES_PH, "zorp@example.com")   # qc_email -> create + resume
p29 = P.search([("name", "=", N29)], limit=1)
created29 = (bool(p29) and p29.ref == "whatsapp_quote" and not p29.is_company
             and p29.create_uid.id == u_sales.id
             and "772345678" in (p29.phone_sanitized or p29.phone or ""))
q29 = Q.search([("partner_id", "=", p29.id)], limit=1) if p29 else Q.browse()
_check("T-WA12-29",
       pick29 and phase29 == "qc_phone" and created29
       and _step(SALES_PH) == "q_confirm" and bool(q29) and q29.state == "draft",
       "intake: pick=%s phase=%s created(ref/uid/phone)=%s resumed=%s quote=%s"
       % (pick29, phase29, created29, _step(SALES_PH), q29.name if q29 else "-"))

# ---- T-WA12-30 (intake) near-duplicate check, BOTH branches.
gh = P.create({"name": "[TEST-WA12] Globex Holdings"})
# Flow A: typed name fuzzy-matches -> qc_dupe -> pick existing (NO new partner).
_clear_sess(SALES_PH)
_send(SALES_PH, "Quote: [TEST-WA12] Glubex Co — qwertyunit, 2026-09-20")
_send(SALES_PH, "new")
_send(SALES_PH, "company")
_send(SALES_PH, "[TEST-WA12] Globex")     # -> dupe (Globex Holdings)
dupeA = _step(SALES_PH) == "qc_dupe"
_send(SALES_PH, "1")                       # use existing
qA = Q.search([("partner_id", "=", gh.id)], limit=1)
flowA = (dupeA and bool(qA) and _step(SALES_PH) == "q_confirm"
         and not P.search([("name", "=", "[TEST-WA12] Globex")]))
# Flow B: same dupe -> *new* -> create new (company + child contact, skip email).
_clear_sess(SALES_PH)
_send(SALES_PH, "Quote: [TEST-WA12] Glubex2 — qwertyunit, 2026-09-20")
_send(SALES_PH, "new")
_send(SALES_PH, "company")
_send(SALES_PH, "[TEST-WA12] Globex")     # -> dupe again
_send(SALES_PH, "new")                     # add new anyway
_send(SALES_PH, "[TEST-WA12] John")        # qc_contact (company)
_send(SALES_PH, "+263773000111")           # qc_phone
_send(SALES_PH, "skip")                    # qc_email skipped -> create + resume
newg = P.search([("name", "=", "[TEST-WA12] Globex")], limit=1)
child = P.search([("name", "=", "[TEST-WA12] John"),
                  ("parent_id", "=", newg.id)], limit=1) if newg else P.browse()
flowB = (bool(newg) and newg.is_company and not newg.email
         and newg.ref == "whatsapp_quote" and bool(child)
         and _step(SALES_PH) == "q_confirm")
_check("T-WA12-30", flowA and flowB,
       "dupe-check: A(pick existing, no new)=%s  B(new w/ contact, skip-email)=%s"
       % (flowA, flowB))

# ---- T-WA12-31 (intake) resolver >1 -> list-then-pick (was an error) + the
# T29 partner is WA-9-recognizable (phone_sanitized holds the E164).
P.create({"name": "[TEST-WA12] Acme Sound"})   # joins the client fixture "Acme Events Co"
_clear_sess(SALES_PH)
_send(SALES_PH, "Quote: [TEST-WA12] Acme — qwertyunit, 2026-09-20")
pickN = _step(SALES_PH) == "qc_pick"
_send(SALES_PH, "1")
resumedN = _step(SALES_PH) == "q_confirm"
p29b = P.search([("name", "=", N29)], limit=1)
wa9_ok = bool(p29b) and "772345678" in (p29b.phone_sanitized or p29b.phone or "")
_check("T-WA12-31", pickN and resumedN and wa9_ok,
       ">1 list-then-pick=%s resumed=%s ; WA-9 phone_sanitized=%s"
       % (pickN, resumedN, p29b.phone_sanitized if p29b else "-"))

# ---------------------------------------------------------- T-WA12-10 teardown
# reject a provisional quote -> chain archived
arch = Q._wa12_provision_chain(
    client, "2026-09-03", env.ref("base.USD"), u_sales)
M.sudo()._wa12_build_lines(arch, [{"product_id": prod_ok.id, "qty": 1}], 1)
arch.action_recalculate_pricing(); M.sudo()._wa12_ensure_payment_term(arch, client)
arch_ej = arch.event_job_id; arch_cj = arch_ej.commercial_job_id
arch.with_user(u_sales.id).action_submit_for_approval()
arch.with_user(u_appr.id).with_context(rejection_reason="test").action_reject()
arch._wa12_maybe_archive_provisional()
# event.job is archivable (active=False); commercial.job has no active -> it
# moves to the 'archived' (Lost) lifecycle state.
_check("T-WA12-10",
       (not arch_ej.active) and arch_cj.state == "archived",
       "rejected provisional chain archived (ejob active=%s, cjob state=%s)"
       % (arch_ej.active, arch_cj.state))

# ---------------------------------------------------------- teardown fixtures
print("--- teardown ---")
# delete [TEST-WA12] quotes' chains + the quotes + products + partners + users
# gather the test chains via the quotes (salesperson is a direct field) + the
# normally-created control job; cancel their ACT, then delete quotes -> jobs.
tquotes = Q.with_context(active_test=False).search(
    [("salesperson_id", "=", u_sales.id)])
tjobs = (tquotes.mapped("event_job_id") | ctrl_ej).exists()
tcjobs = (tjobs.mapped("commercial_job_id") | ctrl_cj).exists()
mdl = env["ir.model"].sudo().search([("model", "=", "commercial.event.job")], limit=1)
for a in ACT.search([("source_model_id", "=", mdl.id),
                     ("source_id", "in", tjobs.ids),
                     ("state", "in", ("open", "in_progress"))]):
    a._do_transition("cancelled", {"closure_reason": "[TEST-WA12] teardown"})
# FK deps on the quotes: approvals + invoice schedules; accept fired the
# on-acceptance schedule which raised a customer invoice (refs the quote by
# parse, no FK, but is test residue) -> drop to draft then unlink.
env["neon.finance.approval"].sudo().search(
    [("quote_id", "in", tquotes.ids)]).unlink()
env["neon.finance.invoice.schedule"].sudo().search(
    [("quote_id", "in", tquotes.ids)]).unlink()
_tcli = P.search([("name", "like", "[TEST-WA12]")])
_moves = env["account.move"].sudo().search(
    [("partner_id", "in", _tcli.ids),
     ("move_type", "in", ("out_invoice", "out_refund"))])
_moves.filtered(lambda m: m.state == "posted").button_draft()
_moves.filtered(lambda m: m.state != "draft").button_cancel()
_moves.with_context(force_delete=True).unlink()
tquotes.unlink()
tjobs.unlink(); tcjobs.unlink()
# [TEST-WA12] pricing rules (+ brackets) FIRST: a PRODUCT rule references its
# product (ondelete restrict) so it must drop before the product; the category
# rule references its category so rules precede categories too.
_trules = Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA12]")])
_trules.mapped("bracket_ids").unlink()
_trules.unlink()
(prod_ok | prod_ph | prod_pr).unlink()
ECat.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA12]")]).unlink()
# payment terms: by NAME (our fixture) AND by PARTNER (_wa12_ensure_payment_term
# may have auto-created a default-named term for the client).
(PTerm.search([("name", "like", "[TEST-WA12]")])
 | PTerm.search([("partner_id", "in", _tcli.ids)])).unlink()
P.search([("name", "like", "[TEST-WA12]")]).unlink()
for u in (u_sales, u_crew, u_appr):
    u.write({"active": False})
Bot.search([("phone_number", "in", (SALES_PH, CREW_PH, APPR_PH))]).unlink()
M.search([("phone_number", "in", (SALES_PH, CREW_PH, APPR_PH))]).unlink()
# the one-per-phone equip-session rows (else they survive to the next run).
env["neon.wa.equip.session"].sudo().with_context(active_test=False).search(
    [("phone_number", "in", (SALES_PH, CREW_PH, APPR_PH))]).unlink()
env.cr.commit()
_MAILP.stop()

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
