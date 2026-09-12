# Investigation E2E process — TEST-ORC-SCHEMA-004

## Request acceptance

- Endpoint: `POST /investigate`
- Request ID: `TEST-ORC-SCHEMA-004-LATEST`
- HTTP status: `200`
- Duration: `49583.63 ms`
- Subject: `message / MSG-0901`
- Detection policy: `detection / baseline-v1`
- Input passed the live FastAPI `InvestigationRequest` validation.

## Orchestrator and specialist sequence

1. Orchestrator selected `chat` to inspect `MSG-0901`, the conversation context,
   the external URL, and both participants.
2. `chat` called three tools through Agent Gateway, in this order:
   `get_evidence_records`, `get_account_activity`, and
   `get_virustotal_reputation` for the exact URL.
3. VirusTotal returned `found=false` with the message that no existing report was
   found and that this is not a harmless verdict. It did not submit a new scan.
4. `chat` returned four investigated item scores and recommended checking the
   external page and the platform's official collection-setting flow.
5. Orchestrator selected `order` to check whether the claimed collection-setting
   problem was supported by transaction, payment, fulfilment, refund, or dispute
   records.
6. `order` used the validated evidence already in the ledger and returned five item
   scores. It found an existing delivered transaction but no platform record that
   supported the claimed collection-setting problem.
7. Orchestrator selected `marketplace_info` to check whether seller, listings,
   products, and reports supported a repeated marketplace-level pattern.
8. `marketplace_info` used the validated evidence and called
   `get_subject_association_seeds` and `get_account_commerce_links`. It returned three
   item scores and found `RPT-0901`, whose report reason matched the off-platform
   verification behavior.
9. The three specialist aggregates were combined deterministically. The resulting
   fraud score was `0.527764017113`.
10. The hard maximum of three specialist calls was reached, so the stop reason was
    `budget_exhausted`.
11. Orchestrator synthesized the final Traditional Chinese `summary`; the application
    assembled and validated the complete `InvestigationResult` response.

## Usage

- Specialist calls: `3`
- Orchestrator calls: `4` (three planning calls and one final report call)
- Tool calls: `5` (`chat=3`, `order=0`, `marketplace_info=2`)
- Investigation steps: `11`
- Tokens: `73935`
- Total-token cap: disabled (`max_tokens=0`)

## Output

- Verdict: `suspicious`
- Confidence: `0.055528034226`
- Findings: `11`
- Evidence records: `35`
- Agents invoked: `chat`, `order`, `marketplace_info`
- Stop reason: `budget_exhausted`
