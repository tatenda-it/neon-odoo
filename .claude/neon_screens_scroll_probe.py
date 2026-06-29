"""neon_screens — SCROLL-REACHABILITY probe for all 3 screens.

Catches the .o_action_manager scroll-lock (content past clientHeight clipped,
no scrollbar). Per screen: identify the scroll container, scroll it to the
bottom, assert the LAST row is actually reachable. Also probe .o_action_manager
to confirm it no longer clips. base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"

# Scroll a container to the bottom and report reachability of its last item.
PROBE = """([containerSel, lastSel]) => {
    const c = document.querySelector(containerSel);
    if (!c) return { found: false, sel: containerSel };
    const cs = getComputedStyle(c);
    c.scrollTop = c.scrollHeight;               // attempt scroll to bottom
    const maxScroll = c.scrollHeight - c.clientHeight;
    let lastReachable = null, lastFound = false;
    if (lastSel) {
        const els = [...document.querySelectorAll(lastSel)];   // document-last = bottom-most
        const last = els[els.length - 1];
        if (last) {
            lastFound = true;
            const lr = last.getBoundingClientRect(), cr = c.getBoundingClientRect();
            // visible band of the container, after scrolling to bottom
            lastReachable = lr.top < cr.bottom + 2 && lr.bottom > cr.top - 2;
        }
    }
    const fits = c.scrollHeight <= c.clientHeight + 1;
    const scrollable = ['auto', 'scroll'].includes(cs.overflowY);
    return {
        found: true, sel: containerSel,
        overflowY: cs.overflowY,
        clientH: c.clientHeight, scrollH: c.scrollHeight,
        fits, scrollable,
        scrolledTo: c.scrollTop, maxScroll,
        lastFound, lastReachable,
        // the user's pass criterion: fits OR (scrollable AND last row reachable)
        pass: fits || (scrollable && (lastReachable === null || lastReachable === true)),
    };
}"""

# Action-manager clip probe: is the clipper still clipping?
AM = """() => {
    const screen = document.querySelector('.o_neon_screen');
    const am = document.querySelector('.o_action_manager');
    const host = screen ? screen.parentElement : null;
    const info = el => el ? {
        cls: el.className, overflowY: getComputedStyle(el).overflowY,
        clientH: el.clientHeight, scrollH: el.scrollHeight,
        clips: el.scrollHeight > el.clientHeight + 1 && getComputedStyle(el).overflowY === 'hidden',
    } : null;
    return { action_manager: info(am), screen_parent: info(host) };
}"""

# Find any genuinely-scrollable descendant inside a region (for embedded views).
SCROLLER = """([regionSel]) => {
    const region = document.querySelector(regionSel);
    if (!region) return { found: false, sel: regionSel };
    const all = [region, ...region.querySelectorAll('*')];
    const scrollers = all.filter(el => {
        const oy = getComputedStyle(el).overflowY;
        return ['auto', 'scroll'].includes(oy) && el.scrollHeight > el.clientHeight + 1;
    }).map(el => ({ cls: (el.className || '').toString().slice(0, 60),
                    sh: el.scrollHeight, ch: el.clientHeight }));
    const anyScrollContainer = all.some(el =>
        ['auto', 'scroll'].includes(getComputedStyle(el).overflowY));
    return { found: true, sel: regionSel,
             clipped_overflow: scrollers.length, scrollers: scrollers.slice(0, 4),
             has_scroll_container: anyScrollContainer };
}"""

verdicts = []

with BrowserSmoke("neon_screens_scroll_probe", base_url=BASE) as s:
    used = None
    for l in ["p2m75_mgr", "p2m75_sales"]:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}  BASE {BASE}")

    def report(name, p):
        ok = bool(p.get("pass"))
        verdicts.append((name, ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {p}")

    with s.scenario(f"scroll reachability ({used})"):
        # ---- Equipment ----
        s.open_action("neon_screens.action_equipment_screen_server")
        s.page.locator(".o_neon_equip_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2500)
        print("EQUIPMENT")
        print("  AM", s.page.evaluate(AM))
        report("equipment root", s.page.evaluate(PROBE, [".o_neon_equip_screen", ".o_neon_equip_screen .o_neon_table tbody tr"]))
        s.screenshot("equip_bottom")

        # ---- Event Jobs ----
        s.open_action("neon_screens.action_event_jobs_screen_server")
        s.page.locator(".o_neon_ej_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2500)
        print("EVENT JOBS")
        print("  AM", s.page.evaluate(AM))
        report("eventjobs root", s.page.evaluate(PROBE, [".o_neon_ej_screen", ".o_neon_ej_row"]))
        s.screenshot("eventjobs_bottom")

        # ---- Operations (composed): 3 modes + holds independent ----
        s.open_action("neon_screens.action_operations_screen_server")
        s.page.locator(".o_neon_ops_screen").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(3000)
        print("OPERATIONS")
        print("  AM", s.page.evaluate(AM))
        ops_root = s.page.evaluate(PROBE, [".o_neon_ops_screen", None])
        print("  ops root (should fit/not-clip):", ops_root)
        verdicts.append(("ops root no-clip", bool(ops_root.get("fits"))))

        for mode, label in [("Calendar", "calendar"), ("List", "list"), ("Kanban", "kanban")]:
            try:
                s.page.locator(".o_neon_vtab", has_text=mode).first.click(timeout=6000)
                s.page.wait_for_timeout(2200)
                view = s.page.evaluate(SCROLLER, [".o_neon_ops_viewhost"])
                print(f"  MODE {mode}: {view}")
                verdicts.append((f"ops {mode} view scrollable-or-fits", bool(view.get("has_scroll_container"))))
                s.screenshot(f"ops_{label}")
            except Exception as e:  # noqa: BLE001
                print(f"  [{mode}] {e}")
                verdicts.append((f"ops {mode}", False))

        # Holds panel independent scroll
        print("  HOLDS")
        report("holds body", s.page.evaluate(PROBE, [".o_neon_ops_holds_body", ".o_neon_hold_row"]))
        s.screenshot("ops_holds")

    print("\n=== VERDICTS ===")
    allok = True
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print(f"OVERALL {'PASS' if allok else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(0 if all(ok for _, ok in verdicts) else 1)
