# Ore plan (approved 2026-10-15)

Plan page: https://claude.ai/artifact/45xKKEhAGsP5RCojS6dh5n (picks live in its db collection `decisions`).
Kyle approved every pick and said "Picks in; ship it" on 2026-10-15.

## Picks (all option A)

| Pick | Decision | Kyle's note |
|---|---|---|
| P1 | Name: Ore | |
| P2 | Models only write Ore | "Models only, people irrelevant to read it": no readable printer (`ore view` is dropped), no comments in the store, nothing designed for human reading. Diagnostics stay JSON. |
| P3 | Keep the drafted surface. L1 switches to C-style calls only if they pass 5+ points more often at equal tokens. | |
| P4 | WebAssembly only; native code through wasmtime's ahead-of-time compile | |
| P5 | Perceus reference counting with reuse | |
| P6 | Rust toolchain | |
| P7 | Its own repo: `ore` (this repo) | |
| P8 | First host: Build's agents (ore mcp in Claude Code, wasmtime in BPR, Deno in Supabase Edge Functions) | |
| P9 | Bake-off on the Claude models Kyle's sessions use, plus local Gemma | "And codex too": Codex runs the bake-off as well |
| P10 | No grants by default; every run names its grants | |
| P11 | `fail` is an effect, handled with `catch` | |
| P12 | Local store per project first; shared Supabase store once two hosts use Ore | |
| P13 | Gates as drafted, with the stop rule | |

## Gates

| Gate | Measures | Target |
|---|---|---|
| G1 Tokens | tokens per program against Python, 120-task suite | ≤ 0.75× |
| G2 Edits | output tokens per accepted change, 30 change requests | ≤ 0.5× Python |
| G3 Correct | card only: first check passes; tests pass first try; after 2 fix rounds | ≥ 80%; within 5 points of Python; at or above Python |
| G4 Speed | 8 kernels against Rust `-O` and CPython | ≤ 2× Rust; ≥ 10× faster than CPython |
| G5 Check time | warm check of 1,000 lines; unchanged definitions | ≤ 50 ms; zero work |
| G6 Containment | missing grant, runaway loop, 30 escape attempts | refused; stopped; 30 of 30 blocked |
| G7 Card | spec card size | ≤ 1,500 tokens |

**Stop rule.** Check after L1 and again after L5. If tests pass first try more than 10 points below Python, or edits cost more than 0.8× Python's tokens, stop before the backend (L6–L8) and write up why.

## Build order

L1 ∥ L2 → L3 → L4 ∥ L5 ∥ L9 → L6 → L7 → L8 → L10 → L11 → L12

Briefs: `docs/builders/COMMON.md` (every builder) and `docs/builders/L<n>.md`.
