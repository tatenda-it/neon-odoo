# -*- coding: utf-8 -*-
"""P-B4 -- HTML render for sub-hire request (on-screen only)."""
import html
import json
import logging


_logger = logging.getLogger(__name__)


_STATUS_BANNERS = {
    "draft":      ("alert-secondary", "Draft -- no content yet."),
    "generated":  ("alert-warning",
                    "Generated -- review the draft below."),
    "reviewed":   ("alert-info",
                    "Reviewed -- pick a supplier + approve to "
                    "create the PO draft."),
    "approved":   ("alert-success",
                    "Approved + PO draft created. Confirm + send "
                    "the PO via Purchase Orders menu, then mark "
                    "this request as Sent."),
    "sent":       ("alert-success",
                    "Sent. Manager can un-send if needed."),
    "superseded": ("alert-muted",
                    "Superseded by a newer revision."),
}


def render_subhire_summary_html(draft_json_str, data_quality_note,
                                  status, supplier_name,
                                  po_draft_name):
    parts = []
    css, msg = _STATUS_BANNERS.get(
        status, ("alert-secondary", "Status: " + (status or "?")))
    parts.append(
        '<div class="alert {css}" role="alert">'
        '<strong>Status:</strong> {st} &middot; {msg}'
        '</div>'.format(
            css=css, st=html.escape(status or "?"),
            msg=html.escape(msg)))

    if supplier_name:
        parts.append(
            '<p><strong>Supplier:</strong> {s}</p>'.format(
                s=html.escape(supplier_name)))
    if po_draft_name:
        parts.append(
            '<p><strong>PO draft:</strong> '
            '<code>{p}</code> (state=draft -- '
            'confirm/send via standard Purchase Orders menu)'
            '</p>'.format(p=html.escape(po_draft_name)))

    if data_quality_note:
        parts.append(
            '<div class="alert alert-info" role="alert" '
            'style="font-size:0.9em;">'
            '<strong>Data quality note:</strong> {n}'
            '</div>'.format(n=html.escape(data_quality_note)))

    if not draft_json_str:
        parts.append(
            '<div class="alert alert-secondary">'
            'No draft content yet. Click "Generate" to produce '
            'one.</div>')
        return "\n".join(parts)

    try:
        payload = json.loads(draft_json_str)
    except (ValueError, TypeError):
        parts.append(
            '<div class="alert alert-danger">'
            '<strong>Render error:</strong> '
            'draft JSON is unparseable -- regenerate.</div>')
        return "\n".join(parts)

    # Enquiry subject + body
    subject = payload.get("enquiry_subject") or ""
    body = payload.get("enquiry_body") or ""
    if subject:
        parts.append(
            '<h4 style="color:#5B2A8A;">Enquiry subject</h4>'
            '<p style="font-style:italic;">{s}</p>'.format(
                s=html.escape(subject)))
    if body:
        parts.append(
            '<h4 style="color:#5B2A8A;">Enquiry body</h4>'
            '<div style="border-left:3px solid #ddd;'
            'padding-left:12px;white-space:pre-wrap;">{b}</div>'
            .format(b=html.escape(body)))

    # Line briefs
    briefs = payload.get("line_briefs") or []
    if briefs:
        rows = []
        for entry in briefs:
            rows.append(
                '<tr><td><strong>{p}</strong></td>'
                '<td class="text-end">{q}</td>'
                '<td>{w}</td><td>{c}</td><td>{b}</td></tr>'.format(
                    p=html.escape(
                        (entry or {}).get("product_name") or ""),
                    q=int((entry or {}).get("qty_short") or 0),
                    w=html.escape(
                        (entry or {}).get("event_window") or ""),
                    c=html.escape(", ".join(
                        (entry or {}).get(
                            "competing_event_names") or [])),
                    b=html.escape(
                        (entry or {}).get("brief") or "")))
        parts.append(
            '<h4 style="color:#5B2A8A;">Per-line briefs</h4>'
            '<table class="table table-sm">'
            '<thead><tr>'
            '<th>Item</th>'
            '<th class="text-end">Short by</th>'
            '<th>Event window</th>'
            '<th>Competing events</th>'
            '<th>Brief</th>'
            '</tr></thead>'
            '<tbody>{rows}</tbody></table>'.format(
                rows="".join(rows)))
    return "\n".join(parts)
