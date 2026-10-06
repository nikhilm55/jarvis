---
name: open-pr
description: Pushes the current feature branch and opens a GitHub pull request using the repo template. Use when a change is ready for review. Manual only (/open-pr); it never merges or approves.
argument-hint: "<PR title>"
arguments: [title]
disable-model-invocation: true
allowed-tools: Read Bash(git status) Bash(git diff *) Bash(git log *) Bash(git push *) Bash(gh pr create *) Bash(gh pr view *) Bash(uv run *)
---

# Open a PR: $title

Side effects: pushes a branch and creates a PR on GitHub. Each step that writes asks for confirmation.

1. **Refuse on main.** If the current branch is `main`, stop and say so.
2. **Gate.** Run and paste the summary of:
   `uv run pre-commit run --all-files && uv run mypy && uv run pytest -q`
   Any failure → stop; fix first (skill `debug`).
3. **Size check.** `git diff --stat main...HEAD`. Over ~400 changed lines (excluding docs/lockfile) → propose a split before continuing.
4. **Self-review.** Run the `code-review` skill; fix 🔴 findings. Run `open-questions audit`.
5. **Confirm with the human:** show the title, the branch, the diff stat, and the PR body drafted from `.github/pull_request_template.md` — fill *Verification* with the real command output and tick *AI assistance*. Wait for an explicit "yes".
6. `git push -u origin HEAD`, then `gh pr create --title "$title" --body-file <drafted body>` and add the `ai-assisted` label.
7. Never `gh pr merge`, never approve — a human reviews and merges.

## Verify (mandatory)

`gh pr view --json url,title,labels,statusCheckRollup` — show the URL and that CI started.
