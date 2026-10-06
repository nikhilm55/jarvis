## What & why

<!-- One or two sentences. Link FRS requirement ids (FR-…), ADRs, OQs. -->

## Verification (paste real output)

```
$ uv run pre-commit run --all-files
$ uv run mypy
$ uv run pytest -q
```

- [ ] New/changed behaviour has a test that fails without this change
- [ ] No tests skipped, weakened or deleted
- [ ] Manually checked on: ☐ Linux (X11) ☐ Linux (Wayland) ☐ Windows ☐ n/a

## AI assistance

- [ ] AI agent used. Tool/model: ______. Commits carry `Co-Authored-By`; PR labelled `ai-assisted`
- [ ] I have read and can explain every line of this diff
- [ ] Any new dependency was verified by a human (name, publisher, licence)

## Reviewer checklist

- [ ] Correctness: logic walked with a concrete input
- [ ] Security: no untrusted text reaches a shell, path or tool call without the policy gate; no secrets
- [ ] Consent and policy gate untouched, or changes covered by tests
- [ ] Scope: no unrelated changes; ≤ ~400 changed lines (excluding docs and lockfile)
- [ ] Docs updated (FRS / ADR / architecture / AGENTS.md) where behaviour or decisions changed
- [ ] UI matches `docs/design/jarvis-ui-mockup.html` (if UI changed)
