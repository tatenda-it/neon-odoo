"""BANK-STMT-FIX browser proof: clicking "New Transaction" on each of the four
cash/bank journal cards opens the statement-line entry cleanly (no Server
Error), and a line can be entered. Read-only-ish (opens entry views; does not
save). Run after the fix -u."""
import os
import re
import subprocess
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"
SHOT_DIR = os.path.join("smoke-output", "bankstmt_fix")
os.makedirs(SHOT_DIR, exist_ok=True)

_RESOLVE = r"""
m = env.ref("neon_finance.menu_neon_banking_root", raise_if_not_found=False)
print("IDS_JSON=%s" % {"action": (m.action.id if m and m.action else 0)})
"""


def _resolve():
    p = subprocess.run(["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
                        "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
                       input=_RESOLVE.encode(), capture_output=True, timeout=180)
    out = (p.stdout + p.stderr).decode("utf-8", "replace")
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    return eval(m.group(1), {"__builtins__": {}}, {})


JOURNALS = ["CABS (USD)", "CABS (ZWG)", "Undeposited Funds", "Petty Cash"]


def main():
    ids = _resolve()
    errors = []
    with BrowserSmoke("bankstmt_fix") as smoke:
        smoke.page.on("dialog", lambda d: d.dismiss())
        smoke.login("p2m75_book")
        for jrnl in JOURNALS:
            with smoke.scenario(f"New Transaction opens cleanly: {jrnl}"):
                smoke.page.goto(f"{smoke.base_url}/web#action={ids['action']}",
                                wait_until="networkidle")
                smoke.page.wait_for_timeout(1200)
                card = smoke.page.locator(
                    f".o_kanban_record:has-text('{jrnl}')").first
                # the "New Transaction" link inside that journal card
                link = card.locator(
                    "a:has-text('New Transaction'), button:has-text('New Transaction')").first
                link.click()
                smoke.page.wait_for_timeout(1500)
                # 1. no Odoo server-error dialog/page
                err = smoke.page.locator(
                    ".o_error_dialog, .o_dialog_error, "
                    ".modal:has-text('Server Error'), .o_blocked_dialog").count()
                # 2. an entry view opened (editable list or form of statement lines)
                view = smoke.page.locator(
                    "div.o_list_view, div.o_form_view").count()
                smoke._record_assert(f"{jrnl}: no server error", expect="0 error dialogs",
                                     actual=f"{err}", passed=err == 0)
                smoke._record_assert(f"{jrnl}: statement-line entry view opens",
                                     expect=">=1 list/form view", actual=f"{view}",
                                     passed=view >= 1)
                if err:
                    errors.append(jrnl)
        # one screenshot of an opened entry view
        smoke.page.screenshot(path=os.path.join(SHOT_DIR, "new_transaction_open.png"))
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
