"""P8A XML lint -- every .xml file under addons/neon_*/ must parse
cleanly via lxml.etree.parse.

Surfaced after P8A.M10 deploy broke prod: the OWL template at
neon_dashboard.xml line 56 contained `<!-- M10 -- export buttons -->`.
XML disallows '--' anywhere inside a comment (em-dashes / ' -- '
separators in human-readable text both fall foul of this). The
Odoo asset bundle SILENTLY EXCLUDES files that fail to parse,
producing a misleading 'cache staleness' false signal.

This bug class hit M9 (data XML, caught at -u time) AND M10
(static OWL XML, ONLY surfaced at browser load via OwlError).
Automated lint added as part of the M10 fix round.

T9000-T9019 reserved for XML lint findings. Runs as a Python
smoke from .claude/run_regression.sh -- pure CPython parse check,
no Odoo dependency.

Usage:
    Runs inside odoo shell like the other smokes (env is provided
    even though we don't use it -- keeps the runner consistent).

Coverage:
    addons/neon_*/**/*.xml -- both data XML and static OWL XML.
    Failures listed with file + lxml error message.
"""
import pathlib

from lxml import etree


print("=" * 72)
print("P8A XML lint -- every .xml under addons/neon_*/")
print("=" * 72)


results = {}
failures = []
checked = 0
neon_modules = []


def _project_root():
    """Resolve the host-mounted project root from inside the
    container. The Odoo addons path is /mnt/extra-addons on the
    Docker image we use locally + on Hetzner."""
    candidates = [
        pathlib.Path("/mnt/extra-addons"),
        pathlib.Path("addons"),
        pathlib.Path("/opt/neon-odoo/addons"),
    ]
    for c in candidates:
        if c.exists() and any(p.name.startswith("neon_") for p in c.iterdir()):
            return c
    return pathlib.Path("/mnt/extra-addons")


root = _project_root()
print(f"Scanning {root} ...")


for module_dir in sorted(root.iterdir()):
    if not module_dir.is_dir():
        continue
    if not module_dir.name.startswith("neon_"):
        continue
    neon_modules.append(module_dir.name)
    module_failures = []
    for xml_path in module_dir.rglob("*.xml"):
        checked += 1
        try:
            etree.parse(str(xml_path))
        except etree.XMLSyntaxError as exc:
            module_failures.append((str(xml_path), str(exc)))
            failures.append((str(xml_path), str(exc)))
    test_id = f"T9000_{module_dir.name}"
    results[test_id] = not module_failures
    status = "PASS" if not module_failures else "FAIL"
    print(f"  {test_id} ({len(list(module_dir.rglob('*.xml')))} files): "
          f"{status}")
    for f, e in module_failures:
        print(f"      {f}: {e[:120]}")


# ============================================================
print()
print("=" * 72)
print(f"Modules scanned: {len(neon_modules)}")
print(f"Total XML files: {checked}")
print(f"Failures: {len(failures)}")
print("=" * 72)


# Standard summary line so run_regression.sh picks it up.
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
