# -*- coding: utf-8 -*-
# Load the plain-Python ai/ subpackage FIRST (it defines the chat +
# write audit Odoo Models and the registry/adapters/orchestrator), then
# the provider catalog Model which the dashboard extends via _inherit.
from . import ai
from . import ai_provider
