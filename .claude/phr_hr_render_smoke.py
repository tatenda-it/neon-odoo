"""P-HR HR client render -- server-side payload shape + byte-equivalence.

The HR lens shipped server-side at R3b but the OWL client never drew it
(no kpi_hr_* tiles, no block_hr_* templates). This milestone adds the
client render + a small HR-scoped server reshape so the 5 _kpi_hr_*
dicts carry `value_display` + `empty` (the tile contract). This smoke
proves the SERVER half of the dual byte-equivalence guarantee and the
reshape; the browser smoke proves the DOM half.

T-HRR-01  get_dashboard_data('hr').kpi has all 5 kpi_hr_* keys, each
          carrying value (int, PRESERVED) + value_display (str) + empty.
T-HRR-02  headcount.empty is False AND has an inline act_window
          deeplink to hr.employee (the only clickable HR tile).
T-HRR-03  the four 30-day watch KPIs: empty == (value == 0).
T-HRR-04  the hr payload carries the 3 hr_*_block dicts (rows+row_count).
T-HRR-05  BYTE-EQUIVALENCE: NO non-HR default layout contains any
          kpi_hr_*/block_hr_* widget_key, and a director payload carries
          no HR kpi keys + no hr_*_block keys (HR data never leaks into
          another lens -> the HR markup's isWidgetVisible guards are
          always false there -> inert).
T-HRR-06  positive control: the hr default layout DOES carry all 5
          kpi_hr_* + 3 block_hr_* keys, visible.
T-HRR-07  int-contract preservation (the phr_r3b C1 invariant survives
          the reshape).
"""
from odoo.exceptions import AccessError  # noqa: F401  (parity import)


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-HR HR client render -- payload shape + byte-equivalence")
print("=" * 72)
results = {}

Users = env["res.users"]
Dashboard = env["neon.dashboard"]

HR_KPI_KEYS = {
    "kpi_hr_headcount", "kpi_hr_on_leave_today", "kpi_hr_contracts_30",
    "kpi_hr_licences_30", "kpi_hr_pending_leave",
}
HR_BLOCK_KEYS = {
    "block_hr_contracts", "block_hr_licences", "block_hr_pending_leaves",
}
WATCH_KPIS = HR_KPI_KEYS - {"kpi_hr_headcount"}


# ------------------------------------------------------------------ users
for login in ("phr_hrr_hr", "phr_hrr_super"):
    u = Users.sudo().with_context(active_test=False).search(
        [("login", "=", login)], limit=1)
    if u:
        u.write({"login": login + "_OLD_" + str(u.id), "active": False})

g_super = env.ref("neon_core.group_neon_superuser")
g_hr_admin = env.ref("neon_hr.group_neon_hr_admin")

u_hr = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-HRR HR Admin", "login": "phr_hrr_hr",
    "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_hr_admin.id)],
})
u_super = Users.sudo().with_context(no_reset_password=True).create({
    "name": "PHR-HRR Super", "login": "phr_hrr_super",
    "password": "test123",
    "groups_id": [(4, env.ref("base.group_user").id), (4, g_super.id)],
})
env.cr.commit()

D_hr = Dashboard.with_user(u_hr)
D_super = Dashboard.with_user(u_super)

hr_payload = D_hr.get_dashboard_data("hr")
hr_kpi = hr_payload.get("kpi", {})


# ------------------------------------------------------- T-HRR-01 reshape
shape_ok = (
    set(hr_kpi.keys()) == HR_KPI_KEYS
    and all(
        isinstance(hr_kpi[k].get("value"), int)
        and isinstance(hr_kpi[k].get("value_display"), str)
        and isinstance(hr_kpi[k].get("empty"), bool)
        for k in HR_KPI_KEYS
    )
)
_check("T-HRR-01", shape_ok,
       f"5 HR KPI dicts carry value+value_display+empty: "
       f"{sorted(hr_kpi.keys())}")


# --------------------------------------------------- T-HRR-02 headcount
hc = hr_kpi.get("kpi_hr_headcount", {})
dl = hc.get("deeplink_action")
_check("T-HRR-02",
       hc.get("empty") is False
       and isinstance(dl, dict)
       and dl.get("res_model") == "hr.employee",
       f"headcount empty=False + act_window->hr.employee: "
       f"empty={hc.get('empty')!r} dl_model="
       f"{(dl or {}).get('res_model')!r}")


# ---------------------------------------------- T-HRR-03 watch KPI empty
watch_ok = all(
    hr_kpi[k]["empty"] == (hr_kpi[k]["value"] == 0) for k in WATCH_KPIS
)
_check("T-HRR-03", watch_ok,
       "watch KPIs: empty == (value==0) for "
       + ", ".join(sorted(WATCH_KPIS)))


# ------------------------------------------------- T-HRR-04 block payloads
blocks_ok = all(
    isinstance(hr_payload.get(bk), dict)
    and isinstance(hr_payload[bk].get("rows"), list)
    and isinstance(hr_payload[bk].get("row_count"), int)
    for bk in ("hr_contracts_block", "hr_licences_block",
               "hr_pending_leaves_block")
)
_check("T-HRR-04", blocks_ok,
       "3 hr_*_block payloads present with rows+row_count")


# -------------------------------------------- T-HRR-05 BYTE-EQUIVALENCE
# (a) no non-HR default layout carries an HR widget_key
leak_layouts = []
for variant in ("director", "sales", "bookkeeper", "lead_tech", "tech"):
    ref_id = "neon_dashboard.default_layout_" + variant
    tmpl = env.ref(ref_id, raise_if_not_found=False)
    if not tmpl:
        continue
    # env.ref(default_layout_*) -> neon.dashboard.default.layout, whose
    # One2many is layout_line_ids (NOT layout_ids -- that field is on
    # the per-user neon.dashboard model). [adversarial-review fix]
    keys = set(tmpl.layout_line_ids.mapped("widget_key"))
    bad = keys & (HR_KPI_KEYS | HR_BLOCK_KEYS)
    if bad:
        leak_layouts.append((variant, sorted(bad)))

# (b) a rendered director payload carries no HR keys at all
dir_payload = D_super.get_dashboard_data("director")
dir_layout_keys = {row["widget_key"] for row in dir_payload.get("layout", [])}
dir_kpi_keys = set(dir_payload.get("kpi", {}).keys())
dir_leak = (
    (dir_layout_keys & (HR_KPI_KEYS | HR_BLOCK_KEYS))
    | (dir_kpi_keys & HR_KPI_KEYS)
    | {k for k in dir_payload if k.startswith("hr_") and k.endswith("_block")}
)
_check("T-HRR-05",
       not leak_layouts and not dir_leak,
       f"no HR leak into non-HR lenses: layouts={leak_layouts}, "
       f"director_leak={sorted(dir_leak)}")


# -------------------------------------------- T-HRR-06 positive control
hr_tmpl = env.ref("neon_dashboard.default_layout_hr",
                  raise_if_not_found=False)
hr_layout_keys = set(hr_tmpl.layout_line_ids.filtered("visible").mapped(
    "widget_key")) if hr_tmpl else set()
_check("T-HRR-06",
       (HR_KPI_KEYS | HR_BLOCK_KEYS) <= hr_layout_keys,
       f"hr default layout carries all 8 HR widgets visible: "
       f"{sorted(hr_layout_keys & (HR_KPI_KEYS | HR_BLOCK_KEYS))}")


# --------------------------------------------- T-HRR-07 int preservation
int_ok = all(isinstance(hr_kpi[k]["value"], int) for k in HR_KPI_KEYS)
_check("T-HRR-07", int_ok,
       "value is int on all 5 (phr_r3b C1 invariant preserved)")


# ------------------------------------------------------------- teardown
for u in (u_hr, u_super):
    u.sudo().write({"active": False})
env.cr.commit()


print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
