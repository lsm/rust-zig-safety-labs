#!/usr/bin/env python3
"""Tiny transparent migration for common older Zig code-model syntax.

Not a language transpiler. All edits are explicit, counted and auditable.
This is intended to test whether version-aware tooling cheaply rescues AI code.
"""
from __future__ import annotations
import re


def repair(source: str, *, restricted: bool = False) -> tuple[str, list[str]]:
    out = source
    rules = []

    # Zig requires a second iterable to capture an index in a for loop.
    pattern = r'\bfor\s*\(\s*([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s*\)\s*\|\s*([a-zA-Z_]\w*)\s*,\s*([a-zA-Z_]\w*)\s*\|'
    replaced, count = re.subn(
        pattern, lambda m: f"for ({m.group(1)}, 0..) |{m.group(2)}, {m.group(3)}|",
        out)
    if count:
        out = replaced
        rules.append(f"zig_for_index_capture:{count}")

    # @intCast(type, value) was changed to @as(type, @intCast(value)).
    pattern = r'@intCast\s*\(\s*(u8|u16|u32|u64|usize|i32|i64)\s*,\s*([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)\s*\)'
    replaced, count = re.subn(
        pattern, lambda m: f"@as({m.group(1)}, @intCast({m.group(2)}))",
        out)
    if count:
        out = replaced
        rules.append(f"zig_old_intcast:{count}")

    if restricted and '@import("core")' in out:
        out = out.replace('@import("core")', '@import("core.zig")')
        rules.append("trusted_core_path")

    # Required imported std module may be missing in a generated standalone file.
    if re.search(r'\bstd\s*\.', out) and not re.search(
            r'\b(?:const|var)\s+std\s*=\s*@import\s*\(\s*"std"\s*\)', out):
        out = 'const std = @import("std");\n' + out
        rules.append("explicit_std_import")

    return out, rules
