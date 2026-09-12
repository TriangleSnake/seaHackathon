# Evaluation Framework

This package answers one question with fixed, deterministic rules: is a candidate
policy better than the current baseline when both run on the same cases?

## Architecture

```text
shared EvaluationRequest
        |
        v
EvaluationService -- trusted EvaluationPlanResolver
        |             (policy type + baseline/candidate artifacts)
        v
EvaluatorRouter
        |
        +-- detection ------> DetectionPolicyEvaluator (implemented)
        +-- scoring --------> explicit unsupported placeholder
        +-- exploration ----> explicit unsupported placeholder
        +-- investigation --> explicit unsupported placeholder
        +-- association ----> explicit unsupported placeholder
        |
        v
flexible PolicyEvaluationOutcome
        |
        v
shared EvaluationResult adapter
```

`EvaluationPlanResolver` is intentionally a trusted boundary. The current shared
`EvaluationRequest` identifies a candidate and baseline defense version, but does
not identify the target policy type or either executable policy artifact. A future
registry integration should implement this interface; those missing fields are not
added to the shared schema here.

The generic outcome stores policy-native numeric maps. Detection's precision and
recall model therefore does not constrain future policy evaluators internally.
The final adapter is where compatibility with today's detection-oriented shared
`EvaluationResult` is enforced.

## Detection evaluation

`DetectionPolicyEvaluator` receives a `DetectionRunner` capability. Its runner sees
only immutable, label-free `DetectionInput`; ground truth remains inside the
evaluator. `HttpDetectionRunner` executes the requested policy version through the
Detection service's `POST /detect` endpoint. Configure `DETECTION_URL` and optional
`DETECTION_TIMEOUT_SECONDS`; neither host nor port is embedded in the adapter.

Requested checks are fixed when the runner is constructed, so baseline and
candidate runs use identical checks. Each request includes the exact resolved
policy version and only these fields:

```json
{
  "subject": {"type": "account", "id": "ACC-0001"},
  "requested_checks": ["rule_based", "anomaly"],
  "policy_ref": {"type": "detection", "version": "baseline-v1"},
  "trigger_context": {
    "source": "api",
    "reason": "baseline_candidate_comparison"
  }
}
```

Case facts, labels, expected outcomes, dataset phase metadata, and gates never cross
this boundary. Successful responses must be valid shared `DetectionResult` objects,
must return the requested subject, and must include an
`X-Detection-Policy-Version` header exactly matching the requested version. This
header is required for clean (`detected=false`) results too. HTTP, policy lookup,
transport, timeout, malformed response, subject mismatch, and policy trace failures
raise execution errors rather than becoming clean decisions. Evaluator-originated
calls use trigger source `api`; the reason retains the evaluation-specific baseline
and candidate comparison semantics.

Evaluator metric tests still use the clearly named `FixtureRuleDetectionRunner` so
they remain deterministic and do not require a live Detection service. HTTP runner
tests inject a mock transport.

The evaluator calculates:

- precision, recall (when labelled positives exist), and F1 (when recall exists)
- false-positive count and rate
- trigger volume
- new fraud hits, fraud hits lost, additional/removed false positives
- precision, recall, F1, false-positive, and trigger-volume deltas

Runner failure makes `implementation_valid` false. Passing execution alone does not
pass effectiveness gates: a runnable candidate may still return `status: failed`.
A baseline runtime failure raises an evaluation error because no valid comparison
can be made.

## Fixed gates

Temporary hackathon gates live in
`config/hackathon_detection_gates.json`. They are loaded by trusted evaluator
composition code and injected through `DetectionGateProvider`. Although the shared
request permits a `thresholds` object, caller-provided thresholds are never placed
in an `EvaluationJob` and cannot change pass/fail behavior.

These values are fixtures, not production policy. Replace them through trusted
deployment configuration after the team agrees on production thresholds.

## Dataset separation

`build`, `validation`, and `holdout` retain their shared-schema names. One result
may aggregate multiple dataset refs only when every ref belongs to the same phase;
mixing phases is rejected because the current result schema cannot preserve
per-phase metrics.

- `EvaluationDatasetReader` is the private evaluator capability and may load holdout.
- `BuilderDatasetReader` strips labels from build/validation data.
- `BuilderDatasetReader` rejects holdout before the underlying source is opened.
- `EvaluationService` returns only aggregate metrics and failure information, never
  cases or labels.

This is an access-boundary design, not hardened infrastructure. Production storage
and authorization remain integration work.

## Evaluator-owned message manifests

`ManifestDatasetSource` resolves an exact `DatasetRef` through an explicit path
allowlist. It does not scan directories, preload files, or cache labelled rows.
Each JSON manifest declares its own ref and contains strict case records with:

- `case_id`, `subject_type`, and `subject_id`
- `simulation_time` and `scenario_name`
- evaluator-private `is_fraud` and `label_provenance`
- a `validation` or `holdout` split

Unknown or missing fields, duplicate case IDs, unsupported subject types, naive or
invalid timestamps, inconsistent snapshots, and ref/split mismatches are rejected.
The bundled validation and holdout manifests use real message IDs from the seeded
Environment scenario `taiwan-marketplace-20260912` at
`2026-09-10T12:00:00+08:00`.

Their `synthetic-scenario/manual-adjudication` labels are evaluator-only hackathon
fixtures. They are not runtime Detection truth and must not be copied into the
Environment database, Detection requests, or builder-facing APIs. A manifest case
becomes a `DetectionInput` containing only its case and subject identity; the
Detection runtime is responsible for resolving observable facts from Environment.

The validation split intentionally includes `MSG-0916`, `MSG-0002`, and
`MSG-0009`. Candidate v1's broad `付款` phrase can therefore expose one new fraud
hit and both additional false positives during validation, fail the current
maximum-one-additional-false-positive gate, and drive revision without consulting
holdout. Holdout retains separate fraud and clean controls that are not needed to
discover or tune the v1-to-v2 change.

## Environment snapshot guard

A manifest-backed evaluation requires an injected `EnvironmentSnapshotGuard`.
Immediately before policy execution it reads the existing Environment overview,
confirms that the scenario and simulation time match the manifest, and records the
overview's snapshot identity. In a `finally` block after policy execution it reads
the overview again and requires the full identity, including `updated_at` when
available, to be unchanged. Missing or malformed overview data and any mismatch
fail closed without changing the shared `EvaluationResult` schema.

This is an operational replay guard, not a distributed lock. The overview source
used for the demo must point at a dedicated, isolated evaluator Environment
database already set to the manifest time. Evaluator code never advances, resets,
or otherwise mutates Environment, and the shared/default database must not be used
for evaluation-time clock changes. Tests use fakes only.

## Plan resolution status

The current CandidatePolicy registry and DefenseVersion repository can resolve the
baseline and candidate policy versions, but they do not store validation or
holdout dataset bindings. They are also process-local today. A dataset-aware
production `EvaluationPlanResolver` is therefore intentionally not inferred here;
it needs a trusted persisted dataset binding or catalog contract first. The two
manifest refs remain evaluator-owned configuration in the meantime.

## Tests

From the repository root:

```bash
python3 -m unittest discover -s services/evaluator/tests -v
```

The original deterministic account fixture remains for evaluator behavior and gate
regression coverage. Separate manifest and snapshot tests cover real Environment
message IDs, strict parsing, label isolation, validation/holdout loading, timezone
normalization, matching snapshots, and fail-closed snapshot changes.

## Current shared-schema limitations

- `EvaluationRequest` has no policy identifier or candidate policy artifact ref.
- `EvaluationResult` has one aggregate metrics block and cannot report per-dataset
  or per-phase results.
- Metrics are detection-oriented; precision and false-positive rate are mandatory,
  while only recall and F1 may be null.
- `thresholds` is caller-controlled in the request, so it cannot safely be the
  authority for candidate pass/fail gates.
- The result cannot distinguish evaluator infrastructure failure from an invalid
  candidate implementation without conventions around `implementation_valid` and
  `failure_reasons`.
