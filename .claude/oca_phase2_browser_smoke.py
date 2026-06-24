"""OCA Phase 2 browser smoke -- partner_statement wizard UI layer.

Opens the Activity / Outstanding / Detailed-Activity statement wizard actions
(res.partner-bound) in a real browser as the Bookkeeper and asserts each wizard
form renders. The RENDERED-STATEMENT-WITH-REAL-CONTENT + aging-bucket proof is
the companion partner_statement_depth_verify.py (renders the actual QWeb +
extracts buckets). Read-only. Run AFTER the guarded regression.
"""
import re
import subprocess
import sys

sys.path.insert(0, ".")
from browser_smoke import BrowserSmoke  # noqa: E402

DB = "neon_crm"

_RESOLVE = r"""
ids = {}
refs = {
  "activity": "partner_statement.activity_statement_wizard_action",
  "outstanding": "partner_statement.outstanding_statement_wizard_action",
  "detailed": "partner_statement.detailed_activity_statement_wizard_action",
}
# a real partner to pass as active context (the wizards are res.partner-bound)
p = env["res.partner"].search([("customer_rank", ">", 0)], limit=1) \
    or env["res.partner"].search([("is_company", "=", True)], limit=1)
ids["_partner"] = p.id if p else 0
for k, xid in refs.items():
    rec = env.ref(xid, raise_if_not_found=False)
    ids[k] = rec.id if rec else 0
print("IDS_JSON=%s" % ids)
"""


def _resolve():
    proc = subprocess.run(
        ["docker", "compose", "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo", "odoo", "shell", "-d", DB, "--no-http"],
        input=_RESOLVE.encode("utf-8"), capture_output=True, timeout=180)
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out[-2000:]); raise RuntimeError("could not resolve action ids")
    return eval(m.group(1), {"__builtins__": {}}, {})


WIZARDS = [("activity", "Activity Statement"),
           ("outstanding", "Outstanding Statement"),
           ("detailed", "Detailed Activity Statement")]


def main():
    ids = _resolve()
    pid = ids.get("_partner") or 0
    with BrowserSmoke("oca_phase2") as smoke:
        smoke.login("p2m75_book")
        for key, label in WIZARDS:
            if not ids.get(key):
                smoke._record_assert("wizard action present: %s" % label,
                                     expect="xmlid resolves", actual="MISSING", passed=False)
                continue
            with smoke.scenario("partner_statement wizard opens: %s" % label):
                # pass a partner as active context (these actions are res.partner-bound)
                url = (f"{smoke.base_url}/web#action={ids[key]}"
                       f"&active_model=res.partner&active_ids={pid}&active_id={pid}")
                smoke.page.goto(url, wait_until="networkidle")
                smoke.assert_visible("div.o_form_view, .modal .o_form_view",
                                     "%s wizard form renders" % label)
        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
