# Content migration script pattern (Phase 7e M13)

Reusable structure for one-shot admin scripts that import
content from a legacy source (PHP, CSV, docx, JSON) into Odoo
records. Established in Phase 7e M13 for PHP-to-LMS content;
the same shape works for any future content import.

## Where the script lives

```
addons/<module>/scripts/migrate_<source>_<target>.py
addons/<module>/scripts/__init__.py   # empty package marker
```

The script lives under `scripts/` (not `models/` or `data/`)
to signal "admin-run, not auto-loaded". The `__init__.py` is
empty — the package marker exists so importlib and inspect can
resolve the script, but Odoo never imports it on module load.

## What MUST be true (one-shot wiring)

1. **NOT in `__manifest__.py` `data` list**. The script is not
   data; running it during install would block the deploy.
2. **NO `post_init_hook` reference**. The script is not part
   of the install/upgrade lifecycle.
3. **NO `ir.cron` record**. The script is admin-discretion, not
   scheduled.
4. **NOT imported by the addon's main `__init__.py`**. The
   `scripts/` package is freestanding.

These four invariants are testable via a static smoke (M13's
T7e1306).

## How it runs

```bash
docker compose exec -T odoo odoo shell -d <db> --no-http \
    < addons/<module>/scripts/migrate_<source>_<target>.py
```

The Odoo shell injects `env` into the script's exec namespace.
The script's bottom guard:

```python
if "env" in dir():
    try:
        main(env)
    except Exception as e:
        _logger.exception("Migration failed: %s", e)
        env.cr.rollback()
        print("FAILED: %s" % e)
```

ensures the script does nothing when imported by tests (where
`env` is not in module globals) and runs `main()` when sourced
through the shell.

## Required components

### 1. `preflight_check(input_path, env) -> (ok, message)`

Verifies that all preconditions are met BEFORE any record
creation. Checks:

- Input file exists at the expected path
- Target models are registered (defensive against
  install-order or version-mismatch deploys)
- Target seed data is in place (e.g., parent records that the
  import references)

Returns `(False, human_readable_message)` on any failure;
`main()` aborts without touching the DB.

### 2. Mojibake sanitizer

Known UTF-8 / cp1252 / Latin-1 round-trip artefacts mapped to
their real characters. Common cases:

```python
MOJIBAKE_MAP = [
    ("â€™", "'"),     # apostrophe
    ("â€œ", "“"),     # left double quote
    ("â€",  "”"),     # right double quote
    ("â€"", "—"),     # em-dash
    ("â€"", "–"),     # en-dash
    ("â€¦", "…"),     # ellipsis
    ("Â ",  " "),     # NBSP
    ("Ã©",  "é"),     # accented Latin
    ("﻿", ""),   # BOM
]
```

Apply once per sanitised text block. Characters that degraded
to `?` (irrecoverable loss) stay as `?` — the sanitizer
doesn't guess.

### 3. Section parser with explicit range

```python
MODULE_PATTERN = re.compile(r"^M(\d{2})\b")

def detect_module_code(line):
    m = MODULE_PATTERN.match(line.strip())
    if not m:
        return None
    n = int(m.group(1))
    if 1 <= n <= 17:           # explicit range check
        return "M%02d" % n
    return None
```

Explicit range prevents false positives (M00, M18+, M99,
inline references that happen to start with M\d\d).

### 4. Per-record idempotency check

A re-runnable script must not duplicate records. Two
strategies:

- **Exact-match for stable fields** (codes, names with known
  shape): `model.search([("name", "=", target_name)], limit=1)`
- **Prefix-match for content fields** (free-text question
  prompts, descriptions that may have minor whitespace or
  mojibake variation between runs): match on
  `text[:80].startswith(prior_text[:80])`

Helpers expose this as `<thing>_exists(env, key1, key2)`
functions — single-purpose, callable from smoke tests.

### 5. Per-section atomic transactions

```python
for record_data in records_in_section:
    try:
        with env.cr.savepoint():
            Model.sudo().create(record_data)
            counts["created"] += 1
    except Exception as e:
        _logger.error("Create failed: %s", e)
        counts["errors"] += 1
```

A failure on one record rolls back to the savepoint and the
next record proceeds. Final `env.cr.commit()` lands the whole
import; a fatal pre-commit error rolls back the entire
migration so the DB stays clean.

### 6. Per-section count report

```python
print("Importing slides...")
slide_counts = import_module_slides(env, paragraphs)
print(f"  {slide_counts}")
# Output: {'created': 17, 'skipped': 0, 'errors': 0}
```

Counts come back as `(created, skipped, errors)` dicts.
Skipped > 0 on a re-run is normal (idempotency working);
errors > 0 needs investigation post-run.

## Defensive imports

External deps (python-docx, openpyxl, pyyaml) imported inside
method scope, not module top. See
[[reference_odoo17_deferred_external_dep]].

## Smoke testability

The script's helpers (`preflight_check`, sanitizers, section
parsers, idempotency checks) are pure Python functions taking
`env` as a parameter. They're directly testable by importing
via `importlib.util.spec_from_file_location` and calling the
function — no docx required, no actual import needed. The
M13 smoke (`p7e_m13_smoke.py`) tests:

- Script file exists
- Loads cleanly via importlib (syntax check)
- preflight_check returns clean error on missing input
- Idempotency check detects present vs absent records
- Mojibake sanitizer round-trips known artefacts
- Section parser accepts valid codes + rejects invalid
- All four "one-shot wiring" invariants hold

## Manifest version bump

A content migration script ships in the addon as code. Bump
the manifest patch version so the new file lands cleanly on
upgrade (`-u <module>` picks it up; no migration directory
needed because the script doesn't change schema).

## Cross-references

- [[reference_odoo17_deferred_external_dep]] -- the python-
  docx defer pattern this script uses
