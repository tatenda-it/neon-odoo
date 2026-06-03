# -*- coding: utf-8 -*-
"""neon_lms 17.0.1.16.0 post-migrate -- P7g course-page branding config.

Idempotent. Brands + publishes the Neon Workshop channel to enrolled
MEMBERS (visibility=members, NOT public-internet; enroll model unchanged),
sets Robin Goneso as Responsible (was OdooBot), clears the stock cover
image (the hero is a CSS gradient -- no photo this round), publishes the
real lessons + section headers (were unpublished -> nothing learner-
visible), and deletes the 17 'MNN content' seq-0 orphan placeholders the
P7e import left behind.

Single code path: slide.channel._neon_apply_branding_config (also the
method p7g_smoke exercises). Safe to re-run on every -u.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    channel = env.ref("neon_lms.program_channel", raise_if_not_found=False)
    if not channel:
        channel = env["slide.channel"].sudo().search(
            [("neon_track_ids", "!=", False)])
    if not channel:
        _logger.warning(
            "neon_lms 17.0.1.16.0: no Neon-tracked channel found; "
            "P7g branding config skipped.")
        return
    channel._neon_apply_branding_config()
    _logger.info(
        "neon_lms 17.0.1.16.0: P7g branding config applied to channel "
        "%s (neon_branded + members-published + Robin + lessons published "
        "+ orphans removed).", channel.ids)
