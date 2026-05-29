# -*- coding: utf-8 -*-
"""Phase 12.2 — AI Copilot WRITE tools.

Each module registers one tool via @ai_tool(category="write",
requires_confirmation=True) AND its matching executor via
register_executor(action_type, fn).

The propose function returns a structured proposal dict (no
mutation). The executor runs the actual write inside a savepoint
when the user confirms via /neon/ai_chat/confirm.

⚠️ DECISION (M12.2, D28): propose and execute are two separate
functions in the same module. The decorator binds propose to the
LLM-callable tool registry; register_executor wires execute to the
confirmation endpoint. Splitting them keeps the LLM-callable
surface clearly "read-only-effective" while the execute path stays
private to the controller.
"""
from . import log_lead
from . import move_stage
from . import update_deal_value
from . import post_chatter_note
