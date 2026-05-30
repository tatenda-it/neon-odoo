"""Try flush=False on the savepoint."""
Article = env["neon.kb.article"]
Users = env["res.users"]


u_author = Users.sudo().search(
    [("login", "=", "p7d_m2_author")], limit=1)
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


a = _new_article(name="T7d200 first")
print(f"a.id={a.id}, a.code={a.code!r}")

# Try with flush=False
print()
print("--- savepoint(flush=False) #1 ---")
try:
    with env.cr.savepoint(flush=False):
        a2 = _new_article(name="Dup", code="t7d200-first")
except Exception as e:
    print(f"err: {type(e).__name__}: {str(e)[:120]}")

# Health check
try:
    n = Article.sudo().search_count([])
    print(f"count: {n}")
except Exception as e:
    print(f"count failed: {type(e).__name__}")

env.cr.rollback()
