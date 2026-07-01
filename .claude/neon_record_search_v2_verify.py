"""neon_web_record_search v2 — primary-search-box behaviour + safety verify.

Proves on a real control panel: ONE visible search box (record-search in the
primary spot, native facet input hidden), placeholder "Search…", no corner box;
click -> list appears, type -> narrows, gibberish -> "No records found"; the
Filters button + facet chips still work (apply a filter -> chip appears). Saves
a screenshot at each step for Tatenda's eyeball gate. base_url via argv[1].
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
console_errors = []
V = []

with BrowserSmoke("neon_web_record_search_v2", base_url=BASE) as s:
    s.page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    used = None
    for l in ["p2m75_mgr", "p2m75_sales"]:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l}: {e}")
    print("USING", used)

    with s.scenario("Contacts: one clean search box + behaviour"):
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2500)

        layout = s.page.evaluate("""() => {
            const rec = document.querySelector('.o_cp_searchview .o_neon_recsearch input');
            const nativeInp = document.querySelector('.o_cp_searchview .o_searchview_input');
            const filtersBtn = document.querySelector('.o_cp_searchview .o_searchview_dropdown_toggler');
            const cornerBox = document.querySelector('.o_control_panel_navigation .o_neon_recsearch');
            const vis = (el) => !!el && el.offsetParent !== null;
            return {
                recsearch_in_primary: !!rec,
                recsearch_visible: vis(rec),
                placeholder: rec ? rec.getAttribute('placeholder') : null,
                native_input_present: !!nativeInp,
                native_input_hidden: !!nativeInp && !vis(nativeInp),
                filters_button_visible: vis(filtersBtn),
                corner_box_gone: !cornerBox,
            };
        }""")
        print("LAYOUT:", layout)
        V.append(("record-search is in the primary search box", layout["recsearch_in_primary"] and layout["recsearch_visible"]))
        V.append(('placeholder is "Search…"', (layout["placeholder"] or "").startswith("Search")))
        V.append(("native facet input hidden (one visible search)", layout["native_input_hidden"]))
        V.append(("Filters button still visible", layout["filters_button_visible"]))
        V.append(("no corner box in control-panel navigation", layout["corner_box_gone"]))
        s.screenshot("v2_01_one_clean_box")

        # click -> list appears
        s.page.locator(".o_cp_searchview .o_neon_recsearch input").first.click(timeout=8000)
        s.page.wait_for_timeout(1500)
        d1 = s.page.evaluate("""() => {const m=document.querySelector('.o_neon_recsearch .o-autocomplete--dropdown-menu');
            return {open:!!m, n: m?m.querySelectorAll('.o-autocomplete--dropdown-item').length:0};}""")
        print("CLICK -> list:", d1)
        V.append(("click shows the record list", d1["open"] and d1["n"] > 1))
        s.screenshot("v2_02_click_shows_list")

        # type -> narrows
        s.page.locator(".o_cp_searchview .o_neon_recsearch input").first.fill("rob")
        s.page.wait_for_timeout(1500)
        d2 = s.page.evaluate("""() => {const m=document.querySelector('.o_neon_recsearch .o-autocomplete--dropdown-menu');
            const items=m?[...m.querySelectorAll('.o-autocomplete--dropdown-item')].map(e=>e.textContent.trim()):[];
            return {open:!!m, n: items.length, sample: items.slice(0,5)};}""")
        print("TYPE 'rob' -> narrowed:", d2)
        V.append(("typing narrows the list", d2["open"] and 0 < d2["n"] <= d1["n"]))
        s.screenshot("v2_03_type_narrows")

        # gibberish -> "No records found"
        s.page.locator(".o_cp_searchview .o_neon_recsearch input").first.fill("zzzqxq")
        s.page.wait_for_timeout(1500)
        d3 = s.page.evaluate("""() => {const m=document.querySelector('.o_neon_recsearch .o-autocomplete--dropdown-menu');
            const items=m?[...m.querySelectorAll('.o-autocomplete--dropdown-item')].map(e=>e.textContent.trim()):[];
            return {open:!!m, items};}""")
        print("TYPE gibberish -> empty-state:", d3)
        V.append(('zero result shows "No records found"', d3["open"] and any("No records found" in t for t in d3["items"])))
        s.screenshot("v2_04_empty_state")

        # click a real record -> form opens
        s.page.locator(".o_cp_searchview .o_neon_recsearch input").first.fill("rob")
        s.page.wait_for_timeout(1500)
        s.page.locator(".o_neon_recsearch .o-autocomplete--dropdown-item").first.click(timeout=8000)
        try:
            s.page.locator(".o_form_view").first.wait_for(state="visible", timeout=12000)
            V.append(("click a record opens its form", True))
            s.screenshot("v2_05_opened_form")
        except Exception as e:  # noqa: BLE001
            print("form open:", e); V.append(("click a record opens its form", False))

    with s.scenario("Contacts: facet machinery (Filters menu + chips) still works"):
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2000)
        # open the Filters / Group By / Favorites dropdown
        s.page.locator(".o_cp_searchview .o_searchview_dropdown_toggler").first.click(timeout=8000)
        s.page.wait_for_timeout(1200)
        menu = s.page.evaluate("""() => {const m=document.querySelector('.o_search_bar_menu');
            return {open:!!m, hasFilters: !!document.querySelector('.o_filter_menu'),
                    hasGroupBy: !!document.querySelector('.o_group_by_menu'),
                    hasFavorites: !!document.querySelector('.o_favorite_menu')};}""")
        print("FILTERS MENU:", menu)
        V.append(("Filters menu opens with Filters/Group By/Favorites", menu["open"] and menu["hasFilters"] and menu["hasGroupBy"]))
        s.screenshot("v2_06_filters_menu")
        # apply the first filter checkbox -> a facet chip should appear
        before = s.page.evaluate("() => document.querySelectorAll('.o_searchview_facet').length")
        try:
            s.page.locator(".o_filter_menu .o_menu_item, .o_filter_menu .dropdown-item").first.click(timeout=6000)
            s.page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001
            print("filter click:", e)
        chips = s.page.evaluate("""() => {const c=[...document.querySelectorAll('.o_searchview_facet')];
            return {n: c.length, visible: c.some(e=>e.offsetParent!==null), labels: c.map(e=>e.textContent.trim()).slice(0,4)};}""")
        print(f"CHIPS before={before} after={chips}")
        V.append(("applying a filter adds a visible facet chip (filters work + chips visible)", chips["n"] > before and chips["visible"]))
        s.screenshot("v2_07_filter_applied_chip")

    with s.scenario("Event Jobs: renders in primary spot too"):
        s.page.goto(f"{BASE}/web", wait_until="networkidle")
        s.open_action("neon_jobs.commercial_event_job_action")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2000)
        ej = s.page.evaluate("""() => {const r=document.querySelector('.o_cp_searchview .o_neon_recsearch input');
            return {present:!!r, visible: !!r && r.offsetParent!==null};}""")
        print("EVENT JOBS:", ej)
        V.append(("record-search renders primary on Event Jobs", ej["present"] and ej["visible"]))
        s.screenshot("v2_08_eventjobs")

    real = [e for e in console_errors if e]
    print(f"\nCONSOLE_ERRORS {len(real)}")
    for e in real[:8]:
        print("  CERR:", e)
    print("=== VERDICTS ===")
    for n, ok in V:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in V) else 'FAIL'} | console_errors={len(real)}")
    print("SHOTS:", s.output_dir)

sys.exit(s.summary())
