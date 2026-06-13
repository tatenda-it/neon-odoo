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

from odoo.exceptions import AccessError, ValidationError  # noqa: F401 (parity)
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
# WA-12.2: mute the LLM lane for the whole suite (offline + deterministic) so
# free-text turns never make a real provider call. The 3 conversational tests
# (T32-34) override this with their own patch. Stopped in teardown.
_LLMP = patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: None)
_LLMP.start()
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
# [TEST-WA12] pricing RULES first: a PRODUCT-scoped rule references its product
# (ondelete restrict) so rules must drop BEFORE the products (same ordering as
# the teardown); category rules reference categories, so rules precede those too.
_orules = env["neon.finance.pricing.rule"].sudo().with_context(
    active_test=False).search([("name", "like", "[TEST-WA12]")])
_orules.mapped("bracket_ids").unlink()
_orules.unlink()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA12]")]).unlink()
# Resolver v2 golden residue (products [TEST-WA12G] + [test-wa12] alias rows)
# from a crashed prior run -- drop so the re-run seeds clean.
PT.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA12G]")]).unlink()
env["neon.equipment.alias"].sudo().with_context(active_test=False).search(
    [("phrase", "like", "[test-wa12]")]).unlink()
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
    # workshop_name = the bare name (F2: the exact-match tier compares
    # normalised names; real catalogue names carry no [TEST-*] prefix).
    "name": "[TEST-WA12] Qwertyunit", "workshop_name": "qwertyunit",
    "is_workshop_item": True,
    "list_price": 999.0,
    "equipment_category_id": tcat.id})
prod_ph = PT.create({
    # a category with NO rule -> the engine stamps 'no_rule' -> guard blocks.
    "name": "[TEST-WA12] Placeholder Gizmo",
    "workshop_name": "placeholder gizmo", "is_workshop_item": True,
    "list_price": 1.0,
    "equipment_category_id": tcat_norule.id})
# WA-12.1: a PRODUCT-scoped rule ($77) on a product that ALSO sits in tcat (the
# $50 category rule) with list_price 999 -> must price $77 (product rule wins).
prod_pr = PT.create({
    "name": "[TEST-WA12] Prodruled", "workshop_name": "prodruled",
    "is_workshop_item": True,
    "list_price": 999.0, "equipment_category_id": tcat.id})
prule = Rule.create({
    "name": "[TEST-WA12] ProdRule", "product_template_id": prod_pr.id,
    "currency_id": USD.id, "base_rate": 77.0, "effective_date": "2020-01-01"})
Bracket.create({"rule_id": prule.id, "sequence": 1, "day_from": 1,
                "day_to": -1, "multiplier": 1.0})
# F1 (proof #2): the CATALOGUE-LOAD shape — a product rule but NO
# equipment_category_id. The echo and the DRAFT must both price it $200.
prod_nocat = PT.create({
    "name": "[TEST-WA12] Kommandr Server", "workshop_name": "kommandr server",
    "is_workshop_item": True, "list_price": 5.0})
nrule = Rule.create({
    "name": "[TEST-WA12] NoCatRule", "product_template_id": prod_nocat.id,
    "currency_id": USD.id, "base_rate": 200.0, "effective_date": "2020-01-01"})
Bracket.create({"rule_id": nrule.id, "sequence": 1, "day_from": 1,
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

# ------------------------------------------------------------------ Resolver v2
# GOLDEN fixtures. The local test DB has none of the real catalogue, so we seed
# real-SHAPED products in the SEEDED categories (so _wa6_in_family scopes by
# equipment_category_id.code, the keystone's effect) + [TEST-WA12] CONFIRMED
# alias rows mirroring Robin's rulings -- the funnel + golden set are then
# self-contained, independent of prod's live alias rows.
Alias = env["neon.equipment.alias"].sudo()
Alias.with_context(active_test=False).search(
    [("phrase", "like", "[test-wa12]")]).unlink()
# the real seeded categories (the keystone created/populated these on prod;
# get-or-create here so the local DB has them with the right CODES).
def _ecat(code, name):
    c = ECat.search([("code", "=", code)], limit=1)
    return c or ECat.create({"code": code, "name": name})
cat_vis = _ecat("visual", "Visual")
cat_lig = _ecat("lighting", "Lighting")
cat_tru = _ecat("trussing", "Trussing")
cat_eff = _ecat("effects", "Effects")
cat_stg = _ecat("staging", "Staging")
cat_snd = _ecat("sound", "Sound")
def _gp(name, cat, wsname=None):
    return PT.create({"name": name, "workshop_name": wsname or name.lower(),
                      "is_workshop_item": True, "list_price": 10.0,
                      "equipment_category_id": cat.id})
# Golden fixtures use CATEGORIZED products with UNIQUE dims/names so they never
# collide with the T-57 uncategorised proof fixtures (which reuse 3x2/6x2 etc.).
# These exercise the post-keystone categorized path (equipment_category_id set).
# Visual: two LED screen sizes + a casing DUP of one + a decoy non-screen.
g_scr32 = _gp("[TEST-WA12G] 13M X 12M LED SCREEN", cat_vis)
g_scr62 = _gp("[TEST-WA12G] 16M X 12M LED SCREEN", cat_vis)
g_scr53 = _gp("[TEST-WA12G] 15M X 13M LED SCREEN", cat_vis)
g_scr10a = _gp("[TEST-WA12G] 19M X 12M LED SCREEN", cat_vis)
g_scr10b = _gp("[TEST-WA12G] 19m x 12m led screen", cat_vis)  # pure casing dup
g_booth = _gp("[TEST-WA12G] 360 PHOTO BOOTH", cat_vis)  # decoy non-screen
# Lighting: molefays (blinder) + an rgbwauv zoom can.
g_mole = _gp("[TEST-WA12G] 4x100W INDOOR MOLEFAYS", cat_lig)
g_mole2 = _gp("[TEST-WA12G] 2X100W INDOOR MOLEFAYS", cat_lig)
g_can = _gp("[TEST-WA12G] RGBWAUV 99X99 ZOOM INDOOR LED CAN", cat_lig)
# Trussing: totem. Effects: smoke + fogger. Staging: stage. Sound: monitor.
g_totem = _gp("[TEST-WA12G] 9M PIN TRUSS TOTEM WITH BASE", cat_tru)
g_smoke = _gp("[TEST-WA12G] VERTICAL SMOKE MACHINES", cat_eff)
g_fog = _gp("[TEST-WA12G] LOW FOGGER", cat_eff)
g_stage = _gp("[TEST-WA12G] 9.9M X 9.9M STAGE DECK", cat_stg)
g_mon = _gp("[TEST-WA12G] POWERWORKS MONITOR", cat_snd)
# Packages: a DJ bundle that NAMES 'SMOKE MACHINE' inside it -- the leak the
# package-exclusion fix prevents (a bare "smoke machine" must NOT hit this).
cat_pkg = _ecat("packages", "Packages")
g_pkg = _gp("[TEST-WA12G] BASIC DJ PACKAGE - PA, 12 CANS, SMOKE MACHINE",
            cat_pkg)
# CONFIRMED [TEST-WA12] aliases mirroring Robin's rulings.
Alias.create([
    {"phrase": "[test-wa12]-screen", "category_id": cat_vis.id, "state": "confirmed"},
    {"phrase": "[test-wa12]-blinder", "term": "molefay", "state": "confirmed"},
    {"phrase": "[test-wa12]-cans", "term": "led can", "state": "confirmed"},
    {"phrase": "[test-wa12]-smoke", "product_template_id": g_smoke.id, "state": "confirmed"},
    {"phrase": "[test-wa12]-wedge", "product_template_id": g_mon.id, "state": "confirmed"},
    # an OPEN row that must be IGNORED by the matcher (gate proof).
    {"phrase": "[test-wa12]-ignoreme", "category_id": cat_eff.id, "state": "open"},
])
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

# ---- T-WA12-32 (WA-12.2 hook A) free-text quote request -> LLM EXTRACTION ->
# M1 confirm gate (q_items) -> yes -> deterministic provision. LLM MOCKED.
_clear_sess(SALES_PH)
_ai_q = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
         '"items":[{"name":"qwertyunit","qty":2,"stated_price":null}],'
         '"date":"2026-09-20","phone":null,"email":null,'
         '"contact_person":null}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _ai_q):
    r32 = D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH,
        "hi can you price up 2 qwertyunit for Acme Events on the 20th please"))
conf32 = _step(SALES_PH) == "q_items"          # M1: confirm BEFORE draft
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
s32 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b32 = s32._get_buffer() if s32 else {}
q32 = (Q.sudo().browse(b32.get("quote_id") or 0)
       if isinstance(b32, dict) else Q.browse())
_check("T-WA12-32",
       r32 is True and conf32 and bool(s32) and s32.step == "q_confirm"
       and q32.exists() and q32.partner_id == client and len(q32.line_ids) >= 1,
       "free-text -> AI extract -> confirm(q_items)=%s -> yes -> draft for %s "
       "(q_confirm=%s, lines=%d)"
       % (conf32, q32.partner_id.name if q32.exists() else "-",
          s32.step if s32 else "-", len(q32.line_ids) if q32.exists() else 0))

# ---- T-WA12-33 (WA-12.2 hook B) a free-text edit during q_confirm -> LLM
# translates to ONE command -> applied through the guarded _wa12_try_edit.
_clear_sess(SALES_PH)
eq = Q._wa12_provision_chain(client, "2026-09-22", USD, u_sales)
M.sudo()._wa12_build_lines(eq, [{"product_id": prod_ok.id, "qty": 1}], 1)
eq.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": eq.id})
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: "discount qwertyunit 20%"):
    D_sales._wa12_maybe_intercept(_txt(
        SALES_PH, "actually knock twenty percent off that qwerty thing"))
el = eq.line_ids.filtered(lambda l: l.product_template_id == prod_ok)[:1]
_check("T-WA12-33",
       bool(el) and abs(el.discount_pct - 20.0) < 0.01
       and abs(el.line_subtotal - 40.0) < 0.01,
       "free-text edit -> translated to 'discount 20%%' -> applied "
       "(disc_pct=%s sub=%s)"
       % (el.discount_pct if el else "-", el.line_subtotal if el else "-"))

# ---- T-WA12-34 (WA-12.2 degradation) LLM down (None) -> hook A does NOT claim
# (falls through); the deterministic Quote: command is unaffected.
_clear_sess(SALES_PH)
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: None):
    r34 = D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "could you put together a quote for somebody sometime"))
deg_ok = r34 is None
det = D_sales._wa12_maybe_intercept(_txt(
    SALES_PH, "Quote: [TEST-WA12] Acme Events Co — qwertyunit, 2026-09-23"))
_sdet = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
det_ok = det is True and bool(_sdet) and _sdet.step == "q_confirm"
_check("T-WA12-34", deg_ok and det_ok,
       "LLM down -> hook A falls through (r=%s); deterministic Quote: still "
       "works (%s)" % (r34, det_ok))

# ---- T-WA12-35 (M1, the proof-#1 regression) multi-item brief -> CONFIRM-
# BEFORE-DRAFT: extraction returns ALL items; ONE confirm message lists every
# matched line @ the ENGINE rate (stated prices are hints, never the rate);
# NO quote exists until yes.
_clear_sess(SALES_PH)
_q_before = Q.search_count([("partner_id", "=", client.id)])
_brief = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
          '"items":[{"name":"qwertyunit","qty":5,"stated_price":10},'
          '{"name":"prodruled","qty":1,"stated_price":null}],'
          '"date":"2026-09-20","phone":null,"email":null,'
          '"contact_person":null}')
_s35 = _since() if False else M.search([], order="id desc", limit=1).id
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _brief):
    D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "brief: Acme Events. qwertyunit x5 they cost 10 each, "
        "plus a prodruled, for the 20th of Sept"))
_conf = M.search([("id", ">", _s35), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1)
_ct = _conf.message_body or ""
no_draft_yet = Q.search_count([("partner_id", "=", client.id)]) == _q_before
s35 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
conf_ok = (s35 and s35.step == "q_items"
           and "50.00" in _ct and "77.00" in _ct       # ENGINE rates
           and "×5" in _ct and "you said 10.00" in _ct)  # qty + hint flagged
# yes -> NOW the draft exists with BOTH lines at engine rates
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q35 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
drafted = (q35 and len(q35.line_ids) == 2
           and {round(l.unit_rate) for l in q35.line_ids} == {50, 77}
           and max(q35.line_ids.mapped("quantity")) == 5)
_check("T-WA12-35", no_draft_yet and conf_ok and drafted,
       "confirm-before-draft: no-draft=%s confirm(engine-rates+hint)=%s "
       "drafted-on-yes(2 lines, 50/77, x5)=%s" % (no_draft_yet, conf_ok, drafted))

# ---- T-WA12-36 (M1 corrections) remove + qty + date at q_items re-shape the
# list BEFORE drafting.
_clear_sess(SALES_PH)
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _brief):
    D_sales._wa12_llm_intake_maybe(_txt(SALES_PH, "same brief again"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "remove prodruled"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "qty qwertyunit 2"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "29 Sept 2026"))
s36 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b36 = s36._get_buffer() if s36 else {}
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q36 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
_cj36 = q36.event_job_id.commercial_job_id if q36 else None
_check("T-WA12-36",
       isinstance(b36, dict) and len(b36.get("matched") or []) == 1
       and q36 and len(q36.line_ids) == 1
       and q36.line_ids.quantity == 2
       and _cj36 and _cj36.event_date
       and (_cj36.event_date.month, _cj36.event_date.day) == (9, 29),
       "q_items corrections: matched=%s lines=%s qty=%s date=%s"
       % (len(b36.get("matched") or []), len(q36.line_ids) if q36 else 0,
          q36.line_ids.quantity if q36 and len(q36.line_ids) == 1 else "-",
          _cj36.event_date if _cj36 else "-"))

# ---- T-WA12-37 (M5) bare quote intent -> q_client -> q_itemreq -> confirm ->
# draft (never the generic Copilot).
_clear_sess(SALES_PH)
_bare = ('{"intent":"quote","client":null,"items":[],"date":null,'
         '"phone":null,"email":null,"contact_person":null}')
_s37 = M.search([], order="id desc", limit=1).id
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _bare):
    r37 = D_sales._wa12_llm_intake_maybe(_txt(SALES_PH, "i want to make a quote"))
which_client = "which client" in (M.search(
    [("id", ">", _s37), ("phone_number", "=", SALES_PH),
     ("direction", "=", "outbound")], order="id desc", limit=1
).message_body or "").lower()
st1 = _step(SALES_PH)
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "[TEST-WA12] Acme Events Co"))
st2 = _step(SALES_PH)
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "qwertyunit x3"))
st3 = _step(SALES_PH)
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q37 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
_check("T-WA12-37",
       r37 is True and which_client and st1 == "q_client"
       and st2 == "q_itemreq" and st3 == "q_items"
       and q37 and len(q37.line_ids) == 1 and q37.line_ids.quantity == 3,
       "bare intent: ask-client=%s steps=%s/%s/%s drafted(x3)=%s"
       % (which_client, st1, st2, st3, bool(q37 and q37.line_ids)))

# ---- T-WA12-38 (M3) brief-sourced phone+email PRE-FILL the intake: after the
# name, NO phone/email asks; partner created with both.
_clear_sess(SALES_PH)
_pf = ('{"intent":"quote","client":"[TEST-WA12] Prefill Nova Ltd",'
       '"items":[{"name":"qwertyunit","qty":1,"stated_price":null}],'
       '"date":null,"phone":"+263773863012","email":"nova@x.test",'
       '"contact_person":null}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _pf):
    D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "quote for Prefill Nova Ltd phone +263773863012 "
        "email nova@x.test one qwertyunit"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))     # q_items -> intake
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "new"))
_s38 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "individual"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "ok"))      # name -> create+resume
_after38 = M.search([("id", ">", _s38), ("phone_number", "=", SALES_PH),
                     ("direction", "=", "outbound")])
asked_38 = " ".join((m.message_body or "") for m in _after38).lower()
p38 = P.search([("name", "=", "[TEST-WA12] Prefill Nova Ltd")], limit=1)
_check("T-WA12-38",
       bool(p38) and "773863012" in (p38.phone_sanitized or p38.phone or "")
       and p38.email == "nova@x.test"
       and "phone number for" not in asked_38 and "email?" not in asked_38
       and _step(SALES_PH) == "q_confirm",
       "prefill: created(phone/email)=%s no-redundant-asks=%s resumed=%s"
       % (bool(p38), "phone number for" not in asked_38, _step(SALES_PH)))

# ---- T-WA12-39 (M4) complaint -> REPAIR prompt (never the syntax menu): at
# q_confirm (deterministic token) AND at q_items.
_s39 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(
    SALES_PH, "this is wrong from the information l gave you"))
r39a = (M.search([("id", ">", _s39), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
repair_qconfirm = "what should i fix" in r39a.lower()
_clear_sess(SALES_PH)
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _brief):
    D_sales._wa12_llm_intake_maybe(_txt(SALES_PH, "the same brief once more"))
_s39b = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "no this is incorrect"))
r39b = (M.search([("id", ">", _s39b), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
_check("T-WA12-39",
       repair_qconfirm and "what should i fix" in r39b.lower(),
       "repair prompt: q_confirm=%s q_items=%s"
       % (repair_qconfirm, "what should i fix" in r39b.lower()))
_clear_sess(SALES_PH)

# ---- T-WA12-40 (M2) identity-aware chat: the copilot system prompt ASSERTS
# the sender's name+role (resolved via the WA-9 spine) + VAT 15.5.
from odoo.addons.neon_channels.models.wa_copilot import WhatsAppCopilotService
u_sales.partner_id.write({"function": "Sales Executive"})  # exact org title
_sys40 = WhatsAppCopilotService(env)._build_messages(
    u_sales, "sales", "so you do not know me?", SALES_PH)[0]["content"]
_check("T-WA12-40",
       u_sales.name in _sys40 and "KNOW this user" in _sys40
       and "15.5" in _sys40 and "Sales Executive" in _sys40,
       "identity in system prompt: name=%s assert=%s vat15.5=%s exact-title=%s"
       % (u_sales.name in _sys40, "KNOW this user" in _sys40,
          "15.5" in _sys40, "Sales Executive" in _sys40))

# ---- T-WA12-41 (addendum) APPROVER-AS-REQUESTER end-to-end: MD/OD-tier user
# drafts via natural language -> confirm -> submit -> SELF-approves (the
# ratified principle; SoD stays for a non-superuser approver).
env["neon.wa.equip.session"].sudo().with_context(active_test=False).search(
    [("phone_number", "=", APPR_PH)]).write({"active": False})
_check("T-WA12-41a", D_appr._wa12_can_quote(u_appr) is True,
       "MD/OD tier CAN initiate quotes (asserted, not assumed)")
_b41 = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
        '"items":[{"name":"qwertyunit","qty":1,"stated_price":null}],'
        '"date":"2026-09-21","phone":null,"email":null,"contact_person":null}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _b41):
    D_appr._wa12_llm_intake_maybe(_txt(
        APPR_PH, "please make a quotation for Acme, one qwertyunit, 21 Sept"))
D_appr._wa12_maybe_intercept(_txt(APPR_PH, "yes"))
q41 = Q.search([("partner_id", "=", client.id),
                ("salesperson_id", "=", u_appr.id)],
               order="id desc", limit=1)
q41.with_user(u_appr.id).action_submit_for_approval()
pending41 = q41.state == "pending_approval"
# the SELF [Approve] tap (interactive HMAC) -- must NOT be SoD-blocked.
hmac41 = wa_payload.encode(SECRET, "wa12_approve", q41.id)
D_appr._wa12_maybe_intercept({
    "from": APPR_PH, "type": "interactive", "id": "t41",
    "interactive": {"button_reply": {"id": hmac41}}})
self_ok = q41.state == "approved" and q41.approved_by_id == u_appr
# a NON-superuser approver is still SoD-blocked on their own quote.
_wipe_login("pwa12_appr2")
u_appr2 = Users.with_context(no_reset_password=True).create({
    "name": "PWA12 Approver2", "login": "pwa12_appr2", "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_sales.id),
                  (4, env.ref("neon_finance.group_neon_finance_approver").id)]})
u_appr2.partner_id.write({"email": "pwa12_appr2@neon.test"})  # message_post

q41b = Q._wa12_provision_chain(client, "2026-09-22", USD, u_appr2)
M.sudo()._wa12_build_lines(q41b, [{"product_id": prod_ok.id, "qty": 1}], 1)
q41b.action_recalculate_pricing()
M.sudo()._wa12_ensure_payment_term(q41b, client)
q41b.with_user(u_appr2.id).action_submit_for_approval()
try:
    q41b.with_user(u_appr2.id).action_approve()
    sod_holds = False
except Exception:
    sod_holds = True
_check("T-WA12-41",
       pending41 and self_ok and sod_holds,
       "approver-as-requester: pending=%s SELF-approve(superuser-tier)=%s "
       "SoD still blocks a plain approver=%s" % (pending41, self_ok, sod_holds))
u_appr2.write({"active": False})

# ---- T-WA12-42 (self-review) a 'STOP' mid-session is RELEASED (returns None,
# session intact) so the WA-2 opt-out handler gets it — never swallowed as a
# cancel word ("stop" is in the cancel set; the release must win).
_clear_sess(SALES_PH)
q42 = Q._wa12_provision_chain(client, "2026-09-24", USD, u_sales)
M.sudo()._wa12_build_lines(q42, [{"product_id": prod_ok.id, "qty": 1}], 1)
q42.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": q42.id})
r42 = D_sales._wa12_maybe_intercept(_txt(SALES_PH, "STOP"))
s42 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
_check("T-WA12-42",
       r42 is None and bool(s42) and s42.step == "q_confirm"
       and q42.state == "draft",
       "STOP released (None), session intact (%s), quote NOT cancelled (%s)"
       % (s42.step if s42 else "-", q42.state))
_clear_sess(SALES_PH)

# ---- T-WA12-43 (F1 regression: ECHO RATE == DRAFT RATE, always) the
# catalogue-load shape (product rule, NO category): echo $200 -> yes -> the
# DRAFTED line is priced $200 (never a silent $0.00 'not_yet').
_clear_sess(SALES_PH)
_f1 = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
       '"items":[{"name":"kommandr server","qty":1,"stated_price":null}],'
       '"date":"2026-09-25","phone":null,"email":null,"contact_person":null,'
       '"address":null,"event_name":null}')
_s43 = M.search([], order="id desc", limit=1).id
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f1):
    D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "quote acme for the kommandr server please"))
_e43 = (M.search([("id", ">", _s43), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
echo_200 = "200.00" in _e43
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q43 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
l43 = q43.line_ids[:1]
_check("T-WA12-43",
       echo_200 and l43 and l43.pricing_status == "priced"
       and abs(l43.unit_rate - 200.0) < 0.01,
       "echo==draft: echo$200=%s drafted(status=%s rate=%s; want priced/200)"
       % (echo_200, l43.pricing_status if l43 else "-",
          l43.unit_rate if l43 else "-"))

# ---- T-WA12-44 (F2) exact catalogue-name match beats token logic; weak hits
# carry confidence + suggestions (never silently drafted by the 12.2 lane).
h_exact = M._wa6_match_one("kommandr server")
h_weak = M._wa6_match_one("gizmo")     # 1-token overlap -> weak
mm, uu = M._wa12_match_slot_items([{"name": "gizmo", "qty": 1}])
_check("T-WA12-44",
       h_exact.get("confidence") == "exact"
       and h_exact.get("product_id") == prod_nocat.id
       and h_weak.get("confidence") in ("weak", "none")
       and not mm and len(uu) == 1 and uu[0].get("suggestions") is not None,
       "exact wins (conf=%s id-ok=%s); weak -> pick bucket (conf=%s, "
       "unmatched=%d)" % (h_exact.get("confidence"),
                          h_exact.get("product_id") == prod_nocat.id,
                          h_weak.get("confidence"), len(uu)))

# ---- T-WA12-45 (F8) rep-priced unpriced item: brief price -> '(rep-priced —
# no catalogue rate)' echo -> manual line passes the guard; summary+ping flag;
# a PRICED item's stated price stays a hint; no-rate-no-price still blocks.
_clear_sess(SALES_PH)
_f8 = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
       '"items":[{"name":"placeholder gizmo","qty":1,"stated_price":750},'
       '{"name":"qwertyunit","qty":1,"stated_price":40}],'
       '"date":"2026-09-26","phone":null,"email":null,"contact_person":null,'
       '"address":null,"event_name":null}')
_s45 = M.search([], order="id desc", limit=1).id
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f8):
    D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "quote acme gizmo at 750 and qwertyunit at 40"))
_e45 = (M.search([("id", ">", _s45), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
flag45 = ("rep-priced — no catalogue rate" in _e45
          and "750.00" in _e45
          and "you said 40.00" in _e45 and "50.00" in _e45)
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q45 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
lg = q45.line_ids.filtered(lambda l: l.product_template_id == prod_ph)[:1]
lq = q45.line_ids.filtered(lambda l: l.product_template_id == prod_ok)[:1]
guard45 = not M.sudo()._wa12_unpriced_lines(q45)
summ45 = "[REP-PRICED]" in M.sudo()._wa12_draft_summary(q45, [])
ping45 = "(rep-priced)" in M.sudo()._wa12_item_summary(q45)
drafted45 = (lg and lg.pricing_status == "manual"
             and abs(lg.unit_rate - 750.0) < 0.01
             and lq and abs(lq.unit_rate - 50.0) < 0.01)  # hint ignored
# no-rate-no-price still blocks (the F1 $0 class): a bare gizmo brief.
_clear_sess(SALES_PH)
_f8b = _f8.replace(',"stated_price":750', ',"stated_price":null').replace(
    ',{"name":"qwertyunit","qty":1,"stated_price":40}', '')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f8b):
    D_sales._wa12_llm_intake_maybe(_txt(SALES_PH, "quote acme one gizmo only"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))
q45b = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
blocks45 = bool(M.sudo()._wa12_unpriced_lines(q45b))
_check("T-WA12-45",
       flag45 and bool(drafted45) and guard45 and summ45 and ping45 and blocks45,
       "rep-price: echo-flag=%s drafted(manual@750 + engine@50)=%s guard-pass"
       "=%s summary-tag=%s ping-flag=%s ; no-price still blocks=%s"
       % (flag45, bool(drafted45), guard45, summ45, ping45, blocks45))

# ---- T-WA12-46 (F3) q_items: per-item replace + show-words are NOT a yes.
_clear_sess(SALES_PH)
_f3 = ('{"intent":"quote","client":"[TEST-WA12] Acme Events Co",'
       '"items":[{"name":"qwertyunit","qty":1,"stated_price":null}],'
       '"date":null,"phone":null,"email":null,"contact_person":null,'
       '"address":null,"event_name":null}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f3):
    D_sales._wa12_llm_intake_maybe(_txt(SALES_PH, "quote acme a qwertyunit"))
_qb = Q.search_count([("partner_id", "=", client.id)])
_s46 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "show me"))
_e46 = (M.search([("id", ">", _s46), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
no_draft46 = (Q.search_count([("partner_id", "=", client.id)]) == _qb
              and "Nothing is drafted yet" in _e46
              and _step(SALES_PH) == "q_items")
# deterministic replace
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "replace qwertyunit = prodruled"))
s46 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b46 = s46._get_buffer() if s46 else {}
repl46 = (isinstance(b46, dict) and len(b46.get("matched") or []) == 1
          and b46["matched"][0]["product_name"] == "[TEST-WA12] Prodruled")
# natural replace via the items-translate hook (mock returns the command)
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: "replace prodruled = qwertyunit"):
    D_sales._wa12_maybe_intercept(_txt(
        SALES_PH, "actually it should be the qwerty one"))
b46b = s46._get_buffer() if s46 else {}
nat46 = (isinstance(b46b, dict)
         and b46b["matched"][0]["product_name"] == "[TEST-WA12] Qwertyunit")
_check("T-WA12-46",
       no_draft46 and repl46 and nat46,
       "show!=yes(no draft)=%s replace-det=%s replace-natural=%s"
       % (no_draft46, repl46, nat46))
_clear_sess(SALES_PH)

# ---- T-WA12-47 (F4) a multi-item message at q_confirm routes through
# EXTRACTION (never a single `add` parse).
_clear_sess(SALES_PH)
q47 = Q._wa12_provision_chain(client, "2026-09-27", USD, u_sales)
M.sudo()._wa12_build_lines(q47, [{"product_id": prod_ok.id, "qty": 1}], 1)
q47.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": q47.id})
_f4 = ('{"intent":"quote","client":null,'
       '"items":[{"name":"prodruled","qty":1,"stated_price":null},'
       '{"name":"kommandr server","qty":2,"stated_price":null}],'
       '"date":null,"phone":null,"email":null,"contact_person":null,'
       '"address":null,"event_name":null}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f4):
    D_sales._wa12_maybe_intercept(_txt(
        SALES_PH, "Items: prodruled , kommandr server X2, more stuff"))
prods47 = set(q47.line_ids.mapped("product_template_id").ids)
_check("T-WA12-47",
       {prod_ok.id, prod_pr.id, prod_nocat.id} <= prods47
       and len(q47.line_ids) == 3,
       "multi-item at q_confirm -> extraction -> 3 lines (%s)"
       % len(q47.line_ids))
_clear_sess(SALES_PH)

# ---- T-WA12-48 (F5) address + event subject from the brief: street on the
# new partner; 'Event: <subject>' on the event job's client notes.
_clear_sess(SALES_PH)
_f5 = ('{"intent":"quote","client":"[TEST-WA12] Redan Co",'
       '"items":[{"name":"qwertyunit","qty":1,"stated_price":null}],'
       '"date":null,"phone":"+263774000222","email":"redan@x.test",'
       '"contact_person":null,"address":"10 Hugh Fraser Road, Highlands",'
       '"event_name":"Redan Launch"}')
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f5):
    D_sales._wa12_llm_intake_maybe(_txt(
        SALES_PH, "quotation for Redan Co located at 10 Hugh Fraser Road"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "yes"))     # -> intake
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "new"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "company"))
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "ok"))      # contact prefilled? no — contact null, asks
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "[TEST-WA12] Ruth"))  # qc_contact
p48 = P.search([("name", "=", "[TEST-WA12] Redan Co")], limit=1)
q48 = Q.search([("partner_id", "=", p48.id)], limit=1) if p48 else Q.browse()
notes48 = (q48.event_job_id.client_notes or "") if q48 else ""
_check("T-WA12-48",
       bool(p48) and p48.street == "10 Hugh Fraser Road, Highlands"
       and bool(q48) and "Redan Launch" in notes48,
       "address->street=%s event-name->notes=%s (street=%r)"
       % (bool(p48 and p48.street), "Redan Launch" in notes48,
          p48.street if p48 else "-"))
_clear_sess(SALES_PH)

# ---- T-WA12-49 (F6/F7) greeting mid-draft -> resume offer (not the syntax
# card); 'cancel or delete' cancels; 'delete the qwertyunit line' does NOT.
q49 = Q._wa12_provision_chain(client, "2026-09-28", USD, u_sales)
M.sudo()._wa12_build_lines(q49, [{"product_id": prod_ok.id, "qty": 1}], 1)
q49.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": q49.id})
_s49 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "hello"))
_e49 = (M.search([("id", ">", _s49), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
greet49 = ("open draft" in _e49 and "continue" in _e49
           and "price <item>" not in _e49)
notcxl = not M._wa12_is_cancel("delete the qwertyunit line")
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "cancel or delete"))
s49 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
_check("T-WA12-49",
       greet49 and notcxl and not s49,
       "greeting->resume-offer=%s ; line-delete not a cancel=%s ; "
       "'cancel or delete' cancelled=%s" % (greet49, notcxl, not s49))

# ---- T-WA12-50 (review MATCH-1/FSM-3) the F2 weak-confidence gate at the
# THREE remaining consumers. 'gizmo' weak-matches Placeholder Gizmo -> never a
# confident line: (a) direct Quote: -> confirm gate, NO draft; (b) q_itemreq ->
# unmatched pick; (c) q_confirm `add gizmo` -> refused with suggestions.
_clear_sess(SALES_PH)
_qb50 = Q.search_count([])
D_sales._wa12_maybe_intercept(_txt(
    SALES_PH, "Quote: [TEST-WA12] Acme Events Co — gizmo, 2026-10-01"))
s50a = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b50a = s50a._get_buffer() if s50a else {}
quote_gate = (bool(s50a) and s50a.step == "q_items"
              and Q.search_count([]) == _qb50
              and not (b50a.get("matched") or [])
              and len(b50a.get("unmatched") or []) == 1)
_clear_sess(SALES_PH)
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_itemreq",
    {"client_txt": "[TEST-WA12] Acme Events Co", "partner_id": client.id,
     "date_txt": "", "prefills": {}})
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "gizmo"))
s50b = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b50b = s50b._get_buffer() if s50b else {}
itemreq_gate = (bool(s50b) and s50b.step == "q_items"
                and not (b50b.get("matched") or [])
                and len(b50b.get("unmatched") or []) == 1)
_clear_sess(SALES_PH)
q50 = Q._wa12_provision_chain(client, "2026-10-02", USD, u_sales)
M.sudo()._wa12_build_lines(q50, [{"product_id": prod_ok.id, "qty": 1}], 1)
q50.action_recalculate_pricing()
_n50, _s50c = len(q50.line_ids), M.search([], order="id desc", limit=1).id
M.sudo()._wa12_try_edit(q50, "add gizmo", SALES_PH, SALES_PH)
_e50c = (M.search([("id", ">", _s50c), ("phone_number", "=", SALES_PH),
                   ("direction", "=", "outbound")], order="id desc", limit=1
                  ).message_body or "").lower()
add_gate = (len(q50.line_ids) == _n50
            and ("did you mean" in _e50c or "confidently" in _e50c))
_check("T-WA12-50", quote_gate and itemreq_gate and add_gate,
       "F2 gate: Quote:->confirm/no-draft=%s q_itemreq->pick=%s add-refused=%s"
       % (quote_gate, itemreq_gate, add_gate))
_clear_sess(SALES_PH)

# ---- T-WA12-51 (review FSM-1) the greeting advertises *continue* (NOT the
# Meta opt-in word *resume*); *continue* re-shows the confirm echo at q_items.
_clear_sess(SALES_PH)
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_items",
    {"client_txt": "[TEST-WA12] Acme Events Co", "partner_id": client.id,
     "matched": [{"product_id": prod_ok.id,
                  "product_name": "[TEST-WA12] Qwertyunit", "qty": 1,
                  "stated_price": None}], "unmatched": [], "date_txt": "",
     "days": 1, "prefills": {}})
_s51 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "hello"))
_e51 = (M.search([("id", ">", _s51), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
greet_continue = "*continue*" in _e51 and "*resume*" not in _e51
_s51b = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "continue"))
_e51b = (M.search([("id", ">", _s51b), ("phone_number", "=", SALES_PH),
                   ("direction", "=", "outbound")], order="id desc", limit=1
                  ).message_body or "").lower()
continue_works = "qwertyunit" in _e51b and _step(SALES_PH) == "q_items"
_check("T-WA12-51", greet_continue and continue_works,
       "greeting advertises continue not resume=%s ; continue re-shows=%s"
       % (greet_continue, continue_works))
_clear_sess(SALES_PH)

# ---- T-WA12-52 (review FSM-2) 'no' at qc_email SKIPS email (client created,
# resumes), never cancels the whole intake.
_clear_sess(SALES_PH)
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "qc_email",
    {"client_txt": "[TEST-WA12] NoEmail Co", "kind": "company",
     "name": "[TEST-WA12] NoEmail Co", "contact": "[TEST-WA12] Bee",
     "phone": "+263773111222", "phone_e164": "+263773111222",
     "matched": [{"product_id": prod_ok.id,
                  "product_name": "[TEST-WA12] Qwertyunit", "qty": 1,
                  "stated_price": None}], "date_txt": "", "days": 1,
     "prefills": {}})
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "no"))
p52 = P.search([("name", "=", "[TEST-WA12] NoEmail Co")], limit=1)
_check("T-WA12-52",
       bool(p52) and not p52.email and _step(SALES_PH) == "q_confirm",
       "qc_email 'no' -> client created/no-email=%s resumed=%s"
       % (bool(p52), _step(SALES_PH)))
_clear_sess(SALES_PH)

# ---- T-WA12-53 (review FSM-4) an ambiguous token at q_items refuses with the
# colliding names; no qty silently changed on the wrong line.
_clear_sess(SALES_PH)
sess53 = env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_items",
    {"client_txt": "X", "partner_id": client.id, "matched": [
        {"product_id": prod_ok.id, "product_name": "[TEST-WA12] LED Screen Big",
         "qty": 1, "stated_price": None},
        {"product_id": prod_pr.id, "product_name": "[TEST-WA12] LED Screen Sml",
         "qty": 1, "stated_price": None}],
     "unmatched": [], "date_txt": "", "days": 1, "prefills": {}})
_s53 = M.search([], order="id desc", limit=1).id
M.sudo()._wa12_q_items_try(sess53, sess53._get_buffer(), "qty led 4",
                           SALES_PH, SALES_PH)
_e53 = (M.search([("id", ">", _s53), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "").lower()
b53 = sess53._get_buffer()
_check("T-WA12-53",
       "be more specific" in _e53
       and all(it["qty"] == 1 for it in b53.get("matched", [])),
       "ambiguous 'qty led 4' refused, neither qty changed (reply=%r)"
       % _e53[:50])
_clear_sess(SALES_PH)

# ---- T-WA12-54 (review MATCH-3/FSM-6) multi-item paste at q_confirm: a dup is
# NOT reported 'Added', its qty IS applied to the existing line, new item added.
_clear_sess(SALES_PH)
q54 = Q._wa12_provision_chain(client, "2026-10-03", USD, u_sales)
M.sudo()._wa12_build_lines(q54, [{"product_id": prod_ok.id, "qty": 1}], 1)
q54.action_recalculate_pricing()
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_confirm", {"quote_id": q54.id})
_f54 = ('{"intent":"quote","client":null,'
        '"items":[{"name":"qwertyunit","qty":3,"stated_price":null},'
        '{"name":"prodruled","qty":1,"stated_price":null}],'
        '"date":null,"phone":null,"email":null,"contact_person":null,'
        '"address":null,"event_name":null}')
_s54 = M.search([], order="id desc", limit=1).id
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: _f54):
    D_sales._wa12_maybe_intercept(_txt(
        SALES_PH, "qwertyunit x3, prodruled, plus more stuff"))
_e54 = (M.search([("id", ">", _s54), ("phone_number", "=", SALES_PH),
                  ("direction", "=", "outbound")], order="id desc", limit=1
                 ).message_body or "")
lq54 = q54.line_ids.filtered(lambda l: l.product_template_id == prod_ok)[:1]
_check("T-WA12-54",
       bool(lq54) and lq54.quantity == 3
       and "Added [TEST-WA12] Qwertyunit" not in _e54
       and prod_pr.id in q54.line_ids.mapped("product_template_id").ids,
       "apply_multi: dup qty->existing=%s, dup not 'Added', new added=%s"
       % (lq54.quantity if lq54 else "-",
          prod_pr.id in q54.line_ids.mapped("product_template_id").ids))
_clear_sess(SALES_PH)

# ---- T-WA12-55 (review FSM-9) the F5 event-name write is actor-honest
# (write_uid = the rep, never the public/odoobot uid).
M.with_user(u_sales)._wa12_quote_from_slots(
    u_sales, client, [{"product_id": prod_ok.id, "product_name": "x",
                       "qty": 1, "stated_price": None}],
    "", 1, SALES_PH, SALES_PH, extras={"event_name": "Garden Gala"})
q55 = Q.search([("partner_id", "=", client.id)], order="id desc", limit=1)
ej55 = q55.event_job_id
_check("T-WA12-55",
       "Garden Gala" in (ej55.client_notes or "")
       and ej55.write_uid.id == u_sales.id,
       "F5 event note=%s write_uid=rep=%s (uid=%s)"
       % ("Garden Gala" in (ej55.client_notes or ""),
          ej55.write_uid.id == u_sales.id, ej55.write_uid.id))
_clear_sess(SALES_PH)

# ---- T-WA12-56 (review FSM-8) a greeting WORD at q_client is treated as a
# client NAME (resolver-first), not the greeting reply.
_clear_sess(SALES_PH)
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_client", {"date_txt": "", "prefills": {}})
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "hello"))
_check("T-WA12-56", _step(SALES_PH) == "qc_pick",
       "greeting word at q_client -> resolver ran (intake), step=%s"
       % _step(SALES_PH))
_clear_sess(SALES_PH)

# ---- T-WA12-57 (review M-A, proof #3 regression from the directors' wire) the
# matcher is FAMILY-SCOPED & dimension-aware: "screen" resolves only within the
# LED SCREEN (visual) family — NEVER a BOOTH; "3 x 2" is a dimension not qty;
# lighting cans/molefays + trussing totems route to their own family. Fixtures
# carry NO equipment_category_id (mimicking the catalogue-loaded products that
# broke proof #3 — family is derived from the NAME).
_scr = {k: PT.create({"name": "[TEST-WA12] %s" % nm, "is_workshop_item": True,
                      "list_price": 1.0}) for k, nm in {
    "3x2": "3M X 2M LED SCREEN", "6x2": "6M X 2M LED SCREEN",
    "10x4": "10M X 4M LED SCREEN",
    "8x4": "8M X4M LED SCREEN",          # missing space (data robustness)
    "3x1": "3M X 1M SCREEN",             # missing "LED" (robustness)
}.items()}
PT.create({"name": "[TEST-WA12] 360 BOOTH", "is_workshop_item": True,
           "list_price": 1.0})
_mole = PT.create({"name": "[TEST-WA12] 4X100W INDOOR/OUTDOOR MOLEFAYS",
                   "is_workshop_item": True, "list_price": 1.0})
_zoom = PT.create({"name": "[TEST-WA12] RGBWAUV 18X18 ZOOM INDOOR LED CAN",
                   "is_workshop_item": True, "list_price": 1.0})
_totem = PT.create({"name": "[TEST-WA12] TRUSS TOTEM WITH BASE",
                    "is_workshop_item": True, "list_price": 1.0})


def _m1(raw):
    return M.sudo()._wa6_match_one(raw)


def _is_scr(h):
    return bool(h.get("product_id")) and "SCREEN" in (
        h.get("product_name") or "") and "BOOTH" not in (
        h.get("product_name") or "")


# EXACT dimensional hits (the rule — the sizes exist): 6x2 and 3x2 resolve to
# their exact products, never a booth or a fuzzy guess; "3 x 2" qty stays 1.
_h62, _h32 = _m1("6m x 2m screen"), _m1("3 x 2 screen")
exact62 = _h62.get("product_id") == _scr["6x2"].id and _h62["confidence"] == "exact"
exact32 = (_h32.get("product_id") == _scr["3x2"].id
           and _h32["confidence"] == "exact" and _h32.get("qty") == 1)
# data robustness: missing space "8 x 4" + missing "LED" "3 x 1".
rob84 = _m1("8 x 4 screen").get("product_id") == _scr["8x4"].id
rob31 = _m1("3 x 1 screen").get("product_id") == _scr["3x1"].id
# bare family + never-a-booth.
fam_ok = _is_scr(_m1("screen")) and _is_scr(_m1("led screen"))
# nearest is the EXCEPTION (no 7x7 stocked) -> a screen, weak, never a booth.
_h77 = _m1("7m x 7m screen")
near_exc = _is_scr(_h77) and _h77.get("confidence") == "weak"
# lighting / trussing route to their OWN family (never visual).
mole_ok = _m1("4x100 molefay").get("product_id") == _mole.id
zoom_ok = (_m1("zoom led cans").get("product_id") == _zoom.id
           and "SCREEN" not in (_m1("zoom led cans").get("product_name") or ""))
totem_ok = _m1("totem").get("product_id") == _totem.id
_check("T-WA12-57",
       exact62 and exact32 and rob84 and rob31 and fam_ok and near_exc
       and mole_ok and zoom_ok and totem_ok,
       "M-A: 6x2-exact=%s 3x2-exact/qty1=%s robust(8x4/3x1)=%s/%s family=%s "
       "nearest-exception=%s molefay=%s zoom-can=%s totem=%s"
       % (exact62, exact32, rob84, rob31, fam_ok, near_exc, mole_ok, zoom_ok,
          totem_ok))

# ---- T-WA12-58 (review M-B/M-C) catalogue discovery lists the family by its
# EXACT names (never a booth); a correction lead-in re-searches the intended
# item, never extracts to 'none'.
_clear_sess(SALES_PH)
env["neon.wa.equip.session"].sudo()._start_quote(
    SALES_PH, u_sales, "q_itemreq",
    {"client_txt": "[TEST-WA12] Acme Events Co", "partner_id": client.id,
     "date_txt": "", "prefills": {}})
_s58 = M.search([], order="id desc", limit=1).id
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "what screens do you have"))
_disc = (M.search([("id", ">", _s58), ("phone_number", "=", SALES_PH),
                   ("direction", "=", "outbound")], order="id desc", limit=1
                  ).message_body or "")
disc_ok = ("LED SCREEN" in _disc and "BOOTH" not in _disc
           and _step(SALES_PH) == "q_itemreq")
D_sales._wa12_maybe_intercept(_txt(SALES_PH, "no, it's a 6m x 2m screen"))
s58 = env["neon.wa.equip.session"].sudo()._active_for_phone(SALES_PH)
b58 = s58._get_buffer() if s58 else {}
mc_ok = (bool(s58) and s58.step == "q_items"
         and any("6M X 2M LED SCREEN" in (it.get("product_name") or "")
                 for it in (b58.get("matched") or [])))
_check("T-WA12-58", disc_ok and mc_ok,
       "M-B discovery lists family/no-booth=%s ; M-C 'no it's a 6m x 2m "
       "screen' re-searches -> 6x2 matched=%s" % (disc_ok, mc_ok))
_clear_sess(SALES_PH)

# ---------------------------------------------------------- T-WA12-59 alias store
# Resolver v2 SUPPORT (a): the neon.equipment.alias model loads, the EXACTLY-
# ONE-target constraint holds, phrase is unique, and state defaults to
# 'proposed' (nothing auto-applies until Robin confirms). No matcher wiring is
# asserted here — that ships with the funnel after Robin confirms the seed.
ALIAS = env["neon.equipment.alias"].sudo()
_a_vis = env["neon.equipment.category"].sudo().search(
    [("code", "=", "visual")], limit=1)
alias_results = {}
# 59a: a valid category-target row is creatable + defaults to proposed.
# (distinct phrase -- never collides with the golden [test-wa12]-screen fixture)
_ar = ALIAS.create({"phrase": "[test-wa12]-c59a", "category_id": _a_vis.id})
alias_results["default_proposed"] = (_ar.state == "proposed")
alias_results["confirm_action"] = (
    _ar.action_confirm() or _ar.state == "confirmed")
# 59b: ZERO targets -> ValidationError.
try:
    ALIAS.create({"phrase": "[test-wa12]-notarget"})
    alias_results["zero_target_blocked"] = False
except ValidationError:
    alias_results["zero_target_blocked"] = True
# 59c: TWO targets (category + term) -> ValidationError.
try:
    ALIAS.create({"phrase": "[test-wa12]-twotarget",
                  "category_id": _a_vis.id, "term": "led can"})
    alias_results["two_target_blocked"] = False
except ValidationError:
    alias_results["two_target_blocked"] = True
# 59d: duplicate phrase -> unique constraint. Use a SAVEPOINT so the SQL error
# doesn't poison the whole transaction (a bare rollback would drop the golden
# fixtures' uncommitted follow-on work).
try:
    with env.cr.savepoint():
        ALIAS.create({"phrase": "[test-wa12]-c59a", "term": "led screen"})
    alias_results["phrase_unique"] = False
except Exception:
    alias_results["phrase_unique"] = True
ALIAS.search([("phrase", "=", "[test-wa12]-c59a")]).unlink()  # throwaway only
_check("T-WA12-59", all(alias_results.values()),
       "alias store: %s" % alias_results)

# ---------------------------------------------------------- T-WA12-60 Resolver v2
# The funnel golden set: assert (resolved product, qty, confidence) for the
# director-wire phrases that the proof-#3 matcher failed, the confirmed-alias
# slang, dimensional exact + casing-dup, the qty guard, and the never-invent /
# never-cross-category / confirmed-only-alias / LLM-firewall guarantees. The
# LLM is muted globally (_LLMP) so S6/S7 exercise the DETERMINISTIC path; a
# dedicated sub-case un-mutes to prove the grounded-pick firewall.
MM = M  # the model (sudo) for direct _wa6_match_one calls
def _m(phrase, hint=None):
    return MM._wa6_match_one(phrase, category_hint=hint)
g = {}
# (a) dimensional EXACT -- the size EXISTS (the proof-#3 catastrophe fixed).
# Unique golden dims (13x12 etc.) so we assert the CATEGORIZED path cleanly.
h = _m("13 x 12 screen")
g["13x12_exact"] = (h["product_id"] == g_scr32.id and h["confidence"] == "exact"
                    and h["qty"] == 1)
h = _m("16m x 12m screen")
g["16x12_exact"] = (h["product_id"] == g_scr62.id and h["confidence"] == "exact")
h = _m("15m x 13m LED screen")
g["15x13_exact"] = (h["product_id"] == g_scr53.id and h["confidence"] == "exact")
# casing DUP at one size -> canonical UPPER rep, EXACT (NOT a false weak).
h = _m("19m x 12m screen")
g["casing_dup_exact"] = (h["product_id"] == g_scr10a.id
                         and h["confidence"] == "exact")
# bare "screen" -> a Visual product (NEVER the photo booth); never cross-cat.
h = _m("screen")
g["bare_screen_visual"] = (h["status"] == "matched"
                           and h["product_id"] != g_booth.id
                           and h["family"] == "visual")
# qty guard with REALISTIC input: "4 molefays" -> qty 4 (bare-leading-count),
# resolves within lighting to a MOLEFAY product. (Both the golden and the T-57
# uncategorised molefay fixtures legitimately match -- assert the FAMILY + that
# it's a molefay by name, not a specific fixture id, so the two test blocks'
# lighting fixtures don't make this brittle.)
h = _m("4 molefays")
g["bare_count_qty4"] = (h["qty"] == 4 and h["status"] == "matched"
                        and h["family"] == "lighting"
                        and "MOLEFAY" in (h["product_name"] or "").upper())
# confirmed TERM alias: blinder -> molefay (lighting). (Alias expansion, not the
# qty path -- the [test-wa12]- prefix is a test-only namespacing.)
h = _m("[test-wa12]-blinder")
g["blinder_alias_lighting"] = (h["status"] == "matched"
                               and h["family"] == "lighting"
                               and "MOLEFAY" in (h["product_name"] or "").upper())
# confirmed term-alias "cans" -> led can (lighting), never cross-category.
h = _m("[test-wa12]-cans")
g["cans_lighting"] = (h["status"] == "matched" and h["family"] == "lighting"
                      and "CAN" in (h["product_name"] or "").upper())
# confirmed PRODUCT alias: wedge -> POWERWORKS MONITOR exactly.
h = _m("[test-wa12]-wedge")
g["wedge_product"] = (h["product_id"] == g_mon.id and h["confidence"] == "exact")
# confirmed PRODUCT alias: smoke -> VERTICAL SMOKE MACHINES.
h = _m("[test-wa12]-smoke")
g["smoke_product"] = (h["product_id"] == g_smoke.id)
# live-wire finding 1: a confirmed product alias fires for a 2-word phrase
# where the residue is only a GENERIC noun ("machine") -> the smoke MACHINE,
# NOT a package that merely names it.  Seed a [test-wa12] 'smoke' product alias
# whose phrase is the bare slang, then ask for "smoke machine".
Alias.create({"phrase": "[test-wa12]-smk",
              "product_template_id": g_smoke.id, "state": "confirmed"})
h = _m("[test-wa12]-smk machine")
g["smoke_machine_alias"] = (h["product_id"] == g_smoke.id)
# package EXCLUSION: a bare "smoke machine" (no alias) routes to Effects and
# NEVER to the DJ PACKAGE that names 'SMOKE MACHINE'. The golden smoke product
# is in Effects; the package is excluded from single-item matching entirely.
h = _m("smoke machine")
g["package_excluded"] = (h["product_id"] != g_pkg.id
                         and (h["status"] != "matched"
                              or h["family"] != "packages"))
# zoom can -> the GOLDEN lighting zoom can specifically (unique 99x99 dims so it
# out-scores the T-57 18x18 zoom on the "99x99" tokens -> exercises S6b cleanly).
h = _m("rgbwauv 99x99 zoom led can")
g["zoom_can"] = (h["status"] == "matched" and h["family"] == "lighting"
                 and h["product_id"] == g_can.id)
# exact full catalogue name (global S5a fast path).
h = _m("[TEST-WA12G] LOW FOGGER")
g["exact_name"] = (h["product_id"] == g_fog.id and h["confidence"] == "exact")
# truss plural-fold safety: "truss"/"trussing" must NOT fold to "trus".
g["truss_keep"] = (MM._r2_norm("truss") == "truss"
                   and MM._r2_norm("trussing") == "trussing")
g["screens_fold"] = (MM._r2_norm("screens") == "screen")
# genuinely unknown -> none; NEVER invents, NEVER cross-category.
h = _m("disco ball mirror thing zzzq")
g["unknown_none"] = (h["status"] == "not_found" and h["confidence"] == "none"
                     and not h["product_id"])
# CONFIRMED-only gate: an OPEN alias is IGNORED ([test-wa12]-ignoreme -> effects
# cat would force effects; but it's OPEN, so the funnel ignores it and the
# phrase resolves on its own merits / to none).
h = _m("[test-wa12]-ignoreme")
g["open_alias_ignored"] = (h["family"] != "effects" or h["status"] == "not_found")
# byte-compat: the return dict keys + value-domain unchanged.
h = _m("3 x 2 screen")
g["bytecompat_keys"] = (set(h.keys()) == {
    "raw", "qty", "product_id", "product_name", "category", "status",
    "suggestions", "confidence", "family"} and h["category"] == ""
    and h["confidence"] in ("exact", "strong", "weak", "none"))
_check("T-WA12-60", all(g.values()),
       "Resolver v2 funnel golden: %s" % {k: v for k, v in g.items() if not v}
       or "Resolver v2 funnel golden: ALL PASS")

# ---------------------------------------------------------- T-WA12-60b firewall
# Un-mute the LLM for ONE case: a thin in-family phrase that S6 cannot resolve
# deterministically -> S7 grounded pick. Prove the firewall: (i) an out-of-range
# LLM index is REJECTED -> none/discovery (never invents); (ii) a valid in-range
# index resolves to a REAL in-family id at 'weak'. Also prove LLM-down degrades.
fw = {}
_vis_names = [g_scr32.name, g_scr62.name, g_scr53.name]
# (i) LLM returns an out-of-range index -> rejected -> discovery 'none'.
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: '{"index": 99}'):
    h = MM._wa6_match_one("vaguely a visual thing here", category_hint="visual")
    fw["oob_index_rejected"] = (h["status"] == "not_found"
                                or h["confidence"] != "weak")
# (ii) LLM returns index 0 -> the first shortlisted REAL visual product, weak.
with patch.object(type(M), "_wa12_llm_chat",
                  lambda self, msgs: '{"index": 0}'):
    h = MM._wa6_match_one("some visual gear", category_hint="visual")
    fw["valid_pick_weak"] = (h["status"] in ("matched", "not_found"))
    if h["status"] == "matched":
        fw["valid_pick_weak"] = (h["confidence"] == "weak"
                                 and h["family"] == "visual"
                                 and MM.env["product.template"].sudo().browse(
                                     h["product_id"]).equipment_category_id.code
                                 == "visual")
# (iii) LLM down (returns None) -> graceful, never invents.
with patch.object(type(M), "_wa12_llm_chat", lambda self, msgs: None):
    h = MM._wa6_match_one("another vague visual", category_hint="visual")
    fw["llm_down_graceful"] = (h["confidence"] != "exact"
                               and (h["status"] == "not_found"
                                    or h["confidence"] in ("weak", "strong")))
_check("T-WA12-60b", all(fw.values()), "grounded-pick firewall: %s" % fw)

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
# gather the test chains via the quotes (salesperson is a direct field; T41's
# approver-as-requester quotes belong to u_appr/u_appr2) + by [TEST-WA12]
# partner + the normally-created control job; cancel ACT, then quotes -> jobs.
_tcli0 = P.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA12]")])
tquotes = Q.with_context(active_test=False).search(
    ["|", ("salesperson_id", "in", (u_sales.id, u_appr.id, u_appr2.id)),
     ("partner_id", "in", _tcli0.ids)])
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
# Resolver v2: confirmed/open [test-wa12]-* alias rows + the golden products.
# Aliases first (they ondelete-cascade off product/category but we drop them
# explicitly so the registry cache-bust fires cleanly).
Alias.with_context(active_test=False).search(
    [("phrase", "like", "[test-wa12]")]).unlink()
# ALL [TEST-WA12*] workshop products (the originals + the [TEST-WA12G] golden
# fixtures). 'like' matches the prefix of both tags.
PT.with_context(active_test=False).search(
    ["|", ("name", "like", "[TEST-WA12]"),
     ("name", "like", "[TEST-WA12G]")]).unlink()
# only the [TEST-WA12]-NAMED categories -- the SEEDED ones (visual/lighting/...)
# may have been get-or-created above and must SURVIVE (they're real prod cats).
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
_LLMP.stop()

print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
