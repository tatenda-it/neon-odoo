"""P6 pre-deploy fix-round browser smoke.

Verifies the user-friendly empty-state copy on three menus:
1. Quotes -- no internal milestone tags ('P6.M2' / 'M4')
2. Invoice Schedule -- no dev jargon ('cron' / 'write hook' /
   'on_acceptance' underscore form; the human-readable 'On
   Acceptance' stage label IS allowed elsewhere on the page)
3. Schedule Templates -- no 'auto-instantiate'

Each empty-state body must be at least 100 chars of useful copy.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
import re
sched_action = env.ref(
    'neon_finance.neon_finance_invoice_schedule_action')
quote_action = env.ref('neon_finance.neon_finance_quote_action')
tpl_action = env.ref(
    'neon_finance.neon_finance_invoice_schedule_template_action')

# Strip HTML tags for the term check.
def _strip(html):
    return re.sub(r'<[^>]+>', '', html or '')

print('IDS_JSON=' + repr({
    'quote_action_id': quote_action.id,
    'sched_action_id': sched_action.id,
    'tpl_action_id': tpl_action.id,
    'quote_help_text': _strip(quote_action.help),
    'sched_help_text': _strip(sched_action.help),
    'tpl_help_text': _strip(tpl_action.help),
}))
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        ["docker", "compose",
         "--project-directory", "C:/Users/Neon/neon-odoo",
         "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print(out)
        raise RuntimeError("setup did not produce IDS_JSON marker")
    return eval(m.group(1), {"__builtins__": {}}, {})


def _empty_state_text(smoke):
    """Return the text content of the o_view_nocontent block on the
    current page. Empty string if not present."""
    smoke.page.wait_for_timeout(800)
    locator = smoke.page.locator("div.o_view_nocontent")
    if locator.count() == 0:
        return ""
    return locator.first.inner_text()


def _ensure_empty_list(smoke, action_id):
    """Navigate to a list action filtered to a guaranteed-empty
    domain so the nocontent panel renders. Domain `id=0` returns
    zero rows for any model."""
    smoke.page.goto(
        f"{smoke.base_url}/web#action={action_id}"
        f"&view_type=list",
        wait_until="networkidle",
    )
    # Force the empty-state via context filter (id<0 -> empty)
    # Some action views auto-load records; we apply a filter that
    # matches nothing. Easiest: navigate with active_id=0 OR open
    # a record and back out. Simpler: just check if nocontent is
    # already visible (when no records exist) or fall back to
    # asserting on the action's help arch directly via RPC.
    return smoke.page.locator("div.o_view_nocontent").count() > 0


def main() -> int:
    print("[predeploy] setup: resolving action ids ...")
    ids = _setup_fixtures()
    print(f"[predeploy] setup ok: quote={ids['quote_action_id']} "
          f"sched={ids['sched_action_id']} tpl={ids['tpl_action_id']}")

    # Helper: assert against the help text captured at setup time
    # (admin-side, so no per-user RPC ACL issue). This is more
    # deterministic than trying to coerce Odoo to show the
    # nocontent panel on a list that has records.
    def _check_help(smoke, help_text_key, scenario_name,
                    forbidden_terms, min_length):
        text = ids.get(help_text_key, "")
        if not text:
            raise AssertionFail(
                f"{scenario_name}: help text empty in setup")
        for term in forbidden_terms:
            present = term in text
            smoke._record_assert(
                f"{scenario_name}: forbidden term '{term}' absent",
                expect="not present",
                actual="absent" if not present else "PRESENT",
                passed=not present,
            )
            if present:
                smoke._capture_fail_artifacts(
                    f"{scenario_name}_term_{term}")
                raise AssertionFail(
                    f"{scenario_name} contains forbidden '{term}'")
        # Length check: strip whitespace + collapse runs
        normalised = re.sub(r"\s+", " ", text).strip()
        smoke._record_assert(
            f"{scenario_name}: copy length >= {min_length} chars",
            expect=f">={min_length}",
            actual=f"{len(normalised)} chars",
            passed=len(normalised) >= min_length,
        )
        if len(normalised) < min_length:
            smoke._capture_fail_artifacts(
                f"{scenario_name}_too_short")
            raise AssertionFail(
                f"{scenario_name} copy too short: {len(normalised)}")

    try:
        with BrowserSmoke("p6_predeploy") as smoke:

            with smoke.scenario(
                "Quotes empty-state copy is user-friendly",
            ):
                smoke.login("p2m75_sales")
                # Visual confirmation: navigate to the action so a
                # screenshot captures the rendered empty-state when
                # the list happens to be empty for this user.
                smoke.page.goto(
                    f"{smoke.base_url}/web#action="
                    f"{ids['quote_action_id']}",
                    wait_until="networkidle",
                )
                smoke.page.wait_for_timeout(800)
                # Authoritative assertion via act_window.help RPC
                _check_help(
                    smoke, "quote_help_text", "quotes",
                    forbidden_terms=["P6.M2", "M4", "auto-instantiate",
                                     "cron", "write hook"],
                    min_length=100,
                )
                smoke.screenshot("01_quotes_empty_state")

            with smoke.scenario(
                "Invoice Schedule empty-state copy is user-friendly",
            ):
                smoke.page.goto(
                    f"{smoke.base_url}/web#action="
                    f"{ids['sched_action_id']}",
                    wait_until="networkidle",
                )
                smoke.page.wait_for_timeout(800)
                # 'On Acceptance' (with capital + space) is a
                # legitimate trigger label that appears in the
                # rendered tile, but the underscore form
                # 'on_acceptance' is the dev-jargon flag we forbid.
                _check_help(
                    smoke, "sched_help_text", "invoice_schedule",
                    forbidden_terms=["cron", "write hook",
                                     "on_acceptance", "on_date",
                                     "on_event_state"],
                    min_length=100,
                )
                smoke.screenshot("02_invoice_schedule_empty_state")

            with smoke.scenario(
                "Schedule Template empty-state copy is user-friendly",
            ):
                smoke.login("p2m75_book")  # template menu = book/approver
                smoke.page.goto(
                    f"{smoke.base_url}/web#action="
                    f"{ids['tpl_action_id']}",
                    wait_until="networkidle",
                )
                smoke.page.wait_for_timeout(800)
                _check_help(
                    smoke, "tpl_help_text", "schedule_template",
                    forbidden_terms=["auto-instantiate", "P6.M",
                                     "cron", "write hook"],
                    min_length=100,
                )
                smoke.screenshot("03_schedule_template_empty_state")

        return smoke.summary()
    finally:
        pass  # no fixture teardown needed


if __name__ == "__main__":
    sys.exit(main())
