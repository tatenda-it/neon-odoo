# -*- coding: utf-8 -*-
"""Re-export shim -- moved to neon_ai_core (B11 / PRE-WA-0).

The two-phase write audit Model (neon.finance.ai.chat.write.log) now
lives in neon_ai_core.models.ai.pending_action (model keeps its _name;
core owns the class). Aliased to the core module. APPEND-ONLY
(perm_unlink=0) preserved across core (superuser row) + neon_dashboard
(tier rows) ACLs.
"""
import sys

from odoo.addons.neon_ai_core.models.ai import pending_action as _src

sys.modules[__name__] = _src
