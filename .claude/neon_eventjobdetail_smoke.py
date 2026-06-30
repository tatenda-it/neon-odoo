"""neon_screens — Event Job Detail (#10): row-click drill-down + panels + scroll.

CRITICAL: opening the detail as a non-Training ops user (p2m75_mgr) must NOT
trip the pre-existing neon_training access-error (the detail reads via RPC and
renders OWL, never the native form). base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
console_errors = []

PROBE = """() => {
    const c = document.querySelector('.o_neon_ejd_screen');
    if (!c) return { found: false };
    const cs = getComputedStyle(c);
    c.scrollTop = c.scrollHeight;
    const am = document.querySelector('.o_action_manager');
    // access-error / any blocking dialog visible?
    const dlgTxt = [...document.querySelectorAll('.o_dialog, .modal, .o_error_dialog')]
        .map(d => (d.textContent || '')).join(' ');
    return {
        found: true, overflowY: cs.overflowY, clientH: c.clientHeight, scrollH: c.scrollHeight,
        scrollable: ['auto','scroll'].includes(cs.overflowY),
        fits: c.scrollHeight <= c.clientHeight + 1,
        am_clips: am ? (am.scrollHeight > am.clientHeight + 1 && getComputedStyle(am).overflowY === 'hidden') : null,
        access_error: /access error|not allowed|assignment_gate_log|Neon Training/i.test(dlgTxt),
        panels: {
            header: !!document.querySelector('.o_neon_ejd_header'),
            timeline: document.querySelectorAll('.o_neon_ejd_tl_stage').length,
            equipment_card: /Equipment Allocation/.test(document.body.textContent),
            costing_card: /Budget vs Actual/.test(document.body.textContent),
            crew_card: /Assigned Crew/.test(document.body.textContent),
            commercial_card: /ZIMRA BP/.test(document.body.textContent),
            vat_155: /15\\.5%/.test(document.body.textContent),
        },
        brief_enabled: (() => { const b = [...document.querySelectorAll('.o_neon_ejd_actions button')].find(b => /Brief crew/.test(b.textContent)); return b ? !b.disabled : null; })(),
        aiplan_disabled: (() => { const b = [...document.querySelectorAll('.o_neon_ejd_actions button')].find(b => /AI plan/.test(b.textContent)); return b ? b.disabled : null; })(),
        fa_font: (() => { const i = document.querySelector('.fa'); return i ? getComputedStyle(i, ':before').fontFamily : ''; })(),
    };
}"""

MODAL = """() => {
    const ta = document.querySelector('.o_neon_ejd_brief_text');
    return {
        modal_open: !!document.querySelector('.o_neon_ejd_modal'),
        text: ta ? (ta.value || ta.textContent || '') : '',
        nosend_note: /Nothing is sent automatically/i.test(
            (document.querySelector('.o_neon_ejd_modal') || {}).textContent || ''),
        has_copy: !!document.querySelector('.o_neon_ejd_foot_btns .btn-primary'),
    };
}"""

verdicts = []
with BrowserSmoke("neon_eventjobdetail", base_url=BASE) as s:
    s.page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    used = None
    for cand in ["p2m75_mgr", "p2m75_lead", "p2m75_sales"]:
        try:
            s.login(cand); used = cand; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {cand} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used} (non-Training ops user)")

    with s.scenario(f"event job detail via row-click ({used})"):
        # open the Event Jobs LIST, then CLICK a row -> detail (the real path)
        s.open_action("neon_screens.action_event_jobs_screen_server")
        s.page.locator(".o_neon_ej_row").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(1500)
        s.page.locator(".o_neon_ej_row").first.click(timeout=8000)
        try:
            s.page.locator(".o_neon_ejd_screen").first.wait_for(state="visible", timeout=15000)
        except Exception as e:  # noqa: BLE001
            print(f"[detail] render wait: {e}")
        s.page.wait_for_timeout(2500)
        s.screenshot("detail_via_rowclick")
        probe = s.page.evaluate(PROBE)
        print("PROBE", probe)
        verdicts.append(("detail rendered from row-click", bool(probe.get("found"))))
        verdicts.append(("NO neon_training access-error", probe.get("access_error") is False))
        verdicts.append(("scroll pass", bool(probe.get("fits") or probe.get("scrollable"))))
        verdicts.append(("am not clipping", probe.get("am_clips") is False))
        p = probe.get("panels", {})
        verdicts.append(("all 5 panels present", all([p.get("header"), p.get("equipment_card"),
                         p.get("costing_card"), p.get("crew_card"), p.get("commercial_card")])))
        verdicts.append(("timeline 4 stages", p.get("timeline") == 4))
        verdicts.append(("VAT 15.5%", bool(p.get("vat_155"))))
        verdicts.append(("icons intact", probe.get("fa_font") == "FontAwesome"))
        # Brief crew = draft-only (enabled, opens preview); AI plan = deferred
        verdicts.append(("Brief crew button ENABLED", probe.get("brief_enabled") is True))
        verdicts.append(("AI plan button DEFERRED (disabled)", probe.get("aiplan_disabled") is True))
        s.page.locator(".o_neon_ejd_actions button", has_text="Brief crew").first.click(timeout=8000)
        s.page.locator(".o_neon_ejd_modal").first.wait_for(state="visible", timeout=8000)
        s.page.wait_for_timeout(1500)
        s.screenshot("brief_draft_modal")
        modal = s.page.evaluate(MODAL)
        _m = {k: (v[:60] if k == "text" else v) for k, v in modal.items()}
        print("MODAL", str(_m).encode("ascii", "replace").decode("ascii"))
        verdicts.append(("brief preview opens", bool(modal.get("modal_open"))))
        verdicts.append(("brief composed from real data", "Event Brief" in (modal.get("text") or "")))
        verdicts.append(("no-auto-send note shown", bool(modal.get("nosend_note"))))

    real = [e for e in console_errors if e]
    print(f"CONSOLE_ERRORS {len(real)}")
    for e in real[:8]:
        print("  CERR:", e)
    print("\n=== VERDICTS ===")
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in verdicts) else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
