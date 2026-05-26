# -*- coding: utf-8 -*-
from . import neon_dashboard
from . import neon_dashboard_user_layout
from . import neon_dashboard_target
from . import neon_dashboard_alert_dismissal
from . import neon_dashboard_digest_log
from . import neon_dashboard_weekly_digest
# M11 -- AI Insights provider abstraction. The plain-Python
# adapters live in models/ai/; the two Odoo Models orchestrate.
# Load the ai/ subpackage FIRST so the orchestrator imports
# resolve when the provider model module references them.
from . import ai
from . import neon_dashboard_ai_provider
from . import neon_dashboard_insight
from . import res_users
