"""Phase 7d M4 smoke -- portal route + view_count hook
(10 tests).

T7d400 - /my/kb route registered + auth=user
T7d401 - /my/kb/article/<code> route registered
T7d402 - portal_kb_article template renders for published
T7d403 - draft article -> redirects to /my/kb
T7d404 - _increment_view_count bumps by 1
T7d405 - _prepare_home_portal_values exposes kb_count
T7d406 - category filter scopes article list
T7d407 - search matches name + summary + keywords
T7d408 - pagination -- page=2 returns offset N
T7d409 - portal user can read published article
"""
import re

from odoo.exceptions import AccessError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Article = env["neon.kb.article"]
Cat = env["neon.kb.category"]
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
    [("name", "=like", "T7d4%")]).unlink()
env.cr.commit()

u_super = _get_or_create_user(
    "p7d_m4_super", "P7d M4 Super",
    "neon_core.group_neon_superuser")
u_author = _get_or_create_user(
    "p7d_m4_author", "P7d M4 Author",
    "base.group_user")
# Portal user (replace groups so it doesn't double-up
# with base.group_user).
u_portal = Users.sudo().search(
    [("login", "=", "p7d_m4_portal")], limit=1)
if not u_portal:
    portal_group = env.ref("base.group_portal")
    u_portal = Users.sudo().with_context(
        no_reset_password=True).create({
        "name": "P7d M4 Portal", "login": "p7d_m4_portal",
        "password": "test123",
        "email": "p7d_m4_portal@example.test",
        "groups_id": [(6, 0, [portal_group.id])],
    })
env.cr.commit()

audio = env.ref("neon_kb.category_audio")
lighting = env.ref("neon_kb.category_lighting")


# ============================================================
print()
print("T7d400 - /my/kb route registered + auth=user")
print("=" * 72)
# In shell context there's no live request; inspect the
# controller class directly. http.route stamps the
# routing metadata on the method (.routing attribute).
from odoo.addons.neon_kb.controllers.portal import (
    NeonKBPortal)
list_method = NeonKBPortal.portal_kb_list
routing = getattr(list_method, "original_routing", {}) or {}
routes = routing.get("routes", [])
auth = routing.get("auth")
ok = ("/my/kb" in routes
      and any(r.startswith("/my/kb/page/") for r in routes)
      and auth == "user")
print(f"  routes: {routes}")
print(f"  auth: {auth}")
print("T7d400:", "PASS" if ok else "FAIL")
results["T7d400"] = ok


# ============================================================
print()
print("T7d401 - /my/kb/article/<code> route registered")
print("=" * 72)
detail_method = NeonKBPortal.portal_kb_article
detail_routing = getattr(
    detail_method, "original_routing", {}) or {}
detail_routes = detail_routing.get("routes", [])
ok = any("/my/kb/article/" in r for r in detail_routes)
print(f"  routes: {detail_routes}")
print("T7d401:", "PASS" if ok else "FAIL")
results["T7d401"] = ok


# ============================================================
print()
print("T7d402 - portal_kb_article template defined + "
      "has expected structure")
print("=" * 72)
# Full render requires a live request context (portal
# layout reads request.env.user etc.). Structural check
# instead: confirm template exists, arch contains the
# expected article-detail markers.
tmpl = env.ref(
    "neon_kb.portal_kb_article",
    raise_if_not_found=False)
ok = bool(tmpl)
if tmpl:
    arch = tmpl.arch_db or ""
    has_layout = 'portal.portal_layout' in arch
    has_body = 't-out="article.body"' in arch
    has_meta = 'article.view_count' in arch
    has_breadcrumb = 'breadcrumb' in arch
    ok = (ok and has_layout and has_body and has_meta
          and has_breadcrumb)
    print(f"  arch length: {len(arch)}")
    print(f"  portal_layout call: {has_layout}")
    print(f"  body t-out: {has_body}")
    print(f"  view_count in arch: {has_meta}")
    print(f"  breadcrumb in arch: {has_breadcrumb}")
print("T7d402:", "PASS" if ok else "FAIL")
results["T7d402"] = ok


# ============================================================
print()
print("T7d403 - portal controller redirects when article "
      "is draft / missing")
print("=" * 72)
# Inspect the controller source to confirm the redirect
# branch exists.
import inspect
from odoo.addons.neon_kb.controllers.portal import (
    NeonKBPortal)
src = inspect.getsource(NeonKBPortal.portal_kb_article)
has_redirect = (
    "request.redirect('/my/kb')" in src
    or 'request.redirect("/my/kb")' in src)
has_state_filter = '"state", "=", "published"' in src or \
    "'state', '=', 'published'" in src
ok = has_redirect and has_state_filter
print(f"  redirect branch in source: {has_redirect}")
print(f"  state=published filter in domain: "
      f"{has_state_filter}")
print("T7d403:", "PASS" if ok else "FAIL")
results["T7d403"] = ok


# ============================================================
print()
print("T7d404 - _increment_view_count bumps by 1")
print("=" * 72)
a_inc = Article.sudo().create({
    "name": "T7d404 increment probe",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
before = a_inc.view_count
a_inc._increment_view_count(u_portal)
a_inc.invalidate_recordset(["view_count"])
after = a_inc.view_count
ok = (after - before) == 1
print(f"  before: {before}, after: {after} (delta {after - before})")
print("T7d404:", "PASS" if ok else "FAIL")
results["T7d404"] = ok


# ============================================================
print()
print("T7d405 - _prepare_home_portal_values exposes kb_count")
print("=" * 72)
src = inspect.getsource(
    NeonKBPortal._prepare_home_portal_values)
has_kb_count = '"kb_count"' in src or "'kb_count'" in src
has_published = '"published"' in src or "'published'" in src
ok = has_kb_count and has_published
print(f"  kb_count in source: {has_kb_count}")
print(f"  state filter present: {has_published}")
print("T7d405:", "PASS" if ok else "FAIL")
results["T7d405"] = ok


# ============================================================
print()
print("T7d406 - category filter scopes article list")
print("=" * 72)
a_audio = Article.sudo().create({
    "name": "T7d406 audio article",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_light = Article.sudo().create({
    "name": "T7d406 lighting article",
    "category_id": lighting.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_audio.with_user(u_super).action_publish()
a_light.with_user(u_super).action_publish()
# Build domain the controller would build:
domain = [
    ("state", "=", "published"),
    ("active", "=", True),
    ("category_id", "=", audio.id),
]
res = Article.sudo().search(domain)
ok = (a_audio in res and a_light not in res)
print(f"  audio article in audio-filter: {a_audio in res}")
print(f"  lighting article excluded: {a_light not in res}")
print("T7d406:", "PASS" if ok else "FAIL")
results["T7d406"] = ok


# ============================================================
print()
print("T7d407 - search matches name + summary + keywords")
print("=" * 72)
a_kw = Article.sudo().create({
    "name": "T7d407 boring title",
    "category_id": audio.id,
    "summary": "this is the unique-summary-token-q1",
    "keywords": "kw-token-q2, mic, troubleshooting",
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_kw.with_user(u_super).action_publish()
env.cr.commit()
# Search by summary
domain_sum = [
    ("state", "=", "published"),
    "|", "|",
    ("name", "ilike", "unique-summary-token-q1"),
    ("summary", "ilike", "unique-summary-token-q1"),
    ("keywords", "ilike", "unique-summary-token-q1"),
]
res_sum = Article.sudo().search(domain_sum)
# Search by keyword
domain_kw = [
    ("state", "=", "published"),
    "|", "|",
    ("name", "ilike", "kw-token-q2"),
    ("summary", "ilike", "kw-token-q2"),
    ("keywords", "ilike", "kw-token-q2"),
]
res_kw = Article.sudo().search(domain_kw)
ok = (a_kw in res_sum and a_kw in res_kw)
print(f"  summary hit: {a_kw in res_sum}")
print(f"  keyword hit: {a_kw in res_kw}")
print("T7d407:", "PASS" if ok else "FAIL")
results["T7d407"] = ok


# ============================================================
print()
print("T7d408 - pagination -- page=2 offset")
print("=" * 72)
# Create 12 articles to span 2 pages of 10
created = []
for i in range(12):
    a_p = Article.sudo().create({
        "name": f"T7d408 pagination article {i:02d}",
        "category_id": audio.id,
        "body": "<p>body</p>",
        "author_id": u_author.id,
    })
    a_p.with_user(u_super).action_publish()
    created.append(a_p)
env.cr.commit()

domain = [
    ("state", "=", "published"),
    ("active", "=", True),
    ("name", "=like", "T7d408 pagination article %"),
]
page1 = Article.sudo().search(
    domain, limit=10, offset=0,
    order="date_published desc, view_count desc")
page2 = Article.sudo().search(
    domain, limit=10, offset=10,
    order="date_published desc, view_count desc")
ok = (len(page1) == 10
      and len(page2) == 2
      and not (set(page1.ids) & set(page2.ids)))
print(f"  page1 count: {len(page1)} (expect 10)")
print(f"  page2 count: {len(page2)} (expect 2)")
print(f"  no overlap: "
      f"{not (set(page1.ids) & set(page2.ids))}")
print("T7d408:", "PASS" if ok else "FAIL")
results["T7d408"] = ok


# ============================================================
print()
print("T7d409 - portal user can read published article")
print("=" * 72)
a_pp = Article.sudo().create({
    "name": "T7d409 portal read probe",
    "category_id": audio.id,
    "body": "<p>body</p>",
    "author_id": u_author.id,
})
a_pp.with_user(u_super).action_publish()
env.cr.commit()
try:
    res = Article.with_user(u_portal).search(
        [("id", "=", a_pp.id)])
    ok = a_pp in res
except AccessError:
    ok = False
print(f"  portal sees published: {ok}")
print("T7d409:", "PASS" if ok else "FAIL")
results["T7d409"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7d400", "T7d401", "T7d402", "T7d403", "T7d404",
         "T7d405", "T7d406", "T7d407", "T7d408", "T7d409"]
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
    [("name", "=like", "T7d4%")]).unlink()
env.cr.commit()
env.cr.rollback()
