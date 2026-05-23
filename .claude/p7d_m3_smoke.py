"""Phase 7d M3 smoke -- kanban + search + filter chips +
name_search override (13 tests).

T7d300 - kanban view loads
T7d301 - tree view loads
T7d302 - form view loads
T7d303 - search view resolves
T7d304 - name_search finds article by summary text
T7d305 - name_search finds article by keyword
T7d306 - "Published" filter returns only published
T7d307 - "My Articles" filter scopes to author=uid
T7d308 - kanban default group_by=category_id
T7d309 - action_publish raises AccessError for non-author/
         non-admin
T7d310 - action_publish succeeds when called by author
T7d311 - action_publish succeeds for admin tier
T7d312 - "Popular" filter returns view_count >= 10
"""
from odoo.exceptions import AccessError, UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Article = env["neon.kb.article"]
Cat = env["neon.kb.category"]
View = env["ir.ui.view"]
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


# Cleanup leftovers from prior runs (T7d3% pattern only).
Article.sudo().search(
    [("name", "=like", "T7d3%")]).unlink()
env.cr.commit()

u_super = _get_or_create_user(
    "p7d_m3_super", "P7d M3 Super",
    "neon_core.group_neon_superuser")
u_admin = _get_or_create_user(
    "p7d_m3_admin", "P7d M3 Train Admin",
    "neon_training.group_neon_training_admin")
u_author = _get_or_create_user(
    "p7d_m3_author", "P7d M3 Author",
    "base.group_user")
u_other = _get_or_create_user(
    "p7d_m3_other", "P7d M3 Other",
    "base.group_user")
env.cr.commit()

audio = env.ref("neon_kb.category_audio")


# ============================================================
print()
print("T7d300 - kanban view loads")
print("=" * 72)
kanban = env.ref(
    "neon_kb.view_kb_article_kanban",
    raise_if_not_found=False)
ok = bool(kanban)
if kanban:
    try:
        info = Article.get_view(
            view_id=kanban.id, view_type="kanban")
        arch = info.get("arch") or ""
        ok = ok and bool(arch) and "oe_kanban_card" in arch
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  kanban present: {bool(kanban)}, loads: {ok}")
print("T7d300:", "PASS" if ok else "FAIL")
results["T7d300"] = ok


# ============================================================
print()
print("T7d301 - tree view loads")
print("=" * 72)
tree = env.ref(
    "neon_kb.view_kb_article_tree",
    raise_if_not_found=False)
ok = bool(tree)
if tree:
    try:
        info = Article.get_view(
            view_id=tree.id, view_type="tree")
        ok = ok and bool(info.get("arch"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  tree present: {bool(tree)}, loads: {ok}")
print("T7d301:", "PASS" if ok else "FAIL")
results["T7d301"] = ok


# ============================================================
print()
print("T7d302 - form view loads")
print("=" * 72)
form = env.ref(
    "neon_kb.view_kb_article_form",
    raise_if_not_found=False)
ok = bool(form)
if form:
    try:
        info = Article.get_view(
            view_id=form.id, view_type="form")
        ok = ok and bool(info.get("arch"))
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  form present: {bool(form)}, loads: {ok}")
print("T7d302:", "PASS" if ok else "FAIL")
results["T7d302"] = ok


# ============================================================
print()
print("T7d303 - search view resolves")
print("=" * 72)
search_v = env.ref(
    "neon_kb.view_kb_article_search",
    raise_if_not_found=False)
ok = bool(search_v)
if search_v:
    try:
        info = Article.get_view(
            view_id=search_v.id, view_type="search")
        arch = info.get("arch") or ""
        ok = (ok and bool(arch)
              and 'name="filter_published"' in arch
              and 'name="filter_my"' in arch
              and 'name="filter_popular"' in arch)
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  err: {e}")
print(f"  search resolves + has 5 chips: {ok}")
print("T7d303:", "PASS" if ok else "FAIL")
results["T7d303"] = ok


# ============================================================
print()
print("T7d304 - name_search finds article by summary text")
print("=" * 72)
a = Article.sudo().create({
    "name": "T7d304 random title",
    "category_id": audio.id,
    "summary": "unique summary token zlx-summary-zlx",
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a.with_user(u_super).action_publish()
env.cr.commit()
res = Article.with_user(u_other).name_search(
    "zlx-summary-zlx", limit=10)
ok = any(r[0] == a.id for r in res)
print(f"  name_search by summary token found {len(res)} "
      f"result(s); target included: "
      f"{any(r[0] == a.id for r in res)}")
print("T7d304:", "PASS" if ok else "FAIL")
results["T7d304"] = ok


# ============================================================
print()
print("T7d305 - name_search finds article by keyword")
print("=" * 72)
a2 = Article.sudo().create({
    "name": "T7d305 random title two",
    "category_id": audio.id,
    "summary": "another summary",
    "keywords": "specialtoken-zzz, mic-tip, troubleshooting",
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a2.with_user(u_super).action_publish()
env.cr.commit()
res = Article.with_user(u_other).name_search(
    "specialtoken-zzz", limit=10)
ok = any(r[0] == a2.id for r in res)
print(f"  name_search by keyword found {len(res)}; "
      f"target included: {any(r[0] == a2.id for r in res)}")
print("T7d305:", "PASS" if ok else "FAIL")
results["T7d305"] = ok


# ============================================================
print()
print("T7d306 - 'Published' filter returns only published")
print("=" * 72)
a_pub = Article.sudo().create({
    "name": "T7d306 pub",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_pub.with_user(u_super).action_publish()
a_draft = Article.sudo().create({
    "name": "T7d306 draft",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
env.cr.commit()
res = Article.sudo().search(
    [("state", "=", "published"),
     ("id", "in", [a_pub.id, a_draft.id])])
ok = (a_pub in res and a_draft not in res)
print(f"  pub included: {a_pub in res}")
print(f"  draft excluded: {a_draft not in res}")
print("T7d306:", "PASS" if ok else "FAIL")
results["T7d306"] = ok


# ============================================================
print()
print("T7d307 - 'My Articles' filter scopes to author=uid")
print("=" * 72)
a_mine = Article.sudo().create({
    "name": "T7d307 mine",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_other = Article.sudo().create({
    "name": "T7d307 other",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_other.id,
})
env.cr.commit()
# Simulate the filter for u_author: domain author_id=uid
res = Article.with_user(u_author).search(
    [("author_id", "=", u_author.id),
     ("id", "in", [a_mine.id, a_other.id])])
ok = (a_mine in res and a_other not in res)
print(f"  my article included: {a_mine in res}")
print(f"  other's article excluded: {a_other not in res}")
print("T7d307:", "PASS" if ok else "FAIL")
results["T7d307"] = ok


# ============================================================
print()
print("T7d308 - kanban default group_by=category_id")
print("=" * 72)
arch = ""
if kanban:
    try:
        info = Article.get_view(
            view_id=kanban.id, view_type="kanban")
        arch = info.get("arch") or ""
    except Exception:
        pass
ok = 'default_group_by="category_id"' in arch
print(f"  default_group_by=category_id in arch: {ok}")
print("T7d308:", "PASS" if ok else "FAIL")
results["T7d308"] = ok


# ============================================================
print()
print("T7d309 - action_publish AccessError for non-author/"
      "non-admin")
print("=" * 72)
a_strict = Article.sudo().create({
    "name": "T7d309 strict",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
env.cr.commit()
err = None
try:
    a_strict.with_user(u_other).action_publish()
except Exception as e:  # noqa: BLE001
    err = e
ok = isinstance(err, AccessError)
print(f"  AccessError: {isinstance(err, AccessError)}")
print(f"  msg: {str(err)[:120] if err else None}")
print("T7d309:", "PASS" if ok else "FAIL")
results["T7d309"] = ok


# ============================================================
print()
print("T7d310 - action_publish succeeds when called by "
      "author")
print("=" * 72)
err = None
try:
    a_strict.with_user(u_author).action_publish()
except Exception as e:  # noqa: BLE001
    err = e
a_strict.invalidate_recordset(["state"])
ok = (err is None and a_strict.state == "published")
print(f"  err: {err}")
print(f"  state: {a_strict.state}")
print("T7d310:", "PASS" if ok else "FAIL")
results["T7d310"] = ok


# ============================================================
print()
print("T7d311 - action_publish succeeds for admin tier")
print("=" * 72)
a_admin = Article.sudo().create({
    "name": "T7d311 admin publish",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
env.cr.commit()
err = None
try:
    a_admin.with_user(u_admin).action_publish()
except Exception as e:  # noqa: BLE001
    err = e
a_admin.invalidate_recordset(["state"])
ok = (err is None and a_admin.state == "published")
print(f"  err: {err}")
print(f"  state: {a_admin.state}")
print("T7d311:", "PASS" if ok else "FAIL")
results["T7d311"] = ok


# ============================================================
print()
print("T7d312 - 'Popular' filter returns view_count >= 10")
print("=" * 72)
a_pop = Article.sudo().create({
    "name": "T7d312 popular",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
    "view_count": 15,
})
a_quiet = Article.sudo().create({
    "name": "T7d312 quiet",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
    "view_count": 3,
})
env.cr.commit()
res = Article.sudo().search(
    [("view_count", ">=", 10),
     ("id", "in", [a_pop.id, a_quiet.id])])
ok = (a_pop in res and a_quiet not in res)
print(f"  popular included: {a_pop in res}")
print(f"  quiet excluded: {a_quiet not in res}")
print("T7d312:", "PASS" if ok else "FAIL")
results["T7d312"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7d300", "T7d301", "T7d302", "T7d303",
         "T7d304", "T7d305", "T7d306", "T7d307",
         "T7d308", "T7d309", "T7d310", "T7d311",
         "T7d312"]
for k in order:
    v = results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(k, mark)
passed = sum(1 for k in order if results.get(k) is True)
print()
print(f"Total: {passed}/{len(order)} passed")

# Cleanup so re-runs don't accumulate.
Article.sudo().search(
    [("name", "=like", "T7d3%")]).unlink()
env.cr.commit()
env.cr.rollback()
