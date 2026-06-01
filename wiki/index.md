# ADK Quality Lab Wiki — Index

> **For Copilot**: Read this file first every session.
> Then read only the relevant pages before editing code.
> Update affected wiki pages + `wiki/log.md` after significant changes.

**Last compiled**: 2026-05-28
**Wiki health**: ✅ Current — 8 pages

---

## Pages

| Page | Summary | When to read |
|------|---------|--------------|
| [architecture.md](architecture.md) | Repo map, key components, and control flow | Starting any feature or debugging flow across modules |
| [eval-pipeline.md](eval-pipeline.md) | End-to-end eval flow (`cli.eval` → `runner` → raters) | Changing eval logic, variants, fixture behavior |
| [datasets-raters.md](datasets-raters.md) | Dataset schema, loaders, deterministic/LLM raters | Editing case formats, adding/changing raters |
| [tools-wiring.md](tools-wiring.md) | Agent runner, fixture capture, vendored example wiring | Touching `tools/` or `examples/travel-concierge/adk_quality_lab_wiring/` |
| [testing.md](testing.md) | Test scope, CI behavior, commands | Writing tests or fixing CI |
| [known-issues.md](known-issues.md) | Active gaps and behavior mismatches | Before implementing medium/large changes |
| [cleanup-audit.md](cleanup-audit.md) | Redundant/unused candidates with evidence | Planning deletions, repo cleanup, scope reduction |
| [log.md](log.md) | Session log (append-only) | Orientation and handoff continuity |

---

## Quick-reference: file → wiki page mapping

```
adk_quality_lab/runner.py                    → eval-pipeline.md
adk_quality_lab/cli/eval.py                  → eval-pipeline.md
adk_quality_lab/cli/optimize.py              → known-issues.md + cleanup-audit.md
adk_quality_lab/datasets/schema.py           → datasets-raters.md
adk_quality_lab/datasets/loader.py           → datasets-raters.md
adk_quality_lab/raters/deterministic.py      → datasets-raters.md
adk_quality_lab/raters/groundedness.py       → datasets-raters.md
adk_quality_lab/raters/llm_judge.py          → datasets-raters.md + known-issues.md
adk_quality_lab/tools/agent_runner.py        → tools-wiring.md + eval-pipeline.md
adk_quality_lab/tools/capture_fixtures.py    → tools-wiring.md
adk_quality_lab/tools/generate_cases.py      → cleanup-audit.md
adk_quality_lab/observability/callbacks.py   → cleanup-audit.md
adk_quality_lab/observability/firestore_writer.py → tools-wiring.md + cleanup-audit.md
examples/travel-concierge/                   → architecture.md + tools-wiring.md
tests/                                       → testing.md
Makefile                                     → testing.md + architecture.md
```

---

## Key facts

- **Runtime**: Python `>=3.11` (`pyproject.toml`)
- **Package manager**: `uv`
- **CI gate**: `make ci` (`ruff` + `mypy` + `pytest`)
- **Primary eval CLI**: `python -m adk_quality_lab.cli.eval`
- **Default case sets**: F1 (`count hallucination`) + F2 (`groundedness`)
- **Fixture cache path**: `datasets/fixtures/flights/*.json`
- **Run persistence**: always local `runs/runs.jsonl`; Firestore best-effort
- **Active planning variants**: `baseline`, `arch_fix`
- **Deferred planning variants**: `prompt_tuning_v1`, `structured_output`, `prompt_tuning_v2`, `markdown`, `json_block`
