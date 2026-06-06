"""B11 Programme Status board browser smoke.

Scenarios:
(1) Logged-out: GET /neon/status redirects to /web/login -- the board
    is behind Odoo auth (portal/public never reach it).
(2) NON-ADMIN (sales-rep, no base.group_system) logs in -> /neon/status
    renders the full board (title, donut 84%, 3 track bars, 6 WA cards,
    the live-from-prod box with 3 module rows + bot/whatsapp stats +
    write-log) -> clicks "Refresh live status" -> the /neon/status/data
    endpoint answers 200 + result.ok for that non-admin (THE headline
    guarantee) -> the live box still shows a real version string and the
    status dot returns to OK.

Depth principle: every section asserted is not just present but carries
real content (counts + a version string + a successful refresh round
trip), not bare DOM presence.
"""
from __future__ import annotations

import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP = """
Users = env['res.users']

def _wipe_login(login):
    olds = Users.sudo().with_context(active_test=False).search(
        [('login', '=', login)])
    for u in olds:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})

_wipe_login('pb11_br_sales')
g_sales = env.ref('neon_core.group_neon_sales_rep')
u = Users.sudo().with_context(no_reset_password=True).create({
    'name': 'PB11 BR Sales', 'login': 'pb11_br_sales',
    'password': 'test123',
    'groups_id': [(4, env.ref('base.group_user').id), (4, g_sales.id)],
})
# Sanity: this subject must be a real non-admin (no system group).
assert not u.has_group('base.group_system'), 'fixture is base.group_system!'
env.cr.commit()
print('IDS_JSON=' + repr({'sales': u.id}))
"""

_TEARDOWN = """
Users = env['res.users']
u = Users.sudo().with_context(active_test=False).search(
    [('login', '=', 'pb11_br_sales')], limit=1)
if u:
    u.write({'active': False})
env.cr.commit()
print('TEARDOWN OK')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"),
        capture_output=True, timeout=180)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[pb11_status] SETUP FAILED:")
        print(out[-1500:])
        sys.exit(2)
    start = out.find("{", idx)
    depth = 0
    for i in range(start, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[pb11_status] SETUP parse FAILED:")
    print(out[-1500:])
    sys.exit(2)


def _teardown():
    out = _shell(_TEARDOWN)
    if "TEARDOWN OK" not in out:
        print("[pb11_status] TEARDOWN WARN:")
        print(out[-500:])


def _assert_text_contains(smoke, selector, needle, name):
    """Custom depth assertion: a selector's text contains a substring."""
    try:
        txt = smoke.page.locator(selector).first.inner_text(timeout=10000)
    except Exception as exc:  # noqa: BLE001
        smoke._record_assert(name, expect="contains %r" % needle,
                             actual="locator error: %s" % exc, passed=False)
        smoke._capture_fail_artifacts(name, selector=selector)
        raise AssertionFail("%s: %s not found" % (name, selector)) from exc
    ok = needle.lower() in (txt or "").lower()
    smoke._record_assert(name, expect="contains %r" % needle,
                         actual=(txt or "")[:80], passed=ok)
    if not ok:
        smoke._capture_fail_artifacts(name, selector=selector)
        raise AssertionFail("%s: %r not in %r" % (name, needle, txt))


def run():
    _setup()
    try:
        with BrowserSmoke("pb11_status", base_url=BASE_URL, db=DB) as smoke:

            # ---- (1) logged-out -> redirect to login -----------------
            with smoke.scenario(
                    "Logged-out GET /neon/status redirects to login "
                    "(behind Odoo auth)"):
                smoke.page.goto(f"{BASE_URL}/neon/status",
                                wait_until="domcontentloaded")
                url = smoke.page.url
                passed = "/web/login" in url
                smoke._record_assert(
                    "anonymous /neon/status -> /web/login",
                    expect="redirect to /web/login", actual=url,
                    passed=passed)
                if not passed:
                    raise AssertionFail(
                        "anonymous request not redirected: %s" % url)

            # ---- (2) non-admin: page renders + refresh works ---------
            with smoke.scenario(
                    "Non-admin loads the board + refresh round-trips "
                    "(headline guarantee)"):
                smoke.login("pb11_br_sales")
                smoke.page.goto(f"{BASE_URL}/neon/status",
                                wait_until="domcontentloaded")
                smoke.page.wait_for_selector("#sv-refresh", timeout=10000)

                # title / header
                title = smoke.page.title()
                smoke._record_assert(
                    "page title is the board", expect="Programme Status",
                    actual=title,
                    passed="Programme Status" in title)

                # 2. overall donut + 3 track bars
                _assert_text_contains(
                    smoke, ".donut .pct b", "84%", "donut shows 84%")
                smoke.assert_count(".bars .bar-row", 3, "3 track bars")
                _assert_text_contains(
                    smoke, ".bars", "Core ERP Programme",
                    "track bar names present")

                # 3. WA breakdown -- 6 cards, WA-0 marked Live
                smoke.assert_count(".cards .card", 6, "6 WA module cards")
                _assert_text_contains(
                    smoke, ".cards", "WA-0", "WA-0 card present")
                _assert_text_contains(
                    smoke, ".cards", "Live", "a WA card shows Live state")

                # 4. track milestones
                smoke.assert_count(".mile", 3, "3 track-milestone blocks")

                # 5. live-from-prod box -- real content
                smoke.assert_count("#sv-modules .kv", 3,
                                   "3 module-version rows")
                _assert_text_contains(
                    smoke, "#sv-modules", "17.0",
                    "module versions show a 17.0 string")
                smoke.assert_visible("#sv-bot .bs-num",
                                     "bot-users stat present")
                smoke.assert_visible("#sv-wa .bs-num",
                                     "whatsapp stat present")
                smoke.assert_visible("#sv-writelog", "write-log box present")

                # 6. governance lists
                smoke.assert_count(".glist", 3, "3 governance lists")

                # ---- THE refresh round-trip (non-admin) --------------
                with smoke.page.expect_response(
                        lambda r: "/neon/status/data" in r.url,
                        timeout=15000) as resp_info:
                    smoke.click("#sv-refresh",
                                name="click Refresh live status")
                resp = resp_info.value
                body = {}
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    pass
                result = (body or {}).get("result") or {}
                ok = resp.status == 200 and result.get("ok") is True
                smoke._record_assert(
                    "refresh endpoint 200 + result.ok for NON-ADMIN",
                    expect="200 + ok=True",
                    actual="status=%s ok=%s" % (resp.status,
                                                result.get("ok")),
                    passed=ok)
                if not ok:
                    smoke._capture_fail_artifacts("refresh_roundtrip")
                    raise AssertionFail(
                        "refresh failed for non-admin: status=%s body=%s"
                        % (resp.status, str(body)[:200]))

                # post-refresh: dot back to OK + version still rendered
                smoke.assert_visible("#sv-dot.ok",
                                     "status dot OK after refresh")
                _assert_text_contains(
                    smoke, "#sv-modules", "17.0",
                    "module versions still rendered after refresh")
                smoke.screenshot("status_board_after_refresh")

        return smoke.summary()
    finally:
        _teardown()


if __name__ == "__main__":
    sys.exit(run())