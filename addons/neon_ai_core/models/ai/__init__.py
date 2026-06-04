# -*- coding: utf-8 -*-
"""Shared AI engine -- plain-Python adapters/registry/orchestrator plus
the chat + write-audit Odoo Models.

Load order matters:
  * chat_session_message + pending_action define Odoo Models.
  * tool_registry must load before any consumer registers @ai_tool
    decorators (consumers import it from here).
  * chat_orchestrator imports groq_chat_adapter + tool_registry.

NB: the concrete READ/WRITE business tools do NOT live here -- they stay
in neon_dashboard (and future consumers) and register into this
module's tool_registry singleton at their own import time.
"""
from . import chat_session_message
from . import tool_registry
from . import pending_action
from . import groq_chat_adapter
from . import chat_orchestrator
