# -*- coding: utf-8 -*-
from . import res_partner_bank
# P6.M1 — pricing engine foundation
from . import neon_equipment_category
from . import neon_finance_pricing_rule
from . import neon_finance_pricing_bracket
from . import neon_finance_day_multiplier
from . import neon_finance_conversion_rate
# P6.M2 — quote stack. Load order: payment_term first so the M2O on
# quote resolves; then line so the One2many target exists; quote last.
from . import neon_finance_payment_term
from . import neon_finance_quote_line
from . import neon_finance_quote
# P6.M4 — approval queue + Finance Approval settings inherit.
# Approval must load before quote uses it via the now-resolved
# forward-ref approval_id field, but quote.py imports happen at
# class-def time and the field's comodel_name is a string, so order
# inside this file is not load-order critical; Odoo's registry
# resolves comodel_name lazily.
from . import neon_finance_approval
from . import res_config_settings
# P6.M5 — event cost line + commercial.event.job extension. cost.line
# is loaded before the event_job extension so the One2many target on
# the extension resolves cleanly.
from . import neon_finance_cost_line
from . import commercial_event_job
# P6.M7 — invoice schedule + per-client template. Template + line load
# before schedule (template_line is a foreign-key target on schedule
# instantiation via _from_template). Schedule loads before quote
# extension (the o2m reverse from quote needs schedule registered).
from . import neon_finance_invoice_schedule_template
from . import neon_finance_invoice_schedule
# P6.M9 -- customer payment matching. account.move extends the stored
# compute that drives schedule state propagation; res.partner adds the
# credit-hold flag; account_payment_register adds cross-currency
# enforcement at the register-payment wizard entry point. Load order
# doesn't matter (all three _inherit pure stock Odoo).
from . import account_move
from . import account_payment_register
from . import res_partner
# P6.M10 -- Cash Flow Dashboard virtual model.
from . import neon_finance_dashboard
# P6.M11 -- workshop write-off integration via incident extension.
from . import neon_equipment_incident
