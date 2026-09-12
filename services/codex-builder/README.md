# Real Codex CODE Builder

This service builds Detection implementation candidates with the installed
Codex CLI. Evolution supplies behavioral intent; the builder supplies an
isolated detached Git worktree, a strict write boundary, protected acceptance
tests, regression checks, and immutable candidate metadata.

For the seller conditional-payment capability, runtime Codex can write only:

- `services/detection/app/repository.py`
- `services/detection/app/detectors/rules.py`

Codex runs with `services/detection/app` as its CLI writable root. The outer
builder then rejects any Git change outside the exact two-file allow-list. The
authoritative acceptance test lives outside the candidate worktree and is
hashed before and after the invocation. Evaluator manifests, labels, gates,
governance, shared schemas, and policy artifacts are neither prompt input nor
writable candidate material.

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

The behavioral acceptance test intentionally fails on the integration
baseline. It is run against the isolated candidate by `RealCodexCodeBuilder`.

Run the deterministic hero proposal through the real CLI builder from the
repository root (the installed Codex account supplies authentication; no API
key is passed to the candidate process):

```bash
PYTHONPATH=services/codex-builder \
  python3 services/codex-builder/run_hero_build.py
```
