# -*- coding: utf-8 -*-
"""FamCal calendar CSV -> JSON parser (LOCAL, reference-only).

Parses the FamCal scrape ("Document from Chief (1).csv") into JSON for the
loader. Dates are CLEAN ISO (no mangling). Classifies each event job vs
reminder/admin by a TITLE keyword test (TAG, not delete — all rows kept).
Client-matching is done by the LOADER (needs res.partner), not here.

Usage: python parse_famcal.py [in.csv] [out.json]
"""
import csv
import datetime
import json
import re
import sys

DEFAULT_CSV = r"C:\Users\Neon\Downloads\Document from Chief (1).csv"

# Reminder-type admin (subscription / expiry / renewal / system reminders).
_REMINDER_RE = re.compile(
    r"reminder|expir|renewal|\brenew\b|subscription|\bzoho\b|wi-?fi|"
    r"registration|\bpraz\b|due date", re.I)
# Other non-job admin (personal / calendar housekeeping).
_ADMIN_RE = re.compile(r"birthday|\bleave\b|off\s*day|public holiday", re.I)


def _parse_dt(s):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime(
                "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _yesno(s):
    return str(s or "").strip().lower() in ("yes", "true", "1", "y")


def classify(title, event_type):
    """Return (is_job, category)."""
    t = title or ""
    if (event_type or "").strip().lower() == "task":
        return False, "admin"
    if _REMINDER_RE.search(t):
        return False, "reminder"
    if _ADMIN_RE.search(t):
        return False, "admin"
    return True, "job"


def parse(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    events = []
    bad_dates = 0
    for r in rows:
        title = (r.get("title") or "").strip()
        etype = (r.get("type") or "").strip()
        is_job, category = classify(title, etype)
        ds = _parse_dt(r.get("date_start"))
        de = _parse_dt(r.get("date_end"))
        if r.get("date_start") and ds is None:
            bad_dates += 1
        events.append({
            "date_start": ds, "date_end": de,
            "all_day": _yesno(r.get("all_day")),
            "is_multiday": _yesno(r.get("is_multiday")),
            "title": title,
            "location": (r.get("location") or "").strip(),
            "notes": (r.get("notes") or "").strip(),
            "created_by": (r.get("created_by") or "").strip(),
            "event_type": etype,
            "participants_raw": (r.get("participants") or "").strip(),
            "is_job": is_job, "category": category,
            "source": "famcal_scrape",
        })
    counts = {
        "total": len(events),
        "job": sum(1 for e in events if e["is_job"]),
        "reminder": sum(1 for e in events if e["category"] == "reminder"),
        "admin": sum(1 for e in events if e["category"] == "admin"),
        "bad_dates": bad_dates,
        "multiday": sum(1 for e in events if e["is_multiday"]),
        "all_day": sum(1 for e in events if e["all_day"]),
    }
    return {"events": events, "counts": counts}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].endswith(
        ".json") else DEFAULT_CSV
    out = next((a for a in sys.argv[1:] if a.endswith(".json")), None)
    payload = parse(path)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=str)
    return payload


if __name__ == "__main__":
    p = main()
    c = p["counts"]
    print("FAMCAL PARSE: total=%d job=%d reminder=%d admin=%d bad_dates=%d "
          "multiday=%d all_day=%d"
          % (c["total"], c["job"], c["reminder"], c["admin"], c["bad_dates"],
             c["multiday"], c["all_day"]))
    print("\n-- ALL non-job (admin/reminder) titles for review --")
    for e in p["events"]:
        if not e["is_job"]:
            print("  [%-8s] %s" % (e["category"], e["title"]))
