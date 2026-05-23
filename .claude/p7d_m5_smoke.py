"""Phase 7d M5 smoke -- cross-link M2M to LMS (10 tests).

T7d500 - 3 M2M join tables exist (information_schema)
T7d501 - article.related_sop_ids reads cleanly
T7d502 - sop.kb_article_ids reverse pointer reads cleanly
T7d503 - attach SOP via article side reflects on sop side
T7d504 - attach SOP via sop side reflects on article side
T7d505 - article.related_cert_type_ids works
T7d506 - article.related_module_ids works
T7d507 - deleting article doesn't orphan sop (cascade
         only drops the join row, preserves both ends)
T7d508 - defensive: env.get is unnecessary here since 7d
         hard-depends on 7e; assert dependency present
T7d509 - regression: SOP model basic CRUD unchanged
"""
print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Article = env["neon.kb.article"]
SOP = env["neon.lms.sop"]
CertType = env["neon.training.certification.type"]
Module = env["neon.lms.module"]
Users = env["res.users"]


def _get_or_create_user(login, name, group_xmlid):
    u = Users.sudo().search(
        [("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
            "email": login + "@example.test",
        })
    elif not u.email:
        u.sudo().email = login + "@example.test"
    if group_xmlid:
        g = env.ref(group_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u


# Cleanup leftovers
Article.sudo().search(
    [("name", "=like", "T7d5%")]).unlink()
SOP.sudo().search(
    [("name", "=like", "T7d5%")]).unlink()
env.cr.commit()

u_super = _get_or_create_user(
    "p7d_m5_super", "P7d M5 Super",
    "neon_core.group_neon_superuser")
u_author = _get_or_create_user(
    "p7d_m5_author", "P7d M5 Author",
    "base.group_user")
env.cr.commit()

audio = env.ref("neon_kb.category_audio")


# ============================================================
print()
print("T7d500 - 3 M2M join tables exist")
print("=" * 72)
expected_tables = [
    "neon_kb_article_cert_type_rel",
    "neon_kb_article_sop_rel",
    "neon_kb_article_module_rel",
]
missing = []
for tbl in expected_tables:
    env.cr.execute("""
        SELECT 1 FROM information_schema.tables
         WHERE table_name = %s
    """, [tbl])
    if not env.cr.fetchone():
        missing.append(tbl)
ok = not missing
for tbl in expected_tables:
    status = "MISSING" if tbl in missing else "OK"
    print(f"  {tbl}: {status}")
print("T7d500:", "PASS" if ok else "FAIL")
results["T7d500"] = ok


# ============================================================
print()
print("T7d501 - article.related_sop_ids reads cleanly")
print("=" * 72)
a = Article.sudo().create({
    "name": "T7d501 article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
ok = a.related_sop_ids.ids == []
print(f"  empty M2M reads as []: {a.related_sop_ids.ids}")
print("T7d501:", "PASS" if ok else "FAIL")
results["T7d501"] = ok


# ============================================================
print()
print("T7d502 - sop.kb_article_ids reverse pointer reads")
print("=" * 72)
sop = SOP.sudo().create({"name": "T7d502 probe SOP"})
ok = sop.kb_article_ids.ids == []
print(f"  empty reverse M2M reads as []: "
      f"{sop.kb_article_ids.ids}")
print("T7d502:", "PASS" if ok else "FAIL")
results["T7d502"] = ok


# ============================================================
print()
print("T7d503 - attach SOP via article -> reflects on SOP")
print("=" * 72)
a503 = Article.sudo().create({
    "name": "T7d503 article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
sop503 = SOP.sudo().create({"name": "T7d503 SOP"})
a503.sudo().related_sop_ids = [(4, sop503.id)]
sop503.invalidate_recordset(["kb_article_ids"])
ok = a503 in sop503.kb_article_ids
print(f"  reverse pointer reflects: {ok}")
print("T7d503:", "PASS" if ok else "FAIL")
results["T7d503"] = ok


# ============================================================
print()
print("T7d504 - attach via SOP side -> reflects on article")
print("=" * 72)
a504 = Article.sudo().create({
    "name": "T7d504 article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
sop504 = SOP.sudo().create({"name": "T7d504 SOP"})
sop504.sudo().kb_article_ids = [(4, a504.id)]
a504.invalidate_recordset(["related_sop_ids"])
ok = sop504 in a504.related_sop_ids
print(f"  forward pointer reflects: {ok}")
print("T7d504:", "PASS" if ok else "FAIL")
results["T7d504"] = ok


# ============================================================
print()
print("T7d505 - article.related_cert_type_ids works")
print("=" * 72)
ct = CertType.search([], limit=1)
a505 = Article.sudo().create({
    "name": "T7d505 article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
    "related_cert_type_ids": [(6, 0, [ct.id])],
})
ok = ct in a505.related_cert_type_ids
print(f"  cert type attached: {ok}")
print("T7d505:", "PASS" if ok else "FAIL")
results["T7d505"] = ok


# ============================================================
print()
print("T7d506 - article.related_module_ids works")
print("=" * 72)
mod = Module.search([], limit=1)
a506 = Article.sudo().create({
    "name": "T7d506 article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
    "related_module_ids": [(6, 0, [mod.id])],
})
ok = mod in a506.related_module_ids
print(f"  module attached: {ok}")
print("T7d506:", "PASS" if ok else "FAIL")
results["T7d506"] = ok


# ============================================================
print()
print("T7d507 - deleting article preserves SOP (M2M "
      "cascade)")
print("=" * 72)
a507 = Article.sudo().create({
    "name": "T7d507 to delete",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
sop507 = SOP.sudo().create({"name": "T7d507 SOP survives"})
a507.sudo().related_sop_ids = [(4, sop507.id)]
env.cr.commit()
sop_id = sop507.id
a507.sudo().unlink()
env.invalidate_all()
sop_after = SOP.sudo().browse(sop_id)
ok = (sop_after.exists()
      and len(sop_after.kb_article_ids) == 0)
print(f"  sop survives: {bool(sop_after.exists())}")
print(f"  join row dropped: "
      f"{len(sop_after.kb_article_ids) == 0}")
print("T7d507:", "PASS" if ok else "FAIL")
results["T7d507"] = ok


# ============================================================
print()
print("T7d508 - neon_lms is a hard depend (no env.get "
      "needed)")
print("=" * 72)
manifest_path = (
    "/mnt/extra-addons/neon_kb/__manifest__.py")
with open(manifest_path) as fh:
    txt = fh.read()
has_lms_dep = '"neon_lms"' in txt
has_train_dep = '"neon_training"' in txt
ok = has_lms_dep and has_train_dep
print(f"  neon_lms in depends: {has_lms_dep}")
print(f"  neon_training in depends: {has_train_dep}")
print("T7d508:", "PASS" if ok else "FAIL")
results["T7d508"] = ok


# ============================================================
print()
print("T7d509 - regression: SOP basic CRUD unchanged")
print("=" * 72)
existing_sops = SOP.search([])
sop_reg = SOP.sudo().create({"name": "T7d509 regression"})
ok = (bool(sop_reg.id)
      and sop_reg.active is True
      and hasattr(sop_reg, "kb_article_ids")
      and hasattr(sop_reg, "module_ids"))
print(f"  create OK: {bool(sop_reg.id)}")
print(f"  active default: {sop_reg.active}")
print(f"  new field kb_article_ids: "
      f"{hasattr(sop_reg, 'kb_article_ids')}")
print(f"  legacy field module_ids: "
      f"{hasattr(sop_reg, 'module_ids')}")
print("T7d509:", "PASS" if ok else "FAIL")
results["T7d509"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7d500", "T7d501", "T7d502", "T7d503",
         "T7d504", "T7d505", "T7d506", "T7d507",
         "T7d508", "T7d509"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

# Cleanup
Article.sudo().search(
    [("name", "=like", "T7d5%")]).unlink()
SOP.sudo().search(
    [("name", "=like", "T7d5%")]).unlink()
env.cr.commit()
env.cr.rollback()
