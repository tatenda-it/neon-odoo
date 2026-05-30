"""Reproduce T7d202 using the smoke's actual fixture path."""
Article = env["neon.kb.article"]
Users = env["res.users"]


def _gocu(login, name, group_xmlid):
    u = Users.sudo().search([("login", "=", login)], limit=1)
    if not u:
        u = Users.sudo().create({
            "name": name, "login": login,
            "password": "test123",
            "email": login + "@example.test",
        })
    if group_xmlid:
        g = env.ref(group_xmlid, raise_if_not_found=False)
        if g and u not in g.users:
            g.sudo().write({"users": [(4, u.id)]})
    return u

u_author = _gocu("p7d_m2_author", "P7d M2 Author", "base.group_user")
env.cr.commit()

audio = env.ref("neon_kb.category_audio")


def _new_article(name=None, **vals):
    base = {
        "name": name or "probe",
        "category_id": audio.id,
        "body": "<p>Body</p>",
        "author_id": u_author.id,
    }
    base.update(vals)
    return Article.sudo().create(base)


# T7d200 setup
a = _new_article(name="T7d200 first")
print(f"a.id={a.id}, a.code={a.code!r}")

# T7d202 first try -- explicit code matching the first article
print()
print("--- _try #1 ---")
try:
    with env.cr.savepoint():
        a2 = _new_article(name="DupSlug", code="t7d200-first")
        print(f"unexpected create OK: {a2.id}")
except Exception as e:
    print(f"err: {type(e).__name__}: {str(e)[:140]}")

# Verify transaction is healthy
print()
print("--- post-savepoint health check ---")
try:
    n = Article.sudo().search_count([])
    print(f"count works: {n}")
except Exception as e:
    print(f"count failed: {type(e).__name__}: {str(e)[:140]}")

# T7d202 second try
print()
print("--- _try #2 ---")
existing_code = a.code
try:
    with env.cr.savepoint():
        a3 = _new_article(name="explicit dup", code=existing_code)
        print(f"unexpected create OK: {a3.id}")
except Exception as e:
    print(f"err: {type(e).__name__}: {str(e)[:140]}")

env.cr.rollback()
