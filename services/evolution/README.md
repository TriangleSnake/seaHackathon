# Evolution and version lifecycle

This package is the deterministic Member 4 Evolution Core. It proves the
architecture with test-only fakes and implements the repository-level normal
version lifecycle. It does not implement fraud policy logic, LLM diagnosis,
Codex execution, deployment infrastructure, persistence, or rollback.

## Layers

- `app/domain.py`: internal models for diagnosis, one-policy proposals,
  capability directives, candidates, defense snapshots, and run history.
- `app/ports.py`: replaceable planner, policy adapter, builder, repository, and
  version-naming boundaries.
- `app/repositories.py`: candidate-policy registry plus append-oriented in-memory
  policy and defense version storage.
- `app/state_machine.py`: the only authority that changes EvolutionRun state.
- `app/capabilities.py`: one shared policy adapter registry and CONFIG/CODE
  builder routing.
- `app/versioning.py`: deterministic single-policy composition, evaluation
  linkage, formal numbering, promotion, and activation.
- `app/lifecycle.py`: post-build EvolutionRun transitions around evaluation,
  governance authorization, promotion, and activation.
- `app/adapters.py`: mapping between internal models and existing shared
  contracts without changing those contracts.
- `app/orchestrator.py`: deterministic flow from trigger through candidate
  composition.
- `tests/fakes.py`: clearly labelled deterministic fakes used only by tests.

## Contract mismatches intentionally isolated

1. `EvolutionRequest.pattern_spec` is optional, while `BuildRequest.pattern_spec`
   is required. A change diagnosis without a PatternSpec terminates internally
   as `NEEDS_MORE_EVIDENCE`; the external EvolutionResult maps this to
   `action: no_change` with an explanatory reason.
2. Shared `EvolutionResult` cannot represent `NEEDS_MORE_EVIDENCE` or
   `UNSUPPORTED`. Those remain internal lifecycle states and are mapped to the
   closest external contract without modifying the schema.
3. Shared `CandidateResult` does not identify the resulting PolicyRef. The
   internal `BuildOutcome` carries a `CandidatePolicy` alongside the external
   result; the candidate registry joins them by `candidate_id` before
   VersionManager composes the candidate snapshot.
4. `CandidateVersionFactory` continues to supply non-production candidate names.
   Formal policy and defense numbers are allocated only during approved
   promotion using `DP/SP/EP/IP/AP-NNN` and `DV-NNN` identities.
5. Evaluation and Governance remain owners of their own shared results.
   `VersionLifecycle` consumes those results internally; governance authorizes
   promotion but never activates a defense.

## Normal lifecycle

```text
CandidateResult built
  -> registered CandidatePolicy
  -> immutable candidate DefenseVersion
  -> evaluator validation / holdout gates
  -> governance needs_review / reject / approve
  -> formal Policy + approved DefenseVersion promotion
  -> repository activation (previous active becomes retired)
```

Failed or rejected candidates do not allocate production numbers. Candidate
snapshots and every defense status transition remain in append-oriented history.

## Test

From `services/evolution`:

```bash
python3 -m unittest discover -s tests -v
```
