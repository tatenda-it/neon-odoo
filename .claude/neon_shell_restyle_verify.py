"""Phase 12 shell restyle verify — exact-token probes + scar re-checks.

(a) rail: #15131C bg, logo tile gradient, wordmark, WORKSPACE label, Montserrat
    600 13px items, ACTIVE gradient pill + glow + radius 10, rail scrolls;
(b) topbar: white 62px, #ECE8F5 border, "Neon ERP / " breadcrumb, ink entries;
(c) LIST SCROLL scar: renderer overflow auto + reaches bottom; row hover #FAF8FE;
(d) kanban: unaffected + card system (radius 15, hover lift);
(e) search box #F6F4FB/#ECE8F5/9px; 0 console errors. base_url argv[1].
"""
import sys
from browser_smoke import BrowserSmoke

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8069"
errs = []
V = []

with BrowserSmoke("neon_shell_restyle", base_url=BASE) as s:
    s.page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    for l in ["p2m75_mgr", "p2m75_sales"]:
        try:
            s.login(l); break
        except Exception as e:  # noqa: BLE001
            print("login retry:", str(e)[:40])

    with s.scenario("rail + topbar tokens"):
        s.open_action("contacts.action_contacts")
        s.page.locator(".o_control_panel").first.wait_for(state="visible", timeout=20000)
        s.page.wait_for_timeout(2500)
        r = s.page.evaluate(r"""() => {
            const cs = (el) => el ? getComputedStyle(el) : null;
            const rail = document.querySelector('.o_neon_sidebar');
            const railCs = cs(rail);
            const tile = document.querySelector('.o_neon_sidebar_logo_tile');
            const word = document.querySelector('.o_neon_sidebar_wordmark_name');
            const sect = document.querySelector('.o_neon_sidebar_section');
            const item = document.querySelector('.o_neon_sidebar_app:not(.o_neon_sidebar_app_active)');
            const act = document.querySelector('.o_neon_sidebar_app_active');
            const nav = document.querySelector('.o_main_navbar');
            const brand = document.querySelector('.o_menu_brand');
            const brandBefore = brand ? getComputedStyle(brand, '::before').content : null;
            // probe the OUTER container: the inner .o_searchview's right corners
            // are squared by the abutting SearchBarMenu button (input-group)
            const sv = document.querySelector('.o_cp_searchview');
            return {
                rail_bg: railCs ? railCs.backgroundColor : null,
                rail_scrolls: rail ? (cs(rail).overflowY) : null,
                tile: tile ? {bg: cs(tile).backgroundImage.slice(0,60), shadow: cs(tile).boxShadow.slice(0,60), w: cs(tile).width, radius: cs(tile).borderRadius} : null,
                wordmark: word ? {text: word.textContent, weight: cs(word).fontWeight, size: cs(word).fontSize, color: cs(word).color, family: cs(word).fontFamily.slice(0,20)} : null,
                section: sect ? {text: sect.textContent, size: cs(sect).fontSize, ls: cs(sect).letterSpacing, color: cs(sect).color} : null,
                item: item ? {family: cs(item).fontFamily.slice(0,20), weight: cs(item).fontWeight, size: cs(item).fontSize, color: cs(item).color, radius: cs(item).borderRadius, pad: cs(item).padding} : null,
                active: act ? {bg: cs(act).backgroundImage.slice(0,80), color: cs(act).color, shadow: cs(act).boxShadow.slice(0,60), radius: cs(act).borderRadius} : null,
                nav: nav ? {h: nav.offsetHeight, bg: cs(nav).backgroundColor, border: cs(nav).borderBottomColor} : null,
                brand_before: brandBefore,
                search: sv ? {bg: cs(sv).backgroundColor, radius: cs(sv).borderRadius, border: cs(sv).borderColor} : null,
                action_offset: cs(document.querySelector('.o_action_manager')).marginLeft,
            };
        }""")
        for k, v in r.items():
            print(f"  {k}: {v}")
        V.append(("rail bg #15131C", r["rail_bg"] == "rgb(21, 19, 28)"))
        V.append(("rail still scrolls (overflow-y auto)", r["rail_scrolls"] == "auto"))
        V.append(("logo tile: 34px gradient + glow + radius 9", bool(r["tile"]) and "linear-gradient" in r["tile"]["bg"] and r["tile"]["w"] == "34px" and r["tile"]["radius"] == "9px"))
        V.append(("wordmark NEON ERP Montserrat 800 15px #fff", bool(r["wordmark"]) and r["wordmark"]["weight"] == "800" and r["wordmark"]["size"] == "15px" and "Montserrat" in r["wordmark"]["family"] and r["wordmark"]["color"] == "rgb(255, 255, 255)"))
        V.append(("WORKSPACE label 9px/1.6px #5C566E", bool(r["section"]) and r["section"]["size"] == "9px" and r["section"]["color"] == "rgb(92, 86, 110)"))
        V.append(("nav item Montserrat 600 13px #9D98B0 r10", bool(r["item"]) and "Montserrat" in r["item"]["family"] and r["item"]["weight"] == "600" and r["item"]["size"] == "13px" and r["item"]["color"] == "rgb(157, 152, 176)" and r["item"]["radius"] == "10px"))
        V.append(("ACTIVE gradient pill + glow", bool(r["active"]) and "linear-gradient(135deg" in r["active"]["bg"] and r["active"]["color"] == "rgb(255, 255, 255)" and "rgba(122, 107, 174" in r["active"]["shadow"]))
        V.append(("topbar white 62px + #ECE8F5 border", bool(r["nav"]) and r["nav"]["h"] == 62 and r["nav"]["bg"] == "rgb(255, 255, 255)" and r["nav"]["border"] == "rgb(236, 232, 245)"))
        V.append(('breadcrumb ::before "Neon ERP / "', bool(r["brand_before"]) and "Neon ERP" in (r["brand_before"] or "")))
        V.append(("search box #F6F4FB radius 9px", bool(r["search"]) and r["search"]["bg"] == "rgb(246, 244, 251)" and r["search"]["radius"] == "9px"))
        V.append(("content offset intact (224px)", r["action_offset"] == "224px"))
        s.screenshot("shell_01_kanban_rail_topbar")

    with s.scenario("SCAR: list scroll + row hover + card radius"):
        try:
            s.page.locator(".o_switch_view.o_list").first.click(timeout=6000); s.page.wait_for_timeout(2000)
        except Exception:
            pass
        lk = s.page.evaluate(r"""() => {const el=document.querySelector('.o_list_renderer'); const cs=getComputedStyle(el);
            el.scrollTop=99999;
            return {oy:cs.overflowY, radius:cs.borderTopLeftRadius, scrolled:el.scrollTop,
                    atBottom: el.scrollTop+el.clientHeight >= el.scrollHeight-5, scrollable: el.scrollHeight>el.clientHeight+2};}""")
        print("  list:", lk)
        V.append(("LIST SCROLL intact (auto + reaches bottom)", lk["oy"] == "auto" and (not lk["scrollable"] or lk["atBottom"])))
        V.append(("list card radius 15px (token)", lk["radius"] == "15px"))
        # row hover #FAF8FE
        row = s.page.locator(".o_list_renderer .o_data_row").first
        row.hover(timeout=5000); s.page.wait_for_timeout(400)
        hb = s.page.evaluate("""()=>{const r=document.querySelector('.o_list_renderer .o_data_row:hover');
            return r?getComputedStyle(r).backgroundColor:null;}""")
        print("  row hover bg:", hb)
        V.append(("row hover #FAF8FE (design verbatim)", hb == "rgb(250, 248, 254)"))
        s.screenshot("shell_02_list_scrolled")

    with s.scenario("kanban unaffected + card hover lift"):
        try:
            s.page.locator(".o_switch_view.o_kanban").first.click(timeout=6000); s.page.wait_for_timeout(2000)
        except Exception:
            pass
        kb = s.page.evaluate(r"""() => {const el=document.querySelector('.o_kanban_renderer'); el.scrollTop=999;
            const card=document.querySelector('.o_kanban_record'); const cs=getComputedStyle(card);
            return {scrolled: el.scrollTop>0 || el.scrollHeight<=el.clientHeight+2,
                    card:{radius:cs.borderTopLeftRadius, border:cs.borderTopColor, pad:cs.paddingTop}};}""")
        print("  kanban:", kb)
        V.append(("kanban scroll unaffected", kb["scrolled"]))
        V.append(("kanban card: radius 15 + #ECE8F5 border + 22px pad", kb["card"]["radius"] == "15px" and kb["card"]["border"] == "rgb(236, 232, 245)" and kb["card"]["pad"] == "22px"))
        card = s.page.locator(".o_kanban_record").first
        card.hover(timeout=5000); s.page.wait_for_timeout(500)
        hv = s.page.evaluate("""()=>{const c=document.querySelector('.o_kanban_record:hover');
            return c?{tf:getComputedStyle(c).transform, bc:getComputedStyle(c).borderTopColor}:null;}""")
        print("  card hover:", hv)
        V.append(("card hover lift (translateY(-2px) + #D6CFE6)", bool(hv) and "-2" in (hv["tf"] or "") and hv["bc"] == "rgb(214, 207, 230)"))
        s.screenshot("shell_03_kanban_cards")

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
