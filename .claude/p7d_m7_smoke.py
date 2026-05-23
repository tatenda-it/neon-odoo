"""Phase 7d M7 smoke -- 4 notification stubs (8 tests).

T7d700 - _notify_article_published fires on action_publish
T7d701 - _notify_article_archived fires on action_archive
T7d702 - _notify_article_back_to_draft fires on
         action_back_to_draft
T7d703 - _notify_article_republished fires on action_republish
T7d704 - stub marker uses ASCII hyphen (greppable)
T7d705 - channels recorded in message body
T7d706 - _notify_send uses sudo() on message_post
T7d707 - stub marker substring present in all 4 events
"""
import inspect

from odoo.exceptions import UserError, AccessError


print("=" * 72)
print("SETUP")
print("=" * 72)
results = {}

Article = env["neon.kb.article"]
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
    [("name", "=like", "T7d7%")]).unlink()
env.cr.commit()

u_super = _get_or_create_user(
    "p7d_m7_super", "P7d M7 Super",
    "neon_core.group_neon_superuser")
u_author = _get_or_create_user(
    "p7d_m7_author", "P7d M7 Author",
    "base.group_user")
env.cr.commit()

audio = env.ref("neon_kb.category_audio")
_STUB_MARKER = "[Notification stub - Phase 9 will send]"


def _bodies(a):
    return [m.body or "" for m in a.message_ids]


def _new_draft(name):
    return Article.sudo().create({
        "name": name,
        "category_id": audio.id,
        "body": "<p>body content</p>",
        "author_id": u_author.id,
    })


# ============================================================
print()
print("T7d700 - _notify_article_published on action_publish")
print("=" * 72)
a1 = _new_draft("T7d700 publish")
a1.with_user(u_super).action_publish()
bodies = _bodies(a1)
hit = [b for b in bodies if "kb_article_published" in b]
ok = bool(hit)
print(f"  published event in chatter: {ok}")
print("T7d700:", "PASS" if ok else "FAIL")
results["T7d700"] = ok


# ============================================================
print()
print("T7d701 - _notify_article_archived on archive")
print("=" * 72)
a2 = _new_draft("T7d701 archive")
a2.with_user(u_super).action_publish()
a2.with_user(u_super).action_archive_article()
bodies = _bodies(a2)
hit = [b for b in bodies if "kb_article_archived" in b]
ok = bool(hit)
print(f"  archived event in chatter: {ok}")
print("T7d701:", "PASS" if ok else "FAIL")
results["T7d701"] = ok


# ============================================================
print()
print("T7d702 - _notify_article_back_to_draft on back_to_draft")
print("=" * 72)
a3 = _new_draft("T7d702 back to draft")
a3.with_user(u_super).action_publish()
a3.with_user(u_super).action_back_to_draft()
bodies = _bodies(a3)
hit = [b for b in bodies
       if "kb_article_back_to_draft" in b]
ok = bool(hit)
print(f"  back_to_draft event in chatter: {ok}")
print("T7d702:", "PASS" if ok else "FAIL")
results["T7d702"] = ok


# ============================================================
print()
print("T7d703 - _notify_article_republished on republish")
print("=" * 72)
a4 = _new_draft("T7d703 republish")
a4.with_user(u_super).action_publish()
a4.with_user(u_super).action_archive_article()
a4.with_user(u_super).action_republish()
bodies = _bodies(a4)
hit = [b for b in bodies if "kb_article_republished" in b]
ok = bool(hit)
print(f"  republished event in chatter: {ok}")
print("T7d703:", "PASS" if ok else "FAIL")
results["T7d703"] = ok


# ============================================================
print()
print("T7d704 - marker uses ASCII hyphen (greppable)")
print("=" * 72)
# Check the rendered chatter message body, not the
# Python source -- the source has the marker split
# across two string literals that Python concatenates at
# runtime. The rendered body is what Phase 9's grep sees.
body_a1 = next(
    (b for b in _bodies(a1)
     if "kb_article_published" in b), "")
has_ascii_marker = (
    "[Notification stub - Phase 9 will send]" in body_a1)
has_em_dash = (
    "[Notification stub — Phase 9 will send]" in body_a1
    or "[Notification stub – Phase 9 will send]"
    in body_a1)
ok = has_ascii_marker and not has_em_dash
print(f"  ASCII-hyphen marker in rendered body: "
      f"{has_ascii_marker}")
print(f"  em-dash variant present: {has_em_dash}")
print("T7d704:", "PASS" if ok else "FAIL")
results["T7d704"] = ok


# ============================================================
print()
print("T7d705 - channels recorded in message body")
print("=" * 72)
# Each of the 4 event hooks declares channels=['email'];
# the dispatcher renders that in the chatter post.
bodies_a1 = _bodies(a1)
event_body = next(
    (b for b in bodies_a1
     if "kb_article_published" in b), "")
ok = "email" in event_body
print(f"  channels line includes 'email': {ok}")
print("T7d705:", "PASS" if ok else "FAIL")
results["T7d705"] = ok


# ============================================================
print()
print("T7d706 - _notify_send uses sudo() on message_post")
print("=" * 72)
src = inspect.getsource(Article._notify_send)
has_sudo_post = (
    "self.sudo().message_post(" in src
    or "self.sudo(\n            ).message_post(" in src)
ok = has_sudo_post
print(f"  sudo() before message_post: {ok}")
print("T7d706:", "PASS" if ok else "FAIL")
results["T7d706"] = ok


# ============================================================
print()
print("T7d707 - stub marker present in all 4 event bodies")
print("=" * 72)
all_articles = [a1, a2, a3, a4]
events_expected = [
    ("kb_article_published", a1),
    ("kb_article_archived", a2),
    ("kb_article_back_to_draft", a3),
    ("kb_article_republished", a4),
]
all_markered = True
for event, art in events_expected:
    bodies = _bodies(art)
    event_body = next(
        (b for b in bodies if event in b), "")
    if _STUB_MARKER not in event_body:
        all_markered = False
        print(f"  marker missing for: {event}")
ok = all_markered
print(f"  all 4 events carry stub marker: {ok}")
print("T7d707:", "PASS" if ok else "FAIL")
results["T7d707"] = ok


# ============================================================
print()
print("FULL SUMMARY")
print("=" * 72)
order = ["T7d700", "T7d701", "T7d702", "T7d703",
         "T7d704", "T7d705", "T7d706", "T7d707"]
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
    [("name", "=like", "T7d7%")]).unlink()
env.cr.commit()
env.cr.rollback()
