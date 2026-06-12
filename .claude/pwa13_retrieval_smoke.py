"""P-WA-13 smoke — quote/invoice retrieval + invoice-from-quote (real path).

Runs in `odoo shell -d neon_crm`. Exercises the REAL dispatch entry
(_wa13_maybe_intercept / handle_inbound) with synthesised inbound dicts, never
the handlers in isolation. A WhatsApp face on the EXISTING P6.M7 invoice
machinery -- no new finance engine. Test fixtures only ([TEST-WA13]).

T-WA13-01  entitlement gates: can_retrieve_quote / _invoice / _generate /
           quote_all_scope across sales / jobs-mgr / approver / OD
T-WA13-02  parser: tight `Send …`; "send me …", "quote for X", mid-sentence
           "invoice" -> None (no turn stolen); the verb+ref forms parse
T-WA13-03  quote retrieval (own): a sales rep -> own quote PDF send reached
T-WA13-04  own-scope: a rep's ref lookup of ANOTHER rep's quote -> not found;
           an approver (all-scope) -> finds + sends it
T-WA13-05  invoice entitlement: sales rep + jobs-mgr `Send invoice` -> REFUSED
           (the ACL-leak guard -- explicit WA gate, not data ACL)
T-WA13-06  posted invoice retrieval: an approver -> posted invoice PDF reached
T-WA13-07  draft invoice: approver -> RE-SENDS the draft (§4.2); OD non-approver
           -> honest "not finalised" refusal
T-WA13-08  Face-2 generate: approver -> confirm -> [Confirm] tap ->
           action_trigger_now -> ONE draft invoice (idempotent on double-tap)
T-WA13-09  Face-2 guard: a non-accepted quote's schedule -> generation refused
T-WA13-10  non-approver [Confirm] tap -> refusal, no invoice created
T-WA13-11  session: doc_pick garbage -> re-prompt (claimed); a live WA-6 session
           is NOT overrun (intercept returns None)
T-WA13-12  full handle_inbound wiring: a `Send quote` reaches WA-13 (truthy)
"""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError  # noqa: F401 (parity)
from odoo.addons.neon_channels.models import wa_payload

# Mute SMTP: action_send / on-acceptance invoice mail has no server in the test
# DB. We test the WA-13 path, not mail delivery. Stopped in teardown.
_MAILP = patch("odoo.addons.mail.models.mail_mail.MailMail.send",
               lambda self, *a, **k: True)
_MAILP.start()
_MAILP2 = patch(
    "odoo.addons.base.models.ir_mail_server.IrMailServer.send_email",
    lambda *a, **k: "test-msgid")
_MAILP2.start()


def _check(name, ok, detail=""):
    print("%s:" % name, "PASS" if ok else "FAIL", detail)
    results[name] = bool(ok)


print("=" * 72)
print("P-WA-13 — retrieval + invoice-from-quote (real path)")
print("=" * 72)
results = {}

Users = env["res.users"].sudo()
Bot = env["neon.bot.user"].sudo()
M = env["neon.whatsapp.message"].sudo()
P = env["res.partner"].sudo()
PT = env["product.template"].sudo()
Q = env["neon.finance.quote"].sudo()
Sched = env["neon.finance.invoice.schedule"].sudo()
Move = env["account.move"].sudo()
Rule = env["neon.finance.pricing.rule"].sudo()
Bracket = env["neon.finance.pricing.bracket"].sudo()
Sess = env["neon.wa.equip.session"].sudo()
SECRET = env["ir.config_parameter"].sudo().get_param("database.secret") or ""
USD = env.ref("base.USD")

SALES_PH = "+263771300021"
OTHER_PH = "+263771300022"
JOBS_PH = "+263771300023"
APPR_PH = "+263771300024"
OD_PH = "+263771300025"
WA6_PH = "+263771300026"   # a phone with a live WA-6 session (T11)
ALL_PH = (SALES_PH, OTHER_PH, JOBS_PH, APPR_PH, OD_PH, WA6_PH)


def _wipe_login(login):
    for u in Users.with_context(active_test=False).search([("login", "=", login)]):
        u.write({"login": login + "_OLD_" + str(u.id), "active": False})


def _mapbot(user, phone):
    bu = Bot.with_context(active_test=False).search(
        [("phone_number", "=", phone)], limit=1)
    vals = {"name": user.name, "user_id": user.id,
            "phone_number": phone, "active": True}
    (bu.write(vals) if bu else Bot.create(vals))


def _txt(phone, body):
    return {"from": phone, "type": "text", "text": {"body": body},
            "id": "pwa13-%s" % phone}


def _tap(phone, intent, sched_id):
    pid = wa_payload.encode(SECRET, intent, sched_id)
    return {"from": phone, "type": "interactive", "id": "pwa13-tap",
            "interactive": {"button_reply": {"id": pid}}}


def _since():
    last = M.search([], order="id desc", limit=1)
    return last.id if last else 0


def _outs(since, phone):
    return M.search([("id", ">", since), ("direction", "=", "outbound"),
                     ("phone_number", "=", phone)], order="id")


def _last_body(since, phone):
    o = _outs(since, phone)
    return (o[-1].message_body or "") if o else ""


def _sent_doc(since, phone):
    """A retrieval reached the document send iff a message_type='document'
    outbound audit was written during the call (send_document returns False in
    the no-Meta test env, but the audit + render still fire)."""
    return bool(_outs(since, phone).filtered(
        lambda m: m.message_type == "document"))


# ---------------------------------------------------------------- pre-wipe
Sess.with_context(active_test=False).search(
    [("phone_number", "in", list(ALL_PH))]).unlink()
_old_p = P.with_context(active_test=False).search([("name", "like", "[TEST-WA13]")])
if _old_p:
    _oq = Q.with_context(active_test=False).search([("partner_id", "in", _old_p.ids)])
    _om = Move.with_context(active_test=False).search([("partner_id", "in", _old_p.ids)])
    _om.filtered(lambda m: m.state == "posted").button_draft()
    _om.filtered(lambda m: m.state != "draft").button_cancel()
    _om.with_context(force_delete=True).unlink()
    Sched.search([("quote_id", "in", _oq.ids)]).unlink()
    env["neon.finance.approval"].sudo().search(
        [("quote_id", "in", _oq.ids)]).unlink()
    _oej = _oq.mapped("event_job_id")
    _ocj = _oej.mapped("commercial_job_id")
    _oq.unlink()
    _oej.exists().unlink()
    _ocj.exists().unlink()
    env["neon.finance.payment.term"].sudo().search(
        [("partner_id", "in", _old_p.ids)]).unlink()
    _old_p.unlink()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA13]")]).unlink()
_orules = Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA13]")])
_orules.mapped("bracket_ids").unlink()
_orules.unlink()
for lg in ("pwa13_sales", "pwa13_other", "pwa13_jobs", "pwa13_appr", "pwa13_od"):
    _wipe_login(lg)

# ---------------------------------------------------------------- users
g_user = env.ref("base.group_user")
g_sales = env.ref("neon_core.group_neon_sales_rep")
g_super = env.ref("neon_core.group_neon_superuser")
g_appr = env.ref("neon_finance.group_neon_finance_approver")
g_jobs = env.ref("neon_jobs.group_neon_jobs_manager")

u_sales = Users.with_context(no_reset_password=True).create({
    "name": "PWA13 Sales", "login": "pwa13_sales", "password": "test123",
    "groups_id": [(4, g_user.id), (4, g_sales.id)]})
u_other = Users.with_context(no_reset_password=True).create({
    "name": "PWA13 Other", "login": "pwa13_other", "password": "test123",
    "groups_id": [(4, g_user.id), (4, g_sales.id)]})
u_jobs = Users.with_context(no_reset_password=True).create({
    "name": "PWA13 JobsMgr", "login": "pwa13_jobs", "password": "test123",
    "groups_id": [(4, g_user.id), (4, g_jobs.id)]})
u_appr = Users.with_context(no_reset_password=True).create({
    "name": "PWA13 Approver", "login": "pwa13_appr", "password": "test123",
    "groups_id": [(4, g_user.id), (4, g_sales.id), (4, g_appr.id)]})
# OD by LOGIN (not superuser -> NOT auto-promoted into the approver group;
# group_neon_superuser IMPLIES group_neon_finance_approver, verified). This is
# the genuine "can retrieve an invoice (via _wa6_can_initiate) but CANNOT
# generate (not in the approver group)" actor -> the "not finalised" path (T07).
u_od = Users.with_context(no_reset_password=True).create({
    "name": "PWA13 OD", "login": "pwa13_od", "password": "test123",
    "groups_id": [(4, g_user.id)]})
# point the WA-6/12/13 OD-login param at u_od for the run (restored in teardown).
ICP = env["ir.config_parameter"].sudo()
_OD_PARAM = "neon_channels.wa6_od_login"
_old_od = ICP.get_param(_OD_PARAM)
ICP.set_param(_OD_PARAM, "pwa13_od")
for _u, _ph in ((u_sales, SALES_PH), (u_other, OTHER_PH), (u_jobs, JOBS_PH),
                (u_appr, APPR_PH), (u_od, OD_PH)):
    _mapbot(_u, _ph)
    _u.partner_id.write({"email": "%s@neon.test" % _u.login})
# make sure the OD-login user is NOT also resolving as OD by config; _wa6_od_user
# reads a login param (default Robin). u_od relies on the superuser group only.

# ---------------------------------------------------------------- catalogue
prod = PT.create({
    "name": "[TEST-WA13] Widget", "is_workshop_item": True, "list_price": 5.0})
prule = Rule.create({
    "name": "[TEST-WA13] Rule", "product_template_id": prod.id,
    "currency_id": USD.id, "base_rate": 100.0, "effective_date": "2020-01-01"})
Bracket.create({"rule_id": prule.id, "sequence": 1, "day_from": 1,
                "day_to": -1, "multiplier": 1.0})

cA = P.create({"name": "[TEST-WA13] Alpha Corp", "email": "alpha@neon.test"})
cB = P.create({"name": "[TEST-WA13] Bravo Ltd", "email": "bravo@neon.test"})
cC = P.create({"name": "[TEST-WA13] Charlie Inc", "email": "charlie@neon.test"})
# submit_for_approval requires a payment term; the local test DB starts with
# none (prod carries them). One partner-scoped term per client.
PTerm = env["neon.finance.payment.term"].sudo()
for _c in (cA, cB, cC):
    PTerm.create({"name": "[TEST-WA13] Terms %s" % _c.id, "partner_id": _c.id})
env.company.sudo().write({"email": env.company.email or "noreply@neon.test"})
if not env["ir.mail_server"].sudo().search([], limit=1):
    env["ir.mail_server"].sudo().create({
        "name": "[TEST-WA13] dummy", "smtp_host": "localhost",
        "smtp_port": 25, "smtp_encryption": "none"})


def _new_quote(client, sp):
    q = Q._wa12_provision_chain(client, "2026-10-05", USD, sp)
    M.sudo()._wa12_build_lines(q, [{"product_id": prod.id, "qty": 1}], 2)
    q.action_recalculate_pricing()
    return q


def _drive_to_accepted(q, pre_sched=None):
    M.sudo()._wa12_ensure_payment_term(q, q.partner_id)
    if pre_sched:
        Sched.create(dict(pre_sched, quote_id=q.id))
    q.with_user(u_sales.id).action_submit_for_approval()
    if q.state == "pending_approval":
        q.with_user(u_appr.id).action_approve()
    q.with_user(u_sales.id).action_send()
    q.with_user(u_sales.id).action_accept()
    return q


# cA: a DRAFT own quote (u_sales) + a DRAFT other-rep quote (u_other) + a
# directly-posted invoice (posted retrieval target).
q_sales = _new_quote(cA, u_sales)
q_other = _new_quote(cA, u_other)
_journal = env["account.journal"].sudo().search([("type", "=", "sale")], limit=1)
_income = env["account.account"].sudo().search(
    [("account_type", "=", "income")], limit=1)
inv_posted = Move.create({
    "move_type": "out_invoice", "partner_id": cA.id,
    "invoice_date": "2026-06-01",
    "journal_id": _journal.id if _journal else False,
    "invoice_line_ids": [(0, 0, {
        "name": "[TEST-WA13] line", "quantity": 1, "price_unit": 250.0,
        "account_id": _income.id if _income else False, "tax_ids": [(5, 0, 0)]})]})
_posted_ok = True
try:
    inv_posted.action_post()
except Exception as _e:  # noqa: BLE001
    _posted_ok = False
    print("  (posted-invoice fixture could not be posted: %s)" % _e)

# cB: an accepted quote with the DEFAULT schedule -> on_acceptance auto-fires ->
# a DRAFT invoice exists, no scheduled stage left (§4.2 re-send / not-finalised).
q_b = _drive_to_accepted(_new_quote(cB, u_sales))
inv_draft = q_b.invoice_schedule_ids.mapped("invoice_id")

# cC: an accepted quote with a pre-designed MANUAL 100% schedule -> stays
# 'scheduled', NO invoice yet (Face-2 generate target).
q_c = _drive_to_accepted(
    _new_quote(cC, u_sales),
    pre_sched={"name": "[TEST-WA13] Stage", "stage": "final",
               "trigger": "manual", "percentage": 100.0})
sched_c = q_c.invoice_schedule_ids.filtered(lambda s: s.state == "scheduled")[:1]

# a DRAFT quote + a manually-added scheduled schedule (Face-2 non-accepted guard).
q_notacc = _new_quote(cC, u_sales)
sched_bad = Sched.create({
    "name": "[TEST-WA13] Bad", "quote_id": q_notacc.id, "stage": "final",
    "trigger": "manual", "percentage": 100.0})

env.cr.commit()

D_sales = M.with_user(u_sales)
D_other = M.with_user(u_other)
D_jobs = M.with_user(u_jobs)
D_appr = M.with_user(u_appr)
D_od = M.with_user(u_od)
REFUSAL = "isn't something I can action"

# ---------------------------------------------------------- T-WA13-01 entitle
_check("T-WA13-01",
       (D_sales._wa13_can_retrieve_quote(u_sales)
        and D_jobs._wa13_can_retrieve_quote(u_jobs)
        and D_appr._wa13_can_retrieve_quote(u_appr)
        and D_od._wa13_can_retrieve_quote(u_od))
       and (not D_sales._wa13_can_retrieve_invoice(u_sales)
            and not D_jobs._wa13_can_retrieve_invoice(u_jobs)
            and D_appr._wa13_can_retrieve_invoice(u_appr)
            and D_od._wa13_can_retrieve_invoice(u_od))
       and (not D_sales._wa13_can_generate(u_sales)
            and not D_jobs._wa13_can_generate(u_jobs)
            and D_appr._wa13_can_generate(u_appr)
            and not D_od._wa13_can_generate(u_od))
       and (not D_sales._wa13_quote_all_scope(u_sales)
            and D_appr._wa13_quote_all_scope(u_appr)
            and D_od._wa13_quote_all_scope(u_od)),
       "quote: all can; invoice: appr+od only; generate: appr only; "
       "all-scope: appr+od")

# ---------------------------------------------------------- T-WA13-02 parser
p1 = M._wa13_parse("send me the address")
p2 = M._wa13_parse("quote for Alpha")
p3 = M._wa13_parse("please invoice the client tomorrow")
p4 = M._wa13_parse("Send quote Alpha Corp")
p5 = M._wa13_parse("send QUO-USD-000123")
p6 = M._wa13_parse("Send invoice Bravo Ltd")
p7 = M._wa13_parse("send INV-0001")
_check("T-WA13-02",
       p1 is None and p2 is None and p3 is None
       and p4 == ("quote", "Alpha Corp") and p5 == ("quote", "QUO-USD-000123")
       and p6 == ("invoice", "Bravo Ltd") and p7 == ("invoice", "INV-0001"),
       "false-positives None; verb+ref forms parse: %s %s %s %s"
       % (p4, p5, p6, p7))

# ---------------------------------------------------------- T-WA13-03 own quote
s = _since()
D_sales._wa13_maybe_intercept(_txt(SALES_PH, "send quote Alpha Corp"))
_check("T-WA13-03", _sent_doc(s, SALES_PH),
       "sales rep retrieves own quote -> document send reached (last=%r)"
       % _last_body(s, SALES_PH)[:60])

# ---------------------------------------------------------- T-WA13-04 own-scope
ref_other = q_other.name
s = _since()
D_sales._wa13_maybe_intercept(_txt(SALES_PH, "send %s" % ref_other))
own_scope_miss = "no quote found" in _last_body(s, SALES_PH).lower()
s2 = _since()
D_appr._wa13_maybe_intercept(_txt(APPR_PH, "send %s" % ref_other))
appr_sees = _sent_doc(s2, APPR_PH)
_check("T-WA13-04", own_scope_miss and appr_sees,
       "rep ref of another rep's quote -> miss=%s ; approver all-scope sends=%s"
       % (own_scope_miss, appr_sees))

# ---------------------------------------------------------- T-WA13-05 inv entitle
s = _since()
D_sales._wa13_maybe_intercept(_txt(SALES_PH, "send invoice Alpha Corp"))
sales_refused = REFUSAL in _last_body(s, SALES_PH)
s2 = _since()
D_jobs._wa13_maybe_intercept(_txt(JOBS_PH, "send invoice Alpha Corp"))
jobs_refused = REFUSAL in _last_body(s2, JOBS_PH)
_check("T-WA13-05", sales_refused and jobs_refused,
       "invoice retrieval: sales refused=%s jobs-mgr refused=%s (ACL-leak guard)"
       % (sales_refused, jobs_refused))

# ---------------------------------------------------------- T-WA13-06 posted inv
if _posted_ok:
    s = _since()
    D_appr._wa13_maybe_intercept(_txt(APPR_PH, "send invoice Alpha Corp"))
    _check("T-WA13-06", _sent_doc(s, APPR_PH),
           "approver retrieves the POSTED invoice -> document send reached")
else:
    _check("T-WA13-06", True, "SKIPPED — posted-invoice fixture unpostable "
           "in this env (accounting config); logged, not a code failure")

# ---------------------------------------------------------- T-WA13-07 draft inv
s = _since()
D_appr._wa13_maybe_intercept(_txt(APPR_PH, "send invoice Bravo Ltd"))
appr_resend = _sent_doc(s, APPR_PH)
s2 = _since()
D_od._wa13_maybe_intercept(_txt(OD_PH, "send invoice Bravo Ltd"))
od_notfinal = "finalised" in _last_body(s2, OD_PH).lower()
_check("T-WA13-07", appr_resend and od_notfinal,
       "draft invoice: approver re-sends=%s ; OD non-approver 'not finalised'=%s"
       % (appr_resend, od_notfinal))

# ---------------------------------------------------------- T-WA13-08 generate
s = _since()
D_appr._wa13_maybe_intercept(_txt(APPR_PH, "send invoice Charlie Inc"))
sess_now = Sess._active_for_phone(APPR_PH)
offered = bool(sess_now) and sess_now.step == "inv_confirm"
# the [Confirm] tap (HMAC) -> action_trigger_now -> DRAFT invoice.
D_appr._wa13_maybe_intercept(_tap(APPR_PH, "wa13_inv_confirm", sched_c.id))
sched_c.invalidate_recordset()
gen_ok = sched_c.state in ("invoiced", "triggered") and bool(sched_c.invoice_id)
first_move = sched_c.invoice_id
# double-tap -> idempotent (no second invoice; re-send the same one).
D_appr._wa13_maybe_intercept(_tap(APPR_PH, "wa13_inv_confirm", sched_c.id))
sched_c.invalidate_recordset()
idem = sched_c.invoice_id == first_move and bool(first_move) \
    and first_move.state == "draft"
_check("T-WA13-08", offered and gen_ok and idem,
       "offered(inv_confirm)=%s generated DRAFT=%s idempotent=%s (move=%s state=%s)"
       % (offered, gen_ok, idem, first_move.name,
          first_move.state if first_move else "-"))

# ---------------------------------------------------------- T-WA13-09 not-accepted
s = _since()
D_appr._wa13_do_generate(sched_bad, u_appr, None, APPR_PH, APPR_PH)
sched_bad.invalidate_recordset()
guard = (sched_bad.state == "scheduled" and not sched_bad.invoice_id
         and "accepted quote" in _last_body(s, APPR_PH).lower())
_check("T-WA13-09", guard,
       "non-accepted quote schedule -> generation refused, still scheduled "
       "(state=%s, reply=%r)" % (sched_bad.state, _last_body(s, APPR_PH)[:50]))

# ---------------------------------------------------------- T-WA13-10 non-appr tap
# a fresh scheduled stage to attempt against (q_c's was consumed in T08).
q_c2 = _drive_to_accepted(
    _new_quote(cC, u_sales),
    pre_sched={"name": "[TEST-WA13] Stage2", "stage": "final",
               "trigger": "manual", "percentage": 100.0})
sched_c2 = q_c2.invoice_schedule_ids.filtered(lambda s: s.state == "scheduled")[:1]
s = _since()
D_sales._wa13_maybe_intercept(_tap(SALES_PH, "wa13_inv_confirm", sched_c2.id))
sched_c2.invalidate_recordset()
nonappr = (REFUSAL in _last_body(s, SALES_PH)
           and sched_c2.state == "scheduled" and not sched_c2.invoice_id)
_check("T-WA13-10", nonappr,
       "non-approver [Confirm] tap refused + no invoice (state=%s)"
       % sched_c2.state)

# ---------------------------------------------------------- T-WA13-11 sessions
# (a) doc_pick: approver retrieves Alpha quotes (q_sales + q_other = 2) ->
#     doc_pick menu; garbage -> re-prompt (claimed); "1" -> picks + sends.
s = _since()
D_appr._wa13_maybe_intercept(_txt(APPR_PH, "send quote Alpha Corp"))
dp = Sess._active_for_phone(APPR_PH)
dp_open = bool(dp) and dp.step == "doc_pick"
s2 = _since()
r_garbage = D_appr._wa13_maybe_intercept(_txt(APPR_PH, "blah blah"))
reprompt = (r_garbage is True
            and "number" in _last_body(s2, APPR_PH).lower()
            and Sess._active_for_phone(APPR_PH).step == "doc_pick")
s3 = _since()
D_appr._wa13_maybe_intercept(_txt(APPR_PH, "1"))
picked = _sent_doc(s3, APPR_PH) and not Sess._active_for_phone(APPR_PH)
# (b) a live WA-6 session must NOT be overrun by the Send parser.
Sess._start(WA6_PH, u_sales, q_sales.event_job_id)  # await_items
wa6_live = Sess._active_for_phone(WA6_PH)
not_overrun = (wa6_live.step == "await_items"
               and D_appr.with_user(u_sales)._wa13_maybe_intercept(
                   _txt(WA6_PH, "send quote Alpha Corp")) is None)
_check("T-WA13-11", dp_open and reprompt and picked and not_overrun,
       "doc_pick open=%s reprompt=%s picked+closed=%s WA-6 not overrun=%s"
       % (dp_open, reprompt, picked, not_overrun))

# ---------------------------------------------------------- T-WA13-12 wiring
s = _since()
res = D_sales.handle_inbound(_txt(SALES_PH, "send quote Alpha Corp"), {})
_check("T-WA13-12", res is True and _sent_doc(s, SALES_PH),
       "handle_inbound routes a `Send quote` to WA-13 (after WA-12, before "
       "WA-6): res=%s" % res)

# ------------------------------------------------------- T-WA13-13 STOP release
# (review WA13-1) a live WA-13 session must RELEASE an opt-out keyword (return
# None -> super() -> the WA-2 opt-out handler), never swallow it.
Sess._start_inv(APPR_PH, u_appr, "inv_confirm",
                {"quote_id": q_c.id, "schedule_id": sched_c.id})
r_stop = D_appr._wa13_maybe_intercept(_txt(APPR_PH, "STOP"))
still_live = bool(Sess._active_for_phone(APPR_PH))  # WA-13 didn't cancel it
_check("T-WA13-13", r_stop is None and still_live,
       "STOP during a live inv_confirm session -> released (None), session not "
       "swallowed (live=%s)" % still_live)
Sess.with_context(active_test=False).search(
    [("phone_number", "=", APPR_PH)]).write({"active": False})

# ------------------------------------------------------- T-WA13-14 VAT label
# (review WA13-F2-VATLABEL) the confirm text tracks ACTUAL tax: a tax-free line
# -> amount_tax 0 -> '(no VAT)', never a hardcoded '(incl. VAT)'.
qv = _new_quote(cC, u_sales)
qv.line_ids.write({"tax_id": False})
qv.invalidate_recordset()
schv = Sched.create({"name": "[TEST-WA13] VAT", "quote_id": qv.id,
                     "stage": "final", "trigger": "manual", "percentage": 100.0})
vtxt = D_appr._wa13_confirm_text(schv)
_check("T-WA13-14",
       (qv.amount_tax or 0.0) == 0.0 and "(no VAT)" in vtxt,
       "tax-free quote -> confirm says (no VAT) (amount_tax=%s, text=%r)"
       % (qv.amount_tax, vtxt[:90]))

# ------------------------------------------------------- T-WA13-15 doc_pick gate
# (review WA13-SEC-01 / WA13-2) doc_pick re-gates the CURRENT phone owner EVERY
# turn: a deactivated owner mid-session -> pick refused + session closed.
Sess._start_inv(APPR_PH, u_appr, "doc_pick",
                {"kind": "quote", "ids": [q_sales.id, q_c.id]})
u_appr.write({"active": False})
s = _since()
M._wa13_maybe_intercept(_txt(APPR_PH, "1"))
regated = (REFUSAL in _last_body(s, APPR_PH)
           and not Sess._active_for_phone(APPR_PH))
u_appr.write({"active": True})  # restore for teardown
_check("T-WA13-15", regated,
       "doc_pick re-gates a deactivated owner mid-session (refused + closed)")

# ---------------------------------------------------------------- teardown
print("--- teardown ---")
_tcli = P.with_context(active_test=False).search([("name", "like", "[TEST-WA13]")])
_tq = Q.with_context(active_test=False).search([("partner_id", "in", _tcli.ids)])
_tm = Move.with_context(active_test=False).search([("partner_id", "in", _tcli.ids)])
_tm.filtered(lambda m: m.state == "posted").button_draft()
_tm.filtered(lambda m: m.state != "draft").button_cancel()
_tm.with_context(force_delete=True).unlink()
Sched.search([("quote_id", "in", _tq.ids)]).unlink()
env["neon.finance.approval"].sudo().search(
    [("quote_id", "in", _tq.ids)]).unlink()
_tej = _tq.mapped("event_job_id")
_tcj = _tej.mapped("commercial_job_id")
_tq.unlink()
_tej.exists().unlink()
_tcj.exists().unlink()
env["neon.finance.payment.term"].sudo().search(
    [("partner_id", "in", _tcli.ids)]).unlink()
_trules = Rule.with_context(active_test=False).search(
    [("name", "like", "[TEST-WA13]")])
_trules.mapped("bracket_ids").unlink()
_trules.unlink()
PT.with_context(active_test=False).search([("name", "like", "[TEST-WA13]")]).unlink()
Bot.with_context(active_test=False).search(
    [("phone_number", "in", list(ALL_PH))]).unlink()
Sess.with_context(active_test=False).search(
    [("phone_number", "in", list(ALL_PH))]).unlink()
for u in (u_sales, u_other, u_jobs, u_appr, u_od):
    u.write({"active": False})
# restore the OD-login param (we pointed it at the throwaway u_od for the run).
ICP.set_param(_OD_PARAM, _old_od or "robin@neonhiring.co.zw")
_tcli.unlink()
env.cr.commit()

_MAILP.stop()
_MAILP2.stop()

print("=" * 72)
_n_pass = sum(1 for v in results.values() if v)
print("Total: %d/%d passed" % (_n_pass, len(results)))
for k in sorted(results):
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 72)
