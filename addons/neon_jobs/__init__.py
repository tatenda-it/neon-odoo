# -*- coding: utf-8 -*-
from . import models


def _post_init_hook(env):
    """Make every internal user a Neon Operations User on install.

    Declarative XML cannot do this because base.group_user's
    ir_model_data row has noupdate=true. Migration script for
    17.0.1.1.0 covers existing installs of this module.
    """
    env.ref("base.group_user").write({
        "implied_ids": [(4, env.ref("neon_jobs.group_neon_jobs_user").id)],
    })
