#!/usr/bin/env python3
"""Run hand-authored conformance controls, NOT AI generated trials."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import tempfile
from judge import MODES, evaluate

ROOT = Path(__file__).resolve().parent
TASKS = ("sum_bytes", "bounded_copy_sum", "parallel_partition_sum")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-safe", action="store_true")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="zig-rust-v2-") as root:
        for mode in MODES:
            for task in TASKS:
                suffix = ".rs" if mode == "rust_safe" else ".zig"
                source = (ROOT / "smoke" / mode / (task + suffix)).read_text()
                verdict = evaluate(mode, task, source,
                                   Path(root) / mode / task,
                                   release_safe=args.release_safe)
                results.append(verdict)
                structural = verdict["structural_evidence"]
                signal = (not structural["required"] or structural["observed"])
                print(f"{mode:15s} {task:25s} {verdict['status']} "
                      f"structure={signal}", flush=True)
                if verdict["status"] != "PASS":
                    print(json.dumps(verdict, indent=2)[:5000], flush=True)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "smoke.json").write_text(json.dumps(results, indent=2))
    failures = [x for x in results if x["status"] != "PASS" or
                (x["structural_evidence"]["required"] and
                 not x["structural_evidence"]["observed"])]
    print(f"Controls: {len(results)-len(failures)}/{len(results)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
