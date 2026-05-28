# -*- coding: utf-8 -*-
"""Phase 12.1 — AI Sales Copilot READ tools.

Each module here registers exactly one tool via the @ai_tool
decorator. Import order is alphabetic to keep registration
deterministic; the registry overwrites on re-import so dev
reloads stay clean.
"""
from . import get_cert_expiry
from . import get_crew_availability
from . import get_dashboard_summary
from . import get_my_pipeline
from . import get_open_quotes
from . import get_partner_history
from . import get_pending_deposits
from . import get_quote_details
from . import check_stock_availability
# P12.M1.1 — additional READ tools for Bookkeeper + Lead Tech.
from . import get_overdue_invoices
from . import get_zig_rate
from . import get_budget_status
from . import get_jobs_this_week
from . import get_readiness_gates
