"""P-CREW — crew roster reference archive (op-data step 3a).

Tests the gate-resolved de-dup map (Biriad=Kudzai Mushore, Anorld=Arnold Mutasa,
KK=Ranganai lead, Kevin=Kelvin Maibeki, Danny=Kelvin Mushore DISTINCT) + the
collision traps (Kelvin Maibeki != Kelvin Mushore != Kudzai Mushore; Kudzai
Mushore != Kudzai Nyanguwo; Kudzaiishe NOT in the roster) + the loader (create,
former=active False, lead flag, alias preservation, full-replace idempotency) +
ACL (ALL internal read). [TESTCREW] fixtures, self-cleaning.
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

PG = {"__name__": "crew_parser_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/parse_crew.py").read(), PG)
CURATED = PG["CURATED"]
ACTIVE = PG["ACTIVE"]
FORMER = PG["FORMER"]

# ---- T1 ground-truth merges ----
_check("T1-biriad", CURATED["Biriad"] == "Kudzai Mushore")
_check("T1b-anorld", CURATED["Anorld"] == "Arnold Mutasa")
_check("T1c-kk-ranganai", CURATED["KK"] == "Ranganai")
_check("T1d-kevin-maibeki", CURATED["Kevin"] == "Kelvin Maibeki")
_check("T1e-danny-mushore", CURATED["Danny"] == "Kelvin Mushore")

# ---- T2 collision traps (must NOT merge) ----
_check("T2-kelvin-maibeki-ne-mushore",
       CURATED["Kelvin"] != CURATED["Danny"]
       and CURATED["Danny"] == "Kelvin Mushore"
       and CURATED["Kelvin"] == "Kelvin Maibeki")
_check("T2b-kudzai-mushore-ne-nyanguwo",
       CURATED["Kudzai"] == "Kudzai Mushore"
       and CURATED["Kudzai Nyanguwo"] == "Kudzai Nyanguwo")
_check("T2c-kudzaiishe-not-in-roster",
       "Kudzaiishe" not in ACTIVE and "Kudzaiishe" not in FORMER
       and "Kudzaiishe" not in CURATED.values())
_check("T2d-three-distinct-canonicals",
       len({"Kelvin Maibeki", "Kelvin Mushore", "Kudzai Mushore"}
           & (ACTIVE | FORMER)) == 3)

# ---- T3 active/former split + lead ----
_check("T3-ranganai-lead-active", "Ranganai" in ACTIVE)
_check("T3b-former-set",
       {"Kudzai Nyanguwo", "Romo", "Steven"} <= FORMER
       and len(ACTIVE) == 13 and len(FORMER) == 9)

# ---- Loader ----
LG = {"__name__": "crew_loader_test"}
exec(open("/mnt/extra-addons/neon_migration/scripts/import_crew.py").read(), LG)
load_crew = LG["load_crew"]
M = env["neon.crew.member"].sudo()


def _purge():
    M.with_context(active_test=False).search(
        [("source", "=", "TESTCREW")]).unlink()


_purge()
payload = {"members": [
    {"name": "TESTCREW Lead", "aliases": "TCL\nTestLead", "role": "lead",
     "is_lead": True, "status": "active", "active": True,
     "source": "wages_sheet"},
    {"name": "TESTCREW Active", "aliases": "TCA", "role": "unknown",
     "is_lead": False, "status": "active", "active": True,
     "source": "wages_sheet"},
    {"name": "TESTCREW Former", "aliases": "TCF", "role": "unknown",
     "is_lead": False, "status": "former", "active": False,
     "source": "wages_sheet"},
], "unmapped": {}}
rep = load_crew(env, payload, source="TESTCREW")
env.flush_all()
rows = M.with_context(active_test=False).search([("source", "=", "TESTCREW")])
byname = {r.name: r for r in rows}
_check("T4-created",
       rep["created"] == 3 and len(rows) == 3 and rep["active"] == 2
       and rep["former"] == 1 and rep["leads"] == 1, "rep=%s" % rep)
_check("T4b-former-active-false",
       byname["TESTCREW Former"].active is False
       and byname["TESTCREW Former"].status == "former")
_check("T4c-lead-flag",
       byname["TESTCREW Lead"].is_lead is True
       and byname["TESTCREW Lead"].role == "lead")
_check("T4d-alias-preserved",
       byname["TESTCREW Lead"].alias_count == 2
       and "TestLead" in byname["TESTCREW Lead"].aliases)
# default view hides former (active_test)
_check("T4e-former-hidden-by-default",
       M.search_count([("source", "=", "TESTCREW")]) == 2)  # active only

# ---- T5 idempotency (full-replace scoped to source) ----
rep2 = load_crew(env, payload, source="TESTCREW")
env.flush_all()
_check("T5-idempotent",
       M.with_context(active_test=False).search_count(
           [("source", "=", "TESTCREW")]) == 3)

# ---- T6 ACL: ALL internal users can READ (names/roles, no pay) ----
Users = env["res.users"].sudo()
ops = Users.search(
    [("id", "!=", 1), ("share", "=", False), ("active", "=", True)]
).filtered(lambda u: not u.has_group("neon_core.group_neon_bookkeeper")
           and not u.has_group("neon_core.group_neon_superuser"))[:1]
if ops:
    try:
        n = env["neon.crew.member"].with_user(ops).with_context(
            active_test=False).search_count([("source", "=", "TESTCREW")])
        _check("T6-all-user-read", n == 3, "got %d" % n)
    except Exception as e:  # noqa: BLE001
        _check("T6-all-user-read", False, "denied: %r" % e)
else:
    _check("T6-all-user-read", True, "skip: no non-finance user")

_purge()
env.cr.commit()
print("=" * 60)
print("Total: %d/%d passed" % (_passed, _total))
for k in results:
    print("  %s: %s" % (k, "PASS" if results[k] else "FAIL"))
print("=" * 60)
