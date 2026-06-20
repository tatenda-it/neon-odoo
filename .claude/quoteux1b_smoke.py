"""QUOTE-UX-1b model smoke — PREVIEW persistent across the quote pipeline.

Proves the acceptance conditions of QUOTE-UX-1b:
  (1) action_preview_quote returns the SAME report action
      (neon_finance.report_neon_quote_document) for a quote in EACH active
      state: draft / pending_approval / approved / sent / accepted.
  (2) the rendered report carries the DRAFT-QUOTE banner in draft + pending,
      and has NO banner once approved / sent / accepted (the two report
      faces, proven across the whole pipeline -- report:57-62).
  (3) the quote FORM view (post-inheritance, what the client actually gets)
      exposes exactly ONE Preview button, btn-secondary, whose `invisible`
      is the active-stages set (NOT the old draft-only) -- so it is hidden
      only in the terminal states (rejected / expired / cancelled).

View-only milestone: action_preview_quote is reused UNCHANGED; the model
smoke confirms it behaves correctly in every state it is now reachable from.

WhatsApp sends are neutralised (empty approver audience + monkeypatched send
methods) so submitting a pending quote pings nobody. Everything rolls back.
"""
from datetime import date, timedelta

from lxml import etree

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
Report = env['ir.actions.report']

REPORT_XMLID = 'neon_finance.action_report_neon_quote'
REPORT_NAME = 'neon_finance.report_neon_quote_document'
BANNER = 'DRAFT QUOTE'  # the report banner text (draft/pending faces only)

rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)

# --- neutralise every WhatsApp send path during submit ---
orig = {
    'sb': WCls.send_buttons, 'st': WCls.send_template,
    'win': WCls._wa5_window_open, 'pdf': WCls._wa12_send_pdf,
    'uids': wa12mod._WA12_APPROVER_UIDS,
}
WCls.send_buttons = lambda self, *a, **k: True
WCls.send_template = lambda self, *a, **k: {'ok': True}
WCls._wa5_window_open = lambda self, phone: True
WCls._wa12_send_pdf = lambda self, *a, **k: True
wa12mod._WA12_APPROVER_UIDS = ()  # no approver audience -> submit pings nobody

ICP = env['ir.config_parameter'].sudo()
orig_param = ICP.get_param('neon_finance.approval_required_for_all', 'True')


def mk_quote():
    partner = env['res.partner'].create(
        {'name': '[TEST-QUX1B] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-QUX1B] Venue', 'is_company': True})
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


def render_html(q):
    html = Report._render_qweb_html(REPORT_XMLID, q.ids)[0]
    return html.decode('utf-8') if isinstance(html, bytes) else html


try:
    # ------------------------------------------------------------------
    # Build one quote in EACH active state.
    #   draft               : created, untouched
    #   pending_approval    : require-all submit (empty audience -> no ping)
    #   approved/sent/accepted : auto-approve relaxation, then send / accept
    #     (avoids the SoD dance; the rep acts as their own salesperson)
    # ------------------------------------------------------------------
    ICP.set_param('neon_finance.approval_required_for_all', 'True')
    q_draft = mk_quote()
    q_pending = mk_quote()
    q_pending.with_user(rep.id).action_submit_for_approval()

    ICP.set_param('neon_finance.approval_required_for_all', 'False')
    q_appr = mk_quote()
    q_appr.with_user(rep.id).action_submit_for_approval()
    q_sent = mk_quote()
    q_sent.with_user(rep.id).action_submit_for_approval()
    q_sent.with_user(rep.id).action_send()
    q_acc = mk_quote()
    q_acc.with_user(rep.id).action_submit_for_approval()
    q_acc.with_user(rep.id).action_send()
    q_acc.with_user(rep.id).action_accept()

    by_state = {
        'draft': q_draft,
        'pending_approval': q_pending,
        'approved': q_appr,
        'sent': q_sent,
        'accepted': q_acc,
    }

    # Every fixture actually reached its intended state (else the rest of
    # the assertions are meaningless).
    for st, q in by_state.items():
        chk("fixture reached state %s" % st, q.state == st)

    # (1) Preview returns the SAME report action in every active state.
    for st, q in by_state.items():
        act = q.action_preview_quote()
        chk("(1) Preview[%s] returns an ir.actions.report" % st,
            isinstance(act, dict) and act.get('type') == 'ir.actions.report')
        chk("(1) Preview[%s] targets the quote report" % st,
            isinstance(act, dict) and act.get('report_name') == REPORT_NAME)

    # (2) Banner face per state: DRAFT banner in draft + pending, gone after.
    for st in ('draft', 'pending_approval'):
        html = render_html(by_state[st])
        chk("(2) report[%s] SHOWS the DRAFT banner" % st, BANNER in html)
    for st in ('approved', 'sent', 'accepted'):
        html = render_html(by_state[st])
        chk("(2) report[%s] has NO DRAFT banner (final face)" % st,
            BANNER not in html)

    # Sanity: every face still renders the actual line + total (not a blank
    # page that would trivially pass the "no banner" check).
    for st, q in by_state.items():
        html = render_html(q)
        chk("(2b) report[%s] renders the line item (SOUND RIG)" % st,
            'SOUND RIG' in html)

    # (3) The FORM view (post-inheritance) exposes the persistent Preview.
    view = env.ref('neon_finance.neon_finance_quote_view_form')
    arch = env['neon.finance.quote'].get_view(view.id, 'form')['arch']
    root = etree.fromstring(arch)
    btns = root.findall(".//button[@name='action_preview_quote']")
    chk("(3) exactly ONE Preview button in the quote form", len(btns) == 1)
    if btns:
        btn = btns[0]
        inv = btn.get('invisible') or ''
        chk("(3) Preview invisible = active-stages-only (NOT draft-only)",
            inv == "state not in "
                   "('draft','pending_approval','approved','sent','accepted')")
        chk("(3) Preview is no longer draft-gated",
            "state != 'draft'" not in inv)
        chk("(3) Preview is btn-secondary",
            'btn-secondary' in (btn.get('class') or ''))

finally:
    WCls.send_buttons = orig['sb']
    WCls.send_template = orig['st']
    WCls._wa5_window_open = orig['win']
    WCls._wa12_send_pdf = orig['pdf']
    wa12mod._WA12_APPROVER_UIDS = orig['uids']
    ICP.set_param('neon_finance.approval_required_for_all', orig_param)
    env.cr.rollback()

passed = sum(1 for _, c in results if c)
print("Total: %d/%d passed" % (passed, len(results)))
