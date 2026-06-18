"""P-FAMCAL — FamCal job-history reference archive (op-data step 2).

Parser tests (classify keyword job/reminder/admin; date/multiday parse) +
loader tests (conservative client-match exact/strong/none with raw-title kept;
client-name-wins override flips admin->job on a partner match + the 2 gate-named
titles; reminders never flip; full-replace idempotency) + ACL (ALL internal
users can READ — it carries no money). [TESTFC] fixtures, self-cleaning.
Run in `odoo shell -d neon_crm`.
"""
_passed = _total = 0
results = {}


def _check(n, ok, d=""):
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
    results[n] = ok
    print("%s:" % n, "PASS" if ok else "FAIL", d if not ok else "")


env = env(context=dict(env.context, tracking_disable=True))

PG = {"__name__": "fc_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_famcal.py").read(), PG)
classify = PG["classify"]
parse_dt = PG["_parse_dt"]

# ---- T1 classification ----
_check("T1-classify-reminder", classify("ZOHO Payment Reminder", "event") == (False, "reminder"))
_check("T1b-classify-job", classify("Glamour Events", "event") == (True, "job"))
_check("T1c-classify-admin-birthday", classify("Birthday", "event") == (False, "admin"))
_check("T1d-classify-task", classify("Shared To-Do", "task") == (False, "admin"))
_check("T1e-classify-expiry", classify("WI-FI Expiry Date", "event") == (False, "reminder"))

# ---- T2 date parse ----
_check("T2-date-parse", parse_dt("2024-04-15 05:00") == "2024-04-15 05:00:00"
       and parse_dt("") is None and parse_dt("garbage") is None)

# ---- Loader ----
LG = {"__name__": "fc_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_famcal.py").read(), LG)
load_famcal = LG["load_famcal"]
JH = env["neon.job.history"].sudo()
P = env["res.partner"].sudo()


def _purge():
    JH.with_context(active_test=False).search([("source", "=", "TESTFC")]).unlink()
    P.with_context(active_test=False).search(
        [("name", "=like", "TESTFC %")]).unlink()


_purge()
# A distinctive client partner for matching.
client = P.create({"name": "TESTFC Glamour Widgets"})

payload = {"events": [
    # exact title match -> job, exact
    {"date_start": "2025-01-01 05:00:00", "date_end": "2025-01-01 06:00:00",
     "all_day": False, "is_multiday": False, "title": "TESTFC Glamour Widgets",
     "location": "", "notes": "verbatim notes", "created_by": "x",
     "event_type": "event", "participants_raw": "a@b", "is_job": True,
     "category": "job", "source": "famcal_scrape"},
    # strong: partner name as a token-run inside the title
    {"date_start": "2025-01-02 05:00:00", "date_end": None, "all_day": False,
     "is_multiday": False, "title": "TESTFC Glamour Widgets Annual Gala",
     "location": "", "notes": "", "created_by": "x", "event_type": "event",
     "participants_raw": "", "is_job": True, "category": "job",
     "source": "famcal_scrape"},
    # unmatched job -> none, raw title kept
    {"date_start": "2025-01-03 05:00:00", "date_end": None, "all_day": False,
     "is_multiday": True, "title": "Rakesh", "location": "Leopard Rock",
     "notes": "", "created_by": "x", "event_type": "event",
     "participants_raw": "", "is_job": True, "category": "job",
     "source": "famcal_scrape"},
    # admin + client match -> client-name-wins -> flips to job
    {"date_start": "2025-01-04 05:00:00", "date_end": None, "all_day": True,
     "is_multiday": False, "title": "TESTFC Glamour Widgets - Birthday event",
     "location": "", "notes": "", "created_by": "x", "event_type": "event",
     "participants_raw": "", "is_job": False, "category": "admin",
     "source": "famcal_scrape"},
    # reminder + (would-be) client name -> NEVER flips, stays non-job, no partner
    {"date_start": "2025-01-05 05:00:00", "date_end": None, "all_day": False,
     "is_multiday": False, "title": "TESTFC Glamour Widgets Subscription Renewal",
     "location": "", "notes": "", "created_by": "x", "event_type": "event",
     "participants_raw": "", "is_job": False, "category": "reminder",
     "source": "famcal_scrape"},
    # gate-named forced title (no partner) -> forced to job
    {"date_start": "2025-01-06 05:00:00", "date_end": None, "all_day": False,
     "is_multiday": False, "title": "Glamour Events - Birthday event",
     "location": "", "notes": "", "created_by": "x", "event_type": "event",
     "participants_raw": "", "is_job": False, "category": "admin",
     "source": "famcal_scrape"},
    # plain admin, no match -> stays non-job
    {"date_start": "2025-01-07 05:00:00", "date_end": None, "all_day": False,
     "is_multiday": False, "title": "Birthday", "location": "", "notes": "",
     "created_by": "x", "event_type": "event", "participants_raw": "",
     "is_job": False, "category": "admin", "source": "famcal_scrape"},
]}
rep = load_famcal(env, payload, source="TESTFC")
env.flush_all()
rows = JH.with_context(active_test=False).search(
    [("source", "=", "TESTFC")], order="date_start")
by_title = {r.title: r for r in rows}

_check("T3-created", rep["created"] == 7 and len(rows) == 7, "rep=%s" % rep)
_check("T4-exact-match",
       by_title["TESTFC Glamour Widgets"].partner_id.id == client.id
       and by_title["TESTFC Glamour Widgets"].partner_match == "exact")
_check("T4b-strong-match",
       by_title["TESTFC Glamour Widgets Annual Gala"].partner_id.id == client.id
       and by_title["TESTFC Glamour Widgets Annual Gala"].partner_match == "strong")
_check("T4c-unmatched-kept",
       not by_title["Rakesh"].partner_id
       and by_title["Rakesh"].partner_match == "none"
       and by_title["Rakesh"].title == "Rakesh"
       and by_title["Rakesh"].is_multiday is True)
_check("T5-client-name-wins",  # admin + match -> job
       by_title["TESTFC Glamour Widgets - Birthday event"].is_job is True
       and by_title["TESTFC Glamour Widgets - Birthday event"].category == "job"
       and by_title["TESTFC Glamour Widgets - Birthday event"].partner_id.id == client.id)
_check("T5b-reminder-never-flips",  # reminder stays non-job, no partner
       by_title["TESTFC Glamour Widgets Subscription Renewal"].is_job is False
       and not by_title["TESTFC Glamour Widgets Subscription Renewal"].partner_id)
_check("T5c-forced-title",  # gate-named title forced to job even w/o partner
       by_title["Glamour Events - Birthday event"].is_job is True)
_check("T5d-plain-admin-stays",
       by_title["Birthday"].is_job is False
       and by_title["Birthday"].category == "admin")

# ---- T6 idempotency (full-replace scoped to source) ----
rep2 = load_famcal(env, payload, source="TESTFC")
env.flush_all()
_check("T6-idempotent",
       JH.with_context(active_test=False).search_count([("source", "=", "TESTFC")]) == 7,
       "count=%d" % JH.search_count([("source", "=", "TESTFC")]))

# ---- T7 ACL: ALL internal users can READ (carries no money) ----
Users = env["res.users"].sudo()
ops = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: not u.has_group("neon_core.group_neon_bookkeeper")
           and not u.has_group("neon_core.group_neon_superuser"))[:1]
if ops:
    try:
        n = env["neon.job.history"].with_user(ops).search_count(
            [("source", "=", "TESTFC")])
        _check("T7-all-user-read", n == 7, "non-finance read got %d" % n)
    except Exception as e:  # noqa: BLE001
        _check("T7-all-user-read", False, "denied: %r" % e)
else:
    _check("T7-all-user-read", True, "skip: no non-finance user")

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
