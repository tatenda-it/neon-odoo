# 'system' sign_off_authority for LMS auto-issuance

Phase 7e M9 extended Phase 7a M7's `sign_off_authority`
Selection with a new `'system'` value. Currently used by 8
LMS-driven cert types (7 sub-certs + the Neon Technical
capstone).

## Behaviour

`_resolve_verify_authority_partners` short-circuits to an
empty `res.partner` recordset when a cert type has
`sign_off_authority = 'system'`. There is no human verifier
in the loop — the LMS workflow calls `Cert.sudo().create(...)`
directly with `verified_by_id = SUPERUSER_ID` and
`verified_at = fields.Datetime.now()`, plus the cert is
created already in state `'active'` rather than
`'awaiting_verification'`.

The audit trail still exists: the cert record carries
`create_uid`, `create_date`, and the chatter on creation. The
issuing track.completion or enrollment record also chattters
the cert id via the M12 notification stubs (Phase 9 will route
those to learner channels).

## When to use 'system'

- Cert is earned via verifiable system criteria (quiz scores,
  module completion percentages, scenario sign-off counts) —
  no human judgment required at issuance time.
- The criteria themselves act as the verification — a learner
  cannot trip the issuance trigger without satisfying the rule
  set.
- Audit coverage is achieved via chatter on cert creation +
  the workflow's own log entries (`_logger.info` calls in
  `_issue_sub_cert` and `_check_and_advance_to_certified`).

## When NOT to use 'system'

- Cert requires human judgment (e.g., a practical skills
  assessment that needs a Lead Tech to observe).
- Cert references an external authority (off-site fire safety
  training, an electrical-licence exam) — the external pass
  itself is the verification; Neon merely records it.
- Cert is high-stakes safety-critical and policy requires
  redundant verification (`'lead_tech'` or `'superuser'`
  authority is the right choice there).

## Resolver short-circuit (M9 implementation)

```python
def _resolve_verify_authority_partners(self):
    self.ensure_one()
    if self.sign_off_authority == "system":
        # No human verifier -- LMS workflow issues directly.
        return self.env["res.partner"]
    if self.sign_off_authority == "external":
        return self.env["res.partner"]
    # ... lead_tech / superuser branches resolve to partners
```

The `'external'` branch also returns empty — the difference is
that `'external'` certs still need a human to record the pass
from outside Neon's system, while `'system'` certs are
machine-issued and never enter the verification queue.

## Cross-references

- Source pattern: [[reference_neon_notification_stub_pattern]]
  describes the M12 dispatcher that fires on sub-cert issuance
- Sign-off architecture: Phase 7a M7 (cert verification
  routing), Phase 7a M10 (verification queue UI)
- Capstone aggregator: Phase 7e M8
  (`_check_and_advance_to_certified` on enrollment)
