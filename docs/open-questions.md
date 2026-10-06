# Open questions

Unresolved decisions, tracked instead of guessed. Agents: check this file at session start; if a task depends on an open item, stop and ask. Keep fewer than 10 open. Use the `open-questions` skill to add, audit and resolve entries.

## OQ-001 — Can Jarvis read Teams through Microsoft Graph in the work tenant?
**Status:** open
**Owner:** @nikhilm55
**Context:** FRS §6.2, §12.1; spike M0d.
**Question:** Will the tenant admin consent to a Graph app with chat read/send scopes, or must Teams use UI Automation only?
**Impact:** Decides the S2/S3 implementation path and the M365 catalog entry.

## OQ-002 — Is Jarvis personal tooling or a product for others?
**Status:** open
**Owner:** @nikhilm55
**Context:** FRS §12.2 q3.
**Question:** Personal/internal use only, or distributed to other users?
**Impact:** Affects licensing (OQ-004), the Claude Code terms check (OQ-003), code signing and naming.

## OQ-003 — May a distributed product drive a user's Claude Code subscription?
**Status:** open
**Owner:** @nikhilm55
**Context:** ADR-0003, FRS §12.1.
**Question:** Do Anthropic's current terms allow it, or must distributed builds use API-key mode?
**Impact:** Default brain for anyone other than the owner.

## OQ-004 — Which licence does the repository use?
**Status:** open
**Owner:** @nikhilm55
**Context:** beyondMeetings is MIT; Jarvis has no LICENSE yet. docs/ai/policy.md §Licence.
**Question:** MIT, proprietary (FiftyFive Technologies) or other?
**Impact:** Which third-party code and models can be bundled; how AI-generated code is licensed.

## OQ-005 — Is Hindi/Hinglish a Must for v1?
**Status:** open
**Owner:** @nikhilm55
**Context:** FRS FR-STT-05 (currently S).
**Question:** Promote multilingual commands to Must?
**Impact:** STT model choice and the acceptance suite.

## OQ-006 — Should YOLO override an explicit "never" grant?
**Status:** open
**Owner:** @nikhilm55
**Context:** FRS D12, FR-CON-10.
**Question:** Keep "never" binding in YOLO (current draft), or let YOLO override it?
**Impact:** One rule in the policy gate.

## OQ-007 — Who is the backup owner of the AI configuration?
**Status:** resolved — @nikhilmalhotra55 is backup owner (@nikhilm55, 2026-10-06)
**Owner:** @nikhilm55
**Context:** docs/ai/policy.md §Ownership; `.github/CODEOWNERS`.
**Question:** Which second person can review changes to `.claude/`, `AGENTS.md` and the CI config?
**Impact:** Two-person review of agent config; a single point of failure until resolved.
