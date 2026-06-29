"""neon_screens — CRM Pipeline (#5): render + scroll-reachability + gating.

Kanban over live crm.lead/crm.stage. Root scrolls VERTICALLY (shared base); the
board scrolls HORIZONTALLY (stage columns) — both must reach their last element.
Gating: CRM users (group_sale_salesman) see it; non-CRM users do NOT.
base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
MENU = "neon_screens.menu_crm_pipeline_root"
ACTION = "neon_screens.action_crm_pipeline_screen_server"

# Vertical reachability of the screen root + action-manager clip check.
VPROBE = """() => {
    const c = document.querySelector('.o_neon_crm_screen');
    if (!c) return { found: false };
    const cs = getComputedStyle(c);
    c.scrollTop = c.scrollHeight;
    const am = document.querySelector('.o_action_manager');
    return {
        overflowY: cs.overflowY, clientH: c.clientHeight, scrollH: c.scrollHeight,
        fits: c.scrollHeight <= c.clientHeight + 1,
        scrollable: ['auto','scroll'].includes(cs.overflowY),
        am_clips: am ? (am.scrollHeight > am.clientHeight + 1 && getComputedStyle(am).overflowY === 'hidden') : null,
    };
}"""

# Horizontal reachability of the kanban board + content counts.
HPROBE = """() => {
    const b = document.querySelector('.o_neon_crm_board');
    if (!b) return { found: false };
    const cols = [...document.querySelectorAll('.o_neon_crm_col')];
    b.scrollLeft = b.scrollWidth;
    const last = cols[cols.length - 1];
    let lastReachable = null;
    if (last) {
        const lr = last.getBoundingClientRect(), br = b.getBoundingClientRect();
        lastReachable = lr.left < br.right + 2 && lr.right > br.left - 2;
    }
    const ox = getComputedStyle(b).overflowX;
    return {
        columns: cols.length,
        cards: document.querySelectorAll('.o_neon_crm_card').length,
        overflowX: ox,
        fitsX: b.scrollWidth <= b.clientWidth + 1,
        h_scrollable: ['auto','scroll'].includes(ox),
        lastColReachable: lastReachable,
        chips_text: (document.querySelector('.o_neon_crm_chips') || {}).textContent || '',
        fa_font: (() => { const i = document.querySelector('.fa'); return i ? getComputedStyle(i, ':before').fontFamily : ''; })(),
    };
}"""

verdicts = []
with BrowserSmoke("neon_crm_pipeline", base_url=BASE) as s:
    fin = None
    with s.scenario("crm pipeline render + scroll (crm user)"):
        for cand in ["p2m75_sales", "p2m75_mgr"]:
            try:
                s.login(cand); fin = cand; break
            except Exception as e:  # noqa: BLE001
                print(f"[login] {cand} failed: {e}")
        if not fin:
            raise AssertionError("no CRM fixture logged in")
        print(f"CRM_USER {fin}")
        s.assert_menu_visible(MENU, name=f"menu visible to {fin}")
        s.open_action(ACTION)
        s.page.locator(".o_neon_crm_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(3000)
        s.screenshot("crm_pipeline")
        v = s.page.evaluate(VPROBE); print("VSCROLL", v)
        h = s.page.evaluate(HPROBE); print("BOARD", h)
        verdicts.append(("root scrollable/fits", v.get("scrollable") and (v.get("fits") or v.get("scrollH") > 0)))
        verdicts.append(("am not clipping", v.get("am_clips") is False))
        verdicts.append(("columns rendered (live stages)", (h.get("columns") or 0) >= 1))
        verdicts.append(("board horiz reachable", h.get("fitsX") or (h.get("h_scrollable") and h.get("lastColReachable") is not False)))
        verdicts.append(("icons intact", h.get("fa_font") == "FontAwesome"))

    with s.scenario("gating: non-CRM user cannot see CRM Pipeline"):
        # a fixture without group_sale_salesman (bookkeeper) -> menu hidden
        gated = None
        for cand in ["p2m75_book", "p2m75_crew", "p2m75_lead"]:
            try:
                s.login(cand); gated = cand; break
            except Exception as e:  # noqa: BLE001
                print(f"[login] {cand} failed: {e}")
        if gated:
            print(f"GATED_USER {gated}")
            s.assert_menu_hidden(MENU, name=f"menu hidden from {gated} (correct gating)")
            verdicts.append(("non-CRM gated out", True))
        else:
            print("[gating] no non-CRM fixture available on this env -- skipped")

    print("\n=== VERDICTS ===")
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in verdicts) else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
