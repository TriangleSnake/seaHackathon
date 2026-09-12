# Evolution architecture skeleton

This package is the deterministic Member 4 Evolution Core. It proves the
architecture with test-only fakes; it does not implement fraud policy logic,
LLM diagnosis, Codex execution, evaluation, governance, promotion, or rollback.

## Layers

- `app/domain.py`: internal models for diagnosis, one-policy proposals,
  capability directives, candidates, defense snapshots, and run history.
- `app/ports.py`: replaceable planner, policy adapter, builder, repository, and
  version-naming boundaries.
- `app/state_machine.py`: the only authority that changes EvolutionRun state.
- `app/capabilities.py`: one shared policy adapter registry and CONFIG/CODE
  builder routing.
- `app/versioning.py`: deterministic single-policy replacement in a candidate
  defense snapshot.
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
   result so VersionManager can compose the candidate snapshot.
4. Version numbering policy is undecided. `CandidateVersionFactory` is a port;
   the test fake uses an explicit test-only name.
5. Evaluation and Governance adapters are deferred until their implementation
   slice; their shared schemas remain untouched.

## Test

From `services/evolution`:

```bash
python3 -m unittest discover -s tests -v
```
