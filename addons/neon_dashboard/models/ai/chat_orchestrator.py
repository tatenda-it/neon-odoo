# -*- coding: utf-8 -*-
"""Re-export shim -- moved to neon_ai_core (B11 / PRE-WA-0).

ChatOrchestrator now lives in neon_ai_core.models.ai.chat_orchestrator.
We alias THIS module to the core module in sys.modules so the path
`neon_dashboard.models.ai.chat_orchestrator` resolves to the one
canonical module object -- every attribute, INCLUDING module-level
globals the .claude smokes mutate in place (_RATE_LIMIT_BY_USER,
_WRITE_RATE_LIMIT_BY_USER), is the same object the orchestrator reads.
No redefinition, no copy. Keeps the controller import + smokes green.
"""
import sys

from odoo.addons.neon_ai_core.models.ai import chat_orchestrator as _src

sys.modules[__name__] = _src
