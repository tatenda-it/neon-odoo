"""Phase 7d integration smoke -- full article lifecycle
end-to-end. 1 test, 12 stages.

T7dI001 -- category seed -> draft article -> non-author
visibility check -> publish + notify -> base-user visibility
-> portal-style view_count -> cross-link SOP -> archive +
notify -> republish + notify -> back-to-draft + notify ->
dashboard counters -> final aggregates.

Exercises ~85% of Phase 7d code paths: category seed,
article creation + slug auto-gen, state machine (all 4
transitions + 4 notification stubs), record rules
(author / base / portal), view_count helper, cross-module
M2M to neon.lms.sop, dashboard counter cross-module touch.
"""
from datetime import datetime, timedelta

from odoo.exceptions import AccessError, UserError


print("=" * 72)
print("SETUP")
print("=" * 72)
stage_results = {}

Article = env["neon.kb.article"]
Cat = env["neon.kb.category"]
Tag = env["neon.kb.tag"]
SOP = env["neon.lms.sop"]
Dashboard = env["neon.training.dashboard"]
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


# Cleanup leftovers (integration smoke uses unique slug-
# prefixed names so subsequent runs don't accumulate).
Article.sudo().search(
    [("name", "=like", "T7dI%")]).unlink()
SOP.sudo().search([("name", "=like", "T7dI%")]).unlink()
env.cr.commit()

u_admin = _get_or_create_user(
    "p7d_int_admin", "P7d Int Train Admin",
    "neon_training.group_neon_training_admin")
u_author = _get_or_create_user(
    "p7d_int_author", "P7d Int Author",
    "base.group_user")
u_base = _get_or_create_user(
    "p7d_int_base", "P7d Int Base Other",
    "base.group_user")
# Portal user (separate type)
u_portal = Users.sudo().search(
    [("login", "=", "p7d_int_portal")], limit=1)
if not u_portal:
    portal_group = env.ref("base.group_portal")
    u_portal = Users.sudo().with_context(
        no_reset_password=True).create({
        "name": "P7d Int Portal", "login": "p7d_int_portal",
        "password": "test123",
        "email": "p7d_int_portal@example.test",
        "groups_id": [(6, 0, [portal_group.id])],
    })
env.cr.commit()

_STUB_MARKER = "[Notification stub - Phase 9 will send]"


# ============================================================
print()
print("Stage 1 -- resolve category Audio seed")
print("=" * 72)
audio = env.ref(
    "neon_kb.category_audio",
    raise_if_not_found=False)
ok = (bool(audio)
      and audio.active
      and audio.code == "audio"
      and "Audio" in (audio.name or ""))
print(f"  category: {audio.name if audio else None} "
      f"(code={audio.code if audio else None}, "
      f"icon={audio.icon if audio else None})")
stage_results["s1_category"] = ok


# ============================================================
print()
print("Stage 2 -- create draft article (slug auto-gen)")
print("=" * 72)
article = Article.sudo().create({
    "name": "T7dI Allen & Heath SQ6 Patching Quick Reference",
    "category_id": audio.id,
    "body": "<p>Step 1: Power on the console. Step 2: "
            "Load scene 1. Step 3: Verify input matrix.</p>",
    "summary": "Quick reference for patching the SQ6.",
    "keywords": "sq6, allen-heath, patching, console",
    "author_id": u_author.id,
})
expected_slug = "t7di-allen-heath-sq6-patching-quick-reference"
ok = (bool(article.id)
      and article.state == "draft"
      and article.author_id == u_author
      and article.code == expected_slug)
print(f"  id: {article.id}, code: {article.code!r}, "
      f"state: {article.state}")
stage_results["s2_create_draft"] = ok


# ============================================================
print()
print("Stage 3 -- non-author base user cannot see draft")
print("=" * 72)
visible_base = Article.with_user(u_base).search(
    [("id", "=", article.id)])
ok = article not in visible_base
print(f"  base user (non-author) blocked from draft: "
      f"{article not in visible_base}")
stage_results["s3_draft_hidden"] = ok


# ============================================================
print()
print("Stage 4 -- author publishes + notification fires")
print("=" * 72)
article.with_user(u_author).action_publish()
article.invalidate_recordset([
    "state", "published_by_id", "date_published"])
bodies = "\n".join(article.message_ids.mapped("body"))
ok = (article.state == "published"
      and article.published_by_id == u_author
      and bool(article.date_published)
      and "kb_article_published" in bodies
      and _STUB_MARKER in bodies)
print(f"  state: {article.state}")
print(f"  published_by: {article.published_by_id.login}")
print(f"  published event in chatter: "
      f"{'kb_article_published' in bodies}")
print(f"  stub marker present: {_STUB_MARKER in bodies}")
stage_results["s4_publish"] = ok


# ============================================================
print()
print("Stage 5 -- base user sees published")
print("=" * 72)
visible_base = Article.with_user(u_base).search(
    [("id", "=", article.id)])
ok = article in visible_base
print(f"  base user sees published: "
      f"{article in visible_base}")
stage_results["s5_base_visibility"] = ok


# ============================================================
print()
print("Stage 6 -- portal access + view_count increment")
print("=" * 72)
# Simulate the portal route's increment helper (we can't
# render the QWeb template in shell without a request).
# Portal user has read access via the published rule.
visible_portal = Article.with_user(u_portal).search(
    [("id", "=", article.id)])
before_views = article.view_count
article._increment_view_count(u_portal)
article.invalidate_recordset(["view_count"])
after_views = article.view_count
ok = (article in visible_portal
      and (after_views - before_views) == 1)
print(f"  portal sees published: "
      f"{article in visible_portal}")
print(f"  view_count {before_views} -> {after_views}")
stage_results["s6_portal_view"] = ok


# ============================================================
print()
print("Stage 7 -- cross-link SOP (M5 M2M)")
print("=" * 72)
sop = SOP.sudo().create({"name": "T7dI integration SOP"})
article.sudo().related_sop_ids = [(4, sop.id)]
sop.invalidate_recordset(["kb_article_ids"])
ok = (sop in article.related_sop_ids
      and article in sop.kb_article_ids)
print(f"  article.related_sop_ids has sop: "
      f"{sop in article.related_sop_ids}")
print(f"  sop.kb_article_ids has article: "
      f"{article in sop.kb_article_ids}")
stage_results["s7_cross_link"] = ok


# ============================================================
print()
print("Stage 8 -- archive + notification")
print("=" * 72)
article.with_user(u_author).action_archive_article()
article.invalidate_recordset(["state"])
bodies = "\n".join(article.message_ids.mapped("body"))
ok = (article.state == "archived"
      and "kb_article_archived" in bodies)
print(f"  state: {article.state}")
print(f"  archived event in chatter: "
      f"{'kb_article_archived' in bodies}")
stage_results["s8_archive"] = ok


# ============================================================
print()
print("Stage 9 -- admin republish + notification")
print("=" * 72)
article.with_user(u_admin).action_republish()
article.invalidate_recordset(["state"])
bodies = "\n".join(article.message_ids.mapped("body"))
ok = (article.state == "published"
      and "kb_article_republished" in bodies)
print(f"  state: {article.state}")
print(f"  republished event in chatter: "
      f"{'kb_article_republished' in bodies}")
stage_results["s9_republish"] = ok


# ============================================================
print()
print("Stage 10 -- back to draft + notification")
print("=" * 72)
article.with_user(u_author).action_back_to_draft()
article.invalidate_recordset(["state"])
bodies = "\n".join(article.message_ids.mapped("body"))
ok = (article.state == "draft"
      and "kb_article_back_to_draft" in bodies)
print(f"  state: {article.state}")
print(f"  back_to_draft event in chatter: "
      f"{'kb_article_back_to_draft' in bodies}")
stage_results["s10_back_to_draft"] = ok


# ============================================================
print()
print("Stage 11 -- dashboard counter reflects re-publish")
print("=" * 72)
dash = Dashboard.sudo().create({})
dash.invalidate_recordset([
    "kb_articles_published", "kb_articles_recent_30d"])
before_pub = dash.kb_articles_published
before_recent = dash.kb_articles_recent_30d
# Re-publish so the article is countable.
article.with_user(u_admin).action_publish()
env.cr.commit()
dash.invalidate_recordset([
    "kb_articles_published", "kb_articles_recent_30d"])
after_pub = dash.kb_articles_published
after_recent = dash.kb_articles_recent_30d
ok = ((after_pub - before_pub) == 1
      and (after_recent - before_recent) == 1)
print(f"  published: {before_pub} -> {after_pub} "
      f"(delta {after_pub - before_pub})")
print(f"  recent_30d: {before_recent} -> {after_recent} "
      f"(delta {after_recent - before_recent})")
stage_results["s11_dashboard"] = ok


# ============================================================
print()
print("Stage 12 -- final aggregates")
print("=" * 72)
expected_events = {
    "kb_article_published",
    "kb_article_archived",
    "kb_article_republished",
    "kb_article_back_to_draft",
}
bodies = "\n".join(article.message_ids.mapped("body"))
events_found = {
    ev for ev in expected_events if ev in bodies}
stub_count = bodies.count(_STUB_MARKER)
article.invalidate_recordset(["view_count", "state"])
ok = (
    article.state == "published"
    and events_found == expected_events
    and stub_count >= 4
    and article.view_count >= 1
    and sop in article.related_sop_ids)
print(f"  final state: {article.state}")
print(f"  events fired: {sorted(events_found)}")
print(f"  stub markers in chatter: {stub_count} (>= 4)")
print(f"  view_count: {article.view_count}")
print(f"  cross-link preserved: "
      f"{sop in article.related_sop_ids}")
stage_results["s12_aggregates"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = [
    "s1_category", "s2_create_draft", "s3_draft_hidden",
    "s4_publish", "s5_base_visibility", "s6_portal_view",
    "s7_cross_link", "s8_archive", "s9_republish",
    "s10_back_to_draft", "s11_dashboard",
    "s12_aggregates",
]
for k in order:
    v = stage_results.get(k)
    mark = "PASS" if v is True else ("SKIP" if v is None
                                     else "FAIL")
    print(f"  {k}: {mark}")
passed = sum(1 for k in order
             if stage_results.get(k) is True)
print()
print(f"Stages: {passed}/{len(order)} pass")

overall = passed == len(order)
print()
print("T7dI001:", "PASS" if overall else "FAIL")
print(f"Total: {1 if overall else 0}/1 passed")

# Cleanup
Article.sudo().search(
    [("name", "=like", "T7dI%")]).unlink()
SOP.sudo().search(
    [("name", "=like", "T7dI%")]).unlink()
env.cr.commit()
env.cr.rollback()
