# Deferred external dependency imports

Pattern from Phase 7e M13: when an external Python library is
only needed at runtime by a specific admin feature, defer the
import to method scope instead of the module top. The module
loads cleanly without the dep; failure becomes a clean
`ImportError` at call time.

## Pattern

```python
def parse_docx(self, path):
    # Import inside the method, NOT at module top.
    try:
        from docx import Document
    except ImportError:
        _logger.error(
            "python-docx not installed. Run "
            "`pip install python-docx` and re-run.")
        return []
    doc = Document(path)
    ...
```

## Why

- **Module loads cleanly in environments without the dep**
  (CI runners, fresh Docker images, smoke tests that don't
  exercise the feature). The Odoo registry doesn't refuse to
  initialise just because an optional library is missing.
- **Failure mode is a clean `ImportError` at call time**, not
  a module-load crash that takes down the whole addon.
- **Deps install at admin discretion** when the feature is
  actually used (e.g., once per content migration, then the
  dep can be removed if desired).
- **No `external_dependencies` block** in `__manifest__.py`:
  Odoo's manifest-level external dep check refuses to install
  the module if listed deps are missing. That's the wrong
  trade-off for one-shot admin features.

## When to use

- External libraries only used by specific admin features
  (e.g., `python-docx` for content migration, `openpyxl` for
  one-shot Excel exports).
- Heavy deps that aren't worth installing for typical usage
  patterns.
- Deps with platform-specific availability issues (native
  extensions that don't ship in slim Docker images).
- Anything that runs at admin discretion rather than on every
  request.

## When NOT to use

- Deps used by every request, every cron, or any user-facing
  request handler. List those in `external_dependencies` and
  let Odoo enforce them at install time.
- Deps used by stored compute fields or @api.constrains
  validators — those fire during module load (recompute on
  upgrade) and a deferred import inside a compute method will
  still crash if it runs and the dep is missing.

## Smoke testability

A deferred-import method can still be tested for structure:
the smoke loads the module via `importlib.util.spec_from_
file_location` + `exec_module`, which executes the module body
but not the method bodies. The `from docx import Document`
inside the method never runs, so the smoke passes even though
python-docx is absent. The method's own behaviour (error log +
empty return on ImportError) is testable by stubbing or by
calling the method directly when the dep is genuinely missing.

## Phase 7e M13 example

`addons/neon_lms/scripts/migrate_php_content.py`:

```python
def parse_docx(docx_path):
    try:
        from docx import Document
    except ImportError:
        _logger.error(
            "python-docx not installed. Run: "
            "pip install python-docx -- then re-run.")
        return []
    doc = Document(docx_path)
    ...
```

The script ships in the addon without `python-docx` listed
anywhere. The module installs and upgrades cleanly. Tatenda
installs python-docx in the container at deploy time, uploads
the docx, runs the script — that's the full cycle.

## Cross-references

- [[reference_neon_content_migration_pattern]] -- the M13
  one-shot script structure that uses this pattern
