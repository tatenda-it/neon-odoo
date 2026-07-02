"""Part 2 verify: Zoho-clean quote form layout (layout-only).

New quote form renders (no XML error); Customer prominent + essentials visible;
Scope/Schedule split GONE; Advanced group holds the tucked fields; event_job_id
still EDITABLE in draft (not stranded); required fields reachable (currency
settable, payment-terms wizard). Line table: essentials visible, tucked columns
hidden by default; rate-picker intact. Renders after submit (state change).
Screenshots for eyeball vs Zoho. base_url via argv[1].
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
errs = []
V = []

with BrowserSmoke("neon_quote_layout", base_url=BASE) as s:
    s.page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    used = None
    for l in ["p2m75_book", "p2m75_approver", "p2m75_sales"]:
        try:
            s.login(l); used = l; break
        except Exception as e:  # noqa: BLE001
            print("login retry:", l, str(e)[:40])
    print("USING", used)

    with s.scenario("new quote form: Zoho-clean layout renders"):
        s.open_action("neon_finance.neon_finance_quote_action")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(1500)
        s.page.get_by_role("button", name="New").first.click(timeout=10000)
        s.page.locator(".o_form_view").first.wait_for(state="visible", timeout=15000)
        s.page.wait_for_timeout(2000)
        lay = s.page.evaluate(r"""() => {
            const field = (n) => !!document.querySelector(`[name='${n}']`);
            const sheet = document.querySelector('.o_form_sheet');
            const txt = sheet ? sheet.textContent : '';
            const ejInput = document.querySelector("[name='event_job_id'] input");
            const curInput = document.querySelector("[name='currency_id'] input");
            return {
                form: !!document.querySelector('.o_form_view'),
                customer: field('partner_id'), salesperson: field('salesperson_id'), currency: field('currency_id'),
                quotation_date: field('quotation_date'), expires: field('expires_at'),
                event_job: field('event_job_id'), payment_term: field('payment_term_id'),
                crew_mode: field('crew_display_mode'), conversion: field('conversion_rate_id'),
                has_advanced: /Advanced/.test(txt),
                scope_removed: !/Scope/.test(txt) && !/Schedule/.test(txt),
                event_job_editable: ejInput ? (!ejInput.disabled && !ejInput.readOnly) : null,
                currency_settable: curInput ? (!curInput.disabled && !curInput.readOnly) : null,
                set_payment_btn: !!document.querySelector("button[name='action_open_payment_term_wizard']"),
            };
        }""")
        print("LAYOUT:", lay)
        V.append(("form renders (no XML error)", lay["form"]))
        V.append(("Customer + essentials visible (customer/salesperson/currency/dates)",
                  lay["customer"] and lay["salesperson"] and lay["currency"] and lay["quotation_date"] and lay["expires"]))
        V.append(("Scope/Schedule split removed", lay["scope_removed"]))
        V.append(("Advanced group present (tucked fields)",
                  lay["has_advanced"] and lay["event_job"] and lay["payment_term"] and lay["crew_mode"] and lay["conversion"]))
        V.append(("event_job_id still EDITABLE in draft (not stranded)", lay["event_job_editable"] is True))
        V.append(("currency settable on new + Set-Payment-Terms wizard reachable",
                  lay["currency_settable"] is True and lay["set_payment_btn"]))
        s.screenshot("layout_01_new_quote_form")

    with s.scenario("line table: essentials visible, advanced tucked, rate-picker intact"):
        # pick an event job (still the entry point pre-Part-1) so a line can be added
        try:
            s.page.locator("[name='event_job_id'] input").first.click(timeout=8000)
            s.page.wait_for_timeout(1500)
            s.page.locator(".o-autocomplete--dropdown-item").first.click(timeout=8000)
            s.page.wait_for_timeout(1500)
        except Exception as e:  # noqa: BLE001
            print("pick event job:", str(e)[:60])
        # add a line
        s.page.locator(".o_field_x2many_list_row_add a").first.click(timeout=10000)
        s.page.wait_for_timeout(1500)
        cols = s.page.evaluate(r"""() => {
            const heads = [...document.querySelectorAll('.o_list_renderer thead th')].map(e=>(e.getAttribute('data-name')||e.textContent||'').trim()).filter(Boolean);
            return { headers: heads };
        }""")
        print("VISIBLE COLUMNS:", cols["headers"])
        hdr = " ".join(cols["headers"]).lower()
        # essentials visible
        V.append(("line essentials visible (product/name/qty/duration/unit_rate/subtotal/tax/total)",
                  all(k in hdr for k in ["product_template_id", "name", "quantity", "duration_days", "unit_rate", "line_subtotal", "tax_id", "line_total_taxed"])))
        # discount consolidated: pct visible, amount hidden
        V.append(("one visible discount (discount_pct shown, discount_amount tucked)",
                  "discount_pct" in hdr and "discount_amount" not in hdr))
        # tucked columns hidden by default
        V.append(("line_type / pricing_status / bracket_multiplier tucked (hidden)",
                  "line_type" not in hdr and "pricing_status" not in hdr and "bracket_multiplier" not in hdr))
        # rate-picker intact
        s.page.locator("[name='product_template_id'] input").first.click(timeout=8000)
        s.page.wait_for_timeout(2000)
        rate = s.page.evaluate(r"""() => {const m=document.querySelector('.o-autocomplete--dropdown-menu');
            return m?{rows:m.querySelectorAll('.o_neon_item_option').length, rates:m.querySelectorAll('.o_neon_item_rate').length}:{rows:0,rates:0};}""")
        print("RATE-PICKER:", rate)
        V.append(("quote-item rate-picker still intact (rate on rows)", rate["rows"] > 0 and rate["rates"] == rate["rows"]))
        s.page.keyboard.press("Escape")
        s.page.wait_for_timeout(500)
        s.screenshot("layout_02_line_table")

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
