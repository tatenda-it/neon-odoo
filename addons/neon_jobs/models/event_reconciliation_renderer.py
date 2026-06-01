# -*- coding: utf-8 -*-
"""P-B5 -- HTML render for the post-event reconciliation.

No PDF (defer per B3/B4 precedent). On-screen render only.
"""
import html
import json
import logging


_logger = logging.getLogger(__name__)


_STATUS_BANNERS = {
    "draft": ("alert-secondary",
                "Draft -- no narrative yet."),
    "generated": ("alert-warning",
                    "Generated -- review the narrative below."),
    "reviewed": ("alert-info",
                   "Reviewed -- click Mark Final to close out + "
                   "fire any workshop alerts."),
    "final": ("alert-success",
                "Final -- workshop alerts (if any) have been "
                "posted to chatter."),
    "superseded": ("alert-muted",
                     "Superseded by a newer revision."),
}


def render_reconciliation_html(summary_json_str, facts_json_str,
                                 status, data_quality_note):
    parts = []
    css, msg = _STATUS_BANNERS.get(
        status, ("alert-secondary",
                  "Status: " + (status or "?")))
    parts.append(
        '<div class="alert {css}" role="alert">'
        '<strong>Status:</strong> {st} &middot; {msg}'
        '</div>'.format(
            css=css, st=html.escape(status or "?"),
            msg=html.escape(msg)))

    if data_quality_note:
        parts.append(
            '<div class="alert alert-info" role="alert" '
            'style="font-size:0.9em;">'
            '<strong>Data quality note:</strong> {n}'
            '</div>'.format(n=html.escape(data_quality_note)))

    if not summary_json_str:
        parts.append(
            '<div class="alert alert-secondary">'
            'No reconciliation content yet. Click "Generate" '
            'to produce one.</div>')
        return "\n".join(parts)
    try:
        payload = json.loads(summary_json_str)
    except (ValueError, TypeError):
        parts.append(
            '<div class="alert alert-danger">'
            '<strong>Render error:</strong> summary JSON is '
            'unparseable -- regenerate.</div>')
        return "\n".join(parts)

    # Headline + summary
    if payload.get("headline"):
        parts.append(
            '<h3 style="color:#5B2A8A;">{h}</h3>'.format(
                h=html.escape(payload["headline"])))
    if payload.get("executive_summary"):
        parts.append(
            '<p style="font-style:italic;">{s}</p>'.format(
                s=html.escape(payload["executive_summary"])))

    # What went well / what didn't
    for key, label, css in (
            ("what_went_well", "What went well", "success"),
            ("what_didnt", "What didn't go to plan", "warning")):
        items = payload.get(key) or []
        if items:
            parts.append(
                '<h5 style="color:#5B2A8A;">{l}</h5>'.format(
                    l=html.escape(label)))
            parts.append(
                '<ul class="text-{c}">'.format(c=css))
            for it in items:
                if isinstance(it, str):
                    parts.append(
                        '<li>{x}</li>'.format(
                            x=html.escape(it)))
            parts.append('</ul>')

    # Equipment outcomes block
    eq = payload.get("equipment_outcomes") or {}
    if eq:
        parts.append(
            '<h4 style="color:#5B2A8A;">Equipment outcomes</h4>')
        parts.append(
            '<p>Written-off: <strong>{w}</strong> &middot; '
            'Needs repair: <strong>{n}</strong></p>'.format(
                w=int(eq.get("written_off_count") or 0),
                n=int(eq.get("needs_repair_count") or 0)))
        if eq.get("narrative"):
            parts.append(
                '<p>{n}</p>'.format(
                    n=html.escape(eq["narrative"])))
        flagged = eq.get("flagged_units") or []
        if flagged:
            parts.append(
                '<table class="table table-sm">'
                '<thead><tr>'
                '<th>Serial</th><th>Product</th>'
                '<th>Suggested status</th>'
                '</tr></thead><tbody>')
            for u in flagged:
                if not isinstance(u, dict):
                    continue
                parts.append(
                    '<tr><td><code>{s}</code></td>'
                    '<td>{p}</td><td><em>{n}</em></td></tr>'.format(
                        s=html.escape(
                            u.get("serial_number") or ""),
                        p=html.escape(
                            u.get("product_name") or ""),
                        n=html.escape(
                            u.get("new_status") or "")))
            parts.append('</tbody></table>')
            parts.append(
                '<p class="text-muted" style="font-size:0.85em;">'
                'NOTE: B5 only FLAGS these units. A Workshop user '
                'must flip the condition_status manually on each '
                'unit -- B5 does not auto-change condition.</p>')

    # Sub-hire outcomes
    sh = payload.get("subhire_outcomes") or []
    if sh:
        parts.append(
            '<h4 style="color:#5B2A8A;">Sub-hire outcomes</h4>')
        parts.append(
            '<table class="table table-sm">'
            '<thead><tr>'
            '<th>Request</th><th class="text-end">Lines</th>'
            '<th class="text-end">Qty short</th>'
            '<th>Supplier</th><th>Narrative</th>'
            '</tr></thead><tbody>')
        for s in sh:
            if not isinstance(s, dict):
                continue
            parts.append(
                '<tr><td><code>{r}</code></td>'
                '<td class="text-end">{l}</td>'
                '<td class="text-end">{q}</td>'
                '<td>{sup}</td><td>{n}</td></tr>'.format(
                    r=html.escape(
                        s.get("request_name") or ""),
                    l=int(s.get("line_count") or 0),
                    q=int(s.get("qty_short_total") or 0),
                    sup=html.escape(
                        s.get("supplier_name") or ""),
                    n=html.escape(
                        s.get("narrative") or "")))
        parts.append('</tbody></table>')

    # Cost narrative + facts
    if payload.get("cost_narrative"):
        parts.append(
            '<h4 style="color:#5B2A8A;">Cost variance</h4>')
        parts.append(
            '<p>{c}</p>'.format(
                c=html.escape(payload["cost_narrative"])))
        try:
            facts = (json.loads(facts_json_str)
                      if facts_json_str else {})
        except (ValueError, TypeError):
            facts = {}
        cv = facts.get("cost_variance") or {}
        if cv.get("available"):
            parts.append(
                '<p>Planned: <strong>{p:.2f}</strong> {c} '
                '&middot; Actual: <strong>{a:.2f}</strong> {c} '
                '&middot; Variance: <strong>{v:+.2f}</strong> '
                '{c}</p>'.format(
                    p=cv.get("planned_total", 0.0),
                    a=cv.get("actual_total", 0.0),
                    v=cv.get("variance_total", 0.0),
                    c=html.escape(cv.get("currency", "USD"))))
            parts.append(
                '<p class="text-muted" style="font-size:0.85em;">'
                'NOTE: variance is INFORMATIONAL only -- B5 does '
                'not post journal entries or modify invoices. A '
                'human acts on the figure.</p>')

    # Lessons
    lessons = payload.get("lessons") or []
    if lessons:
        parts.append(
            '<h5 style="color:#5B2A8A;">Lessons</h5>')
        parts.append('<ul>')
        for l in lessons:
            if isinstance(l, str):
                parts.append(
                    '<li>{x}</li>'.format(x=html.escape(l)))
        parts.append('</ul>')

    return "\n".join(parts)
