"""Track B verify: neon_quote_item picker on the quote-line product field.

Create a new quote -> add a line -> click the product picker:
- FULL item list on click (uncapped; local ~53 products > old 50 cap), scrollable.
- Rate sub-label (.o_neon_item_rate) on EVERY row (my optionTemplate applied).
- Typing matches across the full list (uncapped).
- Leak check: Contacts list still scrolls (renderer overflow auto).
- 0 console errors. base_url via argv[1].
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
errs = []
V = []

def dropdown(s):
    return s.page.evaluate(r"""() => {
        const m = document.querySelector('.o-autocomplete--dropdown-menu');
        if (!m) return {open:false};
        const items = [...m.querySelectorAll('.o-autocomplete--dropdown-item')];
        const opts = [...m.querySelectorAll('.o_neon_item_option')];
        const rates = [...m.querySelectorAll('.o_neon_item_rate')].map(e=>e.textContent.trim());
        m.scrollTop = 999999;
        return {
            open:true, items: items.length, neon_option_rows: opts.length,
            rate_rows: rates.length, sample_rates: rates.slice(0,6),
            scrollable: m.scrollHeight > m.clientHeight + 2,
            scrolledToBottom: m.scrollTop + m.clientHeight >= m.scrollHeight - 5,
        };
    }""")

with BrowserSmoke("neon_quote_item_picker", base_url=BASE) as s:
    s.page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    used = None
    for l in ["p2m75_book", "p2m75_sales", "p2m75_approver"]:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print("login retry:", l, str(e)[:40])
    print("USING", used)

    with s.scenario("quote-item picker: full list + rate on every row"):
        s.open_action("neon_finance.neon_finance_quote_action")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(1500)
        # New quote
        s.page.get_by_role("button", name="New").first.click(timeout=10000)
        s.page.locator(".o_form_view").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2000)
        # Add a line
        s.page.locator(".o_field_x2many_list_row_add a").first.click(timeout=10000)
        s.page.wait_for_timeout(1500)
        # Click the product picker cell
        s.page.locator("[name='product_template_id'] input").first.click(timeout=10000)
        s.page.wait_for_timeout(2500)
        d = dropdown(s)
        print("CLICK dropdown:", d)
        V.append(("picker dropdown opens", d.get("open")))
        V.append(("neon_quote_item widget applied (option rows present)", d.get("neon_option_rows", 0) > 0))
        V.append(("FULL list on click (>50 product rows, uncapped)", d.get("neon_option_rows", 0) > 50))
        V.append(("rate sub-label on EVERY product row", d.get("rate_rows", 0) == d.get("neon_option_rows", -1) and d.get("neon_option_rows", 0) > 0))
        V.append(("dropdown scrollable to bottom", d.get("scrollable") and d.get("scrolledToBottom")))
        s.screenshot("qip_01_full_list_rates")
        # scroll back to top for a clean screenshot of rows+rates
        s.page.evaluate("()=>{const m=document.querySelector('.o-autocomplete--dropdown-menu'); if(m) m.scrollTop=0;}")
        s.page.wait_for_timeout(400); s.screenshot("qip_02_top_rows")
        # Type to filter (uncapped match across full list)
        s.page.locator("[name='product_template_id'] input").first.fill("a")
        s.page.wait_for_timeout(2000)
        d2 = dropdown(s)
        print("TYPE 'a' dropdown:", d2)
        V.append(("typing matches (product rows present)", d2.get("open") and d2.get("neon_option_rows", 0) > 0))
        V.append(("typed rows also carry rate sub-label", d2.get("rate_rows", 0) == d2.get("neon_option_rows", -1) and d2.get("neon_option_rows", 0) > 0))
        s.screenshot("qip_03_typed_filter")

    with s.scenario("LEAK CHECK: Contacts list still scrolls"):
        s.page.goto(f"{BASE}/web", wait_until="domcontentloaded")
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(1500)
        try:
            s.page.locator(".o_switch_view.o_list").first.click(timeout=6000); s.page.wait_for_timeout(2000)
        except Exception:
            pass
        lk = s.page.evaluate(r"""()=>{const el=document.querySelector('.o_list_renderer'); if(!el)return{};
            const cs=getComputedStyle(el); el.scrollTop=99999;
            return {oy:cs.overflowY, contain:cs.contain, scrolled: el.scrollTop, scrollable: el.scrollHeight>el.clientHeight+2};}""")
        print("LEAK CHECK list:", lk)
        V.append(("Contacts list renderer overflow AUTO (no leak)", lk.get("oy") in ("auto", "scroll")))
        V.append(("Contacts list still scrolls", (not lk.get("scrollable")) or lk.get("scrolled", 0) > 0))

    real = [e for e in errs if e]
    print(f"\nCONSOLE_ERRORS {len(real)}")
    for e in real[:8]:
        print("  CERR:", e)
    print("=== VERDICTS ===")
    for name, ok in V:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"OVERALL {'PASS' if all(ok for _, ok in V) else 'FAIL'} | console_errors={len(real)}")
    print("SHOTS:", s.output_dir)

sys.exit(s.summary())
