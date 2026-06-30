"""neon_screens — Crew & People (#6): render + scroll-reachability + gating.

Honest directory over neon.crew.member. Local has 0 crew_member rows -> the
directory renders its honest empty state locally; the real 22 verify on prod.
Gating: neon_jobs user/manager/crew_leader see it; basic crew does NOT.
base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
MENU = "neon_screens.menu_crew_people_root"
ACTION = "neon_screens.action_crew_people_screen_server"

PROBE = """([lastSel]) => {
    const c = document.querySelector('.o_neon_crew_screen');
    if (!c) return { found: false };
    const cs = getComputedStyle(c);
    c.scrollTop = c.scrollHeight;
    let lastReachable = null;
    const els = [...document.querySelectorAll(lastSel)];
    const last = els[els.length - 1];
    if (last) {
        const lr = last.getBoundingClientRect(), cr = c.getBoundingClientRect();
        lastReachable = lr.top < cr.bottom + 2 && lr.bottom > cr.top - 2;
    }
    const am = document.querySelector('.o_action_manager');
    return {
        overflowY: cs.overflowY, clientH: c.clientHeight, scrollH: c.scrollHeight,
        fits: c.scrollHeight <= c.clientHeight + 1,
        scrollable: ['auto','scroll'].includes(cs.overflowY),
        lastReachable,
        am_clips: am ? (am.scrollHeight > am.clientHeight + 1 && getComputedStyle(am).overflowY === 'hidden') : null,
        pass: (c.scrollHeight <= c.clientHeight + 1) || (['auto','scroll'].includes(cs.overflowY) && (lastReachable === null || lastReachable === true)),
    };
}"""

CONTENT = """() => {
    const realRows = [...document.querySelectorAll('.o_neon_crew_screen .o_neon_table tbody tr')]
        .filter(tr => !tr.querySelector('.o_neon_crew_empty'));
    return {
        rows: realRows.length,
        empty_state: !!document.querySelector('.o_neon_crew_empty'),
        chips: (document.querySelector('.o_neon_crew_chips') || {}).textContent || '',
        note_present: !!document.querySelector('.o_neon_crew_note'),
        has_score_text: /\\bscore\\b/i.test((document.querySelector('.o_neon_table') || {}).textContent || ''),
        fa_font: (() => { const i = document.querySelector('.fa'); return i ? getComputedStyle(i, ':before').fontFamily : ''; })(),
    };
}"""

verdicts = []
with BrowserSmoke("neon_crew_people", base_url=BASE) as s:
    fin = None
    with s.scenario("crew & people render + scroll (ops user)"):
        for cand in ["p2m75_mgr", "p2m75_lead", "p2m75_sales", "p2m75_mgr", "p2m75_lead"]:
            try:
                s.login(cand); fin = cand; break
            except Exception as e:  # noqa: BLE001
                print(f"[login] {cand} failed: {e}")
        if not fin:
            raise AssertionError("no ops fixture logged in")
        print(f"OPS_USER {fin}")
        s.assert_menu_visible(MENU, name=f"menu visible to {fin}")
        s.open_action(ACTION)
        s.page.locator(".o_neon_crew_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(3000)
        s.screenshot("crew_people")
        content = s.page.evaluate(CONTENT); print("CONTENT", content)
        probe = s.page.evaluate(PROBE, [".o_neon_crew_screen .o_neon_table tbody tr"]); print("SCROLL", probe)
        verdicts.append(("scroll pass", bool(probe.get("pass"))))
        verdicts.append(("am not clipping", probe.get("am_clips") is False))
        verdicts.append(("table rendered", content.get("rows", 0) > 0 or content.get("empty_state")))
        verdicts.append(("NO score column (honest)", not content.get("has_score_text")))
        verdicts.append(("honest deferral note present", bool(content.get("note_present"))))
        verdicts.append(("icons intact", content.get("fa_font") == "FontAwesome"))

    with s.scenario("gating: basic crew cannot see Crew & People"):
        gated = None
        for cand in ["p2m75_crew", "p2m75_book", "p2m75_other"]:
            try:
                s.login(cand); gated = cand; break
            except Exception as e:  # noqa: BLE001
                print(f"[login] {cand} failed: {e}")
        if gated:
            print(f"GATED_USER {gated}")
            s.assert_menu_hidden(MENU, name=f"menu hidden from {gated} (correct gating)")
            verdicts.append(("gated out", True))

    print("\n=== VERDICTS ===")
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in verdicts) else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
