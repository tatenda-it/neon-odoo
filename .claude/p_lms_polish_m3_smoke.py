"""LMS Admin Polish M3 smoke -- slide editor + autosave JS
(5 tests).

T_LP300 - inherit slide form loads without errors
T_LP301 - html widget present on description in combined arch
T_LP302 - autosave JS file exists at expected path
T_LP303 - JS file listed in manifest web.assets_backend
T_LP304 - slide save via ORM write persists description field
"""
import os


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Slide = env["slide.slide"]
View = env["ir.ui.view"]
Module = env["ir.module.module"]


# ============================================================
print()
print("T_LP300 - inherit slide form loads without errors")
print("=" * 72)
inherit = env.ref(
    "neon_lms.view_slide_slide_form_neon_lms",
    raise_if_not_found=False)
ok = bool(inherit)
err_msg = ""
if inherit:
    try:
        view_info = Slide.get_view(
            view_id=inherit.id, view_type="form")
        ok = ok and bool(view_info.get("arch"))
    except Exception as e:  # noqa: BLE001
        ok = False
        err_msg = str(e)
print(f"  inherit view present: {bool(inherit)}")
print(f"  get_view loads: {ok}")
if err_msg:
    print(f"  err: {err_msg[:200]}")
print("T_LP300:", "PASS" if ok else "FAIL")
results["T_LP300"] = ok


# ============================================================
print()
print("T_LP301 - html widget present on description in "
      "combined arch")
print("=" * 72)
arch = ""
try:
    parent = env.ref(
        "website_slides.view_slide_slide_form")
    view_info = Slide.get_view(
        view_id=parent.id, view_type="form")
    arch = view_info.get("arch") or ""
except Exception as e:  # noqa: BLE001
    print(f"  err: {e}")
# Combined arch should have description with widget=html
# (from our M3 inherit xpath attributes).
import re
m = re.search(
    r'<field[^>]*name="description"[^>]*>', arch)
if m:
    fragment = m.group(0)
    has_widget = 'widget="html"' in fragment
    print(f"  description tag: {fragment[:120]}")
else:
    has_widget = False
    print("  description field not found in arch")
# Also verify the autosave indicator span is in arch.
has_indicator = (
    "neon_lms_autosave_indicator" in arch)
ok = has_widget and has_indicator
print(f"  widget=html on description: {has_widget}")
print(f"  autosave indicator span present: {has_indicator}")
print("T_LP301:", "PASS" if ok else "FAIL")
results["T_LP301"] = ok


# ============================================================
print()
print("T_LP302 - autosave JS file exists at expected path")
print("=" * 72)
expected = ("/mnt/extra-addons/neon_lms/static/src/js/"
            "lms_slide_autosave.js")
exists = os.path.isfile(expected)
size = os.path.getsize(expected) if exists else 0
ok = exists and size > 0
print(f"  path: {expected}")
print(f"  exists: {exists}, size: {size}")
print("T_LP302:", "PASS" if ok else "FAIL")
results["T_LP302"] = ok


# ============================================================
print()
print("T_LP303 - JS file listed in manifest "
      "web.assets_backend")
print("=" * 72)
neon_lms_mod = Module.search(
    [("name", "=", "neon_lms")], limit=1)
manifest_path = (
    "/mnt/extra-addons/neon_lms/__manifest__.py")
with open(manifest_path) as fh:
    txt = fh.read()
has_assets_section = '"web.assets_backend"' in txt
has_js_entry = (
    "neon_lms/static/src/js/lms_slide_autosave.js" in txt)
ok = has_assets_section and has_js_entry
print(f"  assets_backend key in manifest: "
      f"{has_assets_section}")
print(f"  JS path in manifest: {has_js_entry}")
print("T_LP303:", "PASS" if ok else "FAIL")
results["T_LP303"] = ok


# ============================================================
print()
print("T_LP304 - slide save via ORM write persists "
      "description field")
print("=" * 72)
channel = env.ref(
    "neon_lms.program_channel", raise_if_not_found=False)
ok = False
if channel:
    s = Slide.search(
        [("channel_id", "=", channel.id)], limit=1)
    if not s:
        # M3 doesn't ship slides; create a probe.
        s = Slide.create({
            "name": "M3 autosave probe",
            "channel_id": channel.id,
            "slide_category": "article",
        })
    probe = (
        "<p>autosave probe content "
        + str(env.cr.now()) + "</p>")
    s.write({"description": probe})
    s.invalidate_recordset(["description"])
    persisted = s.description or ""
    ok = "autosave probe content" in persisted
    print(f"  slide id: {s.id}")
    print(f"  persisted description snippet: "
          f"{persisted[:80]}")
else:
    print("  program channel not found (skip)")
print("T_LP304:", "PASS" if ok else "FAIL")
results["T_LP304"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T_LP300", "T_LP301", "T_LP302", "T_LP303",
         "T_LP304"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
