# REAL Codex CODE Builder — verified demo handoff

Verified 2026-09-12. No main merge, push, activation, production policy number,
shared schema edit, evaluator-gate edit, or completed real-loop worktree edit.

## Result levels

| Claim | Evidence |
|---|---|
| UNIT PASS | Builder lifecycle 6 passed; Evolution 79 passed |
| LIVE CODEX INVOCATION | Official Linux `codex-cli 0.154.0`, exit 0 |
| CODEX BUILD PASS | 12 protected acceptance cases; 39 regression cases passed, 5 initially skipped; compile 20 files; diff check passed |
| FULL DETECTION REGRESSION | Subsequent isolated disposable-database run: 44 passed, zero skips |
| LIVE DETECTION BEFORE/AFTER | MSG-0916 false → true; 9 clean controls false → false; snapshot unchanged |
| FULL EVALUATOR INTEGRATION | **Not implemented**: evaluator identifies policy artifacts, not independent code-engine versions |
| REAL EVOLUTION AGENT → CODE | **Not run**; deterministic valid proposal/Resolver/router proof is verified |

## Requested 24-point report

1. Branch `member4-real-codex-builder`; worktree `/private/tmp/seaHackathon-member4-real-codex-builder`.
2. Exact feature and candidate base `96ab1e05c8f8d9e721816cabdf92d6fdde01e13c`.
   `origin/main` advanced to `0ff9d02dea50f98fe2c0d877639a81e95c4d371c` during the initial fetch; the requested base was retained.
3. Real runtimes available: macOS Codex 0.153.4 and official Linux ARM64 Codex 0.154.0. The final build used Linux.
4. Invocation: dedicated Docker image (official package integrity verified), readonly root and Detection mounts, two RW file overlays, separate RO exam and login mount, non-root user, dropped capabilities, namespace sandbox. `codex --ask-for-approval never [explicit permissions] exec --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check --json --color never -C <candidate-worktree> -`. No API key passed. Full non-secret argv and image ID are in build metadata.
5. Architecture: proposal → existing Resolver CODE directive → thin Evolution adapter → detached exact-base worktree → OS boundary preflight → real Codex → path/HEAD/exam checks → fresh readonly test containers → candidate commit → immutable CandidateResult/metadata. The existing registry and attempt history are reused.
6. Builder implementation files: `services/codex-builder/{Dockerfile,README.md,VERIFICATION.md,requirements.txt,requirements-dev.txt,run_hero_build.py,live_smoke.py,full_regression.py}`, `codex_builder/{__init__,models,runtime,container_runtime}.py`, `tests/test_runtime.py`, and the external acceptance file. Evolution integration: `app/{capabilities,code_builder,domain,orchestrator,ports,repositories,runtime,versioning}.py`, README and relevant tests. No shared schema changes.
7. Effective repository write grants: **only** `services/detection/app/repository.py` and `services/detection/app/detectors/rules.py`. Private container tmpfs state is disposable, not candidate output. Inner CLI permission declarations are not used as the sole write authority; readonly mounts enforce exact file boundaries.
8. Actual runtime Codex edits: exactly those two files.
9. Boundary PASS: allowed files writable; exam/service/policy files non-writable; evaluator/seed/Git/schemas absent; model-tool login reads denied. A final probe with bridge networking enabled also confirmed model-tool network connections denied. Git whitelist and protected exam hashes remained valid.
10. Actual generated diff: **79 insertions, 2 deletions**. Repository exposes time-valid participant roles for messages and background; rules add per-message seller/payment/inducement conjunction, negation guards, and a new deterministic trigger. No outer-agent edits to the generated implementation.
11. Protected acceptance: **12 passed**, including seller/payment/discount, urgency, single-signal negatives, buyer/safety negatives, SQL-backed seller/buyer/support/missing/future-role checks, and no cross-message signal combination. The outer exam was strengthened with explicit user approval before build 004; runtime Codex could not modify it.
12. Detection regression: initial build **39 passed, 5 skipped** (no DB attached). Follow-up on a fresh seed database: **44 passed**, zero skips. The disposable DB/network were removed. These tests were never directed at the frozen port-55432 database.
13. Build `build-real-codex-hero-004`; candidate `code-candidate-build-real-codex-hero-004`; candidate commit **`b6f91b243fe3268b2e66450d301b5c79d4f607eb`**. CandidateResult `status=built`, artifact `git:<commit>`, policy reference **null**. Internal `CodeCandidate` has no production policy version.
14. Deterministic valid role-aware conjunctive proposal resolves to **CODE**, not CONFIG. Router integration has a ConfigBuilder that raises if called. The existing candidate registry records the engine candidate without consuming `DP-001`.
15. Real Codex invocation: **yes**, official CLI, not a generic model call or fixture. Unit-test fake executables are used only for fault-injection tests and are not this proof.
16. Live baseline Detection: **yes**, separate real localhost Uvicorn HTTP process using exact-base Detection.
17. Live candidate Detection: **yes**, separate real localhost Uvicorn HTTP process using the committed candidate.
18. MSG-0916: baseline **false / 0 triggers** → candidate **true / 1 trigger**, with target evidence `MSG-0916` only.
19. Clean controls **9/9 remain false in both engines**: MSG-0902, 0904, 0906, 0908, 0910, 0912, 0914, 0918, 0920. This is a rule-based smoke, not a whole-system accuracy claim.
20. Existing Evaluator cannot cleanly identify both engines with the same policy reference. No fabricated EvaluationResult or policy-version substitution was produced.
21. Missing adapter: independent engine build/commit identity → runtime endpoint/immutable engine artifact → evaluator job/baseline pairing and provenance, while keeping Detection policy identity unchanged. CODE stays in existing `VALIDATING` state pending that adapter; it is never composed into a fake policy defense version.
22. No blocker for the demonstrated CODE build and live before/after. Remaining limits: Linux ARM64/Docker-specific verified transport, account login required, no real Evolution-agent smoke, no full engine-aware evaluator/governance integration, and deterministic linguistic coverage is not a production fraud classifier.
23. Exact next task: implement the engine-version evaluation adapter with same-policy baseline/candidate provenance, integrate it with the existing registry/lifecycle, and verify evaluation/governance before considering promotion. Do not activate this candidate automatically.
24. Final feature-branch commit is supplied in the handoff response (`git rev-parse HEAD`); it is distinct from the candidate engine commit above. This report is tracked with the feature code.

## Immutable local evidence

- [Build metadata](/private/tmp/member4-real-codex-artifacts/code-candidate-build-real-codex-hero-004.json)
- [Live HTTP observations](/private/tmp/member4-real-codex-artifacts/live-smoke-hero-004.json)
- [Full 44-test regression](/private/tmp/member4-real-codex-artifacts/full-regression-hero-004.json)
- Candidate worktree: `/private/tmp/member4-real-codex-candidates/code-candidate-build-real-codex-hero-004`.

The three JSON files are under `/private/tmp/member4-real-codex-artifacts/`.
Preserve them with the candidate commit when packaging the demo; temporary paths
are not a long-term artifact store. No secret values appear in the report.

Frozen Environment identity: `127.0.0.1:55432/fraud_intelligence`, user `fraud`,
scenario `taiwan-marketplace-20260912`, simulation time
`2026-09-10T12:00:00+08:00` (`04:00:00+00:00`). Snapshot and `updated_at` were
identical before/after; the live harness never calls any clock setter and
Detection connections enforce read-only transactions. Both engines used
`baseline-v1`, SHA-256 `ab26b3c8ca2cebf4ab04691cfffcdda3e48cdc77af8ee345d493a0d8c4d7131b`.

Earlier attempts remain FAILED, not rewritten: 001 invalid CLI argument order;
002 real native invocation but outer test imported baseline (later corrected);
003 native execution deliberately rejected by the fail-closed sandbox hook.
Only 004 is the accepted isolated CODE candidate. macOS platform sandbox probes
failed and are not counted as successful isolation.
