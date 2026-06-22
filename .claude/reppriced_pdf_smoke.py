"""REP-PRICED-PDF-FIX model smoke — gate the internal REP-PRICED tag off the
client-facing quote PDF.

REP-PRICED (an internal rep-vs-engine provenance tag, pricing_status=='manual')
was printing on the client-facing quotation, ungated. The fix state-gates the
report span to the WORKING states only (report neon_finance_quote_report.xml).
Proves the two faces (mirrors the DRAFT-banner test in quoteux1b):

  (1) a manual-priced line's report SHOWS "REP-PRICED" in draft + pending_approval;
  (2) it has NO "REP-PRICED" once approved / sent / accepted (client-facing);
  (2b) the line DESCRIPTION still renders in every state (the gate drops only
       the prefix, never the item);
  (3) DISPLAY-ONLY: pricing_status stays 'manual' across all states (the flag,
      not just its render, is what internal approval/WA/AI read -- untouched).

WhatsApp sends are neutralised; everything rolls back.
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
Report = env['ir.actions.report']

REPORT_XMLID = 'neon_finance.action_report_neon_quote'
TAG = 'REP-PRICED'
LINE_NAME = 'MANUAL SOUND RIG'  # deliberately contains no "REP-PRICED" text

rep = env['res.users'].search([('login', '=', 'p2m75_sales')], limit=1)

orig = {
    'sb': WCls.send_buttons, 'st': WCls.send_template,
    'win': WCls._wa5_window_open, 'pdf': WCls._wa12_send_pdf,
    'uids': wa12mod._WA12_APPROVER_UIDS,
}
WCls.send_buttons = lambda self, *a, **k: True
WCls.send_template = lambda self, *a, **k: {'ok': True}
WCls._wa5_window_open = lambda self, phone: True
WCls._wa12_send_pdf = lambda self, *a, **k: True
wa12mod._WA12_APPROVER_UIDS = ()

ICP = env['ir.config_parameter'].sudo()
orig_param = ICP.get_param('neon_finance.approval_required_for_all', 'True')


def mk_quote():
    partner = env['res.partner'].create(
        {'name': '[TEST-RPP] Client', 'is_company': True})
    venue = env['res.partner'].create(
        {'name': '[TEST-RPP] Venue', 'is_company': True})
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
    # a manual-priced line (no equipment_line_id, no product, not custom) ->
    # this is exactly the line that triggers the REP-PRICED tag.
    QLine.create({
        'quote_id': q.id, 'line_type': 'equipment', 'name': LINE_NAME,
        'quantity': 1.0, 'duration_days': 2, 'unit_rate': 300.0,
        'pricing_status': 'manual'})
    return q


def render_html(q):
    html = Report._render_qweb_html(REPORT_XMLID, q.ids)[0]
    return html.decode('utf-8') if isinstance(html, bytes) else html


try:
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
        'draft': q_draft, 'pending_approval': q_pending, 'approved': q_appr,
        'sent': q_sent, 'accepted': q_acc,
    }
    for st, q in by_state.items():
        chk("fixture reached state %s" % st, q.state == st)

    # (1) internal/working states SHOW the tag
    for st in ('draft', 'pending_approval'):
        chk("(1) report[%s] SHOWS REP-PRICED (internal face)" % st,
            TAG in render_html(by_state[st]))

    # (2) client-facing states HIDE the tag
    for st in ('approved', 'sent', 'accepted'):
        chk("(2) report[%s] HIDES REP-PRICED (client face)" % st,
            TAG not in render_html(by_state[st]))

    # (2b) the line description renders in EVERY state (gate drops only prefix)
    for st, q in by_state.items():
        chk("(2b) report[%s] still renders the line item" % st,
            LINE_NAME in render_html(q))

    # (3) DISPLAY-ONLY: the flag itself is unchanged in every state
    for st, q in by_state.items():
        chk("(3) line pricing_status stays 'manual' in %s (flag untouched)" % st,
            q.line_ids[0].pricing_status == 'manual')

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
