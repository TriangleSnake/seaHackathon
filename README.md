# Fraud Intelligence System — Shared Schemas v0.2

Use JSON Schema Draft 2020-12.

Recommended REST contracts:

- POST /detect
  - request: detection.schema.json#/$defs/DetectionRequest
  - response: detection.schema.json#/$defs/DetectionResult
- POST /investigate
  - request: investigation.schema.json#/$defs/InvestigationRequest
  - response: investigation.schema.json#/$defs/InvestigationResult
- POST /patrol/run
  - request: patrol.schema.json#/$defs/PatrolRequest
  - response: patrol.schema.json#/$defs/PatrolResult
- POST /associate
  - request: association.schema.json#/$defs/AssociationRequest
  - response: association.schema.json#/$defs/AssociationResult
- POST /evolution/evaluate
  - request: evolution.schema.json#/$defs/EvolutionRequest
  - response: evolution.schema.json#/$defs/EvolutionResult
- POST /build
  - request: candidate.schema.json#/$defs/BuildRequest
  - response: candidate.schema.json#/$defs/CandidateResult
- POST /evaluate
  - request: evaluation.schema.json#/$defs/EvaluationRequest
  - response: evaluation.schema.json#/$defs/EvaluationResult
- POST /governance/review
  - request: governance.schema.json#/$defs/GovernanceRequest
  - response: governance.schema.json#/$defs/GovernanceResult

Dashboard mainly consumes the service schemas. Its own schema only defines mutation actions:
case review, appeal, and policy update.

Tracing recommendation:
use HTTP `X-Request-ID` and W3C `traceparent` headers instead of repeating trace metadata in every JSON body.


## v0.2 corrections

- Detection does **not** calculate the system fraud score.
  - It only emits `detected`, `triggers`, raw detector outputs, and evidence.
- Investigation does **not** define its own thresholds or budget.
  - It receives only an immutable `scoreboard_config_ref`.
- `scoreboard.schema.json` is owned by the System/control plane.
  - It defines scoring policy version, fraud/normal thresholds, agent/tool/step/token/cost budgets, stopping rules, and agent priorities.
- Investigation returns the resulting `ScoreboardState` for auditability/reproducibility.
