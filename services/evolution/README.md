# Evolution and version lifecycle

This package contains the deterministic Member 4 Evolution Core plus a real
OpenAI-backed planner. The runtime keeps state transitions, retry accounting,
IDs, versioning, evaluator decisions, and governance outside the model. The
model diagnoses policy gaps and proposes what behavior should change and why.

It does not implement ConfigBuilder/Codex execution, Detection HTTP execution,
publishing, deployment, governance, persistent storage, or rollback.

## Layers

- `app/domain.py`: internal models for diagnosis, one-policy proposals,
  CONFIG mutation intent, revision feedback, candidates, defense snapshots,
  and append-oriented attempt history.
- `app/ports.py`: replaceable planner, policy adapter, builder, repository, and
  version-naming boundaries.
- `app/planner.py`: OpenAI Responses structured-output planner, strict response
  validation, Detection CONFIG capability summary, and protected-boundary
  checks.
- `app/repositories.py`: candidate-policy registry plus append-oriented in-memory
  policy and defense version storage.
- `app/state_machine.py`: the only authority that changes EvolutionRun state.
- `app/capabilities.py`: one shared policy adapter registry and CONFIG/CODE
  builder routing.
- `app/config_builder.py`: the real Detection CONFIG builder, dual policy
  validation, and environment-backed local assembly.
- `app/code_builder.py`: the thin adapter from CODE directives to the isolated
  real Codex runtime under `services/codex-builder`, preserving CandidateResult
  and the existing candidate registry flow.
- `app/artifacts.py`: deterministic atomic publication of immutable JSON
  artifacts.
- `app/versioning.py`: deterministic single-policy composition, evaluation
  linkage, formal numbering, promotion, and activation.
- `app/lifecycle.py`: post-build EvolutionRun transitions around evaluation,
  governance authorization, promotion, and activation.
- `app/adapters.py`: mapping between internal models and existing shared
  contracts without changing those contracts.
- `app/orchestrator.py`: deterministic flow from trigger through candidate
  composition plus evaluation-driven autonomous revision.
- `tests/fakes.py`: clearly labelled deterministic fakes used only by tests.

## Runtime planner

`OpenAIEvolutionPlanner` makes separate structured-output calls for diagnosis
and proposal. Model output is validated into `DiagnosisResult`, `PolicyGap`,
`PolicyMutationIntent`, and `PolicyChangeProposal`. Proposal IDs, the base
defense version, target-policy consistency, and provenance are supplied or
checked by runtime code; the model cannot set production versions or artifact
paths.

The current default capability summary exposes every field in the Detection
policy schema. For example, a planner may emit a behavioral CONFIG intent such
as:

```json
{
  "operation": "append_unique",
  "path": "rule_based.chat_request_phrases",
  "values": ["a phrase inferred from the supplied PatternSpec"],
  "rationale": "why this change addresses the diagnosed gap"
}
```

This is carried as `BuildRequest.config.mutation_intent` for the separately
owned ConfigBuilder. It contains no code or policy-file path. A runtime may
inject a fresher capability summary when constructing the planner.

The backend reads `OPENAI_API_KEY` and uses `EVOLUTION_OPENAI_MODEL`, falling
back to the repository-wide `OPENAI_MODEL` and then `gpt-5-mini`. API keys are
never embedded in proposals or source. Malformed JSON, schema-invalid output,
refusals/incomplete responses, unsupported mutation fields, and API failures
raise controlled `PlannerError` subclasses; no fallback proposal is invented.

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

## Revision loop

`EvolutionOrchestrator.handle_evaluation()` links an aggregate validation result
and performs the next planner/build attempt when appropriate:

```text
VALIDATING
  -> PASS: FROZEN
  -> FAIL with retry: REVISING -> RESOLVING -> BUILDING -> VALIDATING
  -> FAIL without retry: REJECTED
```

One failed validation consumes exactly one retry and increments the iteration
before the planner receives `RevisionFeedback`. Every `EvolutionAttempt` keeps
its proposal and candidate ID/version, with validation and holdout evaluation
lineage in distinct fields. Candidate registry and defense-version history
retain the rejected snapshot as well, so candidate IDs and failed attempts are
never overwritten.

Only validation aggregates are returned to the planner: failure reasons,
regressions, baseline/candidate metrics, and incremental value. Holdout rows,
labels, individual cases, caller-supplied thresholds, evaluator gates, and
governance rules have no `RevisionFeedback` representation. Holdout failure is
terminal and is never used for planner revision.

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

## Detection CONFIG candidates

The implemented CONFIG surface is intentionally narrow. A
`PolicyChangeProposal` must identify its exact `base_policy_version` and carry
typed `DetectionPolicyChange` operations. Currently the only accepted path is
`rule_based.chat_request_phrases`, with exact-value `add` and `remove`
operations. A later revision can therefore remove an over-broad phrase and add
a narrower replacement without introducing a rule-expression DSL or changing
Detection's Python logic.

`DetectionPolicyCapabilityAdapter` routes supported typed changes to
`ConfigBuilder`. Unstructured, role-aware, and compound Detection behavior
routes to the CODE builder, while missing capabilities remain unsupported.
`ConfigBuilder` loads the
named baseline through Detection's existing repository, validates the baseline
and candidate with both Detection's Pydantic runtime model and the shared JSON
Schema, then publishes a deterministic `DP-CAND-NNN.json`. The existing
`CandidatePolicyRegistry` allocates that non-production identity and the
existing orchestrator registers the returned `CandidateResult` and
`CandidatePolicy` once.

Local publication must be configured explicitly:

```bash
export DETECTION_CANDIDATE_POLICY_DIR=/path/to/runtime/detection-policies
```

`DETECTION_BASE_POLICY_DIR` and `DETECTION_POLICY_SCHEMA_PATH` may override the
repository-relative defaults. Paths are configuration only; no user-specific
path is embedded in the builder.

The current Detection container bakes `config/policies` into its image and does
not share this host directory. To evaluate freshly published versions without
rebuilding, runtime wiring must expose one read-only policy directory containing
both `baseline-v1.json` and candidate files at `/app/config/policies`. Mounting
a candidates-only directory there would hide the baseline, so that compose
override is intentionally left to the runtime integration step.

## Test

From `services/evolution`:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

The tests use deterministic planners and response clients; they never call the
live API.

## Optional real-planner smoke

With dependencies and `OPENAI_API_KEY` configured, run from
`services/evolution`:

```bash
python3 -m app.manual_smoke
```

The entry point creates a schema-compatible manual EvolutionRequest, invokes
the real diagnosis/proposal backend, prints the validated internal result, and
stops before ConfigBuilder or Detection integration. It is intentionally not a
CI test.
