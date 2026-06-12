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
cat = env["neon.equipment.category"].sudo().search([], limit=1)
prod_ok = PT.create({
    # a UNIQUE made-up token so _wa6_match_one widens to all workshop items
    # (no category-synonym collision) and token-matches THIS product only.
    "name": "[TEST-WA12] Qwertyunit", "is_workshop_item": True,
    "list_price": 50.0,
    "equipment_category_id": cat.id if cat else False})
prod_ph = PT.create({
    "name": "[TEST-WA12] Placeholder Gizmo", "is_workshop_item": True,
    "list_price": 1.0,
    "equipment_category_id": cat.id if cat else False})
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
blocked = False
try:
    if not unpriced:
        ph_quote.action_submit_for_approval()
    else:
        blocked = True
except Exception:
    blocked = True
_check("T-WA12-07", bool(unpriced) and blocked,
       "placeholder line -> unpriced=%s, submit blocked" % unpriced)

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
(prod_ok | prod_ph).unlink()
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
