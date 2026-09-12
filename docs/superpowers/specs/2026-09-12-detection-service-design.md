# Detection Service Design

## Goal

Implement the repository's Detection component as a deterministic FastAPI
service that inspects Environment data and emits the shared `DetectionResult`
contract. Detection finds suspicious signals; it does not decide fraud or
calculate the system fraud score.

## API and boundaries

- `POST /detect` accepts the shared `DetectionRequest`.
- `GET /health` reports process liveness.
- `GET /ready` checks the PostgreSQL dependency.
- The service supports account, shop, product, transaction/order, and message
  subjects by resolving each subject to the relevant account and evidence.
- Every trigger references evidence IDs returned in the same response.
- Unknown subjects return `404`; dependency failures return `503`.
- Callers may select one immutable detection policy with `policy_ref`; missing
  versions fail explicitly and never fall back to another policy.

## Detectors

Policy values are config-based, immutable, versioned JSON artifacts. Rule-based
checks are explicit rules for reports, suspicious chat
language or URLs, account-access security events, and disputed payment or
delivery activity. Anomaly checks use fixed, explainable window thresholds for
login diversity, listing bursts, message bursts, payment churn, and dispute
patterns. A trigger is emitted only when a configured threshold is crossed.

The LLM classifier is opt-in: it runs only when `llm_classifier` is requested
and `OPENAI_API_KEY` is configured. It requests one `true` or `false` token,
normalizes the two candidate log probabilities, and triggers only when
`P(true) >= 0.60` by default. The threshold is configurable and should be
recalibrated once labeled validation data exists. Baseline and candidate calls
may use the same data and simulation time without changing the default policy.
Missing binary candidates
cause an abstention. Its label and log probabilities are stored only in
`raw_result`; they are not converted into a fraud score. The
`ml_classifier` enum remains contract-compatible but returns no trigger until a
model is implemented.

## Data access and time safety

Detection connects directly to PostgreSQL with a read-only repository. Event
queries use `visible_*` views so future simulated events cannot leak into a
result. Static entity tables are joined only to currently visible evidence.
SQL is fixed and parameterized; callers cannot submit SQL.

## Runtime structure

The service mirrors Investigation's FastAPI conventions while keeping domain,
repository, detector, and API responsibilities separate. Dependencies are
injected for tests. Docker Compose exposes Detection on host port `10001` and
provides `DETECTION_URL=http://detection:8000` to other services.

## Testing

Unit and API tests cover strict contract validation, clean and suspicious
subjects, requested-check filtering, evidence integrity, unknown subjects,
optional LLM behavior, health/readiness, and database failures. Integration
verification runs representative seed subjects against PostgreSQL.
