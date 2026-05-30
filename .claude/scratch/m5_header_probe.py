from browser_smoke import BrowserSmoke
import pathlib, json
OUT = pathlib.Path("scratch/m5_shots"); OUT.mkdir(exist_ok=True)
res = {}
with BrowserSmoke("m5_header") as smoke:
    smoke.login("p8a_director")
    for w,h,tag in [(1280,800,"desktop"),(375,667,"mobile")]:
        smoke.page.set_viewport_size({"width":w,"height":h})
        smoke.open_action("neon_dashboard.action_neon_dashboard_server")
        smoke.page.wait_for_selector(".o_neon_dashboard_brand h1", timeout=10000)
        smoke.page.wait_for_timeout(400)
        res[tag] = smoke.page.evaluate("""() => {
          const h1=document.querySelector('.o_neon_dashboard_brand h1');
          const sep=document.querySelector('.o_neon_dashboard_sep');
          return {h1Text: h1? h1.textContent.replace(/\s+/g,' ').trim():null,
                  sepChar: sep? sep.textContent:null,
                  sepMarginLeft: sep? getComputedStyle(sep).marginLeft:null,
                  sepMarginRight: sep? getComputedStyle(sep).marginRight:null};
        }""")
        smoke.page.locator(".o_neon_dashboard_header").screenshot(path=str(OUT/f"header_{tag}.png"))
print("J_START"); print(json.dumps(res, ensure_ascii=False, indent=2)); print("J_END")
