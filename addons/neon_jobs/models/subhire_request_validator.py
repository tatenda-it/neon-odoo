# -*- coding: utf-8 -*-
"""P-B4 -- Sub-hire draft validator.

Mirror of B3's validator teeth (gate-1 (a) confirmed). Runs AFTER
Claude returns + BEFORE persistence. Any contradiction between
the LLM output and the gathered facts raises
SubhireValidationError -- caller retries once, then quarantines.

Seven rules (parallel to B3's):
  R1 qty_short matches B2 deficit_qty EXACTLY
  R2 product_name is in B2's deficit set
  R3 competing_event_names is a SUBSET of B2's set
  R4 OMITTED deficit -> reject (cardinal sin -- mirror B3 R4)
  R5 event_window matches the Python-computed label verbatim
  R6 concrete-datetime narrative rule (parse-able only;
     relative phrasing PASSES soft)
  R7 data_quality_note carried verbatim from B2
"""
import logging
import re
from datetime import date, datetime


_logger = logging.getLogger(__name__)


# Same ISO-token regex as B3's validator. Matches:
#   2026-06-15 / 2026-06-15 14:30 / 2026-06-15T14:30:00 / +TZ
_ISO_DATETIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?\b")


class SubhireValidationError(Exception):
    """Raised when the LLM output contradicts the gathered facts.
    Caller catches + quarantines + may re-prompt once."""


class SubhireRequestValidator:
    """One instance per generation attempt. Holds the facts dict
    + the derived sub-hire lines + the event window label."""

    def __init__(self, facts):
        self.facts = facts or {}

    def validate(self, draft):
        """Run all 7 rules; raise on first failure."""
        if not isinstance(draft, dict):
            raise SubhireValidationError(
                "Draft is not a JSON object.")

        # R4 first -- if a deficit was omitted, no point checking
        # the others against an incomplete set.
        self._r4_omitted_lines(draft)
        self._r1_qty_short(draft)
        self._r2_product_names(draft)
        self._r3_competing_events(draft)
        self._r5_event_window(draft)
        self._r6_concrete_datetimes(draft)
        self._r7_data_quality_note(draft)

    # ============================================================
    # R1 -- qty_short matches deficit_qty exactly
    # ============================================================
    def _r1_qty_short(self, draft):
        b2_lines = self.facts.get("subhire_lines") or []
        b2_by_name = {ln["product_name"]: ln for ln in b2_lines}
        for entry in draft.get("line_briefs") or []:
            pname = (entry or {}).get("product_name") or ""
            b2_ln = b2_by_name.get(pname)
            if not b2_ln:
                continue  # R2 will catch
            claimed = entry.get("qty_short")
            actual = b2_ln.get("deficit_qty")
            if claimed != actual:
                raise SubhireValidationError(
                    "R1: line_briefs['{p}'].qty_short = {c!r} but "
                    "B2 says deficit_qty = {a!r}. Quantity "
                    "hallucination.".format(
                        p=pname, c=claimed, a=actual))

    # ============================================================
    # R2 -- product_name is in B2's deficit set
    # ============================================================
    def _r2_product_names(self, draft):
        allowed = {ln["product_name"]
                   for ln in (self.facts.get("subhire_lines")
                               or [])}
        for entry in draft.get("line_briefs") or []:
            pname = (entry or {}).get("product_name") or ""
            if pname not in allowed:
                raise SubhireValidationError(
                    "R2: line_briefs references product {p!r} "
                    "which has no matching B2 deficit line. "
                    "Allowed: {a!r}".format(
                        p=pname, a=sorted(allowed)))

    # ============================================================
    # R3 -- competing_event_names SUBSET of B2's set
    # ============================================================
    def _r3_competing_events(self, draft):
        b2_lines = self.facts.get("subhire_lines") or []
        b2_by_name = {ln["product_name"]: ln for ln in b2_lines}
        for entry in draft.get("line_briefs") or []:
            pname = entry.get("product_name") or ""
            b2_ln = b2_by_name.get(pname)
            if not b2_ln:
                continue
            allowed = set(b2_ln.get("competing_event_names") or [])
            claimed = set(entry.get("competing_event_names") or [])
            bogus = claimed - allowed
            if bogus:
                raise SubhireValidationError(
                    "R3: line_briefs['{p}'].competing_event_names "
                    "lists {b!r} which is not in B2's set {a!r}. "
                    "Hallucinated competing event(s).".format(
                        p=pname, b=sorted(bogus),
                        a=sorted(allowed)))

    # ============================================================
    # R4 -- omitted deficit (the cardinal sin)
    # ============================================================
    def _r4_omitted_lines(self, draft):
        must_appear = {
            ln["product_name"]
            for ln in (self.facts.get("subhire_lines") or [])
        }
        present = {
            (entry or {}).get("product_name") or ""
            for entry in (draft.get("line_briefs") or [])
        }
        missing = must_appear - present
        if missing:
            raise SubhireValidationError(
                "R4: draft omits {n} known B2 deficit/zero-margin "
                "line(s): {m!r}. Every flagged item MUST appear "
                "in line_briefs[]. This is the cardinal sin."
                .format(n=len(missing), m=sorted(missing)))

    # ============================================================
    # R5 -- event_window matches the Python label verbatim
    # ============================================================
    def _r5_event_window(self, draft):
        expected = self.facts.get("event_window_label") or ""
        for entry in draft.get("line_briefs") or []:
            got = (entry or {}).get("event_window") or ""
            if got != expected:
                raise SubhireValidationError(
                    "R5: line_briefs['{p}'].event_window = {g!r} "
                    "but Python-computed label is {e!r}. The "
                    "window string is fact, not narrative.".format(
                        p=entry.get("product_name", ""),
                        g=got, e=expected))

    # ============================================================
    # R6 -- concrete-datetime narrative rule (parse-able only)
    # ============================================================
    def _r6_concrete_datetimes(self, draft):
        """Walk every narrative string (enquiry_subject,
        enquiry_body, line_briefs[].brief); find tokens that parse
        as concrete datetimes; REJECT any not present in facts.

        Relative phrasing ("the morning of the event") doesn't
        parse so it's never tested -- PASS by default per
        gate-1 (a) precedent.
        """
        known = self._collect_known_datetime_tokens()
        blobs = []
        if draft.get("enquiry_subject"):
            blobs.append(draft["enquiry_subject"])
        if draft.get("enquiry_body"):
            blobs.append(draft["enquiry_body"])
        for entry in draft.get("line_briefs") or []:
            if (entry or {}).get("brief"):
                blobs.append(entry["brief"])
        for blob in blobs:
            for token in _ISO_DATETIME_RE.findall(blob or ""):
                parsed = self._try_parse_concrete(token)
                if parsed is None:
                    continue
                if not self._matches_known(parsed, known):
                    raise SubhireValidationError(
                        "R6: narrative contains concrete datetime "
                        "{t!r} which does not match any fact "
                        "(event_date, occupation window, load-in/"
                        "out). Use relative phrasing ('the "
                        "morning of the event') or quote an exact "
                        "fact.".format(t=token))

    def _collect_known_datetime_tokens(self):
        """Pull every datetime/date token from the facts (event_*
        dates + the 8 datetime fields + B2 window)."""
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
                raise SubhireValidationError(
                    "R7: data_quality_note must be carried "
                    "verbatim from B2 when present. Expected "
                    "exact string, got: {d!r}".format(
                        d=(draft_note or "")[:80] + "..."))
        else:
            if draft_note not in (None, ""):
                raise SubhireValidationError(
                    "R7: data_quality_note must be null/empty "
                    "when B2 surfaced none. Got: {d!r}".format(
                        d=(draft_note or "")[:80]))
