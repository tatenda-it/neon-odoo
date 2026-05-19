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
