"""P8A.M10 browser smoke -- on-demand snapshot exports.

Scenarios:

1. p8a_director sees both new header buttons (Download PDF +
   Download Excel) next to Edit Layout + Refresh.
2. Click Download PDF -> browser triggers a download event for
   a .pdf file with the right filename pattern.
3. Click Download Excel -> browser triggers a download event for
   a .xlsx file.
4. Activate Finance filter chip -> click Download Excel -> the
   downloaded file's sheet list excludes Jobs/Sales/Crew.
5. p8a_sales_rep tier export -> filename includes 'sales' + no
   Finance sheet inside.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
# Setup: ensure p8a_director + p8a_sales_rep exist.
Users = env['res.users']

def _get_or_make(login, group_xmlid):
    user = Users.search([('login', '=', login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, group.id)],
        })
    else:
        user.write({'password': 'test123', 'active': True})
        if group.id not in user.groups_id.ids:
            user.write({'groups_id': [(4, group.id)]})
    return user

u_director = _get_or_make('p8a_director', 'neon_core.group_neon_superuser')
u_sales = _get_or_make('p8a_sales_rep', 'neon_core.group_neon_sales_rep')

env.cr.commit()
print('IDS_JSON=' + repr({
    'director_id': u_director.id,
    'sales_id': u_sales.id,
}))
"""


def _run_odoo_shell(script: str) -> str:
    proc = subprocess.run(
        [
            "docker", "compose",
            "--project-directory", "C:/Users/Neon/neon-odoo",
            "exec", "-T", "odoo",
            "odoo", "shell", "-d", DB, "--no-http",
        ],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    return (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def _setup_fixtures() -> dict:
    out = _run_odoo_shell(_SETUP_SCRIPT)
    m = re.search(r"IDS_JSON=(\{.*\})", out)
    if not m:
        print("[p8a_m10] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _trigger_export_and_capture(smoke, format_label):
    """Click the export button + capture the download event.

    Returns the download path (string). Raises AssertionFail on
    timeout / no download.
    """
    btn_class = (".o_neon_dashboard_export_pdf" if format_label == "pdf"
                 else ".o_neon_dashboard_export_xlsx")
    with smoke.page.expect_download(timeout=15000) as dl_info:
        smoke.page.locator(btn_class).click()
    download = dl_info.value
    # Save to a known path so test can inspect bytes.
    target = (smoke._output_dir
              / f"export_{format_label}_{download.suggested_filename}")
    download.save_as(str(target))
    return target


def run() -> int:
    ids = _setup_fixtures()
    with BrowserSmoke("p8a_m10") as smoke:

        # =============================================================
        # Scenario 1: header buttons visible
        # =============================================================
        with smoke.scenario("Director sees Download PDF + Excel buttons"):
            smoke.login("p8a_director")
            smoke.assert_menu_visible(
                "neon_dashboard.menu_neon_dashboard_root")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard_export_pdf", timeout=10000)
            smoke.page.wait_for_selector(
                ".o_neon_dashboard_export_xlsx", timeout=10000)
            smoke._record_assert(
                "PDF + Excel buttons present",
                expect="both visible",
                actual="both visible",
                passed=True,
            )
            smoke.screenshot("export_buttons_visible")

        # =============================================================
        # Scenario 2: click PDF -> download
        # =============================================================
        with smoke.scenario("Click Download PDF -> .pdf downloads"):
            path = _trigger_export_and_capture(smoke, "pdf")
            head = path.read_bytes()[:4]
            ok_magic = head == b"%PDF"
            ok_name = "neon-director-snapshot-" in path.name and path.name.endswith(".pdf")
            smoke._record_assert(
                "PDF download has %PDF magic + correct filename",
                expect="%PDF magic + neon-director-snapshot pattern",
                actual=f"first4={head!r} name={path.name}",
                passed=ok_magic and ok_name,
            )
            if not (ok_magic and ok_name):
                raise AssertionFail(
                    f"PDF download malformed: head={head!r} name={path.name}")

        # =============================================================
        # Scenario 3: click Excel -> download
        # =============================================================
        with smoke.scenario("Click Download Excel -> .xlsx downloads"):
            path = _trigger_export_and_capture(smoke, "xlsx")
            head = path.read_bytes()[:2]
            ok_magic = head == b"PK"  # xlsx = zip
            ok_name = path.name.endswith(".xlsx") and "neon-director-snapshot-" in path.name
            smoke._record_assert(
                "Excel download has PK magic + correct filename",
                expect="PK + neon-director-snapshot pattern",
                actual=f"first2={head!r} name={path.name}",
                passed=ok_magic and ok_name,
            )
            if not (ok_magic and ok_name):
                raise AssertionFail(
                    f"Excel download malformed: head={head!r} name={path.name}")

        # =============================================================
        # Scenario 4: Finance filter -> Excel excludes Jobs/Sales/Crew
        # =============================================================
        with smoke.scenario("Finance filter -> Excel scoped"):
            # Click the Finance filter chip.
            smoke.page.locator(
                ".o_neon_filter_chip", has_text="Finance"
            ).first.click()
            smoke.page.wait_for_timeout(500)
            path = _trigger_export_and_capture(smoke, "xlsx")
            # Inspect zip contents to assert sheet names.
            import zipfile, io as _io
            data = path.read_bytes()
            zf = zipfile.ZipFile(_io.BytesIO(data))
            wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
            sheets = re.findall(r'<sheet name="([^"]+)"', wb_xml)
            # Finance filter should hide: Jobs / Sales / Crew sheets
            # (per _FILTER_HIDE_RULES). Keep Finance + Summary + Alerts
            # + Tasks + KPIs.
            ok = ("Jobs" not in sheets
                  and "Sales" not in sheets
                  and "Crew + Equipment" not in sheets
                  and "Finance" in sheets
                  and "Summary" in sheets)
            smoke._record_assert(
                "Finance filter Excel sheet scope",
                expect="No Jobs/Sales/Crew sheets; Finance + Summary present",
                actual=f"sheets={sheets}",
                passed=ok,
            )
            if not ok:
                raise AssertionFail(
                    f"Finance filter export sheet scope wrong: {sheets}")

        # =============================================================
        # Scenario 5: sales-tier export filename + sheet scope
        # =============================================================
        with smoke.scenario("Sales tier export: filename + sheet scope"):
            smoke.login("p8a_sales_rep")
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_dashboard_export_xlsx", timeout=10000)
            path = _trigger_export_and_capture(smoke, "xlsx")
            ok_name = "neon-sales-snapshot-" in path.name
            import zipfile, io as _io
            zf = zipfile.ZipFile(_io.BytesIO(path.read_bytes()))
            wb_xml = zf.read("xl/workbook.xml").decode("utf-8")
            sheets = re.findall(r'<sheet name="([^"]+)"', wb_xml)
            ok_sheets = ("Finance" not in sheets
                         and "Crew + Equipment" not in sheets
                         and "Sales" in sheets)
            ok = ok_name and ok_sheets
            smoke._record_assert(
                "Sales tier export filename + sheets",
                expect="filename has 'sales'; no Finance/Crew sheets",
                actual=f"name={path.name} sheets={sheets}",
                passed=ok,
            )
            if not ok:
                raise AssertionFail(
                    f"Sales tier export wrong: name={path.name} sheets={sheets}")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
