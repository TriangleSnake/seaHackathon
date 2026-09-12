# Real Codex CODE Builder

This service builds Detection implementation candidates with the real official
Codex CLI in a dedicated Docker container. Evolution supplies behavioral intent; the builder supplies an
isolated detached Git worktree, a strict write boundary, protected acceptance
tests, regression checks, and immutable candidate metadata.

For the seller conditional-payment capability, runtime Codex can write only:

- `services/detection/app/repository.py`
- `services/detection/app/detectors/rules.py`

Codex runs with the detached candidate worktree path as its working directory.
Only Detection is projected into the container: its directory is mounted
read-only, with exactly the two files above overlaid read-write. The root
filesystem is read-only; the process is non-root with all capabilities dropped.
Exams are separate read-only mounts. Evaluator, seed, governance, schemas and
Git metadata are not mounted. The Docker socket and host directories are never
mounted. The CLI's inner Linux sandbox masks the read-only account-login file
and denies model-tool networking; only the trusted CLI can authenticate.
Seccomp permits namespace setup for this inner sandbox; the outer read-only
mounts remain the implementation write authority. Private tmpfs state is discarded.

A mandatory preflight probes actual OS read/write denial before invoking the
model. The outer builder also checks Git paths, unchanged HEAD, protected exam
hashes, and unchanged source during validation. Validation runs in fresh
network-disabled, credential-free containers with all candidate files read-only.
Timeout cleanup targets only uniquely named disposable containers.

Native macOS exec fails closed: the installed CLI's `:minimal` platform profile
grants broad `/tmp` writes. Named permissions alone were not adequate here.
The verified container adapter is mandatory; no unconfined/native fallback.
Permission reference: [official OpenAI documentation](https://learn.chatgpt.com/docs/permissions).

Successful builds require the real Codex process, protected acceptance tests,
the complete Detection regression suite, source compilation, and
`git diff --check`. The builder creates a detached candidate commit only after
all checks pass and publishes JSON metadata containing execution, path, test,
workspace, and commit provenance. It never activates the candidate or allocates
a formal production policy number.

Run isolated builder tests from this directory:

```bash
python3 -m pytest -p no:cacheprovider -q tests/test_runtime.py
```

The behavioral acceptance test intentionally fails on the integration baseline.
It is run against the isolated candidate by `DockerCodexCodeBuilder`.
`RealCodexCodeBuilder` holds the common lifecycle; its native sandbox hook is
disabled. Test fixtures bypass that hook only to test lifecycle fault handling.

Run the deterministic hero proposal through the real CLI builder from the
repository root (the installed Codex account supplies authentication; no API
key is passed to the candidate process):

```bash
docker build -t member4-real-codex-builder:0.154.0 services/codex-builder
PYTHONPATH=services/codex-builder \
  python3 services/codex-builder/run_hero_build.py --build-id build-unique-id
```

The image currently targets Linux ARM64 and uses the cached Detection image
named in the Dockerfile (override `DETECTION_IMAGE` with a compatible image).
The official Codex 0.154.0 package is pinned and SHA-512 verified. Existing
Codex account login is mounted read-only; no OpenAI API key is passed.

CODE identity is `CodeCandidate(candidate_id, base_commit, candidate_commit,
metadata_ref)` in the existing registry. It is **not** a `CandidatePolicy`.
The orchestrator records attempt lineage and stops in `VALIDATING` with an
explicit engine-version-adapter requirement; it does not compose a fake policy
version, evaluate through a policy-only adapter, allocate production numbers,
or activate anything. Planner capability availability must match actual wiring.

`live_smoke.py` checks the frozen isolated database before starting two temporary
HTTP servers, uses the same policy, and saves code-engine provenance separately.
`full_regression.py` runs clock-mutating integration tests only in a new internal-
network seed database, not the frozen demo database. It then removes that database.
See [VERIFICATION.md](VERIFICATION.md) for actual results and artifact paths.
