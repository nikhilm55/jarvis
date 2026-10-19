# The Jarvis agent harness

**Agent = model + harness.** The model is whatever does the work: Claude Opus or Sonnet, or the local Qwen. The harness is everything around it: what it's told before it starts, what checks its work after, and how mistakes turn into new rules. With a model held fixed, a better harness moves quality more than a better model does. That holds for frontier models too, and most of all for a small local one.

**Every delegated task in this repo runs inside this harness.** That covers a Claude session handing work to a subagent, the orchestrator dispatching an implementer or reviewer, and the local model implementing on its own through `scripts/local_model.py`. No exceptions; a hook enforces it (see [Enforcement](#enforcement)).

## The two halves

| | Guides (before the model acts) | Sensors (after it acts) |
|---|---|---|
| **Deterministic** (cheap, run every time) | the brief's exact interfaces and file manifest; `AGENTS.md` house rules; the local model's system prompt [`qwen/system.md`](qwen/system.md); formatters | ruff, `mypy --strict`, pytest; the scope check (only manifest files changed); the test-weakening guard; pre-commit / pre-push hooks; CI on every PR |
| **Judgement** (slower, used at gates) | the plan; the requirement → test map; skills in `.claude/skills/` | a self-review pass in a fresh context; the task reviewer ([`review.md`](review.md)); the whole-branch review; the owner |

## The contract for one delegated task

1. **Brief** ([`brief.md`](brief.md)). Written by whoever delegates. It has to say what "done" means before any code exists: the goal, the spec references, exact interfaces, the file manifest, the verify commands, the limits, and what's out of scope. A vague brief is the most common reason a good model produces bad work.
2. **Plan first.** The worker restates the task, lists the files and public signatures it will produce, and maps **every requirement in the brief to a named test**. For the local model this is a separate planning call; its output feeds every later prompt.
3. **Tests first, then lock them.** Tests are written from the brief before the implementation. After that, fix rounds may change implementation files only. A test file may change only when the test itself is broken: its own import fails (imports only), or once for its own lint/mypy errors (annotations and imports only). A test that fails because the implementation lacks a name is the implementation's problem. Every other top-level statement of a locked test file stays identical (compared as an AST), so no assert can be softened, skipped or moved. This blocks the classic failure: "fixing" a red test by weakening it.
4. **Small edits.** New files are written whole. Existing files are changed with exact search/replace blocks, never rewritten from memory, so untouched code stays untouched.
5. **Sensors after every step.** Format, lint, type-check, test, scope check. Success is silent; failures go back verbatim (trimmed to the relevant file). If the same failure repeats twice, the worker stops and escalates instead of thrashing.
6. **Separate generation from evaluation.** Once green, a fresh context reviews the diff against the brief and the review checklist. Self-grading in the same context skews positive.
7. **Report** ([`report.md`](report.md)). The evidence (commands and real output), the requirement → test map, deviations, open questions, and the share of lines each model wrote.
8. **Ratchet.** When a reviewer or the owner finds a mistake a sensor could have caught, the fix includes the new guide or sensor: a line in `qwen/system.md`, a check in `local_model.py`, a hook, a test, or a lesson in `docs/ai/lessons.md`. Rules that a stronger model no longer needs get removed.

## Who uses what

| Delegator → worker | Brief | Plan / tests first | Sensors | Review |
|---|---|---|---|---|
| Orchestrator → local model (`local_model.py implement`) | `brief.md` + manifest | planning call; tests drafted first and locked | built into the loop | self-review pass, then the finisher and the task reviewer |
| Orchestrator → Claude finisher (the default after the loop) | `brief.md` with `## Local model: finisher` + the loop's log dir | the loop's plan | the repo's hooks + verify commands | task reviewer with `review.md` |
| Orchestrator → Claude implementer (only with `exempt: <reason>`) | `brief.md` with the exemption | the worker's first step, in its report | the repo's hooks + verify commands | task reviewer with `review.md` |
| Orchestrator → Claude reviewer | `brief.md` (the review package: brief + diff + CI status) | — | — | it *is* the sensor; uses `review.md` |
| Any Claude session → subagent | `brief.md` (short form is fine for read-only searches) | if it writes code | hooks | the delegator reads the report critically |

## Enforcement

- **Delegation hook.** `.claude/hooks/guard_delegation.py` (PreToolUse on the subagent tool) rejects a dispatch whose prompt lacks the brief's required sections (`Goal`, `Context`, `Constraints`, `Done when`, `Report`, `Local model`) or leaves one empty or a placeholder. The `Local model` section must name a mode: `loop`, `finisher`, `review` or `exempt: <reason>`. Read-only search agents are exempt.
- **The local model loop** enforces plan → tests first → test lock → scope check → stall stop → self-review in code, and writes the result to `summary.json`. Its `status` is one of `green`, `red`, `stalled`, `scope_violation`, `test_weakened`, `sensor_tamper` (an implementation file imported pytest or unittest.mock, or assigned into an imported module: reverted), `test_error` (a test file's own lint/mypy error survived its one fix round) or `test_disputed` (stalled with a `TEST-DISPUTE:` line from the model: the test itself may be wrong, so a finisher decides).
- **Reviewers** check the brief's requirement map against the tests and fail a task whose tests were weakened, whose scope grew, or whose CI is red.

## Limits

What the loop's sensors guarantee, and what they do not.

- **The test lock is the hard guarantee.** A locked test file is compared as an AST; a weakened, skipped, reordered or rebound test is restored, and the run ends `test_weakened`.
- **The implementation tamper rule is a deterrent, not a sandbox.** It catches accidental or lazy tampering (importing pytest, patching `_pytest`, `os._exit`, `sys.modules` stores). It is a denylist, so a deliberate escape (an aliased `import_module`, `getattr` tricks, `sys._getframe`, `gc`) can get past it. The pytest-summary check backs it up on the result: pytest counts as green only when its exit code is 0 and its stdout's last line reports `N passed` with nothing failed, N at least the number of locked tests (passes are counted against the locked tests, not just the exit code), and no more skipped or xfailed than the locked tests' own skip markers (extra skips count as not clean). An escape that still prints a believable clean summary, for example by writing to stdout after pytest has finished, is for the finisher and the task review.
- **Appended round-0 tests can still mutate shared state** (through calls or aliases) in a test file that already existed. Reviewers check the new tests in existing files.

## Files

| File | What |
|---|---|
| [`brief.md`](brief.md) | Template for every task brief |
| [`report.md`](report.md) | Template for every worker report |
| [`review.md`](review.md) | Checklist for task reviews |
| [`qwen/system.md`](qwen/system.md) | The local model's system prompt (house rules); the loop loads it |
| `../scripts/local_model.py` | The local-model loop that runs this contract |
| `../docs/ai/dev-pipeline.md` | How the harness fits the whole pipeline |

Sources that shaped this: Martin Fowler / Birgitta Böckeler, *Harness engineering for coding agent users* (guides and sensors, computational vs inferential); Addy Osmani, *Agent harness engineering* (ratchet on failures, separate generation from evaluation, success silent / failures verbose); Anthropic, *Effective harnesses for long-running agents* (progress files, one feature at a time, verify before moving on); Aider and Agentless (search/replace edits, filter candidates through tests).
