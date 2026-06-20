"""FIX-FORWARD #1 smoke — cold-template approval list-then-pick (real round-trip).

Proves, by driving the ACTUAL emitted payload through the REAL dispatch
(_wa12_maybe_intercept -> _wa12_extract_tap -> _wa12_handle_tap), never a
hand-built quote_id:
  T1  cold tap + >=2 pending -> an interactive LIST is emitted, one row per
      pending quote, each row id HMAC-encoding (intent, that quote's id).
  T2  tapping a captured row id -> resolves THAT quote + applies the original
      action (approve), and the OTHER pending quote is untouched.
  T3  cold tap + exactly 1 pending -> direct action, NO list emitted.
  T4  in-window HMAC tap (the real button id emitted by the ping) -> unchanged,
      approves the correct quote.

WhatsApp sends are MONKEYPATCHED (no Meta); approver audience pointed at a test
approver; everything rolled back.
"""
from datetime import date, timedelta

import odoo.addons.neon_crew_comms.models.whatsapp_message_wa12 as wa12mod
from odoo.addons.neon_channels.models import wa_payload

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


USD = env.ref('base.USD')
WA = env['neon.whatsapp.message']
WCls = type(WA)
secret = env['ir.config_parameter'].sudo().get_param('database.secret') or ""

rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)
approver = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1)
APPROVER_PHONE = '+263770000077'
RAW = APPROVER_PHONE.lstrip('+')
bot = env['neon.bot.user'].search([('user_id', '=', approver.id)], limit=1)
if not bot:
    bot = env['neon.bot.user'].create({
        'name': '[TEST-FF1] Approver', 'phone_number': APPROVER_PHONE,
        'user_id': approver.id})
else:
    bot.write({'phone_number': APPROVER_PHONE})

sent = []
orig = {k: getattr(WCls, k) for k in (
    'send_buttons', 'send_template', 'send_list', 'send_message',
    '_wa6_reply', '_wa12_send_pdf', '_wa5_window_open')}
orig_uids = wa12mod._WA12_APPROVER_UIDS
WCls.send_buttons = lambda self, phone, body, buttons, *a, **k: (
    sent.append({'kind': 'buttons', 'buttons': buttons}) or True)
WCls.send_template = lambda self, phone, name, body_params=None, *a, **k: (
    sent.append({'kind': 'template'}) or {'ok': True})
WCls.send_list = lambda self, to, body, btn_text, sections, *a, **k: (
    sent.append({'kind': 'list', 'sections': sections, 'body': body}) or True)
WCls.send_message = lambda self, *a, **k: True
WCls._wa6_reply = lambda self, *a, **k: True
WCls._wa12_send_pdf = lambda self, *a, **k: True
WCls._wa5_window_open = lambda self, phone: True
wa12mod._WA12_APPROVER_UIDS = (approver.id,)
env['ir.config_parameter'].sudo().set_param(
    'neon_finance.approval_required_for_all', 'True')


def mkq(name):
    pa = env['res.partner'].create(
        {'name': '[TEST-FF1] %s' % name, 'is_company': True})
    ve = env['res.partner'].create(
        {'name': '[TEST-FF1] Venue', 'is_company': True})
    jb = env['commercial.job'].create({
        'partner_id': pa.id, 'venue_id': ve.id,
        'event_date': (date.today() + timedelta(days=20)).isoformat(),
        'currency_id': USD.id})
    ej = env['commercial.event.job'].create({'commercial_job_id': jb.id})
    tm = env['neon.finance.payment.term'].create({
        'partner_id': pa.id, 'deposit_pct': 50.0, 'deposit_due_days': 0,
        'final_due_days': 30, 'late_policy': 'reminder'})
    q = env['neon.finance.quote'].create({
        'event_job_id': ej.id, 'currency_id': USD.id,
        'salesperson_id': rep.id, 'payment_term_id': tm.id})
    env['neon.finance.quote.line'].create({
        'quote_id': q.id, 'line_type': 'equipment', 'name': 'RIG ' + name,
        'quantity': 1.0, 'duration_days': 2, 'unit_rate': 300.0,
        'pricing_status': 'manual'})
    return q


def cold_tap(text):
    return {'type': 'button', 'from': RAW, 'id': 'c1',
            'button': {'text': text}}


def inwin(payload_id):
    return {'type': 'interactive', 'from': RAW, 'id': 'i1',
            'interactive': {'button_reply': {'id': payload_id}}}


def list_tap(payload_id):
    return {'type': 'interactive', 'from': RAW, 'id': 'l1',
            'interactive': {'list_reply': {'id': payload_id}}}


try:
    q_a = mkq('AAA')
    q_b = mkq('BBB')
    q_a.action_submit_for_approval()
    q_b.action_submit_for_approval()
    chk("two quotes pending_approval",
        q_a.state == 'pending_approval' and q_b.state == 'pending_approval')

    # ---- T1: cold tap + >=2 pending -> interactive list emitted ----
    sent.clear()
    WA._wa12_maybe_intercept(cold_tap('Approve'))
    lists = [s for s in sent if s['kind'] == 'list']
    chk("T1 cold tap (>=2 pending) emits an interactive LIST", len(lists) == 1)
    rows = lists[0]['sections'][0]['rows'] if lists else []
    chk("T1 list has one row per pending quote (2 rows)", len(rows) == 2)
    # decode each row id (the REAL emitted payload) -> (intent, quote_id)
    decoded = [(r['title'], wa_payload.decode(secret, r['id'])) for r in rows]
    ids_in_rows = set()
    intents_ok = True
    for _title, dec in decoded:
        if not dec or dec[0] != 'wa12_approve':
            intents_ok = False
        elif dec[1]:
            ids_in_rows.add(int(dec[1][0]))
    chk("T1 every row id HMAC-encodes the ORIGINAL intent (wa12_approve)",
        intents_ok)
    chk("T1 rows carry BOTH pending quote ids",
        ids_in_rows == {q_a.id, q_b.id})

    # ---- T2: tap the captured row for q_a -> approves q_a only ----
    row_a_id = next(r['id'] for r in rows
                    if wa_payload.decode(secret, r['id'])[1]
                    and int(wa_payload.decode(secret, r['id'])[1][0]) == q_a.id)
    WA._wa12_maybe_intercept(list_tap(row_a_id))
    chk("T2 row tap (real emitted payload) approves the CORRECT quote (q_a)",
        q_a.state == 'approved')
    chk("T2 the OTHER pending quote (q_b) is untouched",
        q_b.state == 'pending_approval')

    # ---- T3: cold tap + exactly 1 pending (q_b) -> direct, NO list ----
    sent.clear()
    WA._wa12_maybe_intercept(cold_tap('Approve'))
    chk("T3 cold tap (1 pending) approves directly", q_b.state == 'approved')
    chk("T3 NO list emitted when exactly 1 pending",
        not any(s['kind'] == 'list' for s in sent))

    # ---- T4: in-window HMAC tap (the real emitted button id) unchanged ----
    q_c = mkq('CCC')
    sent.clear()
    q_c.action_submit_for_approval()   # in-window ping -> send_buttons captured
    btns = [s for s in sent if s['kind'] == 'buttons']
    chk("T4 in-window ping emitted HMAC buttons", bool(btns))
    approve_btn = next((b for b in (btns[0]['buttons'] if btns else [])
                        if wa_payload.decode(secret, b['id'])
                        and wa_payload.decode(secret, b['id'])[0]
                        == 'wa12_approve'), None)
    chk("T4 in-window approve button carries the quote_id",
        bool(approve_btn)
        and int(wa_payload.decode(secret, approve_btn['id'])[1][0]) == q_c.id)
    WA._wa12_maybe_intercept(inwin(approve_btn['id']))
    chk("T4 in-window HMAC tap approves the correct quote (unchanged path)",
        q_c.state == 'approved')

finally:
    for k, v in orig.items():
        setattr(WCls, k, v)
    wa12mod._WA12_APPROVER_UIDS = orig_uids
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
