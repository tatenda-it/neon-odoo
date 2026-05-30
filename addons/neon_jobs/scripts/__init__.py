# -*- coding: utf-8 -*-
# P-B14 -- INTENTIONALLY EMPTY. The scripts/ directory holds one-shot
# admin utilities (load_inventory.py). Per the P7e.M13 content
# migration pattern, these scripts are NEVER imported by the addon
# (`addons/neon_jobs/__init__.py` does not `from . import scripts`)
# and are NEVER listed in the manifest's `data` block. They are
# called via `odoo shell` with an explicit `exec(open(path).read())`.
