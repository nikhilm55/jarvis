"""Fail a PR whose reviewable change is too large (AGENTS.md rule 12).

Counts added + deleted lines from `git diff --numstat <base>...HEAD`, excluding
docs, the lockfile and other non-reviewable files. A human can waive the limit
for one PR by adding the `size-exception` label (checked by the CI workflow).

Usage: uv run python scripts/check_pr_size.py <base-ref> [max_lines]
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys

MAX_LINES = 400
EXCLUDED = ["docs/*", "*.md", "uv.lock", "*.html", ".secrets.baseline", "tests/fixtures/*"]


def changed_lines(numstat: str) -> tuple[int, list[str]]:
    """Sum reviewable line changes; return (total, excluded paths). Binary files count 0."""
    total, skipped = 0, []
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t", 2)
        if any(fnmatch.fnmatch(path, pattern) for pattern in EXCLUDED):
            skipped.append(path)
            continue
        if added != "-":
            total += int(added) + int(deleted)
    return total, skipped


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_pr_size.py <base-ref> [max_lines]")
        return 2
    limit = int(argv[1]) if len(argv) > 1 else MAX_LINES
    numstat = subprocess.run(
        ["git", "diff", "--numstat", f"{argv[0]}...HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    total, skipped = changed_lines(numstat)
    print(f"Reviewable changed lines: {total} (limit {limit}; {len(skipped)} excluded files)")
    if total > limit:
        print("PR too large to review well — split it, or a human adds the 'size-exception' label.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
