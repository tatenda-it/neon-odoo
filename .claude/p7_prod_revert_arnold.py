"""Part 1 -- revert Arnold M. Safety-gated."""
u = env["res.users"].search(
    [("login", "=", "arnold.m@neonhiring.co.zw")])
print(f"Found user: id={u.id}, login={u.login}, name={u.name}")
print(f"Created: {u.create_date}")

assert len(u) == 1, "Expected exactly 1 Arnold M user"
assert u.id == 22, f"Expected uid=22, got {u.id} -- STOP"

# Check for FK references that would block unlink.
referencing_records = []
for model_name in [
    "res.partner", "mail.message", "res.users.log",
    "ir.attachment",
]:
    if model_name in env:
        try:
            count = env[model_name].sudo().search_count(
                [("create_uid", "=", u.id)])
            if count > 0:
                referencing_records.append((model_name, count))
        except Exception as e:
            print(f"  (skip {model_name}: {type(e).__name__})")

if referencing_records:
    print()
    print("FK references from Arnold:")
    for m, c in referencing_records:
        print(f"  {m}: {c} records")

partner = u.partner_id
print(f"\nPartner attached: id={partner.id}, name={partner.name}")

# Attempt unlink. Standard Odoo behavior: res.users.unlink()
# cascades to the partner if no other model references it.
try:
    u.unlink()
    env.cr.commit()
    print(f"Arnold M (uid=22) unlinked from prod")
except Exception as e:
    env.cr.rollback()
    print(f"unlink raised {type(e).__name__}: {e}")
    print("Falling back to deactivation (active=False)...")
    u.sudo().write({"active": False})
    env.cr.commit()
    print(f"Arnold M (uid=22) deactivated; record retained for FK integrity")

# Verify.
verify = env["res.users"].sudo().with_context(
    active_test=False).search(
    [("login", "=", "arnold.m@neonhiring.co.zw")])
if not verify:
    print("Verified: arnold.m@neonhiring.co.zw no longer exists in prod")
else:
    print(f"User still exists (likely deactivated): "
          f"uid={verify.id}, active={verify.active}")
