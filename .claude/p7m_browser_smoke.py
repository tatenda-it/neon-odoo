"""P7m browser smoke -- quick-ref prefix + author-note cleanup (rendered).

Prereq: p7m_browser_setup.py.

1. QUICK-REF: the short summary lesson renders with the "Quick Reference: "
   prefix in its title (visible learner signal).
2. AUTHOR-NOTE: the formerly-meta lesson renders with NO "source brief"
   text, and the rephrased learner sentence is present + siblings intact.
"""
from __future__ import annotations

import sys

from browser_smoke import AssertionFail, BrowserSmoke

QR_PREFIX = "Quick Reference: "
QR_BASE = "L9.1 -- P7M QR Browser Demo"
NOTE_NAME = "L9 -- P7M Note Browser Demo"


def _slide(smoke, name):
    body = smoke.json_rpc(
        "slide.slide", "search_read",
        args=[[["name", "=", name]], ["id", "name", "website_url"]])
    rows = body.get("result") or []
    if not rows:
        raise AssertionFail("slide %r not found -- run p7m_browser_setup.py" % name)
    return rows[0]


def main() -> int:
    with BrowserSmoke("p7m") as smoke:

        with smoke.scenario("quick-reference lesson shows the title prefix"):
            smoke.login("p2m75_sales")
            qr = _slide(smoke, QR_PREFIX + QR_BASE)
            smoke._record_assert(
                "lesson name carries 'Quick Reference:' prefix",
                expect=QR_PREFIX + QR_BASE, actual=qr["name"],
                passed=qr["name"].startswith(QR_PREFIX))
            smoke.page.goto(smoke.base_url + "/slides/slide/%s" % qr["id"],
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(1500)
            body = smoke.page.inner_text("body")
            smoke._record_assert(
                "'Quick Reference:' visible in the rendered lesson page",
                expect="present", actual="present" if QR_PREFIX in body else "absent",
                passed=QR_PREFIX in body)
            if QR_PREFIX not in body:
                raise AssertionFail("prefix not rendered: %r" % body[:160])
            smoke.screenshot("p7m_quickref_prefix")

        with smoke.scenario("author-note lesson renders with no 'source brief' meta"):
            smoke.login("p2m75_sales")
            note = _slide(smoke, NOTE_NAME)
            smoke.page.goto(smoke.base_url + "/slides/slide/%s" % note["id"],
                            wait_until="networkidle")
            smoke.page.wait_for_timeout(1500)
            body = smoke.page.inner_text("body")
            smoke._record_assert(
                "no 'source brief' meta in rendered body",
                expect="absent",
                actual="present" if "source brief" in body.lower() else "absent",
                passed="source brief" not in body.lower())
            smoke._record_assert(
                "rephrased learner sentence present + sibling intact",
                expect="'Technicians must' + 'Protect life first'",
                actual="resp=%s sib=%s" % ("Technicians must respond" in body,
                                           "Protect life first" in body),
                passed="Technicians must respond" in body
                and "Protect life first" in body)
            if "source brief" in body.lower():
                raise AssertionFail("'source brief' still rendered")
            smoke.screenshot("p7m_authornote_clean")

        return smoke.summary()


if __name__ == "__main__":
    sys.exit(main())
