#!/usr/bin/env python3
"""Counterfactual test: model code stays frozen; apply tiny Zig syntax fixes.

Only changed sources require re-execution; unchanged sources retain the exact
original scored verdict. Results must not be called first-pass AI performance.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile

from judge import evaluate
from zig_syntax_repair import repair

ARMS = ("zig_plain", "zig_restricted")


def status(verdict: dict) -> str:
    if verdict["status"] == "PASS" and verdict["structural_evidence"].get("required") and not verdict["structural_evidence"].get("observed"):
        return "STRUCTURE_MISSING"
    return verdict["status"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input-root", type=Path, required=True)
    args = p.parse_args()
    reports = list(args.input_root.rglob("local_ai_shard_*.json"))
    if len(reports) != 3:
        raise RuntimeError("Expected all 3 baseline source-artifact shards")
    out_rows = []
    digests = set()
    identities = set()
    with tempfile.TemporaryDirectory(prefix="zig-syntax-replay-") as tmp:
        for rp in reports:
            data = json.loads(rp.read_text())
            digests.add(data["model_identity"]["digest"])
            if data["model_identity"]["name"] != "qwen2.5-coder:3b-instruct":
                raise RuntimeError("Baseline model mismatch")
            artifact_root = rp.parent.parent
            for r in data["rows"]:
                arm = r["arm"]
                if arm not in ARMS:
                    continue
                task, repeat = r["task"], r["repeat"]
                identity = (arm, task, repeat)
                if identity in identities:
                    raise RuntimeError("Duplicate original generation")
                identities.add(identity)
                matches = [x for x in artifact_root.rglob("initial.zig")
                           if f"/{arm}/{task}/r{repeat}/" in x.as_posix()]
                if len(matches) != 1:
                    raise RuntimeError("Cannot locate " + repr(identity))
                code = matches[0].read_text()
                candidate, fixed_rules = repair(code, restricted=arm == "zig_restricted")
                if candidate == code:
                    after = r["initial_effective"]
                    evaluated = {"status": "UNCHANGED_USE_ORIGINAL"}
                else:
                    verdict = evaluate(arm, task, candidate,
                                       Path(tmp) / arm / task / f"r{repeat}",
                                       release_safe=True)
                    after = status(verdict)
                    evaluated = verdict
                before = r["initial_effective"]
                out_rows.append({
                    "arm": arm, "task": task, "repeat": repeat,
                    "original": before, "after_syntax_fix": after,
                    "changed": bool(fixed_rules), "rules": fixed_rules,
                    "verdict": evaluated,
                })
                print(f"{arm} {task} r{repeat}: {before} -> {after} "
                      f"fixes={fixed_rules}", flush=True)

    if len(out_rows) != 40 or len(digests) != 1:
        raise RuntimeError(f"Incomplete replay: {len(out_rows)} rows")
    scores = {}
    for arm in ARMS:
        subs = [r for r in out_rows if r["arm"] == arm]
        scores[arm] = {
            "original_pass": sum(r["original"] == "PASS" for r in subs),
            "after_transparent_syntax_fixes_pass": sum(
                r["after_syntax_fix"] == "PASS" for r in subs),
            "changed_candidates": sum(r["changed"] for r in subs),
            "rules_applied": dict(Counter(
                rule.split(":")[0] for r in subs for rule in r["rules"])),
            "final_categories": dict(Counter(r["after_syntax_fix"] for r in subs)),
        }
    result = {
        "model": "qwen2.5-coder:3b-instruct",
        "model_digest": next(iter(digests)),
        "total_frozen_candidates": len(out_rows),
        "method": "Same frozen generation, limited deterministic syntax rewrite only, rerun in real Zig Debug and ReleaseSafe",
        "scores": scores,
        "warning": "A compiler migration helper is not a lifetime safety or data race detector; automated fixed code must be reviewed.",
        "samples": out_rows,
    }
    target = Path("bench/results")
    target.mkdir(parents=True, exist_ok=True)
    (target / "replay_syntax.json").write_text(json.dumps(result, indent=2))
    lines = ["# Frozen Qwen 3B code with cheap Zig syntax repair", ""]
    for arm, s in scores.items():
        lines.append(f"{arm}: {s['original_pass']}/20 -> "
                     f"{s['after_transparent_syntax_fixes_pass']}/20; "
                     f"changed {s['changed_candidates']} candidates; "
                     f"rules {s['rules_applied']}")
    lines.extend(["", result["warning"], ""])
    (target / "replay_syntax.md").write_text("\n".join(lines))
    print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
