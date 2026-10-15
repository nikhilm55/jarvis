# Task review checklist

The reviewer is a sensor, not a co-author: report findings, don't fix them. Review the **brief + diff + verify output + CI status**, not a tour of the repo. Each finding gets a severity (Critical / Important / Minor), a `file:line`, and a concrete failure scenario.

## Blocking (any one fails the task)

- [ ] **Every requirement in the brief has a test**, and the report's requirement → test map is true (open the tests).
- [ ] **No test was weakened** to go green: no deleted or loosened asserts, no new `skip`/`xfail` without a platform reason, no mocks replacing the thing under test, no lowered thresholds. Compare against the first draft when the local model wrote it.
- [ ] **Scope:** only the manifest's files changed; no drive-by refactors; no new dependencies the brief didn't name.
- [ ] **CI is green on every required job** of the PR (both OSes). A red job is a finding even for Linux-only code.
- [ ] **Safety rules hold:** every product tool call goes through the policy gate and consent check; no `shell=True`; text I/O passes `encoding="utf-8"`; no secrets, no real user data, no network in tests.
- [ ] **The verify output in the report is real** (it matches what you get when you run it).
- [ ] **New tests in an existing test file** don't change shared state that later tests rely on (the local-model loop can't fully stop this; see `harness/README.md` § Limits).

## Correctness

- [ ] Edge cases from the brief: empty, too long, unicode, concurrent, cancelled, timeout, process death.
- [ ] Errors are raised or reported, never swallowed; messages say what to do.
- [ ] Resources are released on every path (processes, threads, files, sockets).
- [ ] Platform-specific code sits behind a platform check or backend interface (ADR-0002).

## Fit

- [ ] Names, layout and style match the surrounding code.
- [ ] Docs updated in the same change when behaviour changed (FRS, ADR, `docs/architecture.md`).
- [ ] PR ≤ 400 reviewable lines.

## Recurring findings (check these every time)

- [ ] Success messages are backed by a check of the actual result.
- [ ] Structured-file editors can't lose data: try a multi-line string, an inline table and a quoted key.
- [ ] File writes are atomic and keep mode and symlinks; errors become clean messages, not tracebacks.
- [ ] Allowlist or platform branches have a test per branch.
- [ ] Skip reasons say what breaks on the skipped platform.
- [ ] Try to make a failing test pass without fixing the code (skip, exit early, rebind, deselect). If one works, it's a finding.

## Ratchet

- [ ] For each finding: could a guide (brief, system prompt, skill) or a sensor (check, hook, test) have caught it? If yes, name it in the review so the fix round adds it.
