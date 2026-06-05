# -*- coding: utf-8 -*-
"""B11 / WA-0 -- chat-adapter factory.

Returns the right vendor adapter for a neon.dashboard.ai.provider row by
provider_key. Lets consumers (the WA-0 WhatsApp rails) select a provider
from the catalog without hard-coding a class. The dashboard Copilot does
NOT use this -- it constructs GroqChatAdapter directly and keeps Groq as
its is_default provider; WA picks its own provider via config.
"""
from .groq_chat_adapter import GroqChatAdapter
from .gemini_chat_adapter import GeminiChatAdapter


_CHAT_ADAPTERS = {
    "groq": GroqChatAdapter,
    "google": GeminiChatAdapter,
}


def get_chat_adapter(provider):
    """Return an instantiated chat adapter for ``provider`` (a
    neon.dashboard.ai.provider record), or None if its provider_key has
    no chat adapter (e.g. rule_based, which is insight-only)."""
    cls = _CHAT_ADAPTERS.get(provider.provider_key)
    return cls(provider) if cls else None
