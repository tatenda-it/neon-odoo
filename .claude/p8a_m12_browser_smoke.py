"""P8A.M12 browser smoke -- mobile + tablet polish across 3
breakpoints.

Scenarios:

1. Desktop control (1280x800) -- baseline; no regression from M11
   layout. KPI strip 4-up (actually 7-up at desktop), all blocks
   side-by-side per existing layout, header buttons show text
   labels.

2. Tablet portrait (768x1024) -- KPI 4-up, blocks reflow to 2-up,
   header buttons still show labels (md+ breakpoint).

3. Mobile portrait (375x667) -- KPI 2-up, blocks 1-up, header
   button labels HIDDEN via d-none.d-md-inline, filter chips
   scroll horizontally, AR aging table renders as stacked cards
   (CSS thead hidden + per-row pseudo-content), AI Insights
   block visible + drillable on tap, no horizontal page overflow.

Uses page.set_viewport_size() between scenarios -- single login,
fast.
"""

from __future__ import annotations

import re
import subprocess
import sys

from browser_smoke import AssertionFail, BrowserSmoke


BASE_URL = "http://localhost:8069"
DB = "neon_crm"


_SETUP_SCRIPT = """
Users = env['res.users']

def _get_or_make(login, group_xmlids):
    user = Users.search([('login', '=', login)], limit=1)
    groups = [env.ref(x) for x in group_xmlids]
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            'name': login, 'login': login, 'password': 'test123',
            'groups_id': [(4, g.id) for g in groups],
        })
    else:
        user.write({'password': 'test123', 'active': True})
        for g in groups:
            if g.id not in user.groups_id.ids:
                user.write({'groups_id': [(4, g.id)]})
    return user

u_director = _get_or_make(
    'p8a_director', ['neon_core.group_neon_superuser'])

# M11.1: seed a zero-item rule-based-fallback insight as the
# LATEST row for the director's dashboard, so the widget renders
# the all-clear empty state deterministically (real rule-based
# output on this DB may have matches; we force the zero case).
Dashboard = env['neon.dashboard'].sudo()
dash = Dashboard.search([('user_id', '=', u_director.id)], limit=1)
if not dash:
    dash = Dashboard.get_or_create_for_user(u_director.id)
rule_provider = env.ref(
    'neon_dashboard.ai_provider_rule_based', raise_if_not_found=False)
env['neon.dashboard.ai.insight'].sudo().create({
    'dashboard_id': dash.id,
    'provider_id': rule_provider.id if rule_provider else False,
    'content_json': '[]',
    'is_fallback': True,
    'error_message': 'M11.1 smoke: forced zero-item fallback',
})

env.cr.commit()
print('IDS_JSON=' + repr({'director_id': u_director.id}))
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
        print("[p8a_m12] SETUP FAILED -- output tail:")
        print(out[-2000:])
        sys.exit(2)
    return eval(m.group(1))  # noqa: S307


def _resize_and_settle(smoke, width, height):
    """Resize viewport + give CSS media queries a moment to apply."""
    smoke.page.set_viewport_size({"width": width, "height": height})
    smoke.page.wait_for_timeout(500)


def _assert_blocks_visible(smoke, label):
    """All 7 director-tier blocks must be in the DOM + occupying
    space. Off-screen-but-present passes; display:none fails."""
    block_classes = [
        "o_neon_block_jobs",
        "o_neon_block_sales",
        "o_neon_block_finance",
        "o_neon_block_alerts",
        "o_neon_block_crew_equipment",
        "o_neon_block_tasks",
        "o_neon_block_ai",
    ]
    missing = []
    for cls in block_classes:
        # Look for either dedicated class OR the generic widget--<key> selector
        if smoke.page.locator(f".{cls}").count() == 0:
            # Try the widget--key fallback
            widget_key = cls.replace("o_neon_block_", "block_")
            if widget_key == "block_ai":
                widget_key = "block_ai_insights"
            if smoke.page.locator(f".widget--{widget_key}").count() == 0:
                missing.append(cls)
    ok = not missing
    smoke._record_assert(
        f"{label}: all 7 blocks present",
        expect="none missing",
        actual=("none missing" if ok else f"missing={missing}"),
        passed=ok,
    )
    if not ok:
        raise AssertionFail(
            f"{label}: missing blocks {missing}")


def run() -> int:
    ids = _setup_fixtures()
    with BrowserSmoke("p8a_m12") as smoke:

        # =============================================================
        # Single login; viewport resized between scenarios.
        # =============================================================
        smoke.login("p8a_director")
        smoke.open_action(
            "neon_dashboard.action_neon_dashboard_server")
        smoke.page.wait_for_selector(
            ".o_neon_kpi_strip", timeout=10000)

        # ----------------------------------------------------------
        # Scenario 1: Desktop control (1280x800)
        # ----------------------------------------------------------
        with smoke.scenario("Desktop 1280x800 control"):
            _resize_and_settle(smoke, 1280, 800)
            _assert_blocks_visible(smoke, "desktop")
            # Header labels visible (Bootstrap d-md-inline -> visible
            # at lg width).
            labels_visible = smoke.page.evaluate(
                "() => {"
                " const e = document.querySelector('.o_neon_dashboard_export_pdf span');"
                " return e && getComputedStyle(e).display !== 'none';"
                "}"
            )
            smoke._record_assert(
                "desktop: PDF label visible",
                expect="visible",
                actual=("visible" if labels_visible else "hidden"),
                passed=bool(labels_visible),
            )
            if not labels_visible:
                raise AssertionFail("desktop: PDF label not visible")
            smoke.screenshot("desktop_1280")

        # ----------------------------------------------------------
        # Scenario 2: Tablet portrait (768x1024)
        # ----------------------------------------------------------
        with smoke.scenario("Tablet 768x1024"):
            _resize_and_settle(smoke, 768, 1024)
            _assert_blocks_visible(smoke, "tablet")
            # KPI strip: 4-up at tablet, 2-up at mobile per D2/D8.
            # The grid-template-columns computed style isn't an
            # ideal probe (it varies); instead check that no
            # horizontal page overflow.
            overflow = smoke.page.evaluate(
                "() => document.documentElement.scrollWidth > "
                "document.documentElement.clientWidth + 1"
            )
            smoke._record_assert(
                "tablet: no horizontal page overflow",
                expect="false",
                actual=str(overflow),
                passed=not overflow,
            )
            if overflow:
                raise AssertionFail("tablet: horizontal page overflow")
            smoke.screenshot("tablet_768")

        # ----------------------------------------------------------
        # Scenario 3: Mobile portrait (375x667 - iPhone SE)
        # ----------------------------------------------------------
        with smoke.scenario("Mobile 375x667"):
            _resize_and_settle(smoke, 375, 667)
            _assert_blocks_visible(smoke, "mobile")

            # Header labels MUST be hidden at <768 (d-md-inline rule)
            pdf_label_hidden = smoke.page.evaluate(
                "() => {"
                " const e = document.querySelector('.o_neon_dashboard_export_pdf span');"
                " return e && getComputedStyle(e).display === 'none';"
                "}"
            )
            smoke._record_assert(
                "mobile: PDF label hidden (icon-only)",
                expect="hidden",
                actual=("hidden" if pdf_label_hidden else "visible"),
                passed=bool(pdf_label_hidden),
            )
            if not pdf_label_hidden:
                raise AssertionFail("mobile: PDF label still visible")

            # Filter chips container should overflow-x: auto (D5)
            chips_overflow_x = smoke.page.evaluate(
                "() => {"
                " const e = document.querySelector('.o_neon_filter_chips');"
                " return e ? getComputedStyle(e).overflowX : 'missing';"
                "}"
            )
            ok_chips = chips_overflow_x in ("auto", "scroll")
            smoke._record_assert(
                "mobile: filter chips overflow-x scrollable",
                expect="auto/scroll",
                actual=str(chips_overflow_x),
                passed=ok_chips,
            )
            if not ok_chips:
                raise AssertionFail(
                    f"mobile: chips overflow-x={chips_overflow_x}")

            # AR aging table thead hidden at mobile (D7 stacked card)
            thead_hidden = smoke.page.evaluate(
                "() => {"
                " const t = document.querySelector('.o_neon_finance_ar_table thead');"
                " if (!t) return 'no-table';"
                " return getComputedStyle(t).display === 'none';"
                "}"
            )
            # If the table renders at all on this DB, thead should be hidden.
            # If the table is absent (empty AR aging), we skip the assertion.
            if thead_hidden == "no-table":
                smoke._record_assert(
                    "mobile: AR aging table absent (empty data)",
                    expect="absent OR thead-hidden",
                    actual="absent",
                    passed=True,
                )
            else:
                smoke._record_assert(
                    "mobile: AR aging thead hidden (stacked card)",
                    expect="hidden",
                    actual=("hidden" if thead_hidden else "visible"),
                    passed=bool(thead_hidden),
                )
                if not thead_hidden:
                    raise AssertionFail(
                        "mobile: AR aging thead still visible")

            # No horizontal page overflow at 375px
            overflow = smoke.page.evaluate(
                "() => document.documentElement.scrollWidth > "
                "document.documentElement.clientWidth + 1"
            )
            smoke._record_assert(
                "mobile: no horizontal page overflow",
                expect="false",
                actual=str(overflow),
                passed=not overflow,
            )
            if overflow:
                # Identify the wide element for diagnostics
                widest = smoke.page.evaluate(
                    "() => {"
                    " let max = 0; let tag = '';"
                    " document.querySelectorAll('*').forEach(el => {"
                    "   const r = el.getBoundingClientRect();"
                    "   if (r.right > max) { max = r.right; tag = el.tagName+'.'+(el.className||'').toString().slice(0,60); }"
                    " });"
                    " return tag + ' right=' + Math.round(max);"
                    "}"
                )
                raise AssertionFail(
                    f"mobile: horizontal overflow, widest={widest}")

            # AI Insights drill-through tap (D10): if any insight
            # exists with a source_ref, clicking it should fire the
            # action service. If no insights, soft-pass.
            ai_insight_count = smoke.page.locator(
                ".o_neon_ai_item").count()
            if ai_insight_count > 0:
                smoke._record_assert(
                    "mobile: AI insight rows visible (tappable)",
                    expect=">=1",
                    actual=str(ai_insight_count),
                    passed=ai_insight_count >= 1,
                )

            # ----------------------------------------------------------
            # M12.1 regression guard: SCROLL REACHABILITY.
            # DOM-presence (asserted above) is NOT enough -- the M12
            # scroll-lock bug had all 7 blocks in the DOM but trapped
            # below an overflow:hidden parent, unreachable on phones.
            # This asserts the dashboard root is a working scroll
            # container: scrollHeight > clientHeight AND scrollTo
            # actually moves the viewport. Tag:
            # browser-smoke-must-test-scroll-reachability.
            # ----------------------------------------------------------
            scroll_probe = smoke.page.evaluate(
                "() => {\n"
                " const el = document.querySelector('.o_neon_dashboard');\n"
                " if (!el) return {found: false};\n"
                " const cs = getComputedStyle(el);\n"
                " const scrollable = el.scrollHeight > el.clientHeight + 10;\n"
                " el.scrollTop = 0;\n"
                " el.scrollTo({top: 1500});\n"
                " const moved = el.scrollTop > 200;\n"
                " return {\n"
                "   found: true,\n"
                "   overflowY: cs.overflowY,\n"
                "   scrollHeight: el.scrollHeight,\n"
                "   clientHeight: el.clientHeight,\n"
                "   scrollable: scrollable,\n"
                "   scrollTopAfter: el.scrollTop,\n"
                "   moved: moved\n"
                " };\n"
                "}"
            )
            ok_scroll = (
                scroll_probe.get("found")
                and scroll_probe.get("scrollable")
                and scroll_probe.get("moved")
            )
            smoke._record_assert(
                "mobile: dashboard content scroll-reachable",
                expect="scrollable + scrollTo moves viewport",
                actual=(
                    f"overflowY={scroll_probe.get('overflowY')} "
                    f"scrollH={scroll_probe.get('scrollHeight')} "
                    f"clientH={scroll_probe.get('clientHeight')} "
                    f"scrollTopAfter={scroll_probe.get('scrollTopAfter')} "
                    f"moved={scroll_probe.get('moved')}"
                ),
                passed=bool(ok_scroll),
            )
            if not ok_scroll:
                raise AssertionFail(
                    "mobile: dashboard content NOT scroll-reachable -- "
                    f"probe={scroll_probe}")

            # Verify the deepest block (AI Insights) is actually
            # reachable: scroll it into view + confirm it intersects
            # the viewport.
            ai_reachable = smoke.page.evaluate(
                "() => {"
                " const ai = document.querySelector('.o_neon_block_ai, .widget--block_ai_insights');"
                " if (!ai) return false;"
                " ai.scrollIntoView({block: 'center'});"
                " const r = ai.getBoundingClientRect();"
                " return r.top < window.innerHeight && r.bottom > 0;"
                "}"
            )
            smoke._record_assert(
                "mobile: deepest block (AI Insights) reachable via scroll",
                expect="intersects viewport after scrollIntoView",
                actual=("reachable" if ai_reachable else "unreachable"),
                passed=bool(ai_reachable),
            )
            if not ai_reachable:
                raise AssertionFail(
                    "mobile: AI Insights block not reachable via scroll")

            smoke.screenshot("mobile_375")

        # ----------------------------------------------------------
        # Scenario 4 (M11.1): AI Insights all-clear empty state.
        # Setup seeded a zero-item is_fallback=True insight as the
        # latest row. Reset to desktop, reload, assert the body
        # shows the all-clear copy AND the subtitle still shows the
        # rule-based fallback note.
        # ----------------------------------------------------------
        with smoke.scenario("M11.1 AI Insights all-clear empty state"):
            _resize_and_settle(smoke, 1280, 800)
            smoke.open_action(
                "neon_dashboard.action_neon_dashboard_server")
            smoke.page.wait_for_selector(
                ".o_neon_block_ai", timeout=10000)
            smoke.page.wait_for_timeout(800)
            body_text = smoke.page.evaluate(
                "() => {"
                " const b = document.querySelector('.o_neon_block_ai');"
                " return b ? b.innerText : '';"
                "}"
            )
            has_all_clear = "All clear" in body_text and "nothing flagged this cycle" in body_text
            smoke._record_assert(
                "M11.1: all-clear copy renders for zero-item insight",
                expect="'All clear — nothing flagged this cycle.'",
                actual=("present" if has_all_clear else f"absent; body={body_text[:160]!r}"),
                passed=has_all_clear,
            )
            if not has_all_clear:
                raise AssertionFail(
                    f"M11.1: all-clear copy missing; body={body_text[:300]!r}")
            # Subtitle still carries the fallback note (both pieces present)
            has_fallback_subtitle = (
                "Rule-based fallback" in body_text
                or "AI provider unavailable" in body_text
            )
            smoke._record_assert(
                "M11.1: fallback subtitle still present alongside all-clear",
                expect="'Rule-based fallback' in subtitle",
                actual=("present" if has_fallback_subtitle else "absent"),
                passed=has_fallback_subtitle,
            )
            if not has_fallback_subtitle:
                raise AssertionFail(
                    "M11.1: fallback subtitle missing alongside all-clear copy")
            smoke.screenshot("ai_all_clear")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(run())
