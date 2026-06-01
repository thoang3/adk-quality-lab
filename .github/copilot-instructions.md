# GitHub Copilot Instructions — adk-quality-lab

## Scope

This repository is **ADK Quality Lab**, a reproducible quality-evaluation kit for ADK agents.
Primary package: `adk_quality_lab/`.
Vendored target agent: `examples/travel-concierge/`.

### Hard Boundaries

- No live credentials in default CI tests.
- Never log API keys, tokens, signed URLs, or raw sensitive payloads.
- Do not edit vendored upstream source files under `examples/travel-concierge/travel_concierge/` unless explicitly requested; all wiring changes should go into `examples/travel-concierge/adk_quality_lab_wiring/` instead.
- Keep changes minimal and testable; avoid unrelated refactors during hackathon crunch.
- `make ci` failures are stop-ship.

---

## Persistent Wiki (Read First)

A living wiki is in `wiki/` at the repo root.
**Read `wiki/index.md` at the start of every session before editing source files.**

| Wiki page | When to read |
|-----------|--------------|
| `wiki/index.md` | Every session — start here |
| `wiki/architecture.md` | New features / cross-cutting debugging |
| `wiki/eval-pipeline.md` | Changes to eval execution or variants |
| `wiki/datasets-raters.md` | Dataset schema or rater changes |
| `wiki/tools-wiring.md` | Fixture/agent wiring work |
| `wiki/testing.md` | Tests and CI behavior |
| `wiki/known-issues.md` | Before medium/large code changes |
| `wiki/cleanup-audit.md` | Deletion and repo cleanup decisions |
| `wiki/log.md` | Prior work history |

Update `wiki/log.md` at the end of each session.

Each entry should include: files changed, tests run, `make ci` status, and follow-up risks.

---

## Working Loop

For feature/bug/refactor tasks:

1. Understand: read `wiki/index.md` + relevant pages
2. Plan: break into testable steps (use `.plans/task-{slug}/plan.md` for non-trivial tasks)
3. Implement with focused diffs
4. Validate with targeted tests, then `make ci`
5. Lint + typecheck
6. Update wiki pages touched by the change

Do not consider work complete if CI-equivalent checks fail.

---

## Quality Gate (Mandatory)

- Run `make ci` before concluding substantial code changes.
- If formatting issues appear, run `make format` then re-run `make ci`.
- Do not merge/submit with failing `ruff`, `mypy`, or `pytest` checks.

### Eval Fixture Gate (Mandatory for schema/loader/rater-shape changes)

If changing `adk_quality_lab/datasets/schema.py`, `adk_quality_lab/datasets/loader.py`,
or output shape assumptions in `adk_quality_lab/raters/`:

1. Identify impacted datasets/fixtures.
2. Update fixture/data files before test assertions that depend on them.
3. Run focused tests first (for example `uv run pytest tests/test_core.py -v`).
4. Run `make ci`.
5. Report: `Fixture Gate: schema/fixture compatibility verified.`

### TDD Gate (Mandatory for new functions/classes)

1. Write a failing test first.
2. Run targeted pytest and verify expected failure.
3. Implement minimal code.
4. Re-run tests and `make ci`.

---

## Environment

- Python: `>=3.11`
- Package manager: `uv`
- Use existing `.venv/`; do not recreate unless broken and approved.
- Typical setup:

```bash
uv sync --extra dev
make ci
```

---

## Project Layout

```
adk_quality_lab/
  cli/            # eval/optimize/kappa/dashboard/show entrypoints
  datasets/       # pydantic schema + JSONL loaders
  raters/         # deterministic/groundedness/llm_judge
  tools/          # fixture capture + agent wiring
  optimizer/      # observe→propose→verify tuning loop
  observability/  # firestore writes + callback stubs
  runner.py       # parallel execution + persistence
datasets/         # F1/F2/tail cases + fixtures + gold labels
examples/travel-concierge/
tests/
```

---

## Coding Conventions

- Prefer typed public functions and strict mypy compatibility.
- Keep eval runs deterministic when possible (fixture-first behavior).
- Favor absolute imports from `adk_quality_lab...`.
- Keep variant-specific logic isolated to `examples/travel-concierge/adk_quality_lab_wiring/`.
- Ruff line length is 100; keep code formatted and imports consistent.
- Avoid new dependencies unless justified by a concrete need.

## Async and Runtime Safety

- Avoid blocking calls on the event loop in async paths.
- Apply explicit timeouts around async provider calls.
- Handle `asyncio.CancelledError` explicitly in cleanup paths.

## Observability and Privacy

- Use structured logging with run/case context where possible.
- Never include secrets or credentials in logs.
- External write paths (for example Firestore) are best-effort and must not block local run persistence.

---

## Testing Guidance

- Fast local gate: `make ci`
- Eval smoke: `make eval CASE_SET=smoke VARIANT=baseline`
- Full reproducible comparison: `make eval CASE_SET=both VARIANT=<variant>`
- Gold calibration flow:
  1. `make eval CASE_SET=gold VARIANT=baseline`
  2. `make kappa`

Default CI must remain offline-friendly. External provider tests should be opt-in only.

---

## Cleanup / Deletion Workflow

When you identify redundant or unused code:

1. Add evidence to `wiki/cleanup-audit.md` (file + callsite status + risk)
2. Mark recommendation (`delete now`, `archive`, `defer`)
3. If deleting, remove dead references/tests/docs in same change

Do not delete vendored `examples/travel-concierge/` files unless explicitly requested.

---

## Agent Roles

- `@Implementer`: `.github/agents/implementer.agent.md` (plan-first implementation, fixture/TDD gates, CI verification)
- `@Reviewer`: `.github/agents/reviewer.agent.md` (source-first review, structured findings, clear verdict)
