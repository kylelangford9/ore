# Rules for every Ore builder

Read `docs/PLAN.md` first, then your own `L<n>.md`.

## Where you work
- Repo: `C:\Users\NSF\Downloads\ore` (branch `main`). Each builder works in its own git worktree under `D:\Build Artifacts\Local Workspaces\worktrees\ore-<branch>` on its own branch (named in the brief). The coordinator merges. Do not push, and do not merge into `main` yourself.
- Generated output (cargo targets, run logs, bake-off results, benchmark data, scratch) goes under `D:\Build Artifacts\ore\<your builder>\`. Never write generated output to C: or to a synced folder. If D: is missing, stop and report.
- Cargo: always `python scripts/cargo.py <args>` (portable MSVC + target dir on D:). Plain `cargo` fails to link on this PC.
- Python 3.12 is `python`. Node 24 is `node`. There is no deno or wasmtime CLI installed.

## What is true
- The language is `spike/SPEC-CARD.txt` plus the behaviour of `spike/ore.py`. The spike is the reference: when your Rust code and the spike disagree, the spike wins unless you list the divergence in your report with the reason. If the spike has a bug, fix it in the spike in the same commit and say so.
- Kyle's P2 note: "Models only, people irrelevant to read it". Build nothing for human reading: no pretty printer, no doc comments, no colour output. Every command prints JSON lines on stdout.
- Every diagnostic is one JSON object per line: `{"k":"err","code":"P002","line":1,"col":74,"msg":"...","fix":{...}}`. Keep the spike's codes. New codes get a new letter-number and go in `docs/DIAGNOSTICS.md`.

## Compute (Kyle's standing rule)
- No broad test suites. Write a unit test only where a change is risky. Your gate run (named in your brief) runs once at the end, plus one `python scripts/cargo.py check --workspace`.
- At most one heavy process at a time from you (one cargo build, one bake-off batch).
- Don't leave background processes running when you finish.

## Commits
- Small commits on your branch, imperative subject, body says why. End every commit message with:

```
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Q7xarcouPS7DKvwQMH5ds5
```

## Report (your final message)
1. Branch and last commit hash.
2. What you built, crate by crate, in a few lines each.
3. Your gate numbers, with the command that produced them and where the raw output is on D:.
4. Divergences from the spike, and spike fixes.
5. Anything left undone, and why.
