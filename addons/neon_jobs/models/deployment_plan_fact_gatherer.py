# -*- coding: utf-8 -*-
"""P-B3 -- DeploymentPlanFactGatherer.

Pure-Python helper (NOT a Model). Walks a commercial.event.job and
returns the EVERY fact the deployment plan might possibly state.
This dict is what feeds Claude AND what the validator compares
the output against. The two must be the same source of truth.

⚠️ DECISION (B3, D2): the design-seed lock. Quantities / names /
dates ALL come from here. Claude only generates narrative /
structure / sequencing. Any deviation in the output is rejected
by the validator.
"""
import logging
from datetime import timedelta


_logger = logging.getLogger(__name__)


class DeploymentPlanFactGatherer:
    """One instance per generate() call. Read-only on the env --
    no writes here."""

    def __init__(self, env):
        self.env = env

    def gather(self, event_job):
        """Return the full facts dict. The shape is the contract
        between gather, the Claude prompt, the validator, and the
        on-screen renderer."""
        if not event_job or not event_job.exists():
            raise ValueError(
                "Cannot gather facts for a non-existent event job.")
        event_job.ensure_one()

        venue = event_job.venue_id
        room = event_job.venue_room_id
        partner = event_job.partner_id

        # Equipment lines (non-cancelled only -- cancelled lines
        # don't feed the plan).
        eq_lines = []
        for line in event_job.equipment_line_ids.filtered(
                lambda l: not l.cancelled_explicit
                            and l.state != "cancelled"):
            eq_lines.append({
                "product_template_id": line.product_template_id.id,
                "product_name": (
                    line.product_template_id.workshop_name
                    or line.product_template_id.name or ""),
                "category_id": (line.category_id.id
                                 if line.category_id else 0),
                "category_name": (line.category_id.name
                                   if line.category_id else ""),
                "quantity_planned": int(line.quantity_planned or 0),
                "quantity_remaining": int(
                    line.quantity_remaining or 0),
                "notes": line.notes or "",
            })

        # Crew (from parent commercial.job).
        crew = []
        try:
            parent_job = event_job.commercial_job_id
            for c in (parent_job.crew_assignment_ids
                       if parent_job else []):
                crew.append({
                    "crew_id": c.id,
                    "partner_id": (c.partner_id.id
                                    if c.partner_id else 0),
                    "partner_name": (c.partner_id.name
                                      if c.partner_id else ""),
                    "user_id": c.user_id.id if c.user_id else 0,
                    "role": c.role or "",
                    "state": c.state or "",
                    "is_crew_chief": bool(c.is_crew_chief),
                })
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Crew gather failed for event %s -- continuing "
                "without crew list (plan will degrade gracefully).",
                event_job.name)

        # B2 conflict lines touching this event. Snapshot the
        # LATEST run -- the plan freezes against that revision,
        # later runs don't retroactively reshape the plan.
        conflict, conflict_lines = self._gather_b2_conflict(event_job)

        # Call times (Python pre-compute per gate-1 (c)). The
        # validator will assert Claude's crew_call_times array
        # matches this set exactly.
        call_times = self._compute_call_times(event_job, crew)

        return {
            "event_job": {
                "id": event_job.id,
                "name": event_job.name or "",
                "state": event_job.state,
                "event_date": (event_job.event_date.isoformat()
                                if event_job.event_date else None),
                "event_end_date": (
                    event_job.event_end_date.isoformat()
                    if event_job.event_end_date else None),
                "load_in_start": self._dt_iso(
                    event_job.load_in_start),
                "load_in_end": self._dt_iso(
                    event_job.load_in_end),
                "load_out_start": self._dt_iso(
                    event_job.load_out_start),
                "load_out_end": self._dt_iso(
                    event_job.load_out_end),
                "prep_start_datetime": self._dt_iso(
                    event_job.prep_start_datetime),
                "dispatch_datetime": self._dt_iso(
                    event_job.dispatch_datetime),
                "strike_start_datetime": self._dt_iso(
                    event_job.strike_start_datetime),
                "return_eta_datetime": self._dt_iso(
                    event_job.return_eta_datetime),
                "occupation_start": self._dt_iso(
                    event_job.occupation_start),
                "occupation_end": self._dt_iso(
                    event_job.occupation_end),
                "effective_overlap_start": self._dt_iso(
                    event_job.effective_overlap_start),
                "effective_overlap_end": self._dt_iso(
                    event_job.effective_overlap_end),
                "expected_attendee_count": int(
                    event_job.expected_attendee_count or 0),
                "scope_complexity": event_job.scope_complexity or "",
                "client_notes": event_job.client_notes or "",
                "venue_access_notes":
                    event_job.venue_access_notes or "",
                "parking_arrangements":
                    event_job.parking_arrangements or "",
            },
            "venue": {
                "id": venue.id if venue else 0,
                "name": venue.name if venue else "",
                "full_address": (event_job.venue_full_address
                                  or ""),
                "room_name": (room.name if room else ""),
            },
            "partner": {
                "id": partner.id if partner else 0,
                "name": partner.name if partner else "",
            },
            "lead_tech": {
                "user_id": (event_job.lead_tech_id.id
                             if event_job.lead_tech_id else 0),
                "name": (event_job.lead_tech_id.name
                          if event_job.lead_tech_id else ""),
            },
            "crew_chief": {
                "user_id": (event_job.crew_chief_id.id
                             if event_job.crew_chief_id else 0),
                "name": (event_job.crew_chief_id.name
                          if event_job.crew_chief_id else ""),
            },
            "crew": crew,
            "equipment_lines": eq_lines,
            "b2_conflict": {
                "conflict_id": conflict.id if conflict else 0,
                "overall_status": (conflict.overall_status
                                    if conflict else "clear"),
                "window_start": self._dt_iso(
                    conflict.window_start if conflict else False),
                "window_end": self._dt_iso(
                    conflict.window_end if conflict else False),
                "data_quality_note": self._data_quality_note(
                    event_job),
                "lines": conflict_lines,
            },
            "crew_call_times": call_times,
        }

    # --- B2 conflict snapshot --------------------------------------

    def _gather_b2_conflict(self, event_job):
        """Find the LATEST conflict run touching this event +
        return only the lines flagged for THIS event."""
        Conflict = self.env["neon.equipment.conflict"].sudo()
        # Latest run where this event is either the trigger OR
        # appears in a line's competing_event_ids.
        latest = Conflict.search([
            "|",
            ("triggered_by_event_id", "=", event_job.id),
            ("line_ids.competing_event_ids", "in", event_job.id),
        ], order="triggered_at desc", limit=1)
        if not latest:
            return (Conflict.browse(), [])
        lines = []
        for ln in latest.line_ids:
            # Filter to lines that include THIS event in their
            # competing set (the broader cluster may include
            # neighbours we don't care about).
            if event_job.id not in ln.competing_event_ids.ids:
                # If the line's competing set is empty (a
                # below_threshold line with no demand), include it
                # anyway since the engine surfaced it for this
                # cluster.
                if ln.required_qty > 0:
                    continue
            lines.append({
                "line_id": ln.id,
                "product_template_id": (
                    ln.product_template_id.id),
                "product_name": (
                    ln.product_template_id.workshop_name
                    or ln.product_template_id.name or ""),
                "required_qty": int(ln.required_qty),
                "available_qty": int(ln.available_qty),
                "margin": int(ln.margin),
                "deficit_qty": int(ln.deficit_qty),
                "status": ln.status,
                "sub_hire_priority": int(
                    ln.sub_hire_priority or 0),
                "competing_event_names": sorted(
                    e.name for e in ln.competing_event_ids
                    if e.id != event_job.id),
            })
        return (latest, lines)

    def _data_quality_note(self, event_job):
        """Per B2 D2: when load-in/out is imprecise (NOT both set),
        surface the standard note. Verbatim string carried through
        to the plan + UI banner."""
        if (event_job.load_in_start and event_job.load_out_end):
            return None
        return (
            "Equipment conflicts are detected at calendar-day "
            "granularity until the team starts filling in event-job "
            "load-in/out (or dispatch/return) datetimes. Setting "
            "precise windows gives precise conflict detection; "
            "until then the engine uses a conservative same-day-"
            "overnight window which favours over-counting (safer) "
            "over under-counting."
        )

    # --- Call times (D2 + gate-1 (c)) ------------------------------

    def _compute_call_times(self, event_job, crew):
        """Per gate-1 (c): Python pre-computes call times using
        the configurable singleton policy. Validator enforces
        exact-match against Claude's narrated values.

        Returns a list of dicts:
          [{partner_name, role, call_at (ISO), duty}, ...]

        ``duty`` is a short string the narrative can reference
        ("Lead the load-in convoy" / "Coordinate the show" / ...);
        Claude doesn't INVENT durations or call times -- it
        narrates around the Python-fixed times.
        """
        Config = self.env[
            "neon.deployment.plan.call.time.config"].sudo()
        cfg = Config.get_singleton()

        # Anchor selection. If neither prep_start nor dispatch is
        # set, we cannot compute -- return an empty list and let
        # the validator's "no crew_call_times when anchor is
        # blank" rule pass.
        prep = event_job.prep_start_datetime
        dispatch = event_job.dispatch_datetime
        if not prep and not dispatch:
            return []
        if cfg.anchor_policy == "max_prep_dispatch":
            anchor_chief_lead = (
                max(prep, dispatch) if (prep and dispatch)
                else (prep or dispatch))
        else:
            anchor_chief_lead = dispatch or prep
        anchor_rest = dispatch or prep

        rows = []
        crew_chief_name = (event_job.crew_chief_id.name
                            if event_job.crew_chief_id
                            else "")
        lead_tech_name = (event_job.lead_tech_id.name
                           if event_job.lead_tech_id
                           else "")
        # Lead tech entry
        if lead_tech_name:
            rows.append({
                "crew_partner_name": lead_tech_name,
                "role": "lead_tech",
                "call_at": self._dt_iso(
                    anchor_chief_lead - timedelta(
                        minutes=cfg.lead_tech_offset_minutes)),
                "duty": "Lead Tech -- on site to coordinate prep",
            })
        # Crew chief entry
        if crew_chief_name and crew_chief_name != lead_tech_name:
            rows.append({
                "crew_partner_name": crew_chief_name,
                "role": "crew_chief",
                "call_at": self._dt_iso(
                    anchor_chief_lead - timedelta(
                        minutes=cfg.crew_chief_offset_minutes)),
                "duty": "Crew Chief -- run the load-in",
            })
        # Rest of crew
        already_named = {lead_tech_name, crew_chief_name}
        for c in crew:
            if (not c.get("partner_name")
                    or c["partner_name"] in already_named):
                continue
            if c.get("state") not in ("assigned", "confirmed"):
                continue
            rows.append({
                "crew_partner_name": c["partner_name"],
                "role": c.get("role") or "crew",
                "call_at": self._dt_iso(
                    anchor_rest - timedelta(
                        minutes=cfg.rest_offset_minutes)),
                "duty": "Crew -- gear move + setup",
            })
            already_named.add(c["partner_name"])
        return rows

    # --- helpers ---------------------------------------------------

    @staticmethod
    def _dt_iso(value):
        if not value:
            return None
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
