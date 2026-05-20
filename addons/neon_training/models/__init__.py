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
