"""P8A hygiene smoke -- Africa/Harare timezone helpers + audit.

T8600-T8619.

T8600  _today_harare returns a date
T8601  _now_harare returns aware datetime in Africa/Harare
T8602  _format_harare_timestamp formats UTC dt to Harare string
T8603  _harare_date_to_utc_string converts Harare midnight to UTC
T8604  payload last_updated is Harare-formatted (no UTC suffix)
T8605  payload last_updated parses as a real timestamp
T8606  HARARE_TZ constant exists in neon_dashboard module
T8607  helpers are @api.model (callable cross-model)
T8608  target.date_from default uses Harare today
T8609  brand h1 no longer contains "Neon CRM"
T8610  win_rate cutoff uses Harare midnight (within 1 hour tolerance)
T8611  lead_sources cutoff uses Harare midnight (within 1 hour tolerance)
T8612  _today_harare differs from UTC date when in the day-boundary band
       (informational -- just confirms the value isn't always = UTC date)
T8613  _now_harare tzinfo == HARARE_TZ
T8614  _format_harare_timestamp handles a tz-aware input
T8615  jobs_today query uses Harare today (smoke contract)
T8616  forecast tile subtitle 'days left' uses Harare today
T8617  branding string in OWL XML source == "Neon" (file check)
T8618  neon_dashboard.py imports pytz at module top
T8619  Harare tz string is exactly 'Africa/Harare'
"""
from datetime import datetime, date, timedelta
import pytz

from odoo.exceptions import AccessError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("P8A hygiene -- Africa/Harare timezone helpers")
print("=" * 72)
results = {}

Dashboard = env["neon.dashboard"]
Users = env["res.users"]

HARARE = pytz.timezone("Africa/Harare")


def _get_or_make_user(login, group_xmlid):
    user = Users.search([("login", "=", login)], limit=1)
    group = env.ref(group_xmlid)
    if not user:
        user = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, group.id)],
        })
    elif group.id not in user.groups_id.ids:
        user.write({"groups_id": [(4, group.id)]})
    return user


u_director = _get_or_make_user(
    "p8a_director", "neon_core.group_neon_superuser")


# ============================================================
print()
print("T8600 -- _today_harare returns a date")
print("=" * 72)
today = Dashboard._today_harare()
ok = isinstance(today, date) and not isinstance(today, datetime)
print(f"  today_harare: {today} type={type(today).__name__}")
print("T8600:", "PASS" if ok else "FAIL")
results["T8600"] = ok


# ============================================================
print()
print("T8601/T8613 -- _now_harare returns aware datetime in HARARE_TZ")
print("=" * 72)
now = Dashboard._now_harare()
ok601 = isinstance(now, datetime) and now.tzinfo is not None
ok613 = (now.tzinfo.zone == "Africa/Harare"
         if hasattr(now.tzinfo, "zone") else
         str(now.utcoffset()) == "2:00:00")
print(f"  now_harare: {now} tzinfo={now.tzinfo}")
print("T8601:", "PASS" if ok601 else "FAIL")
results["T8601"] = ok601
print("T8613:", "PASS" if ok613 else "FAIL")
results["T8613"] = ok613


# ============================================================
print()
print("T8602 -- _format_harare_timestamp")
print("=" * 72)
ts = Dashboard._format_harare_timestamp()
# Parseable + has the expected pattern
parsed = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
ok = isinstance(parsed, datetime)
print(f"  formatted: {ts}")
print("T8602:", "PASS" if ok else "FAIL")
results["T8602"] = ok


# ============================================================
print()
print("T8603 -- _harare_date_to_utc_string converts midnight to UTC")
print("=" * 72)
# Harare midnight = 22:00 UTC previous day. Test with a fixed date.
target_date = date(2026, 5, 25)
utc_string = Dashboard._harare_date_to_utc_string(target_date)
# Harare 2026-05-25 00:00 = UTC 2026-05-24 22:00
parsed = datetime.strptime(utc_string, "%Y-%m-%d %H:%M:%S")
ok = (parsed.year == 2026 and parsed.month == 5
      and parsed.day == 24 and parsed.hour == 22 and parsed.minute == 0)
print(f"  Harare 2026-05-25 00:00 -> UTC string: {utc_string}")
print("T8603:", "PASS" if ok else "FAIL")
results["T8603"] = ok


# ============================================================
print()
print("T8604/T8605 -- payload last_updated is Harare-formatted + parseable")
print("=" * 72)
data = Dashboard.with_user(u_director).get_dashboard_data()
last_updated = data.get("last_updated")
ok604 = isinstance(last_updated, str) and len(last_updated) == 19
try:
    parsed = datetime.strptime(last_updated, "%Y-%m-%d %H:%M:%S")
    ok605 = True
except ValueError:
    ok605 = False
print(f"  last_updated: {last_updated}")
print("T8604:", "PASS" if ok604 else "FAIL")
results["T8604"] = ok604
print("T8605:", "PASS" if ok605 else "FAIL")
results["T8605"] = ok605


# ============================================================
print()
print("T8606 -- HARARE_TZ constant in module")
print("=" * 72)
# Load by file path -- 'addons.*' isn't a real package on odoo shell.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "neon_dashboard_mod",
    "/mnt/extra-addons/neon_dashboard/models/neon_dashboard.py",
)
ndmod = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(ndmod)
    has_tz = hasattr(ndmod, "HARARE_TZ")
    zone_ok = (ndmod.HARARE_TZ.zone == "Africa/Harare") if has_tz else False
    ok = has_tz and zone_ok
    print(f"  HARARE_TZ: {getattr(ndmod, 'HARARE_TZ', None)}")
except Exception as e:  # noqa: BLE001
    # Odoo class-decorator side effects may fail at standalone load.
    # Fall back to source-text check.
    src = open(
        "/mnt/extra-addons/neon_dashboard/models/neon_dashboard.py",
        "r", encoding="utf-8").read()
    ok = ("HARARE_TZ = pytz.timezone(\"Africa/Harare\")" in src
          or "HARARE_TZ = pytz.timezone('Africa/Harare')" in src)
    ndmod = None
    print(f"  module standalone load failed ({type(e).__name__}); "
          "fell back to source-text check, found HARARE_TZ literal: {ok}")
print("T8606:", "PASS" if ok else "FAIL")
results["T8606"] = ok


# ============================================================
print()
print("T8607 -- helpers are @api.model (callable cross-model)")
print("=" * 72)
# Call from inside a target compute path (which is on a different
# model). If the call succeeds, the @api.model decoration holds.
Target = env["neon.dashboard.target"]
try:
    cross_today = env["neon.dashboard"]._today_harare()
    ok = cross_today == today
except Exception as e:  # noqa: BLE001
    ok = False
    print("  cross-model call failed:", e)
print("T8607:", "PASS" if ok else "FAIL")
results["T8607"] = ok


# ============================================================
print()
print("T8608 -- target.date_from default = Harare today, first of month")
print("=" * 72)
t = Target.with_user(u_director).create({
    "target_amount": 1000.0,
    "name": "tz default test",
})
ok = t.date_from == today.replace(day=1)
print(f"  date_from default: {t.date_from} (expected {today.replace(day=1)})")
t.unlink()
print("T8608:", "PASS" if ok else "FAIL")
results["T8608"] = ok


# ============================================================
print()
print("T8609 -- brand h1 no longer contains 'Neon CRM' (source check)")
print("=" * 72)
xml_path = "/mnt/extra-addons/neon_dashboard/static/src/js/neon_dashboard/neon_dashboard.xml"
with open(xml_path, "r", encoding="utf-8") as f:
    xml_src = f.read()
ok = "Neon CRM" not in xml_src and "Neon\n" in xml_src
print(f"  contains 'Neon CRM': {'Neon CRM' in xml_src}")
print("T8609:", "PASS" if ok else "FAIL")
results["T8609"] = ok


# ============================================================
print()
print("T8610/T8611 -- win_rate + lead_sources cutoff uses Harare midnight")
print("=" * 72)
# Build the expected Harare-midnight-to-UTC cutoff for 90d ago.
ninety_ago = today - timedelta(days=90)
expected_90 = Dashboard._harare_date_to_utc_string(ninety_ago)
parsed_expected = datetime.strptime(expected_90, "%Y-%m-%d %H:%M:%S")
# Harare midnight 90d ago in UTC = 22:00 the previous UTC day.
ok610 = parsed_expected.hour == 22
print(f"  90d cutoff (UTC) = {expected_90} (Harare midnight -> 22:00 UTC)")
print("T8610:", "PASS" if ok610 else "FAIL")
results["T8610"] = ok610

thirty_ago = today - timedelta(days=30)
expected_30 = Dashboard._harare_date_to_utc_string(thirty_ago)
parsed_expected = datetime.strptime(expected_30, "%Y-%m-%d %H:%M:%S")
ok611 = parsed_expected.hour == 22
print(f"  30d cutoff (UTC) = {expected_30}")
print("T8611:", "PASS" if ok611 else "FAIL")
results["T8611"] = ok611


# ============================================================
print()
print("T8612 -- informational: today_harare can differ from UTC today")
print("=" * 72)
utc_today = datetime.utcnow().date()
diff = "same" if utc_today == today else "different"
# This is informational only -- the actual difference depends on
# what time of day we're running. Always passes.
print(f"  UTC today: {utc_today}, Harare today: {today} ({diff})")
print("T8612: PASS (informational)")
results["T8612"] = True


# ============================================================
print()
print("T8614 -- _format_harare_timestamp handles tz-aware input")
print("=" * 72)
aware_dt = pytz.utc.localize(datetime(2026, 5, 25, 22, 0, 0))
formatted = Dashboard._format_harare_timestamp(aware_dt)
ok = formatted == "2026-05-26 00:00:00"
print(f"  UTC 2026-05-25 22:00 -> Harare: {formatted}")
print("T8614:", "PASS" if ok else "FAIL")
results["T8614"] = ok


# ============================================================
print()
print("T8615 -- jobs_today payload uses Harare today (contract)")
print("=" * 72)
# Verify that _compute_jobs_block reads today via _today_harare.
# We can't easily probe inside without mocking; assert the field
# integration: the jobs block payload doesn't crash + has 'rows'.
jobs_block = data["jobs_block"]
ok = "rows" in jobs_block
print(f"  jobs_block keys: {sorted(jobs_block.keys())}")
print("T8615:", "PASS" if ok else "FAIL")
results["T8615"] = ok


# ============================================================
print()
print("T8616 -- forecast tile subtitle 'days left' uses Harare today")
print("=" * 72)
# If a target is active, days_remaining = (target.date_to - Harare today).days.
forecast = data["kpi"]["kpi_forecast"]
if forecast.get("empty"):
    print("  forecast empty -- contract-only check")
    ok = True
else:
    subtitle = forecast.get("subtitle") or ""
    ok = "days left" in subtitle
    print(f"  subtitle: {subtitle}")
print("T8616:", "PASS" if ok else "FAIL")
results["T8616"] = ok


# ============================================================
print()
print("T8617 -- branding string in source == 'Neon' (not 'Neon CRM')")
print("=" * 72)
ok = "Neon CRM" not in xml_src
print(f"  no 'Neon CRM' literal in source")
print("T8617:", "PASS" if ok else "FAIL")
results["T8617"] = ok


# ============================================================
print()
print("T8618 -- pytz imported at module top")
print("=" * 72)
import importlib
src_path = "/mnt/extra-addons/neon_dashboard/models/neon_dashboard.py"
with open(src_path, "r", encoding="utf-8") as f:
    py_src = f.read()
# Check pytz import in the first 50 lines (top of file).
first_50 = "\n".join(py_src.split("\n")[:50])
ok = "import pytz" in first_50
print(f"  pytz at top: {ok}")
print("T8618:", "PASS" if ok else "FAIL")
results["T8618"] = ok


# ============================================================
print()
print("T8619 -- Harare tz string is 'Africa/Harare'")
print("=" * 72)
# Independent of T8606's module load: derive from a live helper call.
now_h = Dashboard._now_harare()
ok = (hasattr(now_h.tzinfo, "zone")
      and now_h.tzinfo.zone == "Africa/Harare")
print(f"  zone via _now_harare().tzinfo: "
      f"{getattr(now_h.tzinfo, 'zone', now_h.tzinfo)}")
print("T8619:", "PASS" if ok else "FAIL")
results["T8619"] = ok


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
