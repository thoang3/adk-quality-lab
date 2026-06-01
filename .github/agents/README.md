# Agents Guide

Use these agents to speed up medium/large tasks in `adk-quality-lab`.

## Available agents

- `@Implementer` → `.github/agents/implementer.agent.md`
- `@Reviewer` → `.github/agents/reviewer.agent.md`

## When to use which

- Use `@Implementer` when you need code changes, tests, fixture updates, or refactors.
- Use `@Reviewer` when you want a structured review of recent changes before merge.

## Typical flow

1. Ask `@Implementer` to produce a plan and implement the task.
2. Ask `@Reviewer` to review branch diff + plan context.
3. Address review findings (if any) and re-run `make ci`.

## Example prompts

### Implementer examples

- `@Implementer implement llm judge wiring into run_eval with tests`
- `@Implementer fix fixture loader regression for tail cases`
- `@Implementer add timeout handling for async provider call path`

### Reviewer examples

- `@Reviewer review recent branch changes for eval correctness`
- `@Reviewer review .plans/task-llm-judge-wiring/plan.md`
- `@Reviewer review round 2 for fixture compatibility fixes`

## Review scope template

Use this when handing implementation to review:

```text
Please review this implementation.
plan_dir: .plans/task-{slug}/
branch: <current-branch>
base_branch: <base-branch>
review_scope: changed files in branch diff + plan context
diff_command: git diff --name-only <base_branch>...HEAD
changed_files:
- <file1>
- <file2>
Instruction: Review source/test/config changes first; use .plans files as context only.
```

## Notes

- Keep `.plans/` as working context; final truth is code + tests + docs.
- For hackathon pace, prioritize small, verifiable diffs over large rewrites.
- Do not treat review as complete if `make ci` is failing.
