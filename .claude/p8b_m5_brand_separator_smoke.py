"""P8B.M5 smoke -- brand separator is an em-dash, not ASCII '--'.

T8B95-T8B97. File-content assertion on the OWL template (the
separator is static template text, not a DB record), mirroring the
p8a_xml_lint file-read approach.
"""
import re

results = {}
print("=" * 72)
print("P8B.M5 -- brand separator polish")
print("=" * 72)

TPL = ("/mnt/extra-addons/neon_dashboard/static/src/js/"
       "neon_dashboard/neon_dashboard.xml")
with open(TPL, "r", encoding="utf-8") as f:
    xml = f.read()

m = re.search(r'<span class="o_neon_dashboard_sep">(.*?)</span>', xml)
sep = m.group(1) if m else None


def _check(tnum, cond, detail=""):
    results[tnum] = bool(cond)
    print(f"{tnum}: {'PASS' if cond else 'FAIL'} {detail}")


# T8B95 -- separator span present + content is the em-dash U+2014.
_check("T8B95", sep == "—", f"sep={sep!r}")

# T8B96 -- no ASCII double-hyphen separator remains.
_check("T8B96",
       '<span class="o_neon_dashboard_sep">--</span>' not in xml,
       "no ASCII -- separator")

# T8B97 -- the em-dash codepoint is exactly U+2014 (not en-dash U+2013).
_check("T8B97", sep is not None and ord(sep) == 0x2014,
       f"codepoint={hex(ord(sep)) if sep else None}")

print("=" * 72)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{len(results)} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
