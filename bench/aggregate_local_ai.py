#!/usr/bin/env python3
"""Aggregate independently generated AI trials without inventing missing data.

Compare *paired* task/repeat instances across all three arms. Confidence
intervals are descriptive Wilson 95% intervals, not a proof of superiority.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from math import sqrt
from pathlib import Path
import re

ARMS = ("zig_plain", "zig_restricted", "rust_safe")
EXPECTED_TASKS = 10


def wilson(k: int, n: int) -> dict | None:
    if n == 0:
        return None
    z = 1.959963984540054
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return {"estimate": round(p, 4),
            "lower": round(max(0.0, mid - half), 4),
            "upper": round(min(1.0, mid + half), 4)}


def analyze(files: list[dict]) -> dict:
    rows = []
    identities = set()
    fingerprints = set()
    seeds = set()
    shards = set()
    requested = 0
    for report in files:
        fingerprint = report.get("model_identity", {}).get("digest")
        fingerprints.add(fingerprint)
        identities.add(report.get("model_identity", {}).get("name"))
        shards.add(report.get("shard"))
        requested += report.get("planned", 0)
        for row in report.get("rows", []):
            identity = (row["task"], row["arm"], row["repeat"])
            if identity in seeds:
                raise ValueError("Duplicate task/arm/repeat: " + repr(identity))
            seeds.add(identity)
            rows.append(row)
    judged = [r for r in rows if r.get("status") == "JUDGED"]
    stats = {}
    for arm in ARMS:
        selected = [r for r in rows if r["arm"] == arm]
        complete = [r for r in selected if r.get("status") == "JUDGED"]
        first_pass = sum(r.get("initial_effective") == "PASS" for r in complete)
        repaired_pass = sum(r.get("final_effective") == "PASS" for r in complete)
        stats[arm] = {
            "attempted": len(selected), "judged": len(complete),
            "initial_success": first_pass, "final_success": repaired_pass,
            "first_pass_wilson95": wilson(first_pass, len(complete)),
            "final_wilson95": wilson(repaired_pass, len(complete)),
            "initial_categories": dict(Counter(
                r.get("initial_effective", "UNKNOWN") for r in complete)),
            "final_categories": dict(Counter(
                r.get("final_effective", "UNKNOWN") for r in complete)),
            "repair_calls": sum(r.get("repair_calls", 0) for r in selected),
            "initial_loc_mean": (
                round(sum(r["initial"]["metrics"]["source_lines"] for r in complete)
                      / len(complete), 2) if complete else None),
            "final_loc_mean": (
                round(sum(r["final"]["metrics"]["source_lines"] for r in complete)
                      / len(complete), 2) if complete else None),
        }
    by_pair = {(r["task"], r["repeat"], r["arm"]): r for r in judged}
    paired = {}
    for i, left in enumerate(ARMS):
        for right in ARMS[i + 1:]:
            keys = {(t, n) for (t, n, a) in by_pair if a == left}
            keys &= {(t, n) for (t, n, a) in by_pair if a == right}
            wins = losses = ties = 0
            for task, repeat in keys:
                a = by_pair[(task, repeat, left)].get("initial_effective") == "PASS"
                b = by_pair[(task, repeat, right)].get("initial_effective") == "PASS"
                if a and not b:
                    wins += 1
                elif b and not a:
                    losses += 1
                else:
                    ties += 1
            paired[f"{left} vs {right}"] = {
                "comparable_pairs": len(keys), "left_only_passed": wins,
                "right_only_passed": losses, "same_outcome": ties,
            }
    full = (len(identities) == 1 and len(fingerprints) == 1 and
            len(shards) == 3 and requested == 60 and
            len(rows) == requested and len(judged) == requested)
    return {
        "complete_60_trial_study": full,
        "model_names": sorted(str(x) for x in identities),
        "model_digests": sorted(str(x) for x in fingerprints),
        "shards": sorted(str(s) for s in shards),
        "expected_or_planned": requested, "observed_rows": len(rows),
        "judged_rows": len(judged), "stats": stats, "paired_initial": paired,
        "limitations": [
            "Only one small local model; do not extrapolate to GPT-6 or other models.",
            "Tests cover 10 short byte-array tasks, not real-world whole applications.",
            "2 seeds per arm/task give wide confidence intervals.",
            "Candidate LOC excludes the separately trusted Zig core.",
            "Passing finite vectors is not memory safety, race freedom, or ownership proof.",
            "Structure checks are lexical heuristics, not enforcement of true thread creation.",
        ],
    }


def summarize_markdown(report: dict) -> str:
    lines = [
        "# AI coding comparison: measured outcomes", "",
        f"Fully complete 60-trial set: **{report['complete_60_trial_study']}**",
        f"Model: {', '.join(report['model_names'])}",
        f"Evaluated: {report['judged_rows']}/{report['expected_or_planned']}",
        "", "| Arm | Judged | First pass | After one repair | 95% interval (first) | Mean initial LOC |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for arm, s in report["stats"].items():
        ci = s["first_pass_wilson95"]
        confidence = (f"[{ci['lower']:.1%}, {ci['upper']:.1%}]" if ci else "N/A")
        lines.append(f"| {arm} | {s['judged']} | {s['initial_success']} | "
                     f"{s['final_success']} | {confidence} | "
                     f"{s['initial_loc_mean']} |")
    lines += ["", "## Paired first-pass outcomes", "",
              "Only tasks and repeats judged in both arms are compared.",
              "| Pair | Comparisons | Left only passed | Right only passed | Same outcome |",
              "|---|---:|---:|---:|---:|"]
    for pair, s in report["paired_initial"].items():
        lines.append(f"| {pair} | {s['comparable_pairs']} | "
                     f"{s['left_only_passed']} | {s['right_only_passed']} | "
                     f"{s['same_outcome']} |")
    lines += ["", "## Important limitations", ""]
    for item in report["limitations"]:
        lines.append("- " + item)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, default=Path("bench/incoming"))
    parser.add_argument("--output-dir", type=Path, default=Path("bench/results"))
    args = parser.parse_args()
    paths = sorted({p.resolve() for p in args.input_root.rglob("local_ai_shard_*.json")
                    if re.fullmatch(r"local_ai_shard_\d+\.json", p.name)})
    if not paths:
        print("NO_RUN: no artifact JSON files were found")
        return 2
    data = analyze([json.loads(p.read_text()) for p in paths])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "local_ai_aggregate.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "local_ai_aggregate.md").write_text(
        summarize_markdown(data))
    print(summarize_markdown(data), flush=True)
    # Do not let a partial run masquerade as a complete experiment.
    return 0 if data["complete_60_trial_study"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
