# -*- coding: utf-8 -*-
# P7a.M1 — load order: category first (parent), then type
# (child Many2one points back at category, so the comodel must be
# in the registry when the type class is built; string comodel_name
# resolution makes Python-side ordering non-critical but the
# convention matches Phase 6).
from . import neon_training_certification_category
from . import neon_training_certification_type
# P7a.M2 -- certification record (per-person) + res.users extension
# for the Training tab. Load after category + type so the One2many
# reverse on res.users resolves cleanly.
from . import neon_training_certification
from . import res_users
# P7a.M6 -- cross-competency record + commercial.event.job inherit
# for the post-state='completed' TODO surface. Cross-competency
# model loads first; the event_job inherit can reference the
# model when scheduling the TODO summary.
from . import neon_training_cross_competency
from . import commercial_event_job
# P7a.M8 -- commercial.job.crew inherit for gate inference engine.
# Loads after cross_competency (gate softening reads cc records) and
# after event_job (no hard load-order need but keeps the file grouped
# with the other cross-cutting inherits).
from . import commercial_job_crew
# P7a.M9 -- assignment_gate_log record + tier-1 gate fire hooks on
# commercial.job.crew. The gate_log model loads BEFORE the crew
# inherit so the env['neon.training.assignment_gate_log'].create
# calls in the crew hooks resolve cleanly.
from . import neon_training_assignment_gate_log
# P7a.M10 -- neon.finance.quote inherit for tier-2 (warn) gating.
# Loads after the gate_log model (which the wizard writes to) and
# after the crew inherit (which provides the gate_status compute
# the M10 hook reads).
from . import neon_finance_quote
