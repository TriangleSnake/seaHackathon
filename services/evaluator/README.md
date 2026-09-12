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
evaluator. The included `ContractDetectionRunner` adapts the existing shared
`DetectionRequest`/`DetectionResult` shape to this capability without adding a
second detection engine.

The repository has no Detection runtime yet. Tests therefore use the clearly named
`FixtureRuleDetectionRunner`, not production detection logic.

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

## Tests

From the repository root:

```bash
python3 -m unittest discover -s services/evaluator/tests -v
```

The deterministic fixture uses fields already present on the repository's
`accounts` table: `status`, `activity_score`, `kyc_status`, and `bot_check_score`.
The baseline catches two obvious fraud cases. Candidate A catches two new frauds
but adds four false positives and fails. Candidate B retains both new hits, narrows
the noisy signal to one false positive, and passes the temporary gates.

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
