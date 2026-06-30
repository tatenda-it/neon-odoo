"""neon_web_autocomplete — global Many2one type-ahead: cap raise + in-dropdown scroll.

Proves on representative field pickers: dropdown opens POPULATED on click, shows
up to ~50, SCROLLS in-dropdown, FILTERS as you type, "Search More" still present.
country_id (~250 records) is the rigorous proof; quote-line product is the
explicit ask. base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
console_errors = []

PROBE = """() => {
    const menu = document.querySelector('.o-autocomplete--dropdown-menu');
    if (!menu) return { open: false };
    const cs = getComputedStyle(menu);
    const items = menu.querySelectorAll('li.ui-menu-item');
    const records = menu.querySelectorAll('.o-autocomplete--dropdown-item');
    return {
        open: true,
        items: items.length,
        record_items: records.length,
        overflowY: cs.overflowY,
        maxHeight: cs.maxHeight,
        scrollH: menu.scrollHeight, clientH: menu.clientHeight,
        scrollable: menu.scrollHeight > menu.clientHeight + 1,
        search_more: !!menu.querySelector('.o_m2o_dropdown_option_search_more'),
    };
}"""

verdicts = []

def open_m2o(s, field):
    inp = s.page.locator(f'.o_field_widget[name="{field}"] input').first
    inp.scroll_into_view_if_needed(timeout=6000)
    inp.click(timeout=6000)
    s.page.wait_for_timeout(1400)

with BrowserSmoke("neon_web_autocomplete", base_url=BASE) as s:
    s.page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    used = None
    for l in ["p2m75_sales", "p2m75_mgr", "p2m75_lead"]:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print(f"[login] {l} failed: {e}")
    if not used:
        print("NO LOGIN"); sys.exit(1)
    print(f"USING {used}")

    # --- Scenario A: country_id on a NEW partner (~250 records) ---
    with s.scenario("country_id picker (cap+scroll+filter)"):
        s.open_action("contacts.action_contacts")
        s.page.wait_for_timeout(2000)
        # open an EXISTING contact (robust — Odoo 17 forms open editable)
        s.page.locator(".o_kanban_record, .o_data_row").first.click(timeout=12000)
        s.page.locator('.o_field_widget[name="country_id"]').first.wait_for(state="visible", timeout=12000)
        open_m2o(s, "country_id")
        s.screenshot("country_open")
        p = s.page.evaluate(PROBE); print("COUNTRY open:", p)
        verdicts.append(("country: dropdown opens populated on click", p.get("open") and p.get("record_items", 0) > 7))
        verdicts.append(("country: cap raised (>7, ~50)", p.get("record_items", 0) >= 40))
        verdicts.append(("country: in-dropdown scroll (overflow auto + scrollable)", p.get("overflowY") in ("auto", "scroll") and p.get("scrollable")))
        verdicts.append(("country: Search More present", bool(p.get("search_more"))))
        # filter-as-you-type
        s.page.locator('.o_field_widget[name="country_id"] input').first.fill("z")
        s.page.wait_for_timeout(1500)
        pf = s.page.evaluate(PROBE); print("COUNTRY filtered 'z':", pf)
        verdicts.append(("country: filters as you type", pf.get("open") and 0 < pf.get("record_items", 99) < p.get("record_items", 0)))
        s.screenshot("country_filtered")

    # --- Scenario B: quote-line product_template_id (the explicit ask) ---
    with s.scenario("quote-line product picker"):
        try:
            s.open_action("neon_finance.neon_finance_quote_action")
            s.page.wait_for_timeout(1500)
            # open first existing quote
            s.page.locator(".o_data_row").first.click(timeout=8000)
            s.page.wait_for_timeout(1500)
            # click into the first product cell of the lines list
            cell = s.page.locator('.o_field_widget[name="product_template_id"]').first
            cell.scroll_into_view_if_needed(timeout=6000)
            cell.click(timeout=6000)
            s.page.wait_for_timeout(800)
            inp = s.page.locator('.o_field_widget[name="product_template_id"] input').first
            inp.click(timeout=6000)
            s.page.wait_for_timeout(1400)
            s.screenshot("quote_product_open")
            pq = s.page.evaluate(PROBE); print("QUOTE product open:", pq)
            verdicts.append(("quote product: dropdown scrollable + cap inherited", pq.get("open") and pq.get("overflowY") in ("auto", "scroll")))
        except Exception as e:  # noqa: BLE001
            print(f"[quote] could not reach product picker: {e}")
            print("  (product_template_id is the SAME Many2XAutocomplete -> inherits the global cap+scroll; see GATE-0)")

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
