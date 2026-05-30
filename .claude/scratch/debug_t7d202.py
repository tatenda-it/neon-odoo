"""Reproduce T7d202 failure mode in isolation."""
Article = env["neon.kb.article"]
Cat = env["neon.kb.category"]
Users = env["res.users"]

u_author = Users.sudo().search([("login", "=", "admin")], limit=1)
audio = env.ref("neon_kb.category_audio")


a = Article.sudo().create({
    "name": "T7d200 first",
    "category_id": audio.id,
    "body": "<p>Body</p>",
    "author_id": u_author.id,
})
print(f"a.id={a.id}, a.code={a.code!r}")

# Try duplicate via savepoint
try:
    with env.cr.savepoint():
        a2 = Article.sudo().create({
            "name": "Dup",
            "code": a.code,
            "category_id": audio.id,
            "body": "<p>Body</p>",
            "author_id": u_author.id,
        })
        print(f"unexpected create OK: {a2.id}")
except Exception as e:
    print(f"err in savepoint: {type(e).__name__}: {str(e)[:120]}")

# Can we do another query after?
try:
    n = Article.sudo().search_count([])
    print(f"after savepoint, count works: {n}")
except Exception as e:
    print(f"after savepoint, count FAILED: {type(e).__name__}: {str(e)[:120]}")

env.cr.rollback()
