"""Summarise docs/spikes/M0b-brain-latency.data.csv into p50/p95 per model, mode and kind."""

from __future__ import annotations

import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "docs" / "spikes" / "M0b-brain-latency.data.csv"


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def main() -> int:
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    ttft: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    failures = 0
    with DATA.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["kind"] in {"warmup", "deny"}:
                continue
            if row["ok"] != "True" or not row["total_s"]:
                failures += 1
                continue
            key = (row["model"], row["mode"], row["kind"])
            groups[key].append(float(row["total_s"]))
            if row["ttft_s"]:
                ttft[key].append(float(row["ttft_s"]))
    print("| Model | Mode | Turn kind | n | first token p50 | total p50 | total p95 | max |")
    print("|---|---|---|---|---|---|---|---|")
    for key in sorted(groups):
        total = groups[key]
        first = ttft[key] or [float("nan")]
        print(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(total)} | {statistics.median(first):.2f} s | "
            f"{statistics.median(total):.2f} s | {pct(total, 0.95):.2f} s | {max(total):.2f} s |"
        )
    print(f"\nfailed turns: {failures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
