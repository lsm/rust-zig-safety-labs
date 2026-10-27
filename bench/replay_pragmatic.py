#!/usr/bin/env python3
"""Counterfactual replay: SAME Qwen 3B Zig code, ONLY the indexing rule changes.

This is NOT a new generation. Frozen candidate files from the previous CI
artifacts are recompiled and tested in ReleaseSafe under a relaxed policy.
"""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path
import tempfile
from judge import evaluate


def status(x: dict) -> str:
    if x["status"] == "PASS" and x["structural_evidence"].get("required") and not x["structural_evidence"].get("observed"):
        return "STRUCTURE_MISSING"
    return x["status"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    args = parser.parse_args()
    reports = list(args.input_root.rglob("local_ai_shard_*.json"))
    if len(reports) != 3:
        raise RuntimeError(f"Expected exactly 3 baseline artifacts; found {len(reports)}")
    results = []
    seen = set()
    digests = set()
    with tempfile.TemporaryDirectory(prefix="pragmatic-replay-") as tmp:
        for path in reports:
            data = json.loads(path.read_text())
            digests.add(data["model_identity"]["digest"])
            if data["model_identity"]["name"] != "qwen2.5-coder:3b-instruct":
                raise RuntimeError("Wrong baseline model, abort replay")
            root = path.parent.parent  # artifact directory, above results/
            initial_rows = {(r["task"], r["repeat"]): r for r in data["rows"]
                            if r["arm"] == "zig_restricted"}
            for (task, rep), previous in initial_rows.items():
                key = (task, rep)
                if key in seen:
                    raise RuntimeError("Duplicate task/repetition")
                seen.add(key)
                candidates = [p for p in root.rglob("initial.zig") if
                              "/zig_restricted/" + task + "/r" + str(rep) + "/" in p.as_posix()]
                if len(candidates) != 1:
                    raise RuntimeError(f"Cannot locate initial Zig source for {key}: {candidates}")
                original = candidates[0].read_text()
                reevaluated = evaluate("zig_pragmatic", task, original,
                                      Path(tmp) / task / ("r" + str(rep)),
                                      release_safe=True)
                current = status(reevaluated)
                previous_status = previous["initial_effective"]
                results.append({
                    "task": task, "repeat": rep,
                    "original_strict_status": previous_status,
                    "allow_checked_indexing_status": current,
                    "compiled": current not in ("COMPILE_ERROR", "POLICY_BLOCKED",
                                                "NOT_RUN", "TIMEOUT"),
                    "verdict": reevaluated,
                })
                print(f"{task} rep={rep} strict={previous_status} "
                      f"-> checked_indexing={current}", flush=True)
    if len(results) != 20 or len(digests) != 1:
        raise RuntimeError("Incomplete original study; cannot claim valid 20/20 replay")
    passed_before = sum(r["original_strict_status"] == "PASS" for r in results)
    passed_after = sum(r["allow_checked_indexing_status"] == "PASS" for r in results)
    rescued = sum(r["original_strict_status"] != "PASS" and
                  r["allow_checked_indexing_status"] == "PASS" for r in results)
    status_counts = dict(Counter(r["allow_checked_indexing_status"] for r in results))
    report = {
        "study": "qwen-3b-frozen-strict-output-index-only-policy-relaxation",
        "changed": "Only allow checked slice indexing in Debug AND ReleaseSafe; still block raw alloc/free, casts, FFI, threading.",
        "sample_count": len(results), "model_digest": next(iter(digests)),
        "strict_pass": passed_before, "relaxed_pass": passed_after,
        "newly_accepted_and_correct": rescued, "status_counts": status_counts,
        "warning": "Same generated source, not an AI prompt intervention; runtime bounds checks do not prevent dangling slices or data races.",
        "samples": results,
    }
    out = Path("bench/results")
    out.mkdir(parents=True, exist_ok=True)
    (out / "replay_pragmatic.json").write_text(json.dumps(report, indent=2))
    summary = [
        "# Strict versus checked-index Zig: frozen-code replay", "",
        f"Original strict PASS: {passed_before}/20",
        f"After allowing checked indexes under ReleaseSafe: {passed_after}/20",
        f"Newly passing: {rescued}", "", "New statuses: " + str(status_counts),
        "", report["warning"], "",
    ]
    (out / "replay_pragmatic.md").write_text("\n".join(summary))
    print("\n".join(summary), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
