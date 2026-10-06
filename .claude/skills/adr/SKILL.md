---
name: adr
description: Records an architecture decision as a numbered ADR in docs/adr/. Use when making or changing a hard-to-reverse decision — process model, brain interface, I/O contract, policy/consent rules, platform abstraction, dependencies, data storage.
argument-hint: "<decision title>"
arguments: [title]
allowed-tools: Read Grep Glob Write Edit
---

# ADR: $title

1. Find the next number: highest `docs/adr/NNNN-*.md` + 1.
2. Create `docs/adr/NNNN-<kebab-title>.md` from `docs/adr/0000-template.md`. Keep it under one page.
3. **Context** cites the FRS section / spike / OQ that forced the decision. **Options** lists at least two real alternatives. **Decision** is one paragraph in the active voice. **Consequences** lists what gets easier, what gets harder, and what must now be true in code.
4. Status is `Proposed` until the human accepts it; then `Accepted (YYYY-MM-DD)`. Superseding an ADR: new ADR + mark the old one `Superseded by NNNN`. Never rewrite an accepted ADR's decision.
5. Link the ADR from the FRS decision table (§12.3) or the doc it changes, and from `docs/architecture.md` if it alters the architecture.

## Verify (mandatory)

Show the new file. Check: number is unique, all five sections are filled, every link in it resolves (`uv run python scripts/check_ai_config.py` checks doc links).
