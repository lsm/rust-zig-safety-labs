#!/usr/bin/env python3
"""Hermetic compiler/runtime judge; generated candidates get no oracle source.

A passing test means passing THESE vectors, not memory-safety proof.
Structural concurrency/allocation checks are explicitly heuristics.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from reference import load_suite, reference

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from policy_check import check_text  # noqa: E402

MODES = ("zig_plain", "zig_restricted", "rust_safe")


def public_prompt(task: dict, mode: str) -> str:
    intro = (
        "Implement one standalone source file in Zig 0.17.0.\n"
        "Required signature: pub fn solve(input: []const u8) u64\n"
        if mode != "rust_safe"
        else "Implement one standalone source file in safe Rust 2021.\n"
             "Required signature: pub fn solve(input: &[u8]) -> u64\n"
    )
    rules = {
        "zig_plain": "Use ordinary Zig standard library facilities. Avoid relying on third-party dependencies.",
        "zig_restricted": (
            "Use the strictly restricted Zig application subset. You may import only std or "
            "core.zig. No direct allocations/free, pointer casts/dereferences, direct indexing, "
            "thread creation or FFI. The audited core.zig offers exactly:\n"
            "  pub fn readAt([]const u8, usize) ?u8\n"
            "  pub fn copySumBounded([]const u8) u64\n"
            "  pub fn parallelPartitionSum([]const u8) u64\n"
            "These core APIs are available as core.readAt, core.copySumBounded, and "
            "core.parallelPartitionSum. For other tasks, implement loops and arithmetic in "
            "your own function, respecting the safe-subset policy."
        ),
        "rust_safe": "Safe Rust only; no unsafe blocks, FFI, raw pointer dereferences or external crates.",
    }[mode]
    cases = "\n".join(
        f"  input={c['input']} -> {c['expected']}"
        for c in task["examples"]
    )
    return (
        f"{intro}{rules}\n\nTask {task['id']}: {task['spec']}\n"
        "All byte values are 0..255 and input length is 0..128. "
        "Sum fits in u64. Return a u64, not a string, and handle empty input.\n"
        f"Visible examples:\n{cases}\n"
        "Output ONLY the complete source file without Markdown or explanation."
    )


def structural_evidence(task_id: str, mode: str, code: str) -> dict:
    if task_id == "parallel_partition_sum":
        pattern = {
            "zig_plain": r"std\s*\.\s*Thread\s*\.\s*spawn",
            "zig_restricted": r"core\s*\.\s*parallelPartitionSum",
            "rust_safe": r"std\s*::\s*thread\s*::\s*scope",
        }[mode]
    elif task_id == "bounded_copy_sum":
        pattern = {
            "zig_plain": r"\.\s*alloc\s*\(",
            "zig_restricted": r"core\s*\.\s*copySumBounded",
            "rust_safe": r"\.\s*to_vec\s*\(",
        }[mode]
    else:
        return {"required": False, "observed": None, "note": "not applicable"}
    return {
        "required": True, "observed": bool(re.search(pattern, code)),
        "note": "Lexical evidence only; cannot prove actual ownership or threading semantics.",
    }


def metrics(code: str) -> dict:
    lines = code.splitlines()
    return {
        "bytes": len(code.encode("utf-8")),
        "source_lines": sum(bool(l.strip()) and not l.strip().startswith(("//", "///")) for l in lines),
        "branch_token_count": len(re.findall(r"\b(?:if|for|while|switch|match|loop)\b", code)),
    }


def _vectors(task_id: str, limit: int | None = None) -> list[tuple[list[int], int]]:
    cases = load_suite()["cases"]
    if limit is not None:
        cases = cases[:limit]
    return [(xs, reference(task_id, xs)) for xs in cases]


def _judge_zig(vectors: list[tuple[list[int], int]]) -> str:
    lines = ['const std = @import("std");', 'const candidate = @import("submission.zig");']
    for i, (xs, want) in enumerate(vectors):
        data = ", ".join(map(str, xs))
        lines.append(
            f'test "vector_{i}" {{ try std.testing.expectEqual(@as(u64, {want}), '
            f'candidate.solve(&[_]u8{{{data}}})); }}'
        )
    return "\n".join(lines) + "\n"


def _judge_rust(vectors: list[tuple[list[int], int]]) -> str:
    lines = ['#[path = "submission.rs"] mod candidate;']
    for i, (xs, want) in enumerate(vectors):
        data = ", ".join(f"{x}_u8" for x in xs)
        lines.append(
            f'#[test] fn vector_{i}() {{ assert_eq!(candidate::solve(&[{data}]), {want}_u64); }}'
        )
    return "\n".join(lines) + "\n"


def command(argv: list[str], cwd: Path, timeout: int = 80) -> dict:
    executable = argv[0]
    if shutil.which(executable) is None:
        return {"kind": "NOT_RUN", "message": f"Tool not installed: {executable}"}
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {
            "kind": "OK" if p.returncode == 0 else "FAILED",
            "exit_code": p.returncode,
            "log_tail": ((p.stdout or "") + "\n" + (p.stderr or ""))[-6500:],
        }
    except subprocess.TimeoutExpired:
        return {"kind": "TIMEOUT", "message": f"Timeout after {timeout}s"}


def evaluate(mode: str, task_id: str, code: str, work: Path, *,
             vector_limit: int | None = None, release_safe: bool = False) -> dict:
    if mode not in MODES:
        raise ValueError(mode)
    work.mkdir(parents=True, exist_ok=True)
    structural = structural_evidence(task_id, mode, code)
    result = {"mode": mode, "task_id": task_id, "metrics": metrics(code),
              "structural_evidence": structural}
    if mode == "zig_restricted":
        issues = check_text(code)
        if issues:
            return {**result, "status": "POLICY_BLOCKED", "policy_issues": issues}
        (work / "core.zig").write_text((ROOT / "bench" / "core.zig").read_text())
    if mode == "rust_safe" and re.search(r"\bunsafe\b|\bextern\b|std\s*::\s*ptr\s*::", code):
        return {**result, "status": "RUST_UNSAFE_REJECTED"}
    if mode.startswith("zig"):
        (work / "submission.zig").write_text(code)
        (work / "judge.zig").write_text(_judge_zig(_vectors(task_id, vector_limit)))
        modes = ["debug", "safe"] if release_safe else ["debug"]
        cmds = []
        for optimize in modes:
            outcome = command(["zig", "test", "judge.zig", "-O", optimize], work)
            cmds.append({"optimize": optimize, **outcome})
            if outcome["kind"] != "OK":
                log = outcome.get("log_tail", "")
                is_compiler_error = bool(re.search(r"(?m)^.*?:\d+:\d+: error:", log))
                status = ("COMPILE_ERROR" if is_compiler_error else
                          "NOT_RUN" if outcome["kind"] == "NOT_RUN" else
                          "TIMEOUT" if outcome["kind"] == "TIMEOUT" else "TEST_FAILED")
                return {**result, "status": status, "runs": cmds}
        return {**result, "status": "PASS", "runs": cmds}

    (work / "submission.rs").write_text(code)
    (work / "judge.rs").write_text(_judge_rust(_vectors(task_id, vector_limit)))
    built = command(["rustc", "--edition=2021", "--test", "judge.rs", "-o", "judge-bin"], work)
    if built["kind"] != "OK":
        return {**result, "status": "COMPILE_ERROR" if built["kind"] == "FAILED" else built["kind"],
                "build": built}
    # Absolute path because command() deliberately resolves executables through shutil.which.
    binary = work.resolve() / "judge-bin"
    try:
        out = subprocess.run([str(binary), "--quiet"], cwd=work, capture_output=True, text=True, timeout=35)
        status = "PASS" if out.returncode == 0 else "TEST_FAILED"
        return {**result, "status": status, "build": built, "test_exit_code": out.returncode,
                "test_log_tail": ((out.stdout or "") + "\n" + (out.stderr or ""))[-6500:]}
    except subprocess.TimeoutExpired:
        return {**result, "status": "TIMEOUT", "build": built}


def task_by_id(task_id: str) -> dict:
    return next(t for t in load_suite()["tasks"] if t["id"] == task_id)
