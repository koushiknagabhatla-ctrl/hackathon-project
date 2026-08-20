# 0009 — Human approval for public-impact action

**Status:** Accepted

## Context
A public alert cannot be unsaid. A wrong evacuation advisory moves people into
danger and burns the credibility that makes the next one work. The 2024
Budameru event is the reference case: the cost of a late alert and the cost of
a wrong alert are both measured in lives, and only a person holding statutory
authority may weigh them.

## Decision
Public impact escalates the tier, and the tier compels a human.

- `core/risk.py` gives `notify_public` a base tier of **R4**, and
  `public_facing=True` is an escalation input for every other action class.
  The escalation cap is R4 — escalation can never manufacture an R5.
- `DUAL_CONTROL` requires **two distinct unexpired approvals** at R4/R5. Not
  two clicks: `valid_approvals()` de-duplicates by `approver_id` and drops any
  approval whose `expires_at` has passed.
- `REVERSIBILITY_REQUIRED` forces a named human to accept irreversibility above
  R3. `alert.publish_cap` is registered `reversible=False` with the reason on
  the manifest: "a published alert can only be superseded, never unsaid".
- `verification_method` for `alert.publish_cap` is `human_confirmation`, not
  `readback`. The machine cannot mark a public alert verified by reading its
  own database; a person confirms it went out.
- The `approval` row records `approver_id`, `approver_authority`, `rationale`,
  `decided_at`, `expires_at` and `dual_control_of`. Authority is recorded
  because in India the alerting authority is statutory (see
  `docs/compliance-map.md`) — the system drafts, an authorised official
  publishes.
- `EMERGENCY_OVERRIDE` break-glass requires a reason code, and at R4/R5 a
  second approver who is **not** the requesting principal.
- The gateway re-checks approvals at execution time (step 10) against
  re-computed live inputs. An approval granted at R3 does not authorise an
  action that is R4 by the time it runs.

## Consequences
- Latency on public action is deliberate and bounded by human availability.
  This is a design property, not a bug, and the runbook for a genuinely urgent
  alert is a break-glass with two named people, not an autonomous path.
- Approval expiry means an approval left open overnight does not authorise a
  morning execution.
- Cost: an operator cannot self-approve their own R4. Staffing must provide two
  qualified approvers, which is an operational commitment a pilot city has to
  make explicitly.

## Earned-complexity trigger
Revisit when **more than ~20 approvals/hour** are required in a live event —
human approval becomes the bottleneck and the answer is narrower pre-authorised
action classes with tight preconditions, reviewed and signed off in advance,
not a lower tier for the same action. Revisit also when a second jurisdiction
with a different authority chain joins (ADR 0019): approver authority becomes a
per-jurisdiction mapping rather than a free-text column.
