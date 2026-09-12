# Detection Service Implementation Plan

1. Add failing contract and API tests for health, readiness, `/detect`, strict
   validation, unknown subjects, and detector filtering.
2. Implement Detection Pydantic models that mirror the shared JSON schemas.
3. Add a read-only PostgreSQL repository using replay-aware Environment views.
4. Implement deterministic rule and anomaly detectors with evidence deduping.
5. Add an opt-in OpenAI binary-classifier adapter and a disabled ML placeholder.
6. Wire the FastAPI application, request IDs, settings, and error responses.
7. Add Docker image, Compose service, environment variables, and service README.
8. Run unit, contract, Compose, and representative seed-data verification.
