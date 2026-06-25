"""STAGE-0 relabel browser evidence: the relabelled screens render + show the
new words. Read-only. Run after -i."""
import os
import re
import subprocess
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"
SHOT = os.path.join("smoke-output", "relabel")
os.makedirs(SHOT, exist_ok=True)

_R = r"""
out = {}
out["transactions_action"] = env.ref("account.action_bank_statement_tree").id
inv = env["account.move"].search([("move_type","=","out_invoice"),("state","=","posted")], limit=1)
out["invoice_id"] = inv.id if inv else 0
print("IDS_JSON=%s" % out)
"""


def _r():
    p = subprocess.run(["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
                        "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
                       input=_R.encode(), capture_output=True, timeout=180)
    o = (p.stdout + p.stderr).decode("utf-8", "replace")
    return eval(re.search(r"IDS_JSON=(\{.*\})", o).group(1), {"__builtins__": {}}, {})


def main():
    ids = _r()
    with BrowserSmoke("relabel") as smoke:
        smoke.login("p2m75_book")
        with smoke.scenario("Transactions register renders with new title"):
            smoke.page.goto(f"{smoke.base_url}/web#action={ids['transactions_action']}",
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(1200)
            smoke.assert_visible("div.o_action_manager", "register renders")
            body = smoke.page.locator(".o_breadcrumb, .o_control_panel").first.inner_text()
            smoke._record_assert("title shows 'Transactions'", expect="Transactions",
                                 actual=body[:40].replace(chr(10), " "),
                                 passed="Transactions" in body)
            smoke.page.screenshot(path=os.path.join(SHOT, "transactions_register.png"))
        if ids.get("invoice_id"):
            with smoke.scenario("invoice shows 'Record Payment' (not 'Register Payment')"):
                smoke.page.goto(f"{smoke.base_url}/web#id={ids['invoice_id']}"
                                f"&model=account.move&view_type=form",
                                wait_until="networkidle")
                smoke.page.wait_for_timeout(1200)
                rec = smoke.page.locator("button:has-text('Record Payment')").count()
                reg = smoke.page.locator("button:has-text('Register Payment')").count()
                smoke._record_assert("'Record Payment' button present",
                                     expect=">=1", actual=f"{rec}", passed=rec >= 1)
                smoke._record_assert("no 'Register Payment' button",
                                     expect="0", actual=f"{reg}", passed=reg == 0)
                smoke.page.screenshot(path=os.path.join(SHOT, "invoice_record_payment.png"))
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
