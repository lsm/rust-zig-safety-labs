#!/usr/bin/env python3
"""Deterministic evaluation oracle for ten byte-array tasks (not model-visible)."""
from __future__ import annotations
import json
from pathlib import Path

TASKS = Path(__file__).with_name("tasks.json")


def reference(task_id: str, data: list[int]) -> int:
    assert all(isinstance(x, int) and 0 <= x <= 255 for x in data)
    assert len(data) <= 128
    if task_id in {"sum_bytes", "parallel_partition_sum"}:
        return sum(data)
    if task_id == "count_digits":
        return sum(48 <= x <= 57 for x in data)
    if task_id == "even_index_sum":
        return sum(data[::2])
    if task_id == "max_byte":
        return max(data, default=0)
    if task_id == "adjacent_equal":
        return sum(a == b for a, b in zip(data, data[1:]))
    if task_id == "longest_run":
        best = run = 0
        last = None
        for byte in data:
            run = run + 1 if byte == last else 1
            best = max(best, run)
            last = byte
        return best
    if task_id == "first_repeat_index":
        seen = set()
        for i, byte in enumerate(data):
            if byte in seen:
                return i
            seen.add(byte)
        return len(data)
    if task_id == "mirror_matches":
        return sum(data[i] == data[-i-1] for i in range(len(data)//2))
    if task_id == "bounded_copy_sum":
        return 0 if len(data) > 64 else sum(bytes(data))
    raise KeyError(task_id)


def load_suite() -> dict:
    return json.loads(TASKS.read_text())


def check_examples() -> None:
    suite = load_suite()
    assert len(suite["tasks"]) == 10, "Expected 10 tasks"
    ids = set()
    for task in suite["tasks"]:
        assert task["id"] not in ids
        ids.add(task["id"])
        for case in task["examples"]:
            assert reference(task["id"], case["input"]) == case["expected"]
        for case in suite["cases"]:
            reference(task["id"], case)


if __name__ == "__main__":
    check_examples()
    print("10 task specs and all oracle vectors checked")
