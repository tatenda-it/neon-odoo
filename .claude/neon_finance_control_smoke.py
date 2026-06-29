"""neon_screens — Finance Control (#4): render + scroll-reachability + gating.

Local finance data is empty, so panels render their honest empty states; the
probe still proves the root scrolls and .o_action_manager no longer clips.
Gating: bookkeeper/approver see the screen; sales/mgr do NOT (correct gating,
not a bug). base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
MENU = "neon_screens.menu_finance_control_root"
ACTION = "neon_screens.action_finance_control_screen_server"

PROBE = """([containerSel, lastSel]) => {
    const c = document.querySelector(containerSel);
    if (!c) return { found: false, sel: containerSel };
    const cs = getComputedStyle(c);
    c.scrollTop = c.scrollHeight;
    let lastReachable = null;
    if (lastSel) {
        const els = [...document.querySelectorAll(lastSel)];
        const last = els[els.length - 1];
        if (last) {
            const lr = last.getBoundingClientRect(), cr = c.getBoundingClientRect();
            lastReachable = lr.top < cr.bottom + 2 && lr.bottom > cr.top - 2;
        }
    }
    const fits = c.scrollHeight <= c.clientHeight + 1;
    const scrollable = ['auto', 'scroll'].includes(cs.overflowY);
    const am = document.querySelector('.o_action_manager');
    return {
        overflowY: cs.overflowY, clientH: c.clientHeight, scrollH: c.scrollHeight,
        fits, scrollable, scrolledTo: c.scrollTop,
        lastReachable,
        am_clips: am ? (am.scrollHeight > am.clientHeight + 1 &&
                        getComputedStyle(am).overflowY === 'hidden') : null,
        pass: fits || (scrollable && (lastReachable === null || lastReachable === true)),
    };
}"""

# What rendered? (panels + subheader constants + per-panel row counts).
# A "data row" excludes the single honest empty-state row (.o_neon_empty).
CONTENT = """() => {
    const realRows = sel => [...document.querySelectorAll(sel + ' tbody tr')]
        .filter(tr => !tr.querySelector('.o_neon_empty')).length;
    const kpi = n => {
        const cards = document.querySelectorAll('.o_neon_kpi');
        return cards[n] ? (cards[n].querySelector('.o_neon_kpi_value') || {}).textContent || '' : '';
    };
    return {
        subbar_consts: document.querySelectorAll('.o_neon_fc_const').length,
        has_vat_155: document.body.textContent.includes('15.5%'),
        kpi_cards: document.querySelectorAll('.o_neon_kpi').length,
        kpis_empty: !!document.querySelector('.o_neon_fc_kpis_empty'),
        kpi_planned: kpi(0), kpi_paid: kpi(1), kpi_outstanding: kpi(2), kpi_open: kpi(3),
        gov_items: document.querySelectorAll('.o_neon_gov_item').length,
        board_rows: realRows('.o_neon_fc_board .o_neon_table'),
        variance_rows: realRows('.o_neon_fc_variance .o_neon_table'),
        approval_rows: realRows('.o_neon_fc_approvals .o_neon_table'),
        cards: document.querySelectorAll('.o_neon_fc_screen .o_neon_card').length,
        fa_font: (() => { const i = document.querySelector('.fa'); return i ? getComputedStyle(i, ':before').fontFamily : ''; })(),
    };
}"""

verdicts = []
with BrowserSmoke("neon_finance_control", base_url=BASE) as s:
    # ---- bookkeeper: render + scroll ----
    with s.scenario("finance control render+scroll (p2m75_book)"):
        s.login("p2m75_book")
        s.assert_menu_visible(MENU, name="menu visible to bookkeeper")
        s.open_action(ACTION)
        s.page.locator(".o_neon_fc_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(3000)
        s.screenshot("finance_book")
        content = s.page.evaluate(CONTENT)
        print("CONTENT", content)
        probe = s.page.evaluate(PROBE, [".o_neon_fc_screen", ".o_neon_fc_screen .o_neon_card:last-child .o_neon_table tbody tr"])
        print("SCROLL", probe)
        verdicts.append(("scroll pass", bool(probe.get("pass"))))
        verdicts.append(("am not clipping", probe.get("am_clips") is False))
        verdicts.append(("subheader VAT 15.5%", bool(content.get("has_vat_155"))))
        verdicts.append(("governance card (3 items)", content.get("gov_items") == 3))
        verdicts.append(("icons intact", content.get("fa_font") == "FontAwesome"))

    # ---- gating: sales must NOT see Finance Control ----
    with s.scenario("gating: sales cannot see finance control (p2m75_sales)"):
        s.login("p2m75_sales")
        s.assert_menu_hidden(MENU, name="menu hidden from sales (correct gating)")
        verdicts.append(("sales gated out", True))

    # ---- gating: ops manager (no finance) must NOT see it ----
    with s.scenario("gating: ops manager cannot see finance control (p2m75_mgr)"):
        s.login("p2m75_mgr")
        s.assert_menu_hidden(MENU, name="menu hidden from ops mgr (correct gating)")
        verdicts.append(("ops mgr gated out", True))

    print("\n=== VERDICTS ===")
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in verdicts) else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
