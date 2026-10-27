#!/usr/bin/env python3
"""Reproducible 10-task x 3-arm x 5 independent AI coding experiment.

No model request is sent in --dry-run. Generated code sees public examples,
never held-out vectors; compiler-error repair receives filtered diagnostics.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
from urllib import request, error

from judge import MODES, evaluate, public_prompt
from reference import load_suite

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
OUTPUT = ROOT / "generated"
SYSTEM = ("You are a systems programmer. Return the complete source for one file "
          "only, no Markdown, no comments about your process, no dependencies.")


def code_only(text: str) -> str:
    value = text.strip()
    fence = chr(96) * 3
    if value.startswith(fence) and value.endswith(fence):
        value = "\n".join(value.splitlines()[1:-1]).strip()
    return value + "\n"


def response_text(payload: dict) -> str:
    if payload.get("output_text"):
        return payload["output_text"]
    return "\n".join(c.get("text", "") for m in payload.get("output", [])
                     if m.get("type") == "message"
                     for c in m.get("content", []) if c.get("type") == "output_text")


def generate(model: str, prompt: str, key: str, tokens: int) -> dict:
    body = json.dumps({"model": model, "instructions": SYSTEM, "input": prompt,
                       "store": False, "max_output_tokens": tokens}).encode()
    for attempt in range(3):
        call = request.Request("https://api.openai.com/v1/responses", data=body,
                               method="POST", headers={
                                   "Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
        try:
            with request.urlopen(call, timeout=180) as r:
                response = json.load(r)
            source = response_text(response)
            if not source.strip():
                raise RuntimeError("Model returned no source")
            return {"code": code_only(source), "response_id": response.get("id"),
                    "model": response.get("model"), "usage": response.get("usage", {})}
        except error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise RuntimeError(f"Model API HTTP {e.code}") from e
    raise RuntimeError("Response API retry limit exceeded")


def compiler_feedback(verdict: dict) -> str:
    if verdict.get("status") != "COMPILE_ERROR":
        return ""
    log = (verdict.get("build") or (verdict.get("runs") or [{}])[-1]).get("log_tail", "")
    # Never disclose judge-generated held-out vectors to the model.
    parts = [s for s in log.splitlines() if not any(
        phrase in s for phrase in ("judge.zig:", "judge.rs:", "vector_", "assert_eq!"))]
    return "\n".join(parts)[-2000:] or "Compiler rejected the source, check signature."


def summary(records: list[dict]) -> dict:
    out = {}
    for arm in MODES:
        rows = [r for r in records if r["arm"] == arm]
        judged = [r for r in rows if "final" in r]
        out[arm] = {
            "attempted": len(rows), "judged": len(judged),
            "first_pass": sum(r["initial"]["status"] == "PASS" for r in judged),
            "final_pass": sum(r["final"]["status"] == "PASS" for r in judged),
            "policy_rejections": sum(r["final"]["status"] == "POLICY_BLOCKED" for r in judged),
            "repair_requests": sum(r.get("repair_calls", 0) for r in rows),
            "structural_evidence": sum(
                r["final"]["status"] == "PASS" and (
                    not r["final"]["structural_evidence"]["required"] or
                    r["final"]["structural_evidence"]["observed"]) for r in judged),
            "mean_candidate_loc": (
                round(sum(r["final"]["metrics"]["source_lines"] for r in judged) / len(judged), 2)
                if judged else None),
        }
    return out


def write_results(meta: dict, records: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    scores = summary(records)
    (RESULTS / "ai_trials.json").write_text(json.dumps(
        {**meta, "summary": scores, "trials": records}, indent=2, ensure_ascii=False))
    table = ["# AI coding experiment", "", "Status: " + meta["status"],
             "Requested model: " + str(meta["model"]), "",
             "| Arm | Judged | First pass | Final pass | Structure* | Repairs | LOC |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for arm, s in scores.items():
        table.append(f"| {arm} | {s['judged']} | {s['first_pass']} | {s['final_pass']} | "
                     f"{s['structural_evidence']} | {s['repair_requests']} | {s['mean_candidate_loc']} |")
    table += ["", "*Structure is heuristic evidence, not proof of correct concurrency/allocation.",
              "Passing a test is not a lifetime, race-freedom or memory-safety guarantee.",
              "NOT_RUN trials are not counted as passes."]
    (RESULTS / "ai_trials.md").write_text("\n".join(table) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.environ.get("OPENAI_MODEL", ""))
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--task-limit", type=int, default=10)
    ap.add_argument("--repairs", type=int, default=1)
    ap.add_argument("--max-requests", type=int, default=300)
    ap.add_argument("--max-output-tokens", type=int, default=3500)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (1 <= a.trials <= 25 and 1 <= a.task_limit <= 10 and
            0 <= a.repairs <= 2 and a.max_requests > 0):
        ap.error("Invalid trial count or call budget")
    tasks = load_suite()["tasks"][:a.task_limit]
    jobs = [(t, m, n) for t in tasks for m in MODES for n in range(a.trials)]
    random.Random(20261027).shuffle(jobs)
    meta = {"model": a.model or None,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "NOT_STARTED", "planned_trials": len(jobs),
            "model_requests": 0, "prompt_hash": hashlib.sha256(SYSTEM.encode()).hexdigest(),
            "languages": "Zig 0.17.0 / stable Rust, compiler versions logged in CI"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "study_plan.json").write_text(json.dumps(
        {"task_ids": [t["id"] for t in tasks],
         "mode_counts": {m: len(tasks)*a.trials for m in MODES},
         "dry_run": a.dry_run, "max_requests": a.max_requests}, indent=2))
    if a.dry_run:
        meta["status"] = "NOT_RUN_NO_MODEL_CALLS"
        write_results(meta, [])
        print(f"Study plan: {len(tasks)} tasks x {len(MODES)} arms x {a.trials} "
              f"repeats = {len(jobs)} planned independent generations. NO API calls.")
        return 0
    key = os.environ.pop("OPENAI_API_KEY", None)
    if not key or not a.model:
        meta["status"] = "NOT_RUN_MISSING_KEY_OR_MODEL"
        write_results(meta, [])
        print("No AI calls: set OPENAI_API_KEY and --model.", file=sys.stderr)
        return 2

    records = []
    for task, arm, rep in jobs:
        row = {"task": task["id"], "arm": arm, "repeat": rep, "repair_calls": 0}
        if meta["model_requests"] >= a.max_requests:
            row["status"] = "NOT_RUN_REQUEST_BUDGET"
            records.append(row)
            continue
        prompt = public_prompt(task, arm)
        row["prompt_sha256"] = hashlib.sha256((SYSTEM + prompt).encode()).hexdigest()
        where = OUTPUT / arm / task["id"] / str(rep)
        where.mkdir(parents=True, exist_ok=True)
        suffix = ".rs" if arm == "rust_safe" else ".zig"
        try:
            meta["model_requests"] += 1
            first = generate(a.model, prompt, key, a.max_output_tokens)
            row["generation"] = {k: first[k] for k in ("response_id", "model", "usage")}
            code = first["code"]
            (where / ("initial" + suffix)).write_text(code)
            row["initial"] = evaluate(arm, task["id"], code, where / "judge_initial")
            verdict = row["initial"]
            for n in range(a.repairs):
                diagnostics = compiler_feedback(verdict)
                if not diagnostics or meta["model_requests"] >= a.max_requests:
                    break
                retry = (prompt + "\nPrevious source:\n" + code +
                         "\nCompiler diagnostics (candidate only):\n" + diagnostics +
                         "\nReturn corrected complete source, no commentary.")
                meta["model_requests"] += 1
                revised = generate(a.model, retry, key, a.max_output_tokens)
                row.setdefault("repair_generations", []).append({
                    k: revised[k] for k in ("response_id", "model", "usage")})
                code = revised["code"]
                (where / (f"repair{n+1}" + suffix)).write_text(code)
                row["repair_calls"] += 1
                verdict = evaluate(arm, task["id"], code, where / f"judge_repair{n+1}")
            row["final"] = verdict
            row["status"] = "JUDGED"
            print(f"{arm:15s} {task['id']:25s} rep={rep}: "
                  f"raw={row['initial']['status']} final={verdict['status']}", flush=True)
        except Exception as exc:
            row["status"] = "API_OR_JUDGE_ERROR"
            row["error"] = type(exc).__name__ + ": " + str(exc)[:200]
            records.append(row)
            meta["status"] = "INTERRUPTED"
            write_results(meta, records)
            print(row["error"], file=sys.stderr)
            return 2
        records.append(row)
        meta["status"] = "IN_PROGRESS"
        write_results(meta, records)
    meta["status"] = ("COMPLETE" if all(r["status"] == "JUDGED" for r in records)
                      else "PARTIAL_REQUEST_BUDGET")
    write_results(meta, records)
    print(f"{meta['status']}: {sum(r['status']=='JUDGED' for r in records)}/"
          f"{len(jobs)} judged; {meta['model_requests']} model API requests")
    return 0 if meta["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
