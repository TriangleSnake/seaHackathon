# Detection service

Detection reads the replay-visible Environment database and emits the shared
`DetectionResult` contract. It identifies signals only; Investigation owns the
fraud verdict and the system-owned scoreboard owns scoring.

## API

- `GET /health`
- `GET /ready`
- `POST /detect`

Example:

```bash
curl http://localhost:10001/detect \
  -H 'Content-Type: application/json' \
  -d '{"subject":{"type":"message","id":"MSG-0901"}}'
```

By default `/detect` runs `rule_based` and `anomaly`. To request the optional
LLM classifier:

```json
{
  "subject": {"type": "message", "id": "MSG-0901"},
  "requested_checks": ["rule_based", "llm_classifier"],
  "policy_ref": {"type": "detection", "version": "baseline-v1"}
}
```

The LLM classifier is enabled only when `OPENAI_API_KEY` is set. It requests a
single `true` or `false` token, reads both candidate log probabilities, and
triggers when normalized `P(true)` is at least the selected policy's
`llm_classifier.confidence_threshold` (default `0.60`). If either candidate is absent it abstains. The raw candidates,
probabilities, threshold, model, and response ID are returned in the trigger's
`raw_result`; they are not a system fraud score.

The default Detection model is `gpt-4.1-mini`, a non-reasoning model suitable
for the one-output-token contract. Override it with `DETECTION_OPENAI_MODEL`.

## Versioned policies

Detection policies are immutable JSON artifacts under `config/policies`. Their
format is defined by `shared/schemas/detection-policy.schema.json`. The filename
must be `<version>.json` and the internal `version` must match. A running process
caches a resolved policy, so evaluating another version never mutates the
default or previously resolved artifact.

Evaluator should hold the Environment simulation time fixed and call `/detect`
twice with the same subject and checks, changing only `policy_ref.version`:

```json
{
  "subject": {"type": "message", "id": "MSG-0901"},
  "requested_checks": ["rule_based", "anomaly"],
  "policy_ref": {"type": "detection", "version": "candidate-v1"},
  "trigger_context": {"source": "api", "reason": "evaluation:eval-001"}
}
```

A successful response remains the shared `DetectionResult` contract:

```json
{
  "detection_id": "DET-<uuid>",
  "subject": {"type": "message", "id": "MSG-0901"},
  "detected": true,
  "triggers": [
    {
      "type": "suspicious_chat_request",
      "detector": "rule_based",
      "rule_id": "RULE-CHAT-001",
      "reason": "Outbound chat asks for risky off-platform payment or verification action.",
      "raw_result": {
        "matches": ["reserved-risk-domain", "驗證頁重新開通"],
        "policy_version": "candidate-v1"
      },
      "evidence_refs": ["MSG-0901"]
    }
  ],
  "evidence": [
    {
      "id": "MSG-0901",
      "source": "environment",
      "type": "message",
      "ref_id": null,
      "observed_at": "2026-09-02T02:00:00Z",
      "data": {
        "conversation_id": "CONV-031",
        "sender_account_id": "ACC-0052",
        "recipient_account_id": "ACC-0111",
        "text": "系統顯示收款設定未完成，請到驗證頁重新開通，完成後我才能出貨。",
        "urls": ["https://verify-market.invalid/session"]
      }
    }
  ]
}
```

An unknown or unsafe version returns HTTP `404` with error code
`policy_not_found`; it never falls back to the active/default policy.

Each request reads one PostgreSQL repeatable-read snapshot and captures its
Environment simulation time as `as_of`. Anomaly windows use `(as_of - window,
as_of]`, exclude undated events, and expire old activity. Login diversity is
computed per account; security-change correlations require the same account and
a successful novel-device login. Trigger raw results include `as_of`.

An empty check list, unimplemented ML check, or unconfigured LLM check returns
HTTP 422 `check_unavailable`. Missing LLM text or unusable classifier output
(including missing binary logprobs) returns HTTP 422 `check_inconclusive` with
the reason. A valid binary probability below 0.6 is a completed, non-triggering
decision, not an execution failure. Incomplete multi-check requests return an
error rather than a partial clean result. The successful DetectionResult schema
is unchanged; error responses must not be counted as negative predictions.

## Local run

```bash
docker compose up -d --build detection
docker compose exec -T postgres \
  psql -U fraud -d fraud_intelligence \
  -c "SELECT set_simulation_time('2026-09-10 12:00:00+08');"
curl http://localhost:10001/ready
```

Run isolated unit tests:

```bash
docker build --target test -t fraud-detection-test services/detection
docker run --rm fraud-detection-test
```
