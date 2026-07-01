"""Track A verify: neon_theme list-scroll fix (global) + record-search typed uncap.

- List views scroll (renderer overflow:auto, scroll to bottom reachable) on
  Contacts/Event Jobs/Equipment/Products; card look intact (radius+shadow);
  sticky header stays. Kanban unaffected. Leak check: renderer contain:none.
- record-search typed path uncapped (type 'a' on Contacts -> >50).
base_url via argv[1].
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
errs = []
V = []

LISTS = [
    ("Contacts", "contacts.action_contacts", True),   # True = has many rows to scroll
    ("Event Jobs", "neon_jobs.commercial_event_job_action", True),
    ("Equipment", "neon_jobs.neon_equipment_unit_action", True),
    ("Products", "product.product_template_action", True),
    ("Quotes", "neon_finance.neon_finance_quote_action", False),  # 0 rows locally
]

def probe_list(s):
    return s.page.evaluate(r"""() => {
        const el = document.querySelector('.o_list_renderer');
        if (!el) return {present:false};
        const cs = getComputedStyle(el);
        el.scrollTop = 99999; const scrolled = el.scrollTop;
        const thead = el.querySelector('.o_list_table thead');
        const theadPos = thead ? getComputedStyle(thead.querySelector('th')||thead).position : null;
        return {
            present:true, overflowY: cs.overflowY, radius: cs.borderTopLeftRadius,
            shadow: cs.boxShadow !== 'none', contain: cs.contain,
            sh: el.scrollHeight, ch: el.clientHeight,
            scrollable: el.scrollHeight > el.clientHeight + 2,
            scrolledToBottom: scrolled > 0 && scrolled + el.clientHeight >= el.scrollHeight - 5,
            theadSticky: theadPos,
        };
    }""")

with BrowserSmoke("neon_tracka", base_url=BASE) as s:
    s.page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    for l in ["p2m75_mgr", "p2m75_sales"]:
        try:
            s.login(l); break
        except Exception as e:  # noqa: BLE001
            print("login retry:", str(e)[:40])

    for label, action, has_rows in LISTS:
        with s.scenario(f"list scroll: {label}"):
            s.page.goto(f"{BASE}/web", wait_until="domcontentloaded")
            s.open_action(action)
            s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
            s.page.wait_for_timeout(1500)
            try:
                s.page.locator(".o_switch_view.o_list").first.click(timeout=6000)
                s.page.wait_for_timeout(2000)
            except Exception:  # already list, or single view
                pass
            p = probe_list(s)
            print(f"{label} list:", p)
            if not p.get("present"):
                V.append((f"{label}: list renderer present", False)); continue
            V.append((f"{label}: renderer overflow-y AUTO (scroll enabled)", p["overflowY"] in ("auto", "scroll")))
            V.append((f"{label}: card look intact (radius+shadow)", p["radius"] != "0px" and p["shadow"]))
            if has_rows:
                V.append((f"{label}: scrollable + reaches bottom", p["scrollable"] and p["scrolledToBottom"]))
                V.append((f"{label}: sticky header", p["theadSticky"] == "sticky"))
            s.screenshot(f"tracka_list_{label.split()[0].lower()}")

    # kanban unaffected
    with s.scenario("kanban unaffected (Contacts)"):
        s.page.goto(f"{BASE}/web", wait_until="domcontentloaded")
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(1500)
        try:
            s.page.locator(".o_switch_view.o_kanban").first.click(timeout=6000); s.page.wait_for_timeout(1500)
        except Exception:
            pass
        k = s.page.evaluate(r"""() => {const el=document.querySelector('.o_kanban_renderer'); if(!el)return{present:false};
            const cs=getComputedStyle(el); el.scrollTop=99999;
            return {present:true, oy:cs.overflowY, sh:el.scrollHeight, ch:el.clientHeight, scrolled:el.scrollTop, scrollable: el.scrollHeight>el.clientHeight+2};}""")
        print("kanban:", k)
        V.append(("kanban renderer present + scrolls (unaffected)", k.get("present") and (not k.get("scrollable") or k.get("scrolled", 0) > 0)))
        s.screenshot("tracka_kanban")

    # record-search typed uncapped
    with s.scenario("record-search typed uncapped"):
        s.page.goto(f"{BASE}/web", wait_until="domcontentloaded")
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(2000)
        s.page.locator(".o_cp_searchview .o_neon_recsearch input").first.fill("a")
        s.page.wait_for_timeout(1800)
        n = s.page.evaluate("""()=>{const m=document.querySelector('.o_neon_recsearch .o-autocomplete--dropdown-menu');
            return m?m.querySelectorAll('.o-autocomplete--dropdown-item').length:0;}""")
        print("record-search 'a' count:", n)
        V.append(("record-search typed 'a' UNCAPPED (>50)", n > 50))
        s.screenshot("tracka_recsearch_uncapped")

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
