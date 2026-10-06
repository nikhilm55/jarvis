# AI observability — usage, cost, failures

**Owner:** @nikhilm55

## Usage telemetry

Claude Code supports OpenTelemetry metrics (sessions, tokens, cost, lines changed, commits and PRs). To enable it on your machine, add this to your **user** settings or shell profile, not to the repo:

```
CLAUDE_CODE_ENABLE_TELEMETRY=1
OTEL_METRICS_EXPORTER=otlp            # or "console" to inspect locally
OTEL_EXPORTER_OTLP_ENDPOINT=<org collector URL>
```

- **Never** set `OTEL_LOG_USER_PROMPTS=1`. Prompt content is not exported (policy §7).
- With no org collector yet, use `/usage` and `/context` per session, plus the subscription usage page, and note monthly totals in the review log (`docs/ai/lessons.md`).

## Cost

- Primary use is a Claude subscription (flat cost). Watch weekly usage limits on the usage page.
- API keys used for product testing (Anthropic, OpenAI, Groq) have **monthly spend limits and email alerts** set in each provider console. The owner sets them when creating a key.
- Session token budgets: `docs/ai/workflow.md`.

## Failure tracking and outcomes

| Signal | How |
|---|---|
| AI-assisted PRs | label `ai-assisted` (the `open-pr` skill adds it) |
| A defect caused by AI-written code | label `ai-bug` on the fixing PR, plus an entry in `docs/ai/lessons.md` |
| Reverts of AI changes | commit message `revert: … (ai-bug)` |
| Outcome split | Monthly: count merged PRs with and without `ai-assisted`, and `ai-bug` fixes (`gh pr list --label …`), and log the numbers in the review log |

Unattended (CI) agent runs: none exist. If any are added, their logs and artifacts must be retained by the workflow.
