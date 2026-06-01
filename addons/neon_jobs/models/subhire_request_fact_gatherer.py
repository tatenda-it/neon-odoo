# -*- coding: utf-8 -*-
"""P-B4 -- thin wrapper over B3's DeploymentPlanFactGatherer.

⚠️ DECISION (B4, D2): REUSE B3's fact-gather verbatim. The B2
deficit lines + the event window + the data_quality_note all
come from the same gather() call. This wrapper just filters the
B2 lines to status in (deficit, zero_margin) -- the surviving
set is the sub-hire demand. Conflict recomputation is forbidden.
"""
from .deployment_plan_fact_gatherer import (
    DeploymentPlanFactGatherer,
)


class SubhireRequestFactGatherer:
    """One instance per generate() call. Read-only on env."""

    def __init__(self, env):
        self.env = env
        self._plan_gatherer = DeploymentPlanFactGatherer(env)

    def gather(self, event_job):
        """Return the facts dict for a sub-hire request.

        Shape (mirrors B3's facts dict for downstream prompt
        compatibility, plus a `subhire_lines` derived list):

        {
          "event_job": {...},          # verbatim B3
          "venue": {...},
          "partner": {...},
          "b2_conflict": {...},
          "subhire_lines": [           # derived: B2 lines where
              {...},                   #   status in (deficit,
              ...                      #   zero_margin)
          ],
          "event_window_label": str,   # per validator R5 -- exact
                                       #   string the validator
                                       #   enforces verbatim
        }
        """
        base = self._plan_gatherer.gather(event_job)

        # Filter to lines that are actionable for sub-hire.
        all_lines = (base.get("b2_conflict", {})
                     .get("lines") or [])
        subhire_lines = [ln for ln in all_lines
                          if ln.get("status") in (
                              "deficit", "zero_margin")]

        # Event-window label per validator R5. Precise when load
        # in_start AND load_out_end are both set; otherwise the
        # event_date fallback.
        ev = base.get("event_job") or {}
        load_in = ev.get("load_in_start")
        load_out = ev.get("load_out_end")
        if load_in and load_out:
            window_label = "{} -> {}".format(load_in, load_out)
        else:
            start_d = ev.get("event_date") or ""
            end_d = (ev.get("event_end_date")
                      or start_d or "")
            window_label = "{} -> {}".format(start_d, end_d)

        base["subhire_lines"] = subhire_lines
        base["event_window_label"] = window_label
        return base
