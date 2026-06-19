"""QUOTE-UX-1 model smoke — routing unification + approver visibility + preview.

Proves the WHATSAPP-PRESERVATION acceptance conditions explicitly:
  (a) WA-origin submit pings the approver EXACTLY ONCE (no double, no zero)
  (b) approve AND reject via the WA tap path still work identically
  (c) Odoo-origin submit now ALSO pings WhatsApp exactly once
plus: ping carries itemised lines + rates + total; REQUESTER = salesperson_id
for both origins; the Approval Queue form exposes the LIVE quote lines + total;
Preview returns the quote PDF action; the contentless guard never presents a
blind Approve; the cold (out-of-window) path carries rates in a newline-free
param.

WhatsApp sends + replies are MONKEYPATCHED (no Meta); the approver audience is
pointed at a test approver; everything is rolled back at the end.
"""
from datetime import date, timedelta

import odoo.addons.neon_crew_comms.models.whatsapp_message_wa12 as wa12mod

results = []


def chk(n, c):
    results.append((n, bool(c)))
    print(("  ok  " if c else "FAIL  ") + n)


USD = env.ref('base.USD')
WA = env['neon.whatsapp.message']
WCls = type(WA)
Quote = env['neon.finance.quote']
QLine = env['neon.finance.quote.line']

rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)
approver = env['res.users'].search([('login', '=', 'p2m75_approver')], limit=1)
APPROVER_PHONE = '+263770000099'
REP_PHONE = '+263771234567'

bot = env['neon.bot.user'].search([('user_id', '=', approver.id)], limit=1)
if not bot:
    bot = env['neon.bot.user'].create({
        'name': '[TEST-QUX1] Approver', 'phone_number': APPROVER_PHONE,
        'user_id': approver.id})
else:
    bot.write({'phone_number': APPROVER_PHONE})

# --- monkeypatches (restored in finally) ---
sent = []
replies = []
orig = {
    'sb': WCls.send_buttons, 'st': WCls.send_template,
    'win': WCls._wa5_window_open, 'reply': WCls._wa6_reply,
    'pdf': WCls._wa12_send_pdf, 'draft': WCls._wa12_draft_summary,
    'uids': wa12mod._WA12_APPROVER_UIDS,
}
WCls.send_buttons = lambda self, phone, body, buttons, *a, **k: (
    sent.append({'kind': 'buttons', 'phone': phone, 'body': body,
                 'buttons': buttons}) or True)
WCls.send_template = lambda self, phone, name, body_params=None, *a, **k: (
    sent.append({'kind': 'template', 'phone': phone, 'name': name,
                 'params': body_params or []}) or {'ok': True})
WCls._wa5_window_open = lambda self, phone: True
WCls._wa6_reply = lambda self, raw, e164, text, *a, **k: (
    replies.append(text) or True)
WCls._wa12_send_pdf = lambda self, *a, **k: True
wa12mod._WA12_APPROVER_UIDS = (approver.id,)

env['ir.config_parameter'].sudo().set_param(
    'neon_finance.approval_required_for_all', 'True')


def mk_quote():
    partner = env['res.partner'].create(
        {'name': '[TEST-QUX1] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-QUX1] Venue', 'is_company': True})
    job = env['commercial.job'].create({
        'partner_id': partner.id, 'venue_id': venue.id,
        'event_date': (date.today() + timedelta(days=20)).isoformat(),
        'currency_id': USD.id})
    ej = env['commercial.event.job'].create({'commercial_job_id': job.id})
    term = env['neon.finance.payment.term'].create({
        'partner_id': partner.id, 'deposit_pct': 50.0, 'deposit_due_days': 0,
        'final_due_days': 30, 'late_policy': 'reminder'})
    q = Quote.create({
        'event_job_id': ej.id, 'currency_id': USD.id,
        'salesperson_id': rep.id, 'payment_term_id': term.id})
    QLine.create({
        'quote_id': q.id, 'line_type': 'equipment', 'name': 'SOUND RIG',
        'quantity': 1.0, 'duration_days': 2, 'unit_rate': 300.0,
        'pricing_status': 'manual'})
    return q


try:
    # ---- (c) ODOO-ORIGIN submit pings WhatsApp exactly once ----
    sent.clear()
    q1 = mk_quote()
    q1.with_user(rep.id).action_submit_for_approval()
    chk("(c) Odoo-origin submit pings WhatsApp EXACTLY ONCE", len(sent) == 1)
    chk("(c) Odoo-origin quote is pending_approval",
        q1.state == 'pending_approval')
    body1 = sent[0]['body'] if sent else ''
    chk("ping carries the line name", 'SOUND RIG' in body1)
    chk("ping carries rate/day", '/day' in body1 and '300' in body1)
    chk("ping carries the total", ('%.2f' % q1.amount_total) in body1)
    chk("REQUESTER = salesperson_id (rep name in ping)",
        bool(rep.name) and rep.name in body1)
    chk("in-window ping has 3 buttons (Approve/Reject/View PDF)",
        len(sent[0]['buttons']) == 3)

    # ---- D-Odoo: approval form exposes the LIVE quote lines + total ----
    appr = env['neon.finance.approval'].search([('quote_id', '=', q1.id)],
                                                limit=1)
    chk("approval record created", bool(appr))
    chk("approval.quote_line_ids exposes the quote lines",
        len(appr.quote_line_ids) == len(q1.line_ids)
        and appr.quote_line_ids[0].name == 'SOUND RIG')
    chk("approval.quote_amount_total matches the quote",
        abs((appr.quote_amount_total or 0) - (q1.amount_total or 0)) < 0.01)
    chk("approval.notification_sent set after the ping", appr.notification_sent)

    # ---- (a) WA-ORIGIN submit pings exactly once (no double) ----
    sent.clear()
    q2 = mk_quote()
    sess = env['neon.wa.equip.session']._start_quote(
        REP_PHONE, rep, 'q_confirm', {'quote_id': q2.id})
    WA._wa12_submit(q2, sess, REP_PHONE, REP_PHONE.lstrip('+'))
    chk("(a) WA-origin submit pings WhatsApp EXACTLY ONCE (no double)",
        len(sent) == 1)
    chk("(a) WA-origin quote is pending_approval",
        q2.state == 'pending_approval')
    import inspect
    chk("(a) _wa12_submit no longer calls _wa12_send_approval_ping (de-dup)",
        '_wa12_send_approval_ping' not in inspect.getsource(WCls._wa12_submit))

    # ---- (b) approve via the WA tap still works ----
    msg = {'type': 'interactive', 'from': APPROVER_PHONE.lstrip('+'), 'id': 't'}
    WA._wa12_handle_tap('wa12_approve', q1, APPROVER_PHONE,
                        APPROVER_PHONE.lstrip('+'), msg)
    chk("(b) WA approve tap -> quote approved", q1.state == 'approved')

    # ---- (b) reject via the WA tap path still works ----
    q3 = mk_quote()
    q3.with_user(rep.id).action_submit_for_approval()
    WA._wa12_handle_tap('wa12_reject', q3, APPROVER_PHONE,
                        APPROVER_PHONE.lstrip('+'), msg)
    rsess = env['neon.wa.equip.session'].search(
        [('phone_number', '=', APPROVER_PHONE), ('step', '=', 'q_reject')],
        limit=1)
    chk("(b) WA reject tap opens a q_reject session", bool(rsess))
    WA._wa12_apply_reject_comment(q3, 'too pricey', rsess, APPROVER_PHONE,
                                  APPROVER_PHONE.lstrip('+'))
    chk("(b) WA reject comment -> quote rejected", q3.state == 'rejected')

    # ---- (C) Preview returns the quote PDF report action ----
    q4 = mk_quote()
    act = q4.action_preview_quote()
    chk("(C) Preview returns an ir.actions.report",
        isinstance(act, dict) and act.get('type') == 'ir.actions.report')

    # ---- contentless guard: rich summary fails -> View-PDF-only, no blind Approve ----
    sent.clear()

    def _boom(self, q, u):
        raise ValueError('contentless test')
    WCls._wa12_draft_summary = _boom
    try:
        q5 = mk_quote()
        q5.with_user(rep.id).action_submit_for_approval()
    finally:
        WCls._wa12_draft_summary = orig['draft']
    chk("contentless guard: ping still sent", len(sent) == 1)
    chk("contentless guard: NO blind Approve (View-PDF-only, 1 button)",
        bool(sent) and len(sent[0]['buttons']) == 1)

    # ---- cold (out-of-window) path: rates in a NEWLINE-FREE template param ----
    sent.clear()
    WCls._wa5_window_open = lambda self, phone: False
    q6 = mk_quote()
    q6.with_user(rep.id).action_submit_for_approval()
    chk("cold path uses the Meta template",
        len(sent) == 1 and sent[0]['kind'] == 'template')
    cold = sent[0]['params'][2] if (sent and len(sent[0]['params']) >= 3) else ''
    chk("cold summary carries rate, newline-free",
        '/day' in cold and '\n' not in cold)
    WCls._wa5_window_open = lambda self, phone: True

finally:
    WCls.send_buttons = orig['sb']
    WCls.send_template = orig['st']
    WCls._wa5_window_open = orig['win']
    WCls._wa6_reply = orig['reply']
    WCls._wa12_send_pdf = orig['pdf']
    WCls._wa12_draft_summary = orig['draft']
    wa12mod._WA12_APPROVER_UIDS = orig['uids']
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
