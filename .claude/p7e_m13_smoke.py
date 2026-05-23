"""P7e.M13 smoke -- PHP content migration script structure.

7 static tests verifying the one-shot migration script's
structure, helper functions, and one-shot wiring. Actual docx
parsing + content import is NOT tested here -- those run when
Tatenda invokes the script manually post-deploy.

Tests:
- T7e1300: script file exists at scripts/migrate_php_content.py
- T7e1301: script loads cleanly via importlib (syntactically
  valid + `if env in dir()` guard skips when env absent)
- T7e1302: preflight_check returns (False, error) for missing
  docx
- T7e1303: quiz_question_exists detects present vs absent
  records correctly (idempotency check function)
- T7e1304: sanitize_mojibake round-trips known html-to-docx
  artifacts (apostrophe + ellipsis + em-dash)
- T7e1305: detect_module_code accepts M01-M17 + rejects M00,
  M18, and 'Module M01' (no leading code)
- T7e1306: script is one-shot -- not in manifest data files,
  no post_init_hook, no ir.cron record references it
"""
import importlib.util
import inspect
import os
import re

from odoo import fields, SUPERUSER_ID
import odoo.addons.neon_lms as nlms

results = {}

ADDON_DIR = os.path.dirname(nlms.__file__)
SCRIPT_PATH = os.path.join(
    ADDON_DIR, "scripts", "migrate_php_content.py")
MANIFEST_PATH = os.path.join(ADDON_DIR, "__manifest__.py")


print("=" * 72)
print("SETUP")
print("=" * 72)
print("addon_dir:", ADDON_DIR)
print("script_path:", SCRIPT_PATH)


# ============================================================
print()
print("T7e1300 - script file exists")
print("=" * 72)
ok = os.path.isfile(SCRIPT_PATH)
print(f"  exists: {ok}")
print("T7e1300:", "PASS" if ok else "FAIL")
results["T7e1300"] = ok


# ============================================================
print()
print("T7e1301 - script loads cleanly via importlib (syntax ok)")
print("=" * 72)
mod = None
load_err = None
try:
    spec = importlib.util.spec_from_file_location(
        "neon_lms_migrate_php_content", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    # Guard: `env` must NOT be in module globals before
    # exec_module so the script's bottom `if "env" in dir()`
    # block skips. importlib doesn't inject env -- this is the
    # default safe behaviour we're relying on.
    spec.loader.exec_module(mod)
    ok = True
except Exception as e:
    load_err = e
    ok = False
print(f"  load ok: {ok}")
if load_err:
    print(f"  err: {load_err}")
print("T7e1301:", "PASS" if ok else "FAIL")
results["T7e1301"] = ok


# ============================================================
print()
print("T7e1302 - preflight_check detects missing docx")
print("=" * 72)
ok = False
if mod is not None:
    pf_ok, pf_msg = mod.preflight_check(
        "/nonexistent/path/does_not_exist.docx", env)
    ok = (
        pf_ok is False
        and isinstance(pf_msg, str)
        and "DOCX not found" in pf_msg)
    print(f"  preflight returned: ({pf_ok}, {pf_msg!r})")
print("T7e1302:", "PASS" if ok else "FAIL")
results["T7e1302"] = ok


# ============================================================
print()
print("T7e1303 - quiz_question_exists detects present vs absent")
print("=" * 72)
ok = False
if mod is not None:
    Module = env["neon.lms.module"]
    QQ = env["neon.lms.quiz.question"]
    m01 = Module.sudo().search(
        [("code", "=", "M01")], limit=1)
    # Create + assert exists returns True
    sentinel_text = (
        "T7e1303 idempotency sentinel: which PPE applies "
        "for rigging at 2m height?")
    QQ.sudo().create({
        "module_id": m01.id,
        "question_text": sentinel_text,
        "question_type": "short_answer",
        "correct_answer": "PPE for working at height",
    })
    present = mod.quiz_question_exists(
        env, "M01", sentinel_text)
    absent = mod.quiz_question_exists(
        env, "M01",
        "T7e1303 NEVER-EXISTED text that no record has")
    ok = (present is True and absent is False)
    print(f"  present-check: {present}, absent-check: {absent}")
print("T7e1303:", "PASS" if ok else "FAIL")
results["T7e1303"] = ok


# ============================================================
print()
print("T7e1304 - sanitize_mojibake round-trip")
print("=" * 72)
ok = False
if mod is not None:
    cases = [
        ("Arnoldâ€™s",
         "Arnold's"),
        ("module M01â€”M03",
         "module M01—M03"),  # em-dash
        ("function roomâ€¦",
         "function room…"),  # ellipsis
        ("plain ASCII no change", "plain ASCII no change"),
        ("", ""),
    ]
    all_pass = True
    for inp, expected in cases:
        out = mod.sanitize_mojibake(inp)
        marker = "ok" if out == expected else "MISMATCH"
        print(f"  {marker}: {inp!r} -> {out!r} "
              f"(expected {expected!r})")
        if out != expected:
            all_pass = False
    ok = all_pass
print("T7e1304:", "PASS" if ok else "FAIL")
results["T7e1304"] = ok


# ============================================================
print()
print("T7e1305 - detect_module_code accepts M01-M17 + rejects others")
print("=" * 72)
ok = False
if mod is not None:
    accept_cases = [
        ("M01 Safety Foundations", "M01"),
        ("M07 LED / Video Advanced", "M07"),
        ("M17 Truss Systems", "M17"),
        ("  M03  with leading space", "M03"),
    ]
    reject_cases = [
        "Module M01: Safety",  # no leading M01
        "M00 Out of range low",
        "M18 Out of range high",
        "M99 Out of range",
        "Hello world",
        "",
    ]
    all_pass = True
    for inp, expected in accept_cases:
        out = mod.detect_module_code(inp)
        marker = "ok" if out == expected else "MISMATCH"
        print(f"  accept {marker}: {inp!r} -> {out!r} "
              f"(expected {expected!r})")
        if out != expected:
            all_pass = False
    for inp in reject_cases:
        out = mod.detect_module_code(inp)
        marker = "ok" if out is None else "MISMATCH"
        print(f"  reject {marker}: {inp!r} -> {out!r} "
              f"(expected None)")
        if out is not None:
            all_pass = False
    ok = all_pass
print("T7e1305:", "PASS" if ok else "FAIL")
results["T7e1305"] = ok


# ============================================================
print()
print("T7e1306 - script is one-shot (no auto-trigger)")
print("=" * 72)
ok = False
manifest_src = ""
if os.path.isfile(MANIFEST_PATH):
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest_src = f.read()
# 1. Manifest has no post_init_hook referencing the script
no_post_init = "post_init_hook" not in manifest_src
# 2. Script not listed in data files
no_data_ref = "migrate_php_content" not in manifest_src
# 3. No ir.cron record references the script
Cron = env["ir.cron"]
crons = Cron.sudo().search([])
cron_ref = crons.filtered(
    lambda c: "migrate_php_content" in (c.code or ""))
no_cron = len(cron_ref) == 0
# 4. addon's main __init__.py doesn't import scripts/
main_init = os.path.join(ADDON_DIR, "__init__.py")
init_src = ""
if os.path.isfile(main_init):
    with open(main_init, "r", encoding="utf-8") as f:
        init_src = f.read()
no_init_import = "scripts" not in init_src
ok = (
    no_post_init
    and no_data_ref
    and no_cron
    and no_init_import)
print(f"  no post_init_hook in manifest: {no_post_init}")
print(f"  no data-file reference: {no_data_ref}")
print(f"  no ir.cron referencing script: {no_cron}")
print(f"  not imported from addon __init__: {no_init_import}")
print("T7e1306:", "PASS" if ok else "FAIL")
results["T7e1306"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e1300", "T7e1301", "T7e1302", "T7e1303",
         "T7e1304", "T7e1305", "T7e1306"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
