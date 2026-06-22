"""DASH-DUALROLE-1 model smoke -- dual-role dashboard lens resolution.

The pre-existing resolver (landed b9cf2af) assumed one tier per user:
it ranked HR ABOVE Bookkeeper and returned a SINGLE tier, so a dual-role
Bookkeeper+HR non-superuser (Kudzai, uid 10) landed on HR and the View-As
switcher only ever offered HR -- Bookkeeper was unreachable.

This smoke proves the generalised resolver (lens selection only -- no
group / ACL / menu change):
  * _entitled_lenses_for_user returns the UNION of a user's lenses
  * dual-role landing = 'bookkeeper' (ranks ABOVE hr), with hr reachable
  * _available_types_for_user ships BOTH lenses for the dual user
  * _resolve_dashboard_type honours ANY entitled lens (not just 'hr');
    a non-entitled request coerces to the default (no AccessError)
  * SINGLE-TIER users are byte-identical to before (the zero-new rail):
    bookkeeper-only -> [] + 'bookkeeper'; hr-only -> [{hr}] + 'hr';
    sales-only -> [] + 'sales'; lead -> 'lead_tech'; crew -> 'tech'
  * superuser still sees all six + lands on 'director'
  * preferred_dashboard_type still wins first

T-DR-01 ... T-DR-18.
"""

Users = env["res.users"]
Dashboard = env["neon.dashboard"]
results = {}


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = bool(ok)


print("=" * 72)
print("DASH-DUALROLE-1 -- dual-role dashboard lens resolution")
print("=" * 72)


# ============================================================
# Fixtures -- get-or-create with EXACT tier membership. (6,0,...)
# sets the listed tier groups; implied_ids re-cascade automatically.
# Dedicated dash_dr_* logins; never mutate existing/real users.
# ============================================================
def _get_or_make(login, group_xmlids):
    grp_ids = [env.ref("base.group_user").id]
    for xmlid in group_xmlids:
        g = env.ref(xmlid, raise_if_not_found=False)
        if g:
            grp_ids.append(g.id)
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"active": True, "groups_id": [(6, 0, grp_ids)]})
    else:
        u = Users.sudo().with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(6, 0, grp_ids)],
        })
    return u


u_dual = _get_or_make("dash_dr_dual", [
    "neon_core.group_neon_bookkeeper",
    "neon_hr.group_neon_hr_admin",
])
u_book = _get_or_make("dash_dr_book", ["neon_core.group_neon_bookkeeper"])
u_hr = _get_or_make("dash_dr_hr", ["neon_hr.group_neon_hr_admin"])
u_sales = _get_or_make("dash_dr_sales", ["neon_core.group_neon_sales_rep"])
u_lead = _get_or_make("dash_dr_lead", ["neon_core.group_neon_lead_tech"])
u_crew = _get_or_make("dash_dr_crew", ["neon_core.group_neon_crew"])
u_super = _get_or_make("dash_dr_super", ["neon_core.group_neon_superuser"])
env.cr.commit()


def _vals(opts):
    return [o["value"] for o in opts]


# ============================================================
# T-DR-01..08 -- the dual-role user (Kudzai's exact combo)
# ============================================================
ent_dual = Dashboard._entitled_lenses_for_user(u_dual)
_check("T-DR-01", ent_dual == ["bookkeeper", "hr"],
       f"entitled lenses (bookkeeper before hr): {ent_dual}")

avail_dual = Dashboard._available_types_for_user(u_dual)
_check("T-DR-02",
       _vals(avail_dual) == ["bookkeeper", "hr"]
       and len(avail_dual) == 2,
       f"View-As shows BOTH lenses (>=2 -> switcher visible): "
       f"{_vals(avail_dual)}")

_check("T-DR-03",
       Dashboard._default_dashboard_type_for_user(u_dual.id) == "bookkeeper",
       "dual-role LANDS on Bookkeeper (was: HR)")

D_dual = Dashboard.with_user(u_dual)
_check("T-DR-04", D_dual._resolve_dashboard_type("hr") == "hr",
       "dual-role may switch TO hr (entitled, not coerced)")
_check("T-DR-05",
       D_dual._resolve_dashboard_type("bookkeeper") == "bookkeeper",
       "dual-role may switch back TO bookkeeper (entitled)")
_check("T-DR-06",
       D_dual._resolve_dashboard_type("sales") == "bookkeeper",
       "dual-role requesting a NON-entitled lens -> coerced to default")
_check("T-DR-07",
       D_dual._resolve_dashboard_type(None) == "bookkeeper",
       "dual-role default resolve (None) -> bookkeeper")
_check("T-DR-08",
       D_dual._resolve_dashboard_type("lead_tech") == "bookkeeper",
       "dual-role requesting lead_tech (not held) -> coerced")


# ============================================================
# T-DR-09..15 -- SINGLE-TIER users unchanged (the zero-new rail)
# ============================================================
_check("T-DR-09",
       Dashboard._available_types_for_user(u_book) == []
       and Dashboard._default_dashboard_type_for_user(u_book.id)
       == "bookkeeper",
       "bookkeeper-only: avail==[] + default bookkeeper (unchanged)")

avail_hr = Dashboard._available_types_for_user(u_hr)
_check("T-DR-10",
       len(avail_hr) == 1 and avail_hr[0]["value"] == "hr"
       and Dashboard._default_dashboard_type_for_user(u_hr.id) == "hr",
       f"hr-only: avail==[{{hr}}] + default hr (legacy R3b preserved): "
       f"{_vals(avail_hr)}")

_check("T-DR-11",
       Dashboard._available_types_for_user(u_sales) == []
       and Dashboard._default_dashboard_type_for_user(u_sales.id)
       == "sales",
       "sales-only: avail==[] + default sales (unchanged -- T8216 rail)")

_check("T-DR-12",
       Dashboard._available_types_for_user(u_lead) == []
       and Dashboard._default_dashboard_type_for_user(u_lead.id)
       == "lead_tech",
       "lead-only: avail==[] + default lead_tech (unchanged)")

_check("T-DR-13",
       Dashboard._available_types_for_user(u_crew) == []
       and Dashboard._default_dashboard_type_for_user(u_crew.id)
       == "tech",
       "crew-only: avail==[] + default tech (unchanged)")

D_hr = Dashboard.with_user(u_hr)
_check("T-DR-14",
       D_hr._resolve_dashboard_type("hr") == "hr"
       and D_hr._resolve_dashboard_type("bookkeeper") == "hr",
       "hr-only: 'hr' honoured; non-entitled 'bookkeeper' -> coerced to hr")

D_sales = Dashboard.with_user(u_sales)
_check("T-DR-15",
       D_sales._resolve_dashboard_type("hr") != "hr"
       and D_sales._resolve_dashboard_type("hr") == "sales",
       "sales-only requesting 'hr' -> downgraded (legacy R3b rail)")


# ============================================================
# T-DR-16..17 -- superuser unchanged (all six + director)
# ============================================================
avail_super = Dashboard._available_types_for_user(u_super)
_check("T-DR-16",
       set(_vals(avail_super))
       == {"director", "sales", "bookkeeper", "lead_tech", "tech", "hr"}
       and Dashboard._default_dashboard_type_for_user(u_super.id)
       == "director",
       f"superuser: all six lenses + lands director: {_vals(avail_super)}")

D_super = Dashboard.with_user(u_super)
_check("T-DR-17",
       D_super._resolve_dashboard_type("bookkeeper") == "bookkeeper"
       and D_super._resolve_dashboard_type("hr") == "hr",
       "superuser may flip to any lens (unchanged)")


# ============================================================
# T-DR-18 -- preferred_dashboard_type still wins first
# ============================================================
u_dual.write({"preferred_dashboard_type": "sales"})
pref_wins = (
    Dashboard._default_dashboard_type_for_user(u_dual.id) == "sales")
u_dual.write({"preferred_dashboard_type": False})
pref_cleared = (
    Dashboard._default_dashboard_type_for_user(u_dual.id) == "bookkeeper")
_check("T-DR-18", pref_wins and pref_cleared,
       "preferred='sales' wins over tier-walk; cleared -> back to "
       "bookkeeper")


# ============================================================
# Cleanup -- mark fixtures inactive (never unlink; CLAUDE.md rule).
# get-or-create reactivates them next run.
# ============================================================
for u in (u_dual, u_book, u_hr, u_sales, u_lead, u_crew, u_super):
    u.sudo().write({"active": False})
env.cr.commit()


print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
