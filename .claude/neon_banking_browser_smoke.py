"""BANKING-SETUP browser verify: the Banking shortcut opens the journal-cards
dashboard showing the four journals; the menu shows for a bookkeeper and is
hidden for non-finance roles. Read-only. Run after -u."""
import os
import re
import subprocess
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"
SHOT_DIR = os.path.join("smoke-output", "neon_banking")
os.makedirs(SHOT_DIR, exist_ok=True)

_RESOLVE = r"""
out = {}
m = env.ref("neon_finance.menu_neon_banking_root", raise_if_not_found=False)
out["action"] = m.action.id if m and m.action else 0
out["menu"] = m.id if m else 0
# model-level group gating: does each user hold >=1 of the menu's groups?
mg = set(m.groups_id.ids) if m else set()
for lg in ("p2m75_book", "p2m75_sales", "p2m75_crew"):
    u = env["res.users"].search([("login", "=", lg)], limit=1)
    out["sees_" + lg] = bool(u and (mg & set(u.groups_id.ids)))
print("IDS_JSON=%s" % out)
"""


def _resolve():
    p = subprocess.run(["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
                        "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
                       input=_RESOLVE.encode(), capture_output=True, timeout=180)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out[-1500:]); raise RuntimeError("resolve failed")
    return eval(m.group(1), {"__builtins__": {}}, {})


def main():
    ids = _resolve()
    with BrowserSmoke("neon_banking") as smoke:
        # model-level gating (group intersection)
        smoke._record_assert("Banking menu visible to bookkeeper (group gating)",
                             expect="True", actual=str(ids.get("sees_p2m75_book")),
                             passed=ids.get("sees_p2m75_book") is True)
        smoke._record_assert("Banking menu HIDDEN for sales (non-finance-admin)",
                             expect="False", actual=str(ids.get("sees_p2m75_sales")),
                             passed=ids.get("sees_p2m75_sales") is False)
        smoke._record_assert("Banking menu HIDDEN for crew",
                             expect="False", actual=str(ids.get("sees_p2m75_crew")),
                             passed=ids.get("sees_p2m75_crew") is False)

        smoke.login("p2m75_book")
        # the Banking shortcut appears in the sidebar rail (it reads the menu tree)
        smoke.page.goto(f"{smoke.base_url}/web", wait_until="networkidle")
        smoke.page.wait_for_timeout(800)
        with smoke.scenario("Banking appears in the bookkeeper's launcher/rail"):
            rail_has = smoke.page.locator(
                ".o_neon_sidebar .o_neon_sidebar_app:has-text('Banking')").count()
            smoke._record_assert("Banking in sidebar rail for bookkeeper",
                                 expect=">=1", actual=f"{rail_has}", passed=rail_has >= 1)

        # open the Banking dashboard -> the four journal cards
        with smoke.scenario("Banking opens the journal-cards dashboard (4 cards)"):
            smoke.page.goto(f"{smoke.base_url}/web#action={ids['action']}",
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(1500)
            smoke.assert_visible("div.o_action_manager", "dashboard renders")
            body = smoke.page.locator("body").inner_text()
            for label in ["CABS (USD)", "CABS (ZWG)", "Petty Cash", "Undeposited Funds"]:
                smoke._record_assert(f"journal card present: {label}",
                                     expect="on dashboard", actual=("yes" if label in body else "no"),
                                     passed=label in body)
            smoke.page.screenshot(path=os.path.join(SHOT_DIR, "banking_dashboard.png"))
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
