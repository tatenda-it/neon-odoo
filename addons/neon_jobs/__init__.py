# -*- coding: utf-8 -*-
from . import models
from . import wizards


def _post_init_hook(env):
    """Hook reserved for one-shot install actions.

    Up to and including P2.M2 (17.0.1.1.0) this hook added an implied_ids
    edge from base.group_user to group_neon_jobs_user so every internal
    user automatically gained Operations User rights. P2.M7.6 removed
    that auto-implication: future Neon installs assign neon_jobs_*
    groups explicitly per role, since Crew and Crew Leader tiers must
    NOT inherit user-tier permissions through internal-user membership.

    Migration scripts in 17.0.1.7.1/ handle the existing-DB cleanup
    (strip the leak from crew/crew_leader, grant explicit user to
    plain internal users).
    """
    return
