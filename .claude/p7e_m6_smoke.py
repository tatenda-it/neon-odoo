"""P7e.M6 smoke -- SOP model + module-SOP M2M (7 tests)."""
import base64

from odoo.exceptions import AccessError, ValidationError


def _try(fn):
    try:
        with env.cr.savepoint():
            return (None, fn())
    except Exception as e:  # noqa: BLE001
        return (e, None)


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

SOP = env["neon.lms.sop"]
Module = env["neon.lms.module"]
Attachment = env["ir.attachment"]
Users = env["res.users"]


def _get_or_create_user(login, name, group_xmlids):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
        })
    for g_xmlid in group_xmlids:
        g = env.ref(g_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


u_admin = _get_or_create_user(
    "p7e_m4_admin", "P7e M4 Train Admin",
    ["neon_training.group_neon_training_admin"])
u_crew = _get_or_create_user(
    "p7e_m1_crew", "P7e M1 Crew",
    ["neon_jobs.group_neon_jobs_crew"])
env.cr.commit()

m08 = env.ref("neon_lms.module_m08")
m15 = env.ref("neon_lms.module_m15")  # SQ6


# ============================================================
print()
print("T7e600 - sop creates with name + equipment")
print("=" * 72)
sop1 = SOP.sudo().create({
    "name": "Allen and Heath SQ6 Startup",
    "equipment_or_procedure": "Allen and Heath SQ6 console",
    "summary": "Power on, set gain stages, verify routing.",
})
ok = bool(sop1) and "SQ6" in sop1.name
print(f"  id={sop1.id} name={sop1.name}")
print("T7e600:", "PASS" if ok else "FAIL")
results["T7e600"] = ok


# ============================================================
print()
print("T7e601 - sop linked to module forward + reverse")
print("=" * 72)
sop1.sudo().write({"module_ids": [(4, m15.id)]})
sop1.invalidate_recordset()
m15.invalidate_recordset()
ok = (m15 in sop1.module_ids
      and sop1 in m15.sop_ids)
print(f"  m15 in sop1.module_ids: {m15 in sop1.module_ids}")
print(f"  sop1 in m15.sop_ids: {sop1 in m15.sop_ids}")
print("T7e601:", "PASS" if ok else "FAIL")
results["T7e601"] = ok


# ============================================================
print()
print("T7e602 - same SOP can attach to multiple modules")
print("=" * 72)
sop1.sudo().write({"module_ids": [(4, m08.id)]})
sop1.invalidate_recordset()
ok = (len(sop1.module_ids) >= 2
      and m08 in sop1.module_ids
      and m15 in sop1.module_ids)
print(f"  module count: {len(sop1.module_ids)}")
print("T7e602:", "PASS" if ok else "FAIL")
results["T7e602"] = ok


# ============================================================
print()
print("T7e603 - attachment URL when document set")
print("=" * 72)
att = Attachment.sudo().create({
    "name": "sq6_startup.pdf",
    "datas": base64.b64encode(b"%PDF-1.4 SOP test"),
    "res_model": "neon.lms.sop",
    "res_id": sop1.id,
    "mimetype": "application/pdf",
})
sop1.sudo().write({"document_attachment_id": att.id})
url = sop1._get_attachment_url()
ok = (isinstance(url, str)
      and url.startswith("/web/content/")
      and str(att.id) in url)
print(f"  url: {url}")
print("T7e603:", "PASS" if ok else "FAIL")
results["T7e603"] = ok


# ============================================================
print()
print("T7e604 - attachment URL falsy when no doc")
print("=" * 72)
sop_no_att = SOP.sudo().create({
    "name": "Text-only SOP",
    "summary": "No attachment needed.",
})
url_empty = sop_no_att._get_attachment_url()
ok = not url_empty
print(f"  url: {url_empty}")
print("T7e604:", "PASS" if ok else "FAIL")
results["T7e604"] = ok


# ============================================================
print()
print("T7e605 - all internal users read SOP")
print("=" * 72)
err_r, _r = _try(lambda: SOP.with_user(u_crew).search([]).read(["name"]))
ok = err_r is None
print(f"  crew read err: {err_r}")
print("T7e605:", "PASS" if ok else "FAIL")
results["T7e605"] = ok


# ============================================================
print()
print("T7e606 - only admin can create/edit SOP")
print("=" * 72)
err_c, _r = _try(lambda: SOP.with_user(u_crew).create({
    "name": "Crew create fail",
}))
err_a, sop_admin = _try(
    lambda: SOP.with_user(u_admin).create({
        "name": "Admin create OK",
    }))
ok = (isinstance(err_c, AccessError)
      and err_a is None
      and bool(sop_admin))
print(f"  crew create: {type(err_c).__name__ if err_c else None}")
print(f"  admin create: {bool(sop_admin)}")
print("T7e606:", "PASS" if ok else "FAIL")
results["T7e606"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7e600", "T7e601", "T7e602", "T7e603",
         "T7e604", "T7e605", "T7e606"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

env.cr.rollback()
