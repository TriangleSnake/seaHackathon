# Detection service

Detection reads the replay-visible Environment database and emits the shared
`DetectionResult` contract. It identifies signals only; Investigation owns the
fraud verdict and the system-owned scoreboard owns scoring.

## API

- `GET /health`
- `GET /ready`
- `POST /detect`
- `GET /policies/detection`
- `POST /policies/detection/validate`
- `POST /policies/detection/drafts`
- `POST /policies/detection/test`
- `POST /policies/detection/publish`
- `POST /policies/detection/rollback/{version}`

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

Bundled Detection policies live under `config/policies`; mutable control-plane
state lives in the shared `agent_policies` table. Their format is defined by
`shared/schemas/detection-policy.schema.json`. Each policy can select versioned
components, enable or disable them, override their configuration, and choose
whether a component failure aborts detection or is reported while processing
continues. Published versions are immutable and exactly one version can be
active. Evolution can create and test a draft without changing production,
then publish it after evaluation; rollback only changes the active pointer.

Detector implementations register by `(type, version)` and declare the evidence
they require. Detection loads the union of those requirements once, executes
the selected components, and reports each component as `completed`,
`unavailable`, or `failed` in `component_results`. This keeps policy iteration
separate from code deployment while making missing model keys or detector
versions visible instead of silently returning a clean result.

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
  "policy_ref": {"type": "detection", "version": "candidate-v1"},
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
  ],
  "component_results": [
    {
      "component_id": "marketplace-rules",
      "detector": "rule_based",
      "version": "builtin-v1",
      "status": "completed",
      "trigger_count": 1,
      "latency_ms": 0.2,
      "reason": null
    }
  ]
}
```

An unknown or unsafe version returns HTTP `404` with error code
`policy_not_found`; it never falls back to the active/default policy.

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
