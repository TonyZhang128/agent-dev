# Repository Guidelines

Applies to the entire repository: a Qwen business agent API using Python 3.12, uv, FastAPI, Pydantic, and LangChain 1.x. Use Ollama on macOS and a separate vLLM service on Linux; select the model endpoint through `.env`.

## Before You Start

- Read `README.md`, `pyproject.toml`, and affected modules. API contracts are in `docs/agents-api.md`.
- Check `git status`. Preserve existing changes, `.env`, files, models, and user data.
- Check installed tools and environments before installing. Use Homebrew for Mac tools and uv for this project; never install into system Python or another project's environment.
- Use the pinned LangChain versions. Check official documentation and provider compatibility before upgrades; avoid deprecated APIs such as `AgentExecutor` and `initialize_agent`.

## Architecture

- `app/main.py`: HTTP routes, dependency lifecycle, and error mapping. Keep prompts and model protocol details elsewhere.
- `app/schemas.py`: strict Pydantic contracts; reject extra fields and enforce lengths, enums, and cross-field constraints.
- `app/agents/`: business inputs, rules, and execution. Store system prompts in `app/prompts/<name>.md` and load them with `load_prompt()`.
- Every business agent must reuse `app/agents/base.py`: inherit `StructuredAgent[Request, Result]` for structured output or `BaseAgent[Request, Result]` otherwise. Reuse prompt loading, construction, and invocation; extend the base classes for shared needs. See `log_summary.py` and `chat.py`.
- Route all inference through `build_agent()` / `invoke_agent()` in `app/agents/runtime.py`, using `langchain.agents.create_agent()`. Do not add direct SDK inference paths.
- `app/llm.py`: shared `ChatOpenAI` factory, HTTP clients, and readiness checks only. Close clients through the application lifecycle; keep business prompts and classification rules elsewhere.
- Structured agents must use `ProviderStrategy(schema, strict=True)` for native JSON Schema output, then validate with Pydantic. Never fall back to loose text parsing or fabricated success results.
- Keep messages and state isolated per request; never mutate shared compiled agents. Intent classification uses a fixed schema and five server-defined business classes plus the `unknown` fallback; do not restore custom candidates.
- Use LangChain messages, tools, and middleware. Register `@tool` tools through `build_agent(..., tools=...)`; retain response checks, total timeouts, and recursion limits.
- All business requests require user_id and session_id. Intent/chat also require current-session history (first turn: []); log-summary and plan reject history. Pass identity through request-local LangChain metadata, not model prompts. Caller-supplied IDs are not authentication. Do not persist messages, enable a checkpointer, or share implicit state across requests.

## API Contracts

- Preserve paths and request/response fields for `/api/business/plan`, `/api/agents/log-summary`, `/api/agents/intent`, and `/api/agents/chat`. Document contract changes and add compatibility tests.
- Log summaries accept text or JSON objects. Never invent dates, achievements, or tasks.
- Intent results must use `work_list`, `supervision_log`, `image_library`, `business_management`, `chat`, or the fallback `unknown`. Request `intents` must be omitted or `[]`; reject nonempty values with `422` before inference. Scores below `0.65` or any need for clarification must yield `unknown` and `needs_clarification=true`. Scores are not calibrated probabilities.
- Intent/chat accept complete alternating user/assistant history only. Keep all history that fits the configured context budget; trim the oldest complete turns, retaining the current input and system prompt. Use the shared request-local history helper and document its conservative byte estimate. Enforce the configured full-input size cap; do not restore the old 10-message/4000-character conversation limits. Reject caller-supplied system prompts and do not echo identity or messages in validation errors.
- Return `422` for invalid input, `503` for an unreachable model, `504` for inference timeouts, and `502` for upstream errors or invalid output. Never expose keys, original user input, or upstream error bodies in errors.
- `/health` checks process liveness. `/ready` checks the model list without inference.

## Adding an Agent

1. Define request/result schemas and validation in `app/schemas.py`; add `app/prompts/<name>.md`.
2. Inherit from the shared base class. Structured agents define `name`, `result_type`, and `user_content()`; other agents define `name`, `messages()`, and `parse_result()`. Follow `intent.py` for fixed intent rules and low-confidence fallback, preserving request isolation.
3. Create the instance in the FastAPI lifespan and declare the route's `response_model`.
4. Follow TDD for normal, boundary, and failure cases; update API documentation and the README structure.
5. Before connecting tools with external side effects, design identity, authorization, idempotency, and business confirmation. Current agents do not execute approvals, order changes, or notifications.

## Test-Driven Development Policy

1. Define observable acceptance criteria and normal, boundary, and failure cases before implementing each feature.
2. Add or update pytest tests before editing production code.
3. Run new tests and confirm they fail for the expected behavioral reason (RED).
4. Make the smallest correct change that passes them (GREEN).
5. Refactor while keeping tests passing (REFACTOR).
6. Use unit tests for pure business logic and contract/integration tests for cross-module behavior.
7. Mock external LLM, OCR, and third-party services in fast tests. Never mock the code under test.
8. Keep real LLM evaluations in a separate suite with versioned datasets and explicit success criteria.
9. Include a regression test reproducing the original failure with every bug fix.
10. Never delete, weaken, skip, or rewrite a failing test solely to make the implementation pass. Request approval when requirements truly change.
11. Run `uv run --locked pytest tests/unit/ tests/integration/ -v` before reporting completion.
12. Report tests added, initial failures, final results, and untested risks. Never claim unexecuted tests passed.

## Environment and Dependencies

- Manage dependencies with `uv add`; commit `pyproject.toml` and `uv.lock` together. Never hand-edit the lockfile.
- Use Python 3.12 syntax. Ruff handles formatting, basic linting, and import order.
- Pin verified versions of `langchain`, `langchain-core`, and `langchain-openai`. Prefer provider-specific integration packages; avoid Dify and unnecessary frameworks.
- Keep Linux vLLM separate from the Mac business environment. Ollama manages local model weights; never commit them.
- Default to `LANGSMITH_TRACING=false`; enable tracing only through explicit configuration. Supply credentials at runtime and never commit real business traces.
- Update `Settings`, `.env.example`, and README for new configuration. Preserve `.env`.

## Verification

Run from the repository root:

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

Fast tests use pytest / pytest-asyncio with real LangChain agents and mocked model HTTP responses; they require neither network access nor Ollama. Pass relevant checks without removing validation or tests. Tests currently live directly under `tests/`; the TDD command above requires `tests/unit/` and `tests/integration/`, which do not yet exist. Report this mismatch if the command fails.

For inference protocol, prompt, model configuration, or agent flow changes, restart the API and verify against the real model:

```zsh
zsh scripts/dev/services.sh restart-api
uv run --locked python -m scripts.common.verify_agents
# Also run for Ollama GPU or deployment script changes:
uv run --locked python -m scripts.dev.verify_live
```

Keep verification output in local `verification/`, outside Git. Restart background services after code changes; offline tests alone do not establish deployment success. Linux CI runs offline tests and Ruff without downloading models.

## Git and Operations

- Keep `origin` at `https://github.com/TonyZhang128/agent-dev.git`. Preserve history and use commit messages describing the final behavior.
- Review staged changes. Commit only task-related files; exclude `.env`, secrets, models, `.venv`, caches, logs, verification output, and local `skills/`.
- Never perform destructive cleanup, force-push, or overwrite user changes.
- Manage Mac services with `scripts/dev/services.sh`; avoid duplicate instances and never stop processes started elsewhere. Logs are in `.logs/`. Do not edit shell profiles.
- Report changes, actual verification results, project path, and run instructions. Explicitly distinguish any Linux GPU deployment that was not performed.

## Optional Local Skills

Read and follow matching skills before relevant work when these files exist. Local `skills/` is Git-ignored and is not required in fresh clones.

- LangChain agents, tools, structured output: `skills/langchain-fundamentals/SKILL.md`
- LangChain dependencies: `skills/langchain-dependencies/SKILL.md`
- Retrieval and knowledge bases: `skills/langchain-rag/SKILL.md`
- LangGraph state and workflows: `skills/langgraph-fundamentals/SKILL.md`

Source: https://github.com/langchain-ai/langchain-skills
Pinned revision: `16a992f09ab3ccfb642dd4f08d350d833d1990bf`.

Use local `skills/` because this environment protects `.agents/` and `.codex/` from writes. These skills do not require global discovery; repository files remain authoritative for structure, dependencies, and operation.
