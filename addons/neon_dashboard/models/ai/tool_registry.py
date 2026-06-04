# -*- coding: utf-8 -*-
"""Re-export shim -- moved to neon_ai_core (B11 / PRE-WA-0).

The tool registry now lives in neon_ai_core.models.ai.tool_registry.
Aliased to the core module so the singleton dicts (_AI_TOOLS,
_AI_WRITE_EXECUTORS) are the SAME objects the orchestrator reads and
that tools/* + write_tools/* register into via `from ..tool_registry
import ai_tool`. No redefinition.
"""
import sys

from odoo.addons.neon_ai_core.models.ai import tool_registry as _src

sys.modules[__name__] = _src
