# Governance service

This service is the deterministic trust boundary for candidate defense changes.
It answers whether a successfully built and evaluated candidate is authorized to
proceed. It never builds candidates, changes evaluation gates, creates a defense
version, promotes a version, activates production, or performs rollback.

## Decision flow

`POST /governance/review` accepts the shared `GovernanceRequest` and returns the
shared `GovernanceResult`:

1. fixed system policy checks run;
2. any failed hard gate returns `reject`;
3. a required but missing human decision returns `needs_review`;
4. an explicit human approval permits `approve` only after every system check
   passes;
5. the system decision is appended to the audit trail.

The current regression policy and default human-approval requirement are
provisional configuration supplied when `GovernanceService` is constructed.
Candidate artifacts and request extras cannot change this configuration. A
request may require additional human scrutiny, but cannot disable a requirement
set by trusted configuration.

## Human review and audit

`GovernanceService.record_human_decision` is the internal interface for an
explicit approve/reject action. It requires a reviewer identifier and appends a
separate `human_review_decision` event. No LLM or automatic path invokes it.

The initial repositories are in-memory and append-only. They are intentionally
small integration seams: replace them with durable adapters later without
changing policy evaluation. In-memory state is process-local and is not yet
production persistence.

`approved_defense_version` is always `null`. VersionManager owns version creation,
promotion, activation, numbering, stale-base handling, and rollback.

## Run tests

```bash
python -m pytest
```
