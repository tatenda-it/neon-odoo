# -*- coding: utf-8 -*-
"""Neon Onboarding -- Phase 7b. Candidate state machine +
admin override + audit trail."""
import logging

from . import models
from . import wizards

_logger = logging.getLogger(__name__)


def _post_init_hook(env):
    """M1 install hook. Nothing to seed yet -- M2 will add
    requirement templates, M9 will add cert type references.
    Logs install for deploy correlation.
    """
    _logger.info(
        "neon_onboarding M1 installed -- candidate model + "
        "audit log + skip wizard ready. Requirement templates "
        "deferred to M2; required-cert integration to M4.")
