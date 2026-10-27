#!/usr/bin/env python3
"""Real, reproducible AI code trials using a local open-weight coding model.

The LLM sees only public_prompt(); hidden test vectors are never passed to it.
Separate fresh requests with different seeds; generated code is tested by the
existing compiler/runtime judge. A lexical safe-subset is not formal safety.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib import request, error

from judge import MODES, evaluate, public_prompt
from reference import load_suite
from run_ai import code_only, compiler_feedback

HERE = Path(__file__).resolve().parent
HOST = "http://127.0.0.1:11434"
SYSTEMS = {
    "zig_plain": (
        "LANGUAGE: ZIG 0.17.0 ONLY. Return Zig source, never Rust or C. "
        "A minimal unrelated syntax example: "
        "pub fn length_only(input: []const u8) u64 { return @as(u64, @intCast(input.len)); } "
        "Implement the specified task using the requested pub fn solve signature. "
        "Output code only, no Markdown."),
    "zig_restricted": (
        "LANGUAGE: ZIG 0.17.0 ONLY. Return Zig source, never Rust or C. "
        "An unrelated syntax example: "
        "pub fn length_only(input: []const u8) u64 { return @as(u64, @intCast(input.len)); } "
        "Follow the safe-subset contract strictly: NEVER write input[i], direct heap ops, "
        "or direct thread spawning. Import trusted API exactly as @import(\"core.zig\"); "
        "Use core.readAt(input, i) orelse 0 for indexed reads and core functions for "
        "copying and parallelism. Looping with for(input) |byte| is also allowed. "
        "Implement pub fn solve, output code only."),
    "zig_pragmatic": (
        "LANGUAGE: ZIG 0.17.0 ONLY. Return Zig source, never Rust or C. "
        "The practical safe subset ALLOWS direct slice indexing input[i] because "
        "every solution is checked in Debug AND ReleaseSafe with bound traps. "
        "Do not disable runtime safety. Still NO direct alloc/free, pointer casts, "
        "pointer dereferencing, FFI or direct thread spawning. "
        "Use core.copySumBounded and core.parallelPartitionSum for tasks requiring "
        "real ownership or two actual threads. You may @import(\"core.zig\") "
        "and use ordinary Zig loops and index arithmetic. "
        "Implement pub fn solve, output code only."),
    "rust_safe": (
        "LANGUAGE: RUST 2021 ONLY. Return valid Rust code, never Zig or C. "
        "An unrelated syntax example: "
        "pub fn length_only(input: &[u8]) -> u64 { input.len() as u64 } "
        "Use Rust let bindings, iterators, for item in input, and Rust type casts as needed. "
        "Do NOT write @import, @as, var, catch, []const u8 or any Zig construct. "
        "Implement pub fn solve using safe Rust only, output code only."),
}

MODEL_DEFAULT = "qwen2.5-coder:3b-instruct"


def api(path: str, payload: dict | None = None, timeout: int = 240) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        HOST + path, data=body, method="GET" if body is None else "POST",
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except (error.URLError, TimeoutError, ValueError) as exc:
            if attempt == 2:
                raise RuntimeError(f"Local model API unavailable ({type(exc).__name__})") from exc
            time.sleep(1 + attempt * 2)
    raise RuntimeError("Unreachable local model API")


def complete(model: str, prompt: str, seed: int, max_tokens: int, system: str) -> dict:
    response = api("/api/chat", {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": "20m",
        "options": {"seed": seed, "temperature": 0.22, "top_p": 0.92,
                    "num_predict": max_tokens, "num_ctx": 4096},
    })
    output = response.get("message", {}).get("content", "")
    if not output.strip():
        raise RuntimeError("Model returned empty source")
    return {"code": code_only(output),
            "tokens": response.get("eval_count"),
            "tokens_per_second": round(
                1e9 * response.get("eval_count", 0) /
                max(1, response.get("eval_duration", 1)), 2),
            "done_reason": response.get("done_reason")}


def model_identity(model: str) -> dict:
    response = api("/api/tags")
    match = next((x for x in response.get("models", [])
                  if x.get("name") == model or x.get("model") == model), None)
    if match is None:
        raise RuntimeError("Requested model not pulled: " + model)
    return {"name": model, "digest": match.get("digest"),
            "size_bytes": match.get("size"),
            "details": match.get("details", {})}


def effective_status(verdict: dict) -> str:
    status = verdict.get("status", "UNKNOWN")
    check = verdict.get("structural_evidence", {})
    if status == "PASS" and check.get("required") and not check.get("observed"):
        return "STRUCTURE_MISSING"
    return status


def repair_feedback(verdict: dict) -> str:
    status = effective_status(verdict)
    if status == "COMPILE_ERROR":
        return compiler_feedback(verdict) + "\nUse only the exact requested language."
    if status == "POLICY_BLOCKED":
        return "Safe-subset policy violations:\n" + "\n".join(
            verdict.get("policy_issues", [])[:12])
    if status == "STRUCTURE_MISSING":
        return ("Required behavior was not demonstrated. Actually implement the "
                "specified real OS threading or temporary owned allocation. "
                "The test requires the corresponding language-specific mechanism.")
    return ""  # Hidden runtime vectors never become repair prompts.


def per_arm(rows: list[dict]) -> dict:
    result = {}
    for arm in tuple(dict.fromkeys([*MODES, *(r["arm"] for r in rows)])):
        entries = [r for r in rows if r["arm"] == arm]
        evaluated = [r for r in entries if r.get("initial") and r.get("final")]
        result[arm] = {
            "trials": len(entries), "judged": len(evaluated),
            "initial_pass": sum(r["initial_effective"] == "PASS" for r in evaluated),
            "final_pass": sum(r["final_effective"] == "PASS" for r in evaluated),
            "compiler_rejects": sum(r["initial"]["status"] == "COMPILE_ERROR" for r in evaluated),
            "policy_rejects": sum(r["initial"]["status"] == "POLICY_BLOCKED" for r in evaluated),
            "logic_failures": sum(r["initial"]["status"] == "TEST_FAILED" for r in evaluated),
            "structural_missing": sum(r["initial_effective"] == "STRUCTURE_MISSING" for r in evaluated),
            "repairs": sum(r.get("repair_calls", 0) for r in entries),
            "mean_initial_loc": (
                round(sum(r["initial"]["metrics"]["source_lines"] for r in evaluated) /
                      len(evaluated), 2) if evaluated else None),
        }
    return result


def persist(shard: int, metadata: dict, rows: list[dict]) -> None:
    folder = HERE / "results"
    folder.mkdir(parents=True, exist_ok=True)
    data = {**metadata, "summary": per_arm(rows), "rows": rows}
    (folder / f"local_ai_shard_{shard}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Real AI generated code - shard " + str(shard), "",
        "Status: " + str(metadata["status"]), "",
        "Model: " + str(metadata.get("model_identity", {}).get("name")), "",
        "| Arm | Judged | First-pass valid | After repair | Compiler errors | Policy rejects | Missing behavior |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm, x in data["summary"].items():
        lines.append(f"| {arm} | {x['judged']} | {x['initial_pass']} | {x['final_pass']} | "
                     f"{x['compiler_rejects']} | {x['policy_rejects']} | "
                     f"{x['structural_missing']} |")
    lines += ["", "Structural checks are heuristics, not proofs.",
              "No statement about Rust-equivalent memory safety follows from this experiment."]
    (folder / f"local_ai_shard_{shard}.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL_DEFAULT)
    parser.add_argument("--arms", default="zig_plain,zig_restricted,rust_safe")
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=3)
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--repairs", type=int, default=1)
    parser.add_argument("--task-limit", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=640)
    parser.add_argument("--max-calls", type=int, default=80)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (1 <= args.shards <= 10 and 0 <= args.shard < args.shards and
            1 <= args.trials <= 10 and 0 <= args.repairs <= 2 and
            1 <= args.task_limit <= 10 and 80 <= args.max_tokens <= 2000):
        parser.error("invalid experiment bounds")

    selected_arms = tuple(x.strip() for x in args.arms.split(","))
    if not selected_arms or len(selected_arms) != len(set(selected_arms)) or any(
            x not in MODES + ("zig_pragmatic",) for x in selected_arms):
        parser.error("Bad --arms; allowed: " + str(MODES + ("zig_pragmatic",)))
    tasks = [(n, t) for n, t in enumerate(load_suite()["tasks"][:args.task_limit])
             if n % args.shards == args.shard]
    jobs = [(n, task, arm, rep) for n, task in tasks
            for rep in range(args.trials) for arm in selected_arms]
    metadata = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "model_identity": {"name": args.model}, "backend": "ollama-local-cpu",
        "generator_system_sha256": {arm: hashlib.sha256(SYSTEMS[arm].encode()).hexdigest() for arm in selected_arms},
        "temperature": 0.22, "top_p": 0.92, "ctx": 4096,
        "max_output_tokens": args.max_tokens, "shard": args.shard,
        "shards": args.shards, "repeat_count": args.trials,
        "max_calls": args.max_calls, "call_count": 0,
        "planned": len(jobs), "status": "NOT_RUN",
        "selected_arms": list(selected_arms),
        "methodology": ("Same Qwen model and prompt framework across all arms; "
                        "different seeds; public prompts only; one optional "
                        "compile/policy/structural repair; held-out tests. "
                        "This measures THIS small model, not general AI safety."),
    }
    if args.dry_run:
        metadata["status"] = "DRY_RUN_NO_GENERATION"
        persist(args.shard, metadata, [])
        print("DRY RUN only; expected candidate count", len(jobs))
        return 0
    metadata["model_identity"] = model_identity(args.model)
    rows = []
    for task_idx, task, arm, rep in jobs:
        seed = 2600000 + 100003 * rep + 97 * task_idx + 1009 * {"zig_plain": 0, "zig_restricted": 1, "zig_pragmatic": 1, "rust_safe": 2}[arm]
        prompt = public_prompt(task, arm)
        name = task["id"]
        folder = HERE / "generated_local" / f"shard_{args.shard}" / arm / name / f"r{rep}"
        folder.mkdir(parents=True, exist_ok=True)
        suffix = ".rs" if arm == "rust_safe" else ".zig"
        (folder / "public_prompt.txt").write_text(prompt, encoding="utf-8")
        (folder / "system_prompt.txt").write_text(SYSTEMS[arm], encoding="utf-8")
        row = {
            "task": name, "arm": arm, "repeat": rep, "seed": seed,
            "public_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "status": "NOT_RUN", "repair_calls": 0,
        }
        try:
            if metadata["call_count"] >= args.max_calls:
                row["status"] = "CALL_BUDGET_EXCEEDED"
                rows.append(row)
                continue
            metadata["call_count"] += 1
            generation = complete(args.model, prompt, seed, args.max_tokens, SYSTEMS[arm])
            code = generation.pop("code")
            (folder / ("initial" + suffix)).write_text(code, encoding="utf-8")
            row["generation"] = generation
            first = evaluate(arm, name, code, folder / "check_initial", release_safe=True)
            row["initial"] = first
            row["initial_effective"] = effective_status(first)
            verdict = first
            for attempt in range(1, args.repairs + 1):
                feedback = repair_feedback(verdict)
                if not feedback or metadata["call_count"] >= args.max_calls:
                    break
                revised_prompt = (prompt + "\nPrevious complete source:\n" + code +
                                  "\nTools detected the following (no hidden test vectors):\n" +
                                  feedback + "\nReturn only corrected complete source.")
                metadata["call_count"] += 1
                fixed = complete(args.model, revised_prompt, seed + 1000000 * attempt,
                                 args.max_tokens, SYSTEMS[arm])
                code = fixed.pop("code")
                (folder / (f"repair{attempt}" + suffix)).write_text(code, encoding="utf-8")
                row.setdefault("repair_generations", []).append(fixed)
                row["repair_calls"] += 1
                verdict = evaluate(arm, name, code, folder / f"check_repair{attempt}",
                                   release_safe=True)
            row["final"] = verdict
            row["final_effective"] = effective_status(verdict)
            row["status"] = "JUDGED"
            print(f"{arm} {name} r{rep}: {row['initial_effective']} -> "
                  f"{row['final_effective']} | model_calls={metadata['call_count']}",
                  flush=True)
        except Exception as exc:
            row["status"] = "ERROR"
            row["error"] = type(exc).__name__ + ": " + str(exc)[:200]
            print(f"Failed {arm}/{name}/{rep}: {row['error']}", file=sys.stderr,
                  flush=True)
        rows.append(row)
        metadata["status"] = "PARTIAL"
        persist(args.shard, metadata, rows)
    metadata["status"] = (
        "COMPLETE" if len(rows) == len(jobs) and
        all(r.get("status") == "JUDGED" for r in rows) else "PARTIAL")
    persist(args.shard, metadata, rows)
    print(f"FINISHED shard={args.shard}: {sum(r['status'] == 'JUDGED' for r in rows)}/"
          f"{len(jobs)} scored, requests={metadata['call_count']}, "
          f"status={metadata['status']}", flush=True)
    return 0 if metadata["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
