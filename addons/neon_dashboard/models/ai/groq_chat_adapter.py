# -*- coding: utf-8 -*-
"""Re-export shim -- moved to neon_ai_core (B11 / PRE-WA-0).

GroqChatAdapter now lives in neon_ai_core.models.ai.groq_chat_adapter.
Aliased to the core module for full attribute fidelity.
"""
import sys

from odoo.addons.neon_ai_core.models.ai import groq_chat_adapter as _src

sys.modules[__name__] = _src
