# -*- coding: utf-8 -*-
"""
Migration to 17.0.2.5.0 — P3.M7 Closeout Workflow.

Converts existing client_feedback Text data on commercial.event.job
into structured commercial.event.feedback records (one per event_job
that has non-empty client_feedback text). Channel='written' and
captured_by defaults to the first Manager user (or admin fallback).
Idempotent: skipped if a 'P3M7 migrated' feedback already exists
for the event_job.

The client_feedback Text field stays on the model for now (read-only
in the view, deprecated) so a rollback of 17.0.2.5.0 doesn't lose
data. Field deletion happens in 17.0.3.x once we're confident no
external integrations are reading it.
"""
import logging

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)

_MIGRATION_TAG = "P3M7 migrated from client_feedback Text"


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    # Pick a manager fallback for captured_by. Prefer the first
    # active user in neon_jobs_manager; fall back to admin (uid=1)
    # if no manager exists (fresh install with no users yet).
    mgr_group = env.ref(
        "neon_jobs.group_neon_jobs_manager", raise_if_not_found=False,
    )
    captured_user = env["res.users"].browse(SUPERUSER_ID)
    if mgr_group:
        first_mgr = env["res.users"].search(
            [("groups_id", "in", mgr_group.id), ("active", "=", True)],
            limit=1, order="id asc",
        )
        if first_mgr:
            captured_user = first_mgr

    EventJob = env["commercial.event.job"].sudo()
    Feedback = env["commercial.event.feedback"].sudo()

    candidates = EventJob.search([
        ("client_feedback", "!=", False),
        ("client_feedback", "!=", ""),
    ])
    migrated = 0
    skipped = 0
    for ej in candidates:
        text = (ej.client_feedback or "").strip()
        if not text:
            continue
        existing = Feedback.search([
            ("event_job_id", "=", ej.id),
            ("feedback_text", "like", _MIGRATION_TAG),
        ], limit=1)
        if existing:
            skipped += 1
            continue
        Feedback.create({
            "event_job_id": ej.id,
            "channel": "written",
            "captured_by": captured_user.id,
            "captured_at": fields.Datetime.now(),
            "feedback_text": "%s\n\n---\n%s" % (text, _MIGRATION_TAG),
            "sentiment": "neutral",
        })
        migrated += 1
    _logger.info(
        "neon_jobs 17.0.2.5.0: migrated %d client_feedback Text entries "
        "to commercial.event.feedback records (skipped %d already-migrated).",
        migrated, skipped,
    )
