# -*- coding: utf-8 -*-
"""P-B3 -- HTML render of a deployment plan (on-screen only).

⚠️ DECISION (B3, D10 trim per gate-1): NO PDF this milestone.
This pure-Python helper produces the plan_summary_html that the
neon.deployment.plan form view embeds in a read-only field.
PDF render is a fast follow.

Renders:
  - Status banner (green/amber/red on status + deficit count)
  - Data-quality note banner (if non-null)
  - ACTION REQUIRED -- sub-hire block (deficit + zero_margin lines)
  - Sections in locked order: load_in setup show_time strike return risks
  - Crew call-times table (Python-computed)
"""
import html
import json
import logging


_logger = logging.getLogger(__name__)


_SECTION_ORDER = (
    "load_in", "setup", "show_time", "strike", "return", "risks")
_SECTION_LABELS = {
    "load_in": "Load-in",
    "setup": "Setup",
    "show_time": "Show time",
    "strike": "Strike",
    "return": "Return",
    "risks": "Risks",
}


def render_plan_summary_html(plan_json_str, data_quality_note,
                              status):
    """Return an HTML string suitable for the form's Html field.
    Empty / unparseable plan -> placeholder block."""
    if not plan_json_str:
        return _empty_placeholder(status)
    try:
        payload = json.loads(plan_json_str)
    except (ValueError, TypeError):
        return _error_placeholder(
            "Plan JSON is unparseable -- regenerate.")
    if not isinstance(payload, dict):
        return _error_placeholder(
            "Plan JSON is not a JSON object -- regenerate.")

    parts = []
    deficits = payload.get("deficits") or []
    parts.append(_status_banner(status, deficits))
    if data_quality_note:
        parts.append(_dq_banner(data_quality_note))
    if deficits:
        parts.append(_deficit_block(deficits))
    parts.append(_sections_block(payload.get("sections") or []))
    parts.append(_call_times_block(
        payload.get("crew_call_times") or []))
    return "\n".join(parts)


# ============================================================
# Banners
# ============================================================

def _status_banner(status, deficits):
    if deficits and any(
            (d or {}).get("deficit_qty", 0) > 0 for d in deficits):
        css = "alert-danger"
        label = "DEFICIT DETECTED -- sub-hire required"
    elif deficits:
        css = "alert-warning"
        label = "Zero-margin or below-threshold items present"
    else:
        css = "alert-success"
        label = "All clear -- no equipment deficit"
    return (
        '<div class="alert {css}" role="alert">'
        '<strong>{label}</strong>'
        ' &middot; Plan status: <em>{st}</em>'
        '</div>'
    ).format(css=css, label=html.escape(label),
             st=html.escape(status or ""))


def _dq_banner(note):
    return (
        '<div class="alert alert-info" role="alert" '
        'style="font-size:0.9em;">'
        '<strong>Data quality note:</strong> {n}'
        '</div>'
    ).format(n=html.escape(note or ""))


def _deficit_block(deficits):
    rows = []
    # Sort by sub_hire_priority asc (lower = more urgent)
    for d in sorted(deficits,
                     key=lambda x: int(
                         (x or {}).get("sub_hire_priority", 999))):
        rows.append(_deficit_row(d or {}))
    return (
        '<div class="alert alert-danger" role="alert" '
        'style="padding:12px;">'
        '<h4 style="margin-top:0;color:#a02020;">'
        'ACTION REQUIRED -- SUB-HIRE</h4>'
        '<table class="table table-sm" style="background:white;">'
        '<thead><tr>'
        '<th>#</th><th>Item</th>'
        '<th class="text-end">Need</th>'
        '<th class="text-end">Have</th>'
        '<th class="text-end">Short by</th>'
        '<th>Competing events</th>'
        '</tr></thead><tbody>'
        '{rows}'
        '</tbody></table>'
        '</div>'
    ).format(rows="".join(rows))


def _deficit_row(d):
    competing = ", ".join(
        html.escape(n) for n in (
            d.get("competing_event_names") or []))
    return (
        '<tr>'
        '<td>{prio}</td>'
        '<td><strong>{p}</strong></td>'
        '<td class="text-end">{req}</td>'
        '<td class="text-end">{ava}</td>'
        '<td class="text-end" style="color:#a02020;'
        'font-weight:700;">{deficit}</td>'
        '<td>{comp}</td>'
        '</tr>'
    ).format(
        prio=html.escape(str(d.get("sub_hire_priority") or "")),
        p=html.escape(d.get("product_name") or ""),
        req=int(d.get("required_qty") or 0),
        ava=int(d.get("available_qty") or 0),
        deficit=int(d.get("deficit_qty") or 0),
        comp=competing or "<em>(none)</em>",
    )


# ============================================================
# Sections + call times
# ============================================================

def _sections_block(sections):
    if not sections:
        return ""
    by_key = {(s or {}).get("key"): s for s in sections}
    parts = ['<div class="o_deployment_sections">']
    for key in _SECTION_ORDER:
        s = by_key.get(key)
        if not s:
            continue
        title = s.get("title") or _SECTION_LABELS.get(key, key)
        parts.append(
            '<h4 style="color:#5B2A8A;margin-top:18px;">{t}</h4>'
            .format(t=html.escape(title)))
        narrative = s.get("narrative") or ""
        if narrative:
            parts.append(
                '<p>{n}</p>'.format(
                    n=html.escape(narrative).replace("\n",
                                                       "<br/>")))
        checklist = s.get("checklist") or []
        if checklist:
            parts.append("<ul>")
            for item in checklist:
                parts.append(
                    "<li>{i}</li>".format(
                        i=html.escape(item or "")))
            parts.append("</ul>")
    parts.append("</div>")
    return "\n".join(parts)


def _call_times_block(times):
    if not times:
        return ""
    rows = []
    for t in times:
        rows.append(
            '<tr><td>{n}</td><td>{r}</td><td>{c}</td><td>{d}</td>'
            '</tr>'.format(
                n=html.escape((t or {}).get("crew_partner_name")
                                or ""),
                r=html.escape((t or {}).get("role") or ""),
                c=html.escape((t or {}).get("call_at") or ""),
                d=html.escape((t or {}).get("duty") or "")))
    return (
        '<h4 style="color:#5B2A8A;margin-top:18px;">'
        'Crew call times</h4>'
        '<table class="table table-sm">'
        '<thead><tr><th>Crew</th><th>Role</th>'
        '<th>Call at</th><th>Duty</th></tr></thead>'
        '<tbody>{rows}</tbody></table>'
    ).format(rows="".join(rows))


def _empty_placeholder(status):
    return (
        '<div class="alert alert-secondary" role="alert">'
        'No plan content yet. Status: <em>{s}</em>. '
        'Click "Generate" to produce one.'
        '</div>'
    ).format(s=html.escape(status or "draft"))


def _error_placeholder(msg):
    return (
        '<div class="alert alert-danger" role="alert">'
        '<strong>Render error:</strong> {m}'
        '</div>'
    ).format(m=html.escape(msg or ""))
