"""Idempotent SQL ALTER TABLE for the cross-module FK.
Same logic as the 17.0.1.3.1 migration; runs here because
fresh install does NOT trigger migrations and the
forward-string FK creation was skipped at neon_training
table-init time (booking model not yet registered).
"""
env.cr.execute("""
    SELECT 1
      FROM pg_constraint
     WHERE conrelid = 'neon_training_certification'::regclass
       AND contype = 'f'
       AND conname =
           'neon_training_certification_external_booking_id_fkey'
""")
if env.cr.fetchone():
    print("FK already present; no-op.")
else:
    env.cr.execute("""
        ALTER TABLE neon_training_certification
          ADD CONSTRAINT
            neon_training_certification_external_booking_id_fkey
          FOREIGN KEY (external_booking_id)
          REFERENCES neon_external_training_booking(id)
          ON DELETE SET NULL
    """)
    env.cr.commit()
    print("FK added with ON DELETE SET NULL.")

# Re-verify
env.cr.execute("""
    SELECT conname, pg_get_constraintdef(oid)
      FROM pg_constraint
     WHERE conrelid = 'neon_training_certification'::regclass
       AND contype = 'f'
       AND conname =
           'neon_training_certification_external_booking_id_fkey'
""")
row = env.cr.fetchone()
print(f"verify: {row}")
