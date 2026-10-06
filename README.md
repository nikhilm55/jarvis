# Jarvis

Voice control for your whole PC, on Windows and Linux. Say **"Jarvis, …"** and it gets done. If it can't, it tells you why and what to do.

> **Status: M0, feasibility spikes.** The spec and the frozen UI design are done; product code is not built yet.

| | |
|---|---|
| Spec | [`docs/FRS.md`](docs/FRS.md) |
| Architecture | [`docs/architecture.md`](docs/architecture.md) · decisions in [`docs/adr/`](docs/adr/0001-record-architecture-decisions.md) |
| UI design (approved, frozen) | [`docs/design/jarvis-ui-mockup.html`](docs/design/jarvis-ui-mockup.html) |
| Open questions | [`docs/open-questions.md`](docs/open-questions.md) |
| Working with AI agents | [`AGENTS.md`](AGENTS.md) · [`docs/ai/onboarding.md`](docs/ai/onboarding.md) · [`docs/ai/policy.md`](docs/ai/policy.md) |

## Develop

Requires [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files && uv run mypy && uv run pytest -q
uv run jarvis --version
```

Full setup, including the Claude Code guardrails, is in [`docs/ai/onboarding.md`](docs/ai/onboarding.md). Contribution rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md).
