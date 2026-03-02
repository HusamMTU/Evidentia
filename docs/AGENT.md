# Agent Entrypoint

Use this file as the first read before making changes.

## Read Order

1. `docs/context/SYSTEM.md` (product goals/non-goals)
2. `docs/context/ARCHITECTURE.md` (how it works + why)
3. `docs/context/SYSTEM_INVARIANTS.md` (hard laws)
4. `docs/reference/CONTRACTS.md` (schema index + validation sequence)
5. `docs/reference/TEST_STRATEGY.md` (invariant-to-test mapping)
6. `docs/REPO_MAP.md` (where things live)

## Canonical Ownership (No Duplication)

No duplication: a concept lives in one canonical place.

- API shapes -> `schemas/`
- Hard rules -> `docs/context/SYSTEM_INVARIANTS.md`
- How it works -> `docs/context/ARCHITECTURE.md`
- Roadmap -> `docs/plans/`

## Enforcement Citation Rule

Docs must cite enforcement.

- Every invariant must link to at least one test or validation function.
- Prefer concrete pointers: schema path, validator function, and test file/test case.

## PR Checklist (Agents + Humans)

- If changing an API: update schema + validation + tests + `docs/reference/CONTRACTS.md`.
- If changing retrieval behavior: update invariant (if affected) + tests + architecture section.
- If changing pipeline stages: update architecture diagram/flow + repo map.

## Default Conflict Resolution

If docs conflict, follow this order:

1. `schemas/` and executable tests in `tests/`
2. runtime validation/code in `validation/` and implementation modules
3. `SYSTEM_INVARIANTS.md`
4. `ARCHITECTURE.md`
5. reference/roadmap docs
