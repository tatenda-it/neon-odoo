# -*- coding: utf-8 -*-
"""P-B13 -- Claude doc-gen adapter package.

Plain-Python (NOT Odoo Model) so B3/B4/B5 import the class
directly without loading an unnecessary registry layer. Mirrors
the structure of neon_dashboard.models.ai.* (groq_chat_adapter
etc.) which use the same pattern.
"""
from . import claude_docgen_adapter
