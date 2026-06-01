# -*- coding: utf-8 -*-
"""P-B5 -- Post-event reconciliation validator.

Mirror of B3/B4 validator teeth. Runs AFTER Claude returns +
BEFORE persistence. Any contradiction between LLM output and
gathered facts -> ReconValidationError -> caller retries once,
then quarantines.

Seven rules:
  R1 planned-vs-actual quantities match Python facts EXACTLY
     (sub-hire qty_short totals, condition delta counts)
  R2 unit serial_number / product / sub-hire request names
     referenced in narrative are in the Python facts set
  R3 sub-hire request references are a SUBSET of facts'
     subhire_snapshot
  R4 OMITTED material fact -> reject (cardinal sin):
        any written_off unit MUST appear in narrative;
        any non-superseded sub-hire MUST be mentioned
  R5 event_window matches the Python-computed label verbatim
  R6 concrete-datetime narrative rule (parse-able only; relative
     phrasing PASSES soft per the R6 split)
  R7 data_quality_note carried verbatim from B2
"""
import logging
import re
from datetime import date, datetime


_logger = logging.getLogger(__name__)


_ISO_DATETIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?\b")


class ReconValidationError(Exception):
    """Raised when the LLM output contradicts the gathered facts.
    Caller catches + quarantines + may re-prompt once."""


class EventReconciliationValidator:
    """One instance per generation attempt."""

    def __init__(self, facts):
        self.facts = facts or {}

    def validate(self, draft):
        """Run all 7 rules; raise on first failure."""
        if not isinstance(draft, dict):
            raise ReconValidationError(
                "Draft is not a JSON object.")
        # R4 first -- if a written-off unit was omitted, no point
        # checking the other quantitative rules against a draft
        # that's missing material facts.
        self._r4_omitted_material_facts(draft)
        self._r1_quantities(draft)
        self._r2_referenced_names(draft)
        self._r3_subhire_subset(draft)
        self._r5_event_window(draft)
        self._r6_concrete_datetimes(draft)
        self._r7_data_quality_note(draft)

    # ============================================================
    # R1 -- planned-vs-actual quantities match facts
    # ============================================================
    def _r1_quantities(self, draft):
        # Sub-hire totals
        snap = (self.facts.get("subhire_snapshot") or [])
        snap_by_name = {s["name"]: s for s in snap}
        for sh in (draft.get("subhire_outcomes") or []):
            name = (sh or {}).get("request_name") or ""
            snap_entry = snap_by_name.get(name)
            if not snap_entry:
                continue  # R3 will catch
            for fname, snap_key in (
                    ("qty_short_total", "qty_short_total"),
                    ("line_count", "line_count")):
                claimed = sh.get(fname)
                actual = snap_entry.get(snap_key)
                if claimed is None:
                    continue
                if claimed != actual:
                    raise ReconValidationError(
                        "R1: subhire_outcomes['{n}'].{f} = {c!r} "
                        "but Python facts say {a!r}. Quantity "
                        "hallucination.".format(
                            n=name, f=fname,
                            c=claimed, a=actual))
        # Condition delta counts
        deltas = (self.facts.get("condition_deltas") or [])
        actual_written_off = sum(
            1 for d in deltas
            if d.get("new_status") == "written_off")
        actual_needs_repair = sum(
            1 for d in deltas
            if d.get("new_status") == "needs_repair")
        eq_block = (draft.get("equipment_outcomes") or {})
        for fname, actual in (
                ("written_off_count", actual_written_off),
                ("needs_repair_count", actual_needs_repair)):
            claimed = eq_block.get(fname)
            if claimed is None:
                continue
            if claimed != actual:
                raise ReconValidationError(
                    "R1: equipment_outcomes.{f} = {c!r} but Python "
                    "facts say {a!r}. Condition-delta hallucination."
                    .format(f=fname, c=claimed, a=actual))

    # ============================================================
    # R2 -- referenced names live in the facts
    # ============================================================
    def _r2_referenced_names(self, draft):
        # Sub-hire request names referenced in subhire_outcomes
        # must appear in the snapshot.
        snap_names = {s["name"]
                      for s in (self.facts.get(
                          "subhire_snapshot") or [])}
        for sh in (draft.get("subhire_outcomes") or []):
            name = (sh or {}).get("request_name") or ""
            if not name:
                continue
            if name not in snap_names:
                raise ReconValidationError(
                    "R2: subhire_outcomes references "
                    "request_name={n!r} which is not in the "
                    "Python snapshot. Allowed: {a!r}".format(
                        n=name, a=sorted(snap_names)))
        # Unit serial_numbers referenced in equipment_outcomes
        # must appear in the condition_deltas.
        delta_serials = {(d.get("serial_number") or "")
                         for d in (self.facts.get(
                             "condition_deltas") or [])}
        unit_refs = ((draft.get("equipment_outcomes") or {})
                      .get("flagged_units") or [])
        for u in unit_refs:
            sn = (u or {}).get("serial_number") or ""
            if not sn:
                continue
            if sn not in delta_serials:
                raise ReconValidationError(
                    "R2: equipment_outcomes.flagged_units lists "
                    "serial_number={s!r} which is not in the "
                    "Python condition_deltas. Allowed: {a!r}".format(
                        s=sn, a=sorted(delta_serials)))

    # ============================================================
    # R3 -- sub-hire references SUBSET of facts
    # ============================================================
    def _r3_subhire_subset(self, draft):
        # This is a tighter pair with R2: every subhire_outcomes
        # entry that has a request_name must map to facts. Already
        # enforced by R2; here we additionally enforce that the
        # supplier_name (if claimed) matches the snapshot supplier.
        snap_by_name = {s["name"]: s
                        for s in (self.facts.get(
                            "subhire_snapshot") or [])}
        for sh in (draft.get("subhire_outcomes") or []):
            name = (sh or {}).get("request_name") or ""
            if name not in snap_by_name:
                continue
            claimed_supplier = (sh.get("supplier_name") or "")
            actual_supplier = (snap_by_name[name].get(
                "supplier_name") or "")
            if claimed_supplier and (
                    claimed_supplier != actual_supplier):
                raise ReconValidationError(
                    "R3: subhire_outcomes['{n}'].supplier_name = "
                    "{c!r} but Python facts say {a!r}. Supplier "
                    "hallucination.".format(
                        n=name, c=claimed_supplier,
                        a=actual_supplier))

    # ============================================================
    # R4 -- omitted material fact (cardinal sin)
    # ============================================================
    def _r4_omitted_material_facts(self, draft):
        # Every WRITTEN-OFF unit MUST appear in the flagged_units.
        deltas = (self.facts.get("condition_deltas") or [])
        must_appear = {(d.get("serial_number") or "")
                       for d in deltas
                       if d.get("new_status") == "written_off"
                          and (d.get("serial_number") or "")}
        present = {(u or {}).get("serial_number") or ""
                   for u in ((draft.get("equipment_outcomes")
                              or {}).get("flagged_units") or [])}
        missing = must_appear - present
        if missing:
            raise ReconValidationError(
                "R4: draft omits {n} written-off unit(s) that "
                "MUST appear in equipment_outcomes.flagged_units: "
                "{m!r}. This is the cardinal sin -- the workshop "
                "won't see the alert.".format(
                    n=len(missing), m=sorted(missing)))
        # Every non-superseded sub-hire MUST appear in
        # subhire_outcomes (otherwise the reader thinks the event
        # had no sub-hire activity).
        snap_names = {(s.get("name") or "")
                      for s in (self.facts.get(
                          "subhire_snapshot") or [])
                      if (s.get("name") or "")}
        outcome_names = {(o or {}).get("request_name") or ""
                         for o in (draft.get(
                             "subhire_outcomes") or [])}
        missing_sh = snap_names - outcome_names
        if missing_sh:
            raise ReconValidationError(
                "R4: draft omits {n} active sub-hire request(s) "
                "that MUST appear in subhire_outcomes: {m!r}. "
                "Every non-superseded request must be referenced."
                .format(n=len(missing_sh), m=sorted(missing_sh)))

    # ============================================================
    # R5 -- event_window matches Python label verbatim
    # ============================================================
    def _r5_event_window(self, draft):
        expected = self.facts.get("event_window_label") or ""
        got = draft.get("event_window") or ""
        if got != expected:
            raise ReconValidationError(
                "R5: draft.event_window = {g!r} but Python label "
                "is {e!r}. The window string is fact, not "
                "narrative.".format(g=got, e=expected))

    # ============================================================
    # R6 -- concrete-datetime narrative rule (parse-able only)
    # ============================================================
    def _r6_concrete_datetimes(self, draft):
        known = self._collect_known_datetime_tokens()
        blobs = []
        for k in ("headline", "executive_summary",
                  "what_went_well", "what_didnt",
                  "equipment_narrative",
                  "subhire_narrative",
                  "cost_narrative", "lessons"):
            v = draft.get(k)
            if isinstance(v, str):
                blobs.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        blobs.append(item)
        # nested narratives
        for sh in (draft.get("subhire_outcomes") or []):
            if isinstance(sh, dict) and isinstance(
                    sh.get("narrative"), str):
                blobs.append(sh["narrative"])
        for blob in blobs:
            for token in _ISO_DATETIME_RE.findall(blob or ""):
                parsed = self._try_parse_concrete(token)
                if parsed is None:
                    continue
                if not self._matches_known(parsed, known):
                    raise ReconValidationError(
                        "R6: narrative contains concrete datetime "
                        "{t!r} which does not match any fact "
                        "(event_date, occupation window, "
                        "load-in/out). Use relative phrasing or "
                        "quote an exact fact.".format(t=token))

    def _collect_known_datetime_tokens(self):
        known = set()
        ev = self.facts.get("event_job", {}) or {}
        for k in ("event_date", "event_end_date", "load_in_start",
                  "load_in_end", "load_out_start", "load_out_end",
                  "prep_start_datetime", "dispatch_datetime",
                  "strike_start_datetime", "return_eta_datetime",
                  "occupation_start", "occupation_end",
                  "effective_overlap_start",
                  "effective_overlap_end"):
            parsed = self._try_parse_concrete(ev.get(k) or "")
            if parsed is not None:
                known.add(parsed)
        b2 = self.facts.get("b2_conflict", {}) or {}
        for k in ("window_start", "window_end"):
            parsed = self._try_parse_concrete(b2.get(k) or "")
            if parsed is not None:
                known.add(parsed)
        return known

    @staticmethod
    def _try_parse_concrete(token):
        if not token:
            return None
        try:
            t = token.strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(t)
            except ValueError:
                pass
            return date.fromisoformat(t)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _matches_known(parsed, known_set):
        if parsed in known_set:
            return True
        if isinstance(parsed, date) and not isinstance(
                parsed, datetime):
            for k in known_set:
                if isinstance(k, datetime) and k.date() == parsed:
                    return True
                if isinstance(k, date) and k == parsed:
                    return True
        if isinstance(parsed, datetime):
            for k in known_set:
                if (isinstance(k, date) and not isinstance(
                        k, datetime) and k == parsed.date()):
                    return True
        return False

    # ============================================================
    # R7 -- data_quality_note verbatim carry-through
    # ============================================================
    def _r7_data_quality_note(self, draft):
        b2_note = (self.facts.get("b2_conflict", {})
                   .get("data_quality_note"))
        draft_note = draft.get("data_quality_note")
        if b2_note:
            if draft_note != b2_note:
                raise ReconValidationError(
                    "R7: data_quality_note must be carried "
                    "verbatim from B2 when present. Expected "
                    "exact string, got: {d!r}".format(
                        d=(draft_note or "")[:80] + "..."))
        else:
            if draft_note not in (None, ""):
                raise ReconValidationError(
                    "R7: data_quality_note must be null/empty "
                    "when B2 surfaced none. Got: {d!r}".format(
                        d=(draft_note or "")[:80]))
