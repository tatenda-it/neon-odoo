"""Browser smoke harness for the milestone pipeline.

Companion to the in-container ``odoo shell`` Python smokes. Verifies
the user-facing surface (menu visibility, list/form rendering, element
counts) that the ORM-layer smokes cannot see.

Run from the host using the bundled venv:

  .\\.claude\\.venv-browser\\Scripts\\python .\\.claude\\p6m1_browser_smoke.py

Each concrete smoke imports :class:`BrowserSmoke`, runs scenarios under
its context manager, then calls ``smoke.summary()`` which writes
``result.json``, updates ``latest.txt`` and returns exit code 0/1 for
the regression gate.

----------------------------------------------------------------------
DEPTH PRINCIPLE  (introduced P6.M1, written into the harness contract)
----------------------------------------------------------------------
For every menu a smoke verifies as visible, CLICK INTO IT and assert
at least one piece of content (row count, specific cell value, a form
notebook tab populated). Menu visibility alone proves the route is
exposed; depth assertions prove the action behind the menu still
works. Yesterday's P6.M1 bug set showed 3 of 4 bugs surfaced as
"menu visible but action broken" --- visibility-only checks would
have missed them.

Negative tests (menu NOT visible / app NOT in launcher) don't need
depth --- absence is its own evidence.

----------------------------------------------------------------------
SPOT-CHECK PROTOCOL
----------------------------------------------------------------------
On any FAIL the harness records:

* the assertion name + expected vs actual
* a screenshot at the failure point (``99_FAIL_<name>.png``)
* a DOM snippet around the locator (outer_html of nearest ancestor)
* a heuristic diagnosis (cache? selector drift? gating? timing?)
* the suggestion line "PAUSE --- recommend fix direction X, want a
  second opinion before applying?"

Routine PASS runs flow through to the commit gate without
intervention; FAIL runs surface the above bundle so Tatenda can
spot-check before any fix lands.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
import pathlib
import sys
import time
import traceback
from typing import Any, Iterable

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


SMOKE_OUTPUT_ROOT = pathlib.Path(__file__).resolve().parent / "smoke-output"
DEFAULT_BASE_URL = "http://localhost:8069"
DEFAULT_DB = "neon_crm"
DEFAULT_PASSWORD = "test123"
DEFAULT_TIMEOUT_MS = 15_000


class AssertionFail(Exception):
    """Raised internally to abort a scenario and route to ``_record_fail``."""


class BrowserSmoke:
    """Context manager wrapping a Playwright browser for one smoke run.

    Usage::

        with BrowserSmoke("p6m1") as smoke:
            with smoke.scenario("p2m75_book reaches pricing rules"):
                smoke.login("p2m75_book")
                smoke.assert_menu_visible("neon_finance.menu_neon_finance_pricing_rules")
                smoke.open_action("neon_finance.neon_finance_pricing_rule_action")
                smoke.assert_count("tr.o_data_row", 18, "pricing rule rows")
                smoke.screenshot("pricing_rules_list")
            ...
        sys.exit(smoke.summary())
    """

    def __init__(
        self,
        name: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        db: str = DEFAULT_DB,
        headless: bool = True,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.db = db
        self.headless = headless

        self.timestamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.output_dir = SMOKE_OUTPUT_ROOT / name / self.timestamp
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._screenshot_counter = 0
        self._scenarios: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None

        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._current_login: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def __enter__(self) -> "BrowserSmoke":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._new_context()
        print(f"[{self.name}] browser launched, output -> {self.output_dir}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        with contextlib.suppress(Exception):
            if self._context is not None:
                self._context.close()
        with contextlib.suppress(Exception):
            if self._browser is not None:
                self._browser.close()
        with contextlib.suppress(Exception):
            if self._pw is not None:
                self._pw.stop()

    def _new_context(self) -> None:
        """(Re)create a fresh context; called on enter and between logins."""
        if self._context is not None:
            with contextlib.suppress(Exception):
                self._context.close()
        assert self._browser is not None
        self._context = self._browser.new_context(viewport={"width": 1400, "height": 900})
        self._context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        self._page = self._context.new_page()
        self._current_login = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("smoke not entered (use 'with BrowserSmoke(...) as smoke')")
        return self._page

    # ------------------------------------------------------------------
    # Scenario tracking
    # ------------------------------------------------------------------
    @contextlib.contextmanager
    def scenario(self, label: str):
        """Group one logical user-journey under ``label``.

        Failures inside the block are caught, recorded, and the harness
        moves on to the next scenario --- one bad assertion does not
        abort the run. Final exit code is based on the aggregate.
        """
        print(f"\n[{self.name}] >>> {label}")
        self._current = {"label": label, "passed": True, "asserts": [], "fail": None}
        try:
            yield
        except AssertionFail as e:
            self._current["passed"] = False
            self._current["fail"] = str(e)
            print(f"[{self.name}]  FAIL: {e}")
        except Exception as e:  # noqa: BLE001 - last-ditch capture
            self._current["passed"] = False
            self._current["fail"] = f"unexpected: {e}"
            print(f"[{self.name}]  CRASH: {e}")
            traceback.print_exc()
            self._capture_fail_artifacts("unexpected_exception")
        finally:
            self._scenarios.append(self._current)
            status = "PASS" if self._current["passed"] else "FAIL"
            print(f"[{self.name}] <<< {status}: {label}")
            self._current = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self, login: str, password: str = DEFAULT_PASSWORD) -> int:
        """Log in via /web/login form (the path real users take).

        Re-uses the existing browser context when switching to the same
        login; spawns a fresh context for a different user to guarantee
        a clean cookie jar (Odoo's session_id is identity-bound).
        """
        if self._current_login is not None and self._current_login != login:
            self._new_context()
        if self._current_login == login:
            return self._uid_from_session()

        page = self.page
        page.goto(f"{self.base_url}/web/login", wait_until="domcontentloaded")
        page.fill("input[name=login]", login)
        page.fill("input[name=password]", password)
        page.click("button[type=submit]")
        try:
            page.wait_for_url(lambda url: "/web/login" not in url, timeout=DEFAULT_TIMEOUT_MS)
        except PlaywrightTimeoutError as exc:
            self._record_assert(
                f"login({login})", expect="navigation away from /web/login", actual="still on /web/login"
            )
            raise AssertionFail(f"login({login}) failed: {exc}") from exc

        uid = self._uid_from_session()
        self._current_login = login
        self._record_assert(f"login({login})", expect="uid>0", actual=f"uid={uid}", passed=uid > 0)
        if uid <= 0:
            raise AssertionFail(f"login({login}) returned uid={uid}")
        return uid

    def _uid_from_session(self) -> int:
        # /web/session/get_session_info is a JSON-RPC endpoint --- requires
        # POST with a body, not a bare GET (which returns empty + 405).
        resp = self.page.request.post(
            f"{self.base_url}/web/session/get_session_info",
            data=json.dumps({"jsonrpc": "2.0", "method": "call", "params": {}}),
            headers={"Content-Type": "application/json"},
        )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return 0
        return int((data.get("result") or {}).get("uid") or 0)

    # ------------------------------------------------------------------
    # Menu introspection
    # ------------------------------------------------------------------
    def _load_web_menus(self) -> dict[str, dict[str, Any]]:
        """Call ir.ui.menu.load_web_menus and return the menu dict.

        The shape is ``{menu_id_str: {name, xmlid, children, ...}}``
        with ``"root"`` as the entry point. Filtering already reflects
        the current user's group reach --- this is exactly what the web
        client renders.
        """
        resp = self.page.request.post(
            f"{self.base_url}/web/dataset/call_kw",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "model": "ir.ui.menu",
                        "method": "load_web_menus",
                        # ir.ui.menu.load_web_menus(self, debug) is a regular
                        # (non-@api.model) instance method; call_kw expects
                        # [ids, *positional_args] --- empty ids + debug=False.
                        "args": [[], False],
                        "kwargs": {},
                    },
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        body = resp.json()
        if "error" in body and body["error"]:
            raise AssertionFail(f"load_web_menus RPC error: {body['error']}")
        return body.get("result") or {}

    def _menu_xmlids(self) -> set[str]:
        menus = self._load_web_menus()
        return {m.get("xmlid") for m in menus.values() if m.get("xmlid")}

    def assert_menu_visible(self, xmlid: str, *, name: str | None = None) -> None:
        label = name or f"menu_visible({xmlid})"
        actual = "visible" if xmlid in self._menu_xmlids() else "hidden"
        self._record_assert(label, expect="visible", actual=actual, passed=actual == "visible")
        if actual != "visible":
            self._capture_fail_artifacts(label)
            raise AssertionFail(f"{label}: menu xmlid not reachable for current user")

    def assert_menu_hidden(self, xmlid: str, *, name: str | None = None) -> None:
        label = name or f"menu_hidden({xmlid})"
        actual = "visible" if xmlid in self._menu_xmlids() else "hidden"
        self._record_assert(label, expect="hidden", actual=actual, passed=actual == "hidden")
        if actual != "hidden":
            self._capture_fail_artifacts(label)
            raise AssertionFail(f"{label}: menu xmlid still reachable for current user")

    # ------------------------------------------------------------------
    # Navigation + UI assertions
    # ------------------------------------------------------------------
    def goto_home(self) -> None:
        """Go to the backend home (/web). The /odoo path falls through to the
        website 404 handler on this build, so /web is the canonical entry."""
        self.page.goto(f"{self.base_url}/web", wait_until="networkidle")

    def open_action(self, xmlid: str) -> None:
        """Deep-link to an act_window keyed by xmlid.

        Resolves xmlid -> numeric action id via /web/action/load (the
        same endpoint the probe scripts use), then navigates to
        ``/web#action=<id>``. The web client expands the hash on load,
        rewriting the URL to include menu_id + view_type. The /odoo/
        action- pattern documented for some 17.x builds 404s here, so
        the hash-route is the reliable path.
        """
        load = self.page.request.post(
            f"{self.base_url}/web/action/load",
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "call", "params": {"action_id": xmlid}}
            ),
            headers={"Content-Type": "application/json"},
        )
        body = load.json()
        result = body.get("result") or {}
        action_id = result.get("id")
        if not action_id:
            raise AssertionFail(f"open_action({xmlid}): xmlid did not resolve to a numeric id ({body})")
        self.page.goto(
            f"{self.base_url}/web#action={action_id}",
            wait_until="networkidle",
        )

    def assert_count(self, selector: str, expected: int, name: str) -> None:
        """Assert the page has exactly ``expected`` elements matching ``selector``.

        Waits up to the default timeout for the count to settle ---
        Odoo's OWL views render the rows asynchronously after the
        action loads, so a bare locator.count() races on first paint.
        """
        page = self.page
        end_t = time.monotonic() + (DEFAULT_TIMEOUT_MS / 1000.0)
        actual = -1
        while time.monotonic() < end_t:
            actual = page.locator(selector).count()
            if actual == expected:
                break
            page.wait_for_timeout(150)
        passed = actual == expected
        self._record_assert(name, expect=str(expected), actual=str(actual), passed=passed)
        if not passed:
            self._capture_fail_artifacts(name, selector=selector)
            raise AssertionFail(f"{name}: expected {expected} elements matching {selector!r}, got {actual}")

    def assert_visible(self, selector: str, name: str) -> None:
        page = self.page
        try:
            page.locator(selector).first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
            actual = "visible"
        except PlaywrightTimeoutError:
            actual = "not visible / not present"
        passed = actual == "visible"
        self._record_assert(name, expect="visible", actual=actual, passed=passed)
        if not passed:
            self._capture_fail_artifacts(name, selector=selector)
            raise AssertionFail(f"{name}: {selector!r} not visible")

    def click(self, selector: str, *, name: str | None = None) -> None:
        label = name or f"click({selector})"
        try:
            self.page.locator(selector).first.click(timeout=DEFAULT_TIMEOUT_MS)
            self._record_assert(label, expect="clickable", actual="clicked", passed=True)
        except PlaywrightTimeoutError as exc:
            self._record_assert(label, expect="clickable", actual="timeout", passed=False)
            self._capture_fail_artifacts(label, selector=selector)
            raise AssertionFail(f"{label}: not clickable within timeout") from exc

    # ------------------------------------------------------------------
    # JSON-RPC (kept narrow: ACL boundary cases only)
    # ------------------------------------------------------------------
    def json_rpc(self, model: str, method: str, args: Iterable[Any] = (), kwargs: dict | None = None) -> dict:
        """Call /web/dataset/call_kw within the current browser session."""
        body = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": list(args),
                "kwargs": kwargs or {},
            },
        }
        resp = self.page.request.post(
            f"{self.base_url}/web/dataset/call_kw",
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
        )
        return resp.json()

    def assert_rpc_denied(self, model: str, method: str, name: str, args: Iterable[Any] = (), kwargs: dict | None = None) -> None:
        body = self.json_rpc(model, method, args=args, kwargs=kwargs)
        err = (body.get("error") or {}).get("data") or {}
        err_name = err.get("name", "")
        passed = err_name == "odoo.exceptions.AccessError"
        actual = err_name or ("success: " + str(body.get("result"))[:80])
        self._record_assert(name, expect="AccessError", actual=actual, passed=passed)
        if not passed:
            self._capture_fail_artifacts(name)
            raise AssertionFail(f"{name}: expected AccessError, got {actual}")

    # ------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------
    def screenshot(self, label: str) -> pathlib.Path:
        self._screenshot_counter += 1
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        path = self.output_dir / f"{self._screenshot_counter:02d}_{safe}.png"
        self.page.screenshot(path=str(path), full_page=True)
        return path

    # ------------------------------------------------------------------
    # Internal: failure capture + bookkeeping
    # ------------------------------------------------------------------
    def _record_assert(self, name: str, *, expect: str, actual: str, passed: bool = True) -> None:
        record = {"name": name, "expect": expect, "actual": actual, "passed": passed}
        if self._current is not None:
            self._current["asserts"].append(record)
        marker = "  ok" if passed else "FAIL"
        print(f"[{self.name}]   {marker}  {name}: expect={expect} actual={actual}")

    def _capture_fail_artifacts(self, label: str, *, selector: str | None = None) -> None:
        """Bundle for spot-check protocol: screenshot + DOM snippet + diagnosis."""
        safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
        shot = self.output_dir / f"99_FAIL_{safe}.png"
        with contextlib.suppress(Exception):
            self.page.screenshot(path=str(shot), full_page=True)
        dom_snippet = ""
        if selector:
            with contextlib.suppress(Exception):
                dom_snippet = self.page.locator(selector).first.evaluate(
                    "el => (el.outerHTML || '').slice(0, 800)"
                ) or ""
                if not dom_snippet:
                    dom_snippet = self.page.locator(f"{selector}").first.evaluate(
                        "el => (el.parentElement && el.parentElement.outerHTML || '').slice(0, 800)"
                    )
        diagnosis = self._diagnose(label, selector, dom_snippet)
        snippet_path = self.output_dir / f"99_FAIL_{safe}.txt"
        with contextlib.suppress(Exception):
            snippet_path.write_text(
                "Assertion: " + label + "\n"
                "URL: " + self.page.url + "\n"
                "Selector: " + (selector or "(n/a)") + "\n"
                "Suggested diagnosis: " + diagnosis + "\n"
                "PAUSE --- recommend fix direction above; second opinion before applying?\n\n"
                "DOM snippet:\n" + (dom_snippet or "(none captured)") + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _diagnose(label: str, selector: str | None, dom: str) -> str:
        lower_label = label.lower()
        if "menu" in lower_label and "hidden" in lower_label:
            return "group gating: a menu the user should NOT see is still in load_web_menus output --- check groups_id on the menuitem and on parent menus."
        if "menu" in lower_label and "visible" in lower_label:
            return "group gating or parent-menu cascade: load_web_menus filtered this xmlid out --- check the parent menu's groups_id (visibility cascades top-down)."
        if "count" in lower_label or "rows" in lower_label:
            return "either the action did not render expected data (seed missing / domain wrong), the OWL view hasn't finished rendering (raise timeout), or the row selector drifted from .o_data_row in this Odoo build."
        if "click" in lower_label:
            return "selector drift (element renamed in a recent Odoo upgrade) or the element is occluded by a modal --- inspect the screenshot."
        if "rpc" in lower_label or "access" in lower_label:
            return "ACL boundary regressed: model is reachable from a role that should be blocked. Check ir.model.access rules and the model's _check_access_rights overrides."
        if selector is None:
            return "no DOM context; check the screenshot and verify the user has session_id cookie + a uid > 0."
        return "general: compare screenshot to the last passing run under .claude/smoke-output/<smoke>/<previous-ts>/."

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    def summary(self) -> int:
        total = len(self._scenarios)
        passed = sum(1 for s in self._scenarios if s["passed"])
        failed = total - passed
        print()
        print("=" * 72)
        print(f"BROWSER SMOKE {self.name}: {passed}/{total} scenarios PASS")
        for s in self._scenarios:
            mark = "PASS" if s["passed"] else "FAIL"
            print(f"  [{mark}] {s['label']}" + (f" -- {s['fail']}" if not s["passed"] else ""))
        print("=" * 72)

        result = {
            "smoke": self.name,
            "started": self.timestamp,
            "base_url": self.base_url,
            "db": self.db,
            "total": total,
            "passed": passed,
            "failed": failed,
            "scenarios": self._scenarios,
        }
        (self.output_dir / "result.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        latest = SMOKE_OUTPUT_ROOT / self.name / "latest.txt"
        latest.write_text(self.timestamp, encoding="utf-8")
        print(f"[{self.name}] artifacts: {self.output_dir}")
        return 0 if failed == 0 else 1


if __name__ == "__main__":
    # Self-test: launch a browser, open localhost:8069, take a screenshot.
    # Not a smoke per se --- just confirms the harness can drive the
    # browser end-to-end after installation.
    with BrowserSmoke("selftest") as s:
        with s.scenario("login page renders"):
            s.page.goto(f"{s.base_url}/web/login", wait_until="domcontentloaded")
            s.assert_visible("input[name=login]", "login form input")
            s.screenshot("login_page")
    sys.exit(s.summary())
