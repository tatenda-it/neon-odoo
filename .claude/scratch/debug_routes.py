"""Debug: inspect controller route registration."""
import inspect
from odoo.addons.neon_kb.controllers.portal import (
    NeonKBPortal)

fn = NeonKBPortal.portal_kb_list
print("portal_kb_list function:", fn)
print("attrs:", [a for a in dir(fn) if not a.startswith("_")])
print("routing:", getattr(fn, "routing", "MISSING"))
print("original_routing:",
      getattr(fn, "original_routing", "MISSING"))

# Try via class introspection
print()
print("--- vars(NeonKBPortal) keys ---")
print([k for k in vars(NeonKBPortal)
       if not k.startswith("_")])

# Check if Odoo recognizes the controller
from odoo.http import Controller
subs = [s for s in Controller.__subclasses__()
        if "neon_kb" in s.__module__]
print(f"\nneon_kb Controller subclasses: {[s.__name__ for s in subs]}")

# Walk all routes via http.root if possible
import odoo.http
print(f"\nhttp.root.controllers_per_module keys count: "
      f"{len(getattr(odoo.http.root, 'controllers_per_module', {}))}")

# Also confirm KB attempt
import sys
mod = sys.modules.get(
    "odoo.addons.neon_kb.controllers.portal")
print(f"\nmodule loaded: {mod is not None}")
