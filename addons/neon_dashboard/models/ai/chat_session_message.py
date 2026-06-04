# -*- coding: utf-8 -*-
"""Re-export shim -- moved to neon_ai_core (B11 / PRE-WA-0).

The chat session + message Odoo Models now live in
neon_ai_core.models.ai.chat_session_message (models keep their _name;
core owns the class definitions). Aliased to the core module so any
code/test importing the old path gets the identical module object.
The model classes are defined ONCE (in core) -- no re-registration.
"""
import sys

from odoo.addons.neon_ai_core.models.ai import chat_session_message as _src

sys.modules[__name__] = _src
