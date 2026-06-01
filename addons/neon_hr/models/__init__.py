# -*- coding: utf-8 -*-
from . import neon_hr_document        # document.type + document
from . import neon_hr_category        # category (M2M -> document.type)
from . import hr_employee             # extend: category, compliance
from . import hr_contract             # extend: renewal SM, notice, AC cron
from . import action_centre_ext       # selection_add: contract_expiry trigger
# ----- R1b-1: leave + crew availability -----
from . import neon_hr_leave_rules      # extend hr.leave.type + neon.hr.category
from . import hr_leave                 # extend hr.employee (approver + availability)
from . import neon_hr_availability     # SQL view: unavailability windows
# ----- R1b-2: payroll + wages + commission + loans -----
from . import neon_hr_statutory        # statutory deduction rules (config)
from . import neon_hr_event_wage       # event wage + freelance grade
from . import neon_hr_loan             # loan + repayment schedule
from . import neon_hr_payslip          # payslip + line (engine)
from . import neon_hr_commission       # sales commission (proposed)
# ----- R2: accidents/NSSA + disciplinary + TOIL + handbook -----
from . import neon_hr_accident         # workplace accident + NSSA 14-day AC
from . import neon_hr_case             # disciplinary/incident/performance/recognition
from . import neon_hr_overtime         # overtime resolution + TOIL accrual
from . import neon_hr_handbook         # handbook versions + acks + compliance flag
# ----- R3a: fleet/driver licences + competency gating -----
from . import neon_hr_licence          # driver licence + expiry AC alert
from . import neon_hr_competency       # competency catalog + employee + role map
from . import commercial_job_crew_ext  # extend commercial.job.crew: gate
