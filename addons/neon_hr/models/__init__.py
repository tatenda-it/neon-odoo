# -*- coding: utf-8 -*-
from . import neon_hr_document        # document.type + document
from . import neon_hr_category        # category (M2M -> document.type)
from . import hr_employee             # extend: category, compliance
from . import hr_contract             # extend: renewal SM, notice, AC cron
from . import action_centre_ext       # selection_add: contract_expiry trigger
