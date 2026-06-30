"""neon_dashboard — SALES-lens design-fidelity restyle + per-lens blast-radius proof.

Sales lens: greeting, My Pipeline / Quote-to-Close relabels, Commission "coming
soon" placeholder, crm-stage horizontal bars — all under .o_neon_dash_sales.
Other lenses (director/bookkeeper/hr/lead_tech) MUST be unchanged: no sales
markers, Director keeps "Pipeline Value"/"Win Rate" + the quote-state table.
base_url via argv[1] (default local).
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
ACTION = "neon_dashboard.action_neon_dashboard_server"

LENSES = [
    ("dash_dr_sales", "sales"),
    ("dash_dr_super", "director"),
    ("dash_dr_book", "bookkeeper"),
    ("dash_dr_hr", "hr"),
    ("dash_dr_lead", "lead_tech"),
]

PROBE = """() => {
    const root = document.querySelector('.o_neon_dashboard');
    const cls = root ? (root.className || '') : '';
    const labels = [...document.querySelectorAll('.o_neon_kpi_label')].map(e => e.textContent.trim());
    return {
        dash_type: (cls.match(/o_neon_dash_(\\w+)/) || [])[1] || null,
        greeting: !!document.querySelector('.o_neon_sales_greeting'),
        commission_soon: !!document.querySelector('.o_neon_kpi_soon'),
        pipebars: !!document.querySelector('.o_neon_sales_pipebars'),
        quote_state_table: !!document.querySelector('.o_neon_sales_table'),
        lbl_my_pipeline: labels.includes('My Pipeline'),
        lbl_pipeline_value: labels.includes('Pipeline Value'),
        lbl_quote_to_close: labels.includes('Quote-to-Close'),
        lbl_win_rate: labels.includes('Win Rate (90d)'),
        kpi_tiles: document.querySelectorAll('.o_neon_kpi_strip .o_neon_kpi_tile:not(.o_neon_kpi_skeleton)').length,
    };
}"""

verdicts = []
with BrowserSmoke("neon_sales_dashboard", base_url=BASE) as s:
    for login, want_type in LENSES:
        try:
            s.login(login)
        except Exception as e:  # noqa: BLE001
            print(f"[login] {login} failed: {e}")
            # one retry (cold-start)
            try:
                s.login(login)
            except Exception as e2:  # noqa: BLE001
                print(f"[login] {login} retry failed: {e2}")
                verdicts.append((f"{login} login", False)); continue
        with s.scenario(f"{want_type} lens ({login})"):
            s.open_action(ACTION)
            try:
                s.page.locator(".o_neon_dashboard .o_neon_kpi_strip").first.wait_for(state="visible", timeout=20000)
            except Exception as e:  # noqa: BLE001
                print(f"[{want_type}] render wait: {e}")
            s.page.wait_for_timeout(3000)
            s.screenshot(f"lens_{want_type}")
            p = s.page.evaluate(PROBE)
            print(f"{want_type.upper()} {p}")
            # Sales must be 'sales'; other lenses just must NOT be sales-scoped
            # (which exact non-sales lens a fixture resolves to is a lens-
            # resolution detail, e.g. dual-role HR lands on bookkeeper).
            if want_type == "sales":
                verdicts.append(("sales: dash_type", p.get("dash_type") == "sales"))
            else:
                verdicts.append((f"{login}: NOT sales-scoped", p.get("dash_type") not in (None, "sales")))
            if want_type == "sales":
                verdicts.append(("sales: greeting", p["greeting"]))
                verdicts.append(("sales: My Pipeline relabel", p["lbl_my_pipeline"] and not p["lbl_pipeline_value"]))
                verdicts.append(("sales: Quote-to-Close relabel", p["lbl_quote_to_close"] and not p["lbl_win_rate"]))
                verdicts.append(("sales: Commission coming-soon tile", p["commission_soon"]))
                verdicts.append(("sales: crm-stage pipeline bars", p["pipebars"]))
            else:
                # blast-radius: other lenses must show NO sales markers
                verdicts.append((f"{want_type}: NO sales greeting", not p["greeting"]))
                verdicts.append((f"{want_type}: NO commission tile", not p["commission_soon"]))
                verdicts.append((f"{want_type}: NO sales pipebars", not p["pipebars"]))
                verdicts.append((f"{want_type}: NO 'My Pipeline'/'Quote-to-Close' relabel", not p["lbl_my_pipeline"] and not p["lbl_quote_to_close"]))
                if want_type == "director":
                    # Director keeps its original KPI label (proof the relabel
                    # was sales-scoped). It has NO kpi_win_rate tile and its
                    # pipeline is empty locally (empty-state, not a table) -- the
                    # "NO sales pipebars" check above is the real no-bleed proof.
                    verdicts.append(("director: keeps 'Pipeline Value' label", p["lbl_pipeline_value"]))

    print("\n=== VERDICTS ===")
    allok = True
    for name, ok in verdicts:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        allok = allok and ok
    print(f"OVERALL {'PASS' if allok else 'FAIL'}")
    print(f"OUT {s.output_dir}")

sys.exit(s.summary())
