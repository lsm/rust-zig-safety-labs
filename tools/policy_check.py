#!/usr/bin/env python3
"""Conservative lexical gate for a tiny Zig application subset.

This is a policy filter, NOT an AST/type checker, ownership proof, or race detector.
The trusted core.zig is outside this gate and must be reviewed separately.
Unknown/high-risk constructs are rejected rather than silently accepted.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Token:
    value: str
    line: int
    kind: str


LEX = re.compile(
    r'(?P<space>\s+)|(?P<comment>//[^\n]*)|'
    r'(?P<string>"(?:\\.|[^"\\])*")|'
    r"(?P<char>'(?:\\.|[^'\\])*')|"
    r'(?P<word>@?[A-Za-z_][A-Za-z_0-9]*)|'
    r'(?P<number>[0-9]+)|(?P<punct>\.\*|.)',
    re.DOTALL,
)
ALLOWED_IMPORTS = {"std", "core.zig"}
ALLOWED_BUILTINS = {
    "@import", "@as", "@intCast", "@splat", "@min", "@max", "@truncate",
    "@TypeOf", "@sizeOf", "@bitSizeOf",
}
HEAP_FIELDS = {"alloc", "free", "create", "destroy", "resize", "realloc", "dupe", "rawAlloc", "rawFree"}
THREAD_FIELDS = {"Thread", "spawn", "join", "detach", "Mutex", "Condition", "Semaphore", "Pool"}
DANGEROUS_FIELDS = {"ptr", "heap", "posix", "os", "c", "atomic", "memcpy", "memset"}
BAD_KEYWORDS = {"undefined", "unreachable", "extern", "export", "asm", "threadlocal", "volatile"}


def tokenize(source: str) -> list[Token]:
    out: list[Token] = []
    line = 1
    for hit in LEX.finditer(source):
        kind = hit.lastgroup or "punct"
        value = hit.group()
        if kind not in ("space", "comment"):
            out.append(Token(value=value, line=line, kind=kind))
        line += value.count("\n")
    return out


def check_text(source: str, *, allow_indexing: bool = False) -> list[str]:
    tokens = tokenize(source)
    violations: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()

    def deny(line: int, code: str) -> None:
        if (line, code) not in seen:
            seen.add((line, code))
            violations.append((line, code))

    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        nxt2 = tokens[i + 2] if i + 2 < len(tokens) else None
        value = tok.value

        if tok.kind in ("string", "char"):
            continue

        if value in BAD_KEYWORDS:
            deny(tok.line, "unsafe_control")

        if value.startswith("@"):
            if value in {"@ptrCast", "@ptrFromInt", "@intFromPtr", "@alignCast",
                         "@constCast", "@volatileCast", "@bitCast"}:
                deny(tok.line, "raw_pointer_ops")
            elif value in {"@memcpy", "@memset", "@memmove"}:
                deny(tok.line, "manual_copy")
            elif value in {"@setRuntimeSafety", "@setFloatMode", "@setAlignStack"}:
                deny(tok.line, "unsafe_control")
            elif value not in ALLOWED_BUILTINS:
                deny(tok.line, "unapproved_builtin")

        if value == "@import":
            # Only direct imports of std and the audited core are allowed.
            if not (nxt and nxt.value == "(" and nxt2 and nxt2.kind == "string"
                    and i + 3 < len(tokens) and tokens[i + 3].value == ")"):
                deny(tok.line, "unauthorized_import(dynamic)")
            else:
                try:
                    imported = ast.literal_eval(nxt2.value)
                except (ValueError, SyntaxError):
                    imported = ""
                if imported not in ALLOWED_IMPORTS:
                    deny(tok.line, f"unauthorized_import({imported})")

        if value == "." and nxt and nxt.kind == "word":
            if nxt.value in HEAP_FIELDS:
                deny(tok.line, "raw_heap")
            if nxt.value in THREAD_FIELDS:
                deny(tok.line, "direct_threading")
            if nxt.value in DANGEROUS_FIELDS:
                deny(tok.line, "raw_pointer_ops")

        if value == ".*" or (value == "." and nxt and nxt.value == "*"):
            deny(tok.line, "raw_pointer_ops")

        # Indexing expressions prohibited; array type declarations and literals
        # following punctuation (e.g. [64]u8 and [_]u8{1}) are allowed.
        if not allow_indexing and value == "[" and prev and (
            prev.kind == "word" or prev.value in {")", "]", "}"}
        ):
            deny(tok.line, "unchecked_index")

        if value == "[" and nxt and nxt.value == "*":
            deny(tok.line, "raw_pointer_ops")

        if value == "*" and prev and prev.value in {":", "?", ")"}:
            deny(tok.line, "raw_pointer_ops")

        # Zig multiline string syntax requires a full lexer: fail closed.
        if value == "\\" and nxt and nxt.value == "\\":
            deny(tok.line, "unsupported_multiline_string")

    return [f"L{line}: {code}" for line, code in violations]


def main() -> int:
    p = argparse.ArgumentParser(description="Conservative Zig safe-subset policy")
    p.add_argument("file", type=Path)
    args = p.parse_args()
    issues = check_text(args.file.read_text(encoding="utf-8"))
    if issues:
        print(f"DENIED: {args.file}")
        print("\n".join(f"  {x}" for x in issues))
        return 1
    print(f"ALLOWED: {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
