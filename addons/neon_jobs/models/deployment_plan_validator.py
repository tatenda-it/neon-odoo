# -*- coding: utf-8 -*-
"""P-B3 -- DeploymentPlanValidator.

Pure-Python guard. Runs AFTER Claude returns, BEFORE persistence.
Implements the design-seed lock with teeth: any contradiction
between the LLM output and the gathered facts -> PlanValidationError.

Seven rules:
  R1 Hallucinated quantities         (required/available/deficit_qty)
  R2 Hallucinated competing events   (competing_event_names)
  R3 Hallucinated crew names         (crew_call_times[].crew_partner_name)
  R4 OMITTED deficit                 (the cardinal sin)
  R5 Wrong section keys              (sections[].key enum)
  R6 Hallucinated concrete datetimes (parseable datetimes only;
                                       relative phrasing passes)
  R7 data_quality_note mismatch      (verbatim carry-through)

⚠️ DECISION (B3, gate-1 (a) refined): R6 uses SPLIT validation --
narrative strings are scanned for tokens that parse() as concrete
datetimes; any concrete datetime that doesn't appear in the facts
dict is REJECTED (same teeth as R1). Relative phrasing ("morning
of the event", "during strike") doesn't parse so it's never tested
-- soft by default for those.
"""
import logging
import re
from datetime import date, datetime


_logger = logging.getLogger(__name__)


_VALID_SECTION_KEYS = (
    "load_in", "setup", "show_time", "strike", "return", "risks")

# Tokens that look like ISO-ish datetimes or dates -- the validator
# attempts to fromisoformat each match. Anything that parses is
# treated as a concrete datetime claim.
# Matches:
#   2026-06-15
#   2026-06-15 14:30
#   2026-06-15T14:30:00
#   14:30 (time only) -- but time-only is too noisy; we skip it
_ISO_DATETIME_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)?\b")


class PlanValidationError(Exception):
    """Raised when the LLM output contradicts the gathered facts.
    Caller (DeploymentPlanGenerator) catches + quarantines + may
    re-prompt once."""


class DeploymentPlanValidator:
    """One instance per generation attempt. Holds the facts dict
    + the B2 conflict snapshot."""

    def __init__(self, facts):
        self.facts = facts or {}

    def validate(self, plan):
        """Run all 7 rules; raise on first failure. Caller surfaces
        the error message to the user."""
        if not isinstance(plan, dict):
            raise PlanValidationError(
                "Plan is not a JSON object.")

        # R5 first -- if section keys are wrong, downstream
        # narrative validation is moot.
        self._r5_section_keys(plan)
        # R1 + R2 + R4 -- the deficit rules. Run as a group so a
        # single missing deficit yields a clear "you omitted X"
        # error rather than seven cascading numeric errors.
        self._r4_omitted_deficits(plan)
        self._r1_quantities(plan)
        self._r2_competing_events(plan)
        # R3 crew + R6 datetimes + R7 note
        self._r3_crew_names(plan)
        self._r6_concrete_datetimes(plan)
        self._r7_data_quality_note(plan)

    # ============================================================
    # R1 -- Hallucinated quantities
    # ============================================================
    def _r1_quantities(self, plan):
        b2_lines = (self.facts.get("b2_conflict", {})
                    .get("lines") or [])
        b2_by_name = {ln["product_name"]: ln for ln in b2_lines}
        for entry in plan.get("deficits", []) or []:
            pname = (entry or {}).get("product_name") or ""
            b2_ln = b2_by_name.get(pname)
            if not b2_ln:
                raise PlanValidationError(
                    "R1: deficit entry references product "
                    "{!r} which has no matching B2 conflict line. "
                    "Hallucinated product.".format(pname))
            for field in ("required_qty", "available_qty",
                           "deficit_qty"):
                claimed = entry.get(field)
                actual = b2_ln.get(field)
                if claimed != actual:
                    raise PlanValidationError(
                        "R1: deficit['{p}'].{f} = {c!r} but B2 "
                        "says {a!r}. Quantity hallucination.".format(
                            p=pname, f=field,
                            c=claimed, a=actual))

    # ============================================================
    # R2 -- Hallucinated competing events
    # ============================================================
    def _r2_competing_events(self, plan):
        b2_lines = (self.facts.get("b2_conflict", {})
                    .get("lines") or [])
        b2_by_name = {ln["product_name"]: ln for ln in b2_lines}
        for entry in plan.get("deficits", []) or []:
            pname = entry.get("product_name") or ""
            b2_ln = b2_by_name.get(pname)
            if not b2_ln:
                # R1 will have raised; defensive
                continue
            allowed = set(b2_ln.get("competing_event_names") or [])
            claimed = set(entry.get("competing_event_names") or [])
            bogus = claimed - allowed
            if bogus:
                raise PlanValidationError(
                    "R2: deficit['{p}'].competing_event_names "
                    "lists {b!r} which is not in B2's set {a!r}. "
                    "Hallucinated competing event(s).".format(
                        p=pname, b=sorted(bogus),
                        a=sorted(allowed)))

    # ============================================================
    # R3 -- Hallucinated crew names
    # ============================================================
    def _r3_crew_names(self, plan):
        # Build the allowed name set: lead_tech + crew_chief +
        # commercial.job.crew + the Python-computed call_times set
        # (which is a subset of those anyway -- belt + braces).
        allowed = set()
        if self.facts.get("lead_tech", {}).get("name"):
            allowed.add(self.facts["lead_tech"]["name"])
        if self.facts.get("crew_chief", {}).get("name"):
            allowed.add(self.facts["crew_chief"]["name"])
        for c in self.facts.get("crew", []) or []:
            if c.get("partner_name"):
                allowed.add(c["partner_name"])
        # Validate
        for entry in plan.get("crew_call_times", []) or []:
            name = (entry or {}).get("crew_partner_name") or ""
            if name and name not in allowed:
                raise PlanValidationError(
                    "R3: crew_call_times mentions {n!r} which is "
                    "not in the assigned crew set {a!r}. "
                    "Hallucinated crew member.".format(
                        n=name, a=sorted(allowed)))
        # Also assert Claude's array matches the Python-computed
        # set EXACTLY -- per gate-1 (c) recommendation.
        expected = self.facts.get("crew_call_times") or []
        if expected:
            expected_pairs = sorted(
                (e["crew_partner_name"], e["call_at"], e["role"])
                for e in expected)
            got_pairs = sorted(
                (e.get("crew_partner_name") or "",
                 e.get("call_at") or "",
                 e.get("role") or "")
                for e in (plan.get("crew_call_times") or []))
            if expected_pairs != got_pairs:
                raise PlanValidationError(
                    "R3: crew_call_times does not match the "
                    "Python-computed policy. Expected "
                    "{e!r} but got {g!r}. The call-time policy is "
                    "fact, not narrative.".format(
                        e=expected_pairs, g=got_pairs))

    # ============================================================
    # R4 -- OMITTED deficits (the cardinal sin)
    # ============================================================
    def _r4_omitted_deficits(self, plan):
        b2_lines = (self.facts.get("b2_conflict", {})
                    .get("lines") or [])
        must_appear = {
            ln["product_name"] for ln in b2_lines
            if ln.get("status") in ("deficit", "zero_margin")
        }
        present = {
            (entry or {}).get("product_name") or ""
            for entry in (plan.get("deficits", []) or [])
        }
        missing = must_appear - present
        if missing:
            raise PlanValidationError(
                "R4: plan omits {n} known B2 deficit/zero-margin "
                "line(s): {m!r}. Every flagged item MUST appear "
                "in deficits[]. This is the cardinal sin.".format(
                    n=len(missing), m=sorted(missing)))

    # ============================================================
    # R5 -- Wrong section keys
    # ============================================================
    def _r5_section_keys(self, plan):
        for sec in plan.get("sections", []) or []:
            key = (sec or {}).get("key")
            if key not in _VALID_SECTION_KEYS:
                raise PlanValidationError(
                    "R5: sections[].key = {k!r} not in allowed "
                    "enum {a!r}.".format(
                        k=key, a=list(_VALID_SECTION_KEYS)))

    # ============================================================
    # R6 -- Hallucinated concrete datetimes (parseable only)
    # ============================================================
    def _r6_concrete_datetimes(self, plan):
        """Walk every narrative + checklist string; find tokens that
        parse as concrete datetimes (fromisoformat or date.fromisoformat);
        reject any concrete datetime NOT in the facts.

        Relative phrasing ("morning of the event") doesn't parse
        so it's never tested -- soft per gate-1 (a) refined.
        """
        known = self._collect_known_datetime_tokens()
        for sec in plan.get("sections", []) or []:
            blobs = [(sec or {}).get("narrative") or ""]
            for item in (sec or {}).get("checklist", []) or []:
                blobs.append(item or "")
            for blob in blobs:
                for token in _ISO_DATETIME_RE.findall(blob or ""):
                    parsed = self._try_parse_concrete(token)
                    if parsed is None:
                        # Token matched the regex but didn't
                        # actually parse -- skip (regex over-match
                        # like a code id "2026-12-99").
                        continue
                    if not self._matches_known(parsed, known):
                        raise PlanValidationError(
                            "R6: narrative contains concrete "
                            "datetime {t!r} which does not match "
                            "any fact (event_date, occupation "
                            "window, load-in/out). Use relative "
                            "phrasing ('morning of the event') or "
                            "quote an exact fact.".format(t=token))

    def _collect_known_datetime_tokens(self):
        """Pull every datetime/date token from the facts dict
        (event_date, all 8 datetime fields, B2 window, call times).
        Returns a set of parsed datetime + date objects."""
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
        for ct in self.facts.get("crew_call_times", []) or []:
            parsed = self._try_parse_concrete(ct.get("call_at") or "")
            if parsed is not None:
                known.add(parsed)
        return known

    @staticmethod
    def _try_parse_concrete(token):
        """Try fromisoformat-ish parsing. Returns date OR datetime
        OR None. Tolerates trailing Z by replacing it with +00:00."""
        if not token:
            return None
        try:
            t = token.strip()
            if t.endswith("Z"):
                t = t[:-1] + "+00:00"
            # Try datetime first
            try:
                return datetime.fromisoformat(t)
            except ValueError:
                pass
            # Then date
            return date.fromisoformat(t)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _matches_known(parsed, known_set):
        """Check whether parsed appears in known. We treat dates as
        matching ANY datetime on that date (so 'morning of 2026-06-15'
        narration matches even if facts only carry '2026-06-15
        14:30')."""
        if parsed in known_set:
            return True
        # Date-vs-datetime: if parsed is a date, accept any known
        # datetime that falls on that date.
        if isinstance(parsed, date) and not isinstance(
                parsed, datetime):
            for k in known_set:
                if isinstance(k, datetime) and k.date() == parsed:
                    return True
                if isinstance(k, date) and k == parsed:
                    return True
        # If parsed is a datetime, accept a matching date in known.
        if isinstance(parsed, datetime):
            for k in known_set:
                if (isinstance(k, date) and not isinstance(
                        k, datetime) and k == parsed.date()):
                    return True
        return False

    # ============================================================
    # R7 -- data_quality_note verbatim carry-through
    # ============================================================
    def _r7_data_quality_note(self, plan):
        b2_note = (self.facts.get("b2_conflict", {})
                   .get("data_quality_note"))
        plan_note = plan.get("data_quality_note")
        if b2_note:
            if plan_note != b2_note:
                raise PlanValidationError(
                    "R7: data_quality_note must be carried "
                    "verbatim from B2 when present. Expected "
                    "exact string, got: {p!r}".format(
                        p=(plan_note or "")[:80] + "..."))
        else:
            if plan_note not in (None, ""):
                raise PlanValidationError(
                    "R7: data_quality_note must be null/empty "
                    "when B2 surfaced none. Got: {p!r}".format(
                        p=(plan_note or "")[:80]))
