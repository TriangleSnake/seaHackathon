# Pattern Synthesis

Pattern Synthesis is the boundary between case-level `InvestigationResult` output
and the existing pattern-level `PatternSpec` consumed by Evolution. It receives an
analyst or future clustering component's already-grouped suspicious/fraud cases,
optional normal counterexamples, and a read-only snapshot of active defense
capabilities. It does not discover clusters, change Investigation, or mutate defense.

## Runtime flow

```text
grouped InvestigationResult(s) + read-only defense context
  -> OpenAI Responses API structured semantic draft
  -> deterministic investigation/provenance validation
  -> runtime-owned deterministic pattern_id
  -> shared pattern.schema.json validation
  -> PatternSynthesisResult.pattern_spec
  -> EvolutionHandoff -> EvolutionRequest.pattern_spec
```

The semantic draft carries evidence refs on every observed signal and behavior
step. Those internal fields are validated and retained in the result's provenance
manifest, then projected away to keep `PatternSpec` exactly compatible with the
existing shared schema. Literal signals are accepted only when their exact string
occurs in cited Investigation evidence.

`current_defense_gap` must cite one or more supplied `capability_id` values in the
internal draft. The validator checks those references. The prompt limits the model
to describing missing behavior; evaluator thresholds, gates, governance decisions,
promotion, and policy mutation are absent from the draft/output contracts.

## Request shape

- `synthesis_id`
- `candidate_results`: one or more stable InvestigationResults with `fraud` or
  `suspicious` verdicts
- `counterexample_results`: optional InvestigationResults with `normal` verdict
- `active_defense_version`: existing `DefenseVersionRef`
- `active_policy_refs`: active shared `PolicyRef` values
- `policy_capability_summary`: named, read-only capabilities and constraints
- optional `pattern_hint` and `grouping_reason` (context only, never evidence)

A single candidate is accepted at the boundary but deterministically returns
`NO_PATTERN`; a reusable emitted pattern requires two supporting cases and at least
one signal grounded across multiple cases.

## Response shape

- `status`: `PATTERN` or `NO_PATTERN`
- `reason`
- `pattern_spec`: schema-valid shared PatternSpec only for `PATTERN`
- `provenance`: per-signal/per-step evidence and case mapping plus defense context
  refs only for `PATTERN`

Hallucinated case, evidence, capability, literal, or cross-case support fails closed
with an explicit synthesis error. Nothing is silently repaired.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Environment variables:

- `OPENAI_API_KEY` (required for `/ready` and real synthesis)
- `PATTERN_SYNTHESIS_OPENAI_MODEL` (falls back to `OPENAI_MODEL`, then
  `gpt-5.4-mini`)
- `OPENAI_TIMEOUT_SECONDS` (default `30`)
- `PATTERN_SYNTHESIS_MAX_OUTPUT_TOKENS` (default `3000`)
- `SHARED_SCHEMA_DIR` (only needed when schemas are outside the repository layout)

Build the container from repository root so it can copy immutable shared schemas:

```bash
docker build -f services/pattern-synthesis/Dockerfile -t pattern-synthesis .
```

## Test

From this directory:

```bash
python3 -m pytest -q
python3 -m compileall -q app tests scripts
```

Tests use a deterministic fake and never call OpenAI.

## Optional real-agent smoke

Provide a JSON request containing real, schema-valid InvestigationResult samples:

```bash
OPENAI_API_KEY=... python3 scripts/live_smoke.py /path/to/request.json
```

The script prints no key, validates every input InvestigationResult, and emits only
a validated result. Exit code `2` means the live smoke was not run because no key
was configured.

## Full System Integration

Call `POST /synthesize`. On `status=PATTERN`, pass the same request and result to
`EvolutionHandoff.build_request(..., system_performance=...)`; the returned object
is validated against `evolution.schema.json#/$defs/EvolutionRequest` and places the
PatternSpec at `pattern_spec`. On `NO_PATTERN`, do not trigger Evolution. A future
Pattern Learning/clustering component only needs to construct the grouped request;
this component deliberately does not own grouping.
