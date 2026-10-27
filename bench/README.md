# Round 2 — Zig safe subset and AI coding comparison

This stage comprises two distinct results:

1. FREE VALIDATION, already runnable: stricter lexical gate for restricted Zig,
   adversarial bypass tests, Python reference oracle, and nine hand-written
   control implementations across Zig plain, Zig restricted and safe Rust.
2. AI TRIALS, requiring a configured model API key: ten small byte-array tasks,
   three arms, five independent generations each, for 150 first-generation
   samples. Up to one compiler-only feedback repair per sample can be attempted.
   Until the AI job actually completes, no AI-code pass-rate claim is justified.

## Comparable tasks

Every solution is a single file implementing solve(input) -> u64 on unsigned
bytes, with input length from 0 through 128. The ten tasks span scanning,
boundary conditions, duplicate values, temporary owned memory and two real
threads. All arms see identical behavior specs and public examples; the
reference vectors used for evaluation are not sent as model prompt content.

Plain Zig uses ordinary Zig 0.17.0 facilities. Restricted Zig is subject to
the application policy and may use a separately audited core. Safe Rust is
compiled as Rust 2021 and disallows unsafe blocks. The trusted core shifts
work out of the restricted app, so candidate LOC alone is not a fair
whole-system size comparison.

## Run free real compiler checks

The workflow at .github/workflows/v2-tests.yml runs Python policy tests,
judge tests, nine hand-authored Zig/Rust controls in real compilers, and
the original first-round regression suite.

Local run commands:

    python3 tools/test_policy.py
    python3 bench/test_reference.py
    python3 bench/test_judge.py
    python3 bench/test_run_ai.py
    python3 bench/smoke.py --release-safe
    python3 bench/run_ai.py --dry-run

The dry-run explicitly writes NOT_RUN; it does not generate AI code.

## Run real model trials when you have an API key

The .github/workflows/ai-trials.yml GitHub Actions workflow is manually
triggered. Add an Actions repository secret named OPENAI_API_KEY, then choose
Run workflow, set one available exact Responses API model ID, five repetitions
and an explicit request-count limit. The workflow records versions, requested
and actual model IDs, token usage, per-trial code, compiler repairs and results.

IMPORTANT: OpenAI model API requests are billed independently of this chat.
150 first drafts plus repairs can be expensive. The configured hard limit is
a cap on NUMBER OF CALLS, not on dollars. No call occurs in --dry-run.
Responses API: https://developers.openai.com/api/reference/python/resources/responses/methods/create

Task/arm order is shuffled using a fixed seed, and no previous model outputs
are included in a fresh generation. Repairs use only compiler diagnostics,
not failed test assertions. Model generations are judged against reference
vectors, but passing finite tests is not formal memory or concurrency safety.

## Interpretation limits

The Zig gate is a conservative lexical filter; it can have false positives
and false negatives and cannot replace ownership analysis. Detection of
allocations and thread creation in candidates is a heuristic, not proof of
runtime use. Candidate LOC excludes the Zig trusted core; review both sizes
when comparing engineering effort. AI accuracy may only be reported after
the manually triggered generation job has completed, with all 150 records.
