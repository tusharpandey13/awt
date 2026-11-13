# Spec: active recall

Status: draft for review. Nothing here is built yet. Once approved, the normative parts move into `SPEC.md` and `tests/TEST-SPEC.md` in the same PR as the code.

## Problem

`awt` records well but is rarely read back. Three gaps:

1. **No cross-referencing.** Agents only consult earlier decisions, answers and notes when a person tells them to.
2. **Records stand alone.** `decide` and `ask` write a row and print its id. Nothing shows that a related decision, or the answer to the same question, already exists in another workspace.
3. **No visibility.** A person cannot tell whether anything was stored during a turn. The Paseo stand-in handoff (`state --scope auto`) is written silently.

## Goals

- When an agent records something, it sees related records from the whole tree, and so does the person reading the transcript.
- Agents know cross-referencing exists and use it when they need it (on demand), without past data being pushed into every turn.
- After each turn, the person sees what `awt` stored for that turn.
- Context cost stays flat. Nothing is added to a turn unless the agent asks for it or has just written a record.

## Non-goals

- Injecting search results into every prompt. This was rejected because it fills context.
- Semantic or embedding search. Word overlap is enough for v1. The relaxed distribution rule (below) leaves room for it later if word overlap proves too weak.
- New verbs. The verb count stays at 16. Everything here is a flag or plugin behaviour.

## Constraint change: distribution

The owner lifted the "one file, stdlib only" requirement on 2026-11-12. `SPEC.md` Distribution, the repository `AGENTS.md` and the plugin section change from "one executable file, stdlib only" to:

> `awt` is a Python 3.9+ executable. It prefers the standard library; a third-party dependency needs a stated reason in its PR and must keep the documented install working.

This feature adds no dependency, so `awt` stays one file in practice.

## R1. `find --like TEXT`: ranked related records

A new flag on the existing `find` verb. It matches records by meaning-bearing words instead of one literal substring.

- **Words:** the lowercase tokens of TEXT that match `[a-z0-9][a-z0-9_./-]+`. A built-in list of about 80 English stopwords is removed, and so is any token shorter than 3 characters. Duplicates are dropped. Ids such as `d-7f3a9c21` and paths are kept as words.
- **Candidates:** event rows only, not files. That keeps it fast across 2,000 nodes. The rows are:
  - current decisions (superseded ones are excluded);
  - questions, with their answer if there is one;
  - notes;
  - refs (title and why);
  - `main`-scope states.
  `auto` states, effects and node rows are excluded.
- **Score:** SQLite FTS5 `bm25` over an in-memory index of the candidates, queried with the OR of the words; rare words count for more (phase 2 replaced the hand-rolled `log(1 + N/df)`; `docs/adr/0004-fts5-over-custom-scoring.md`).
  - A candidate qualifies when it shares at least 2 words, or 1 word when TEXT has at most 2 words.
  - `rule` decisions get a ×1.5 boost.
  - Ties go to the newest row.
- **Scope:** the same node set as `--tree`. `--up` or `--down` narrows it. The caps match `--tree` (depth 8 and 2,000 nodes).
- **Output:** one line per hit, best first:
  ```
  d-7f3a9c21 @workspaces/parsekit/tasks/retry-bug [rule]: Retry with jitter (why: Fixed backoff synchronised the clients)
  q-1a2b3c4d @workspaces/billing/tasks/main: Is the 30 s timeout a hard limit? → Yes, set by the gateway
  ```
  - The node prefix follows the existing `--tree` path rule.
  - Each line is cut to 200 chars.
  - The default limit is 10. `--limit N` (1–40) changes it.
  - When there are no hits, it prints `no related records`. Exit 0.
- `--like` cannot be combined with a TERM. Passing both is a usage error (exit 2).

## R2. `decide` and `ask` list related records

After writing, `decide` and `ask` print their usual first line and then up to N related records, ranked as in R1:

```
d-9e01b2c3 decided
related: d-7f3a9c21 @workspaces/parsekit/tasks/retry-bug [rule]: Retry with jitter (why: ...)
related: n-44aa01bc @workspaces/parsekit/tasks/main: CI retries flaky tests twice
```

- **Query text:** for `decide`, the choice and why. For `ask`, the question text. The row just written is excluded.
- **Answered questions show their answer.** An `ask` whose question was already answered elsewhere therefore shows the answer immediately.
- **N is configurable.** In order of precedence:
  1. the `--related N` flag on `decide` or `ask`;
  2. the `AWT_RELATED` environment variable;
  3. the default, 3.
  N ranges from 0 to 20, and 0 turns the lookup off. Any other value is a usage error (exit 2) for the flag, and is ignored with a stderr warning for the environment variable.
- **The write comes first and is never undone.** Any error in the lookup is swallowed: the write's line is still printed and the exit code stays 0. The lookup also stops after 2 s. When it stops early, it prints `related: (lookup stopped at 2 s; run awt find --like ...)`.
- Plain-text output only. Neither verb has `--json` today, and this spec does not add one.

## R3. Agents are told cross-referencing exists

This is a pointer only. No data is injected.

- **The task `AGENTS.md` template (`SPEC.md` → Templates):** a "Find things" line becomes:
  > `./awt find "term"` for an exact match; `./awt find --like "a sentence"` for related decisions, answers and notes from every workspace in the tree. Check before deciding or asking; `decide` and `ask` also list related records, so read them.
- **The plugin's static prompt block:** add one sentence, keeping the block at 700 chars or less and cache-stable:
  > Before a decision or question, `awt find --like "topic"` shows related past records from every workspace; `decide` and `ask` list them too.
  If the block would go over 700, the existing text is tightened. The cap does not move.
- **The resume brief:** no change, because it has a fixed size. The pointer lives in the template and the prompt block, which agents read once.

## R4. Turn receipt in Paseo

After every turn of an agent that has a node (subagents included), the plugin appends one plugin timeline item that shows what `awt` stored during that turn.

- **When:** in `agent.turn.after`, for any outcome (completed, failed or canceled), after the stand-in handoff has been written, so the receipt includes it.
- **What counts:** event rows with `ts` at or after the turn's start, in the agent's own node and its descendant subagent nodes.
- **How the plugin reads it:** the plugin may not read `.awt/` directly. A new read flag returns the rows: `awt list --since ISO8601 --json` gives an array of rows of every type, each with `type`, `ts`, `by`, `id`, plus `scope` for states. `--since` combines with `--down` to include descendant nodes, and each such row also gets `node`.
- **Timeline item:** `{ type: "plugin", kind: "awt.receipt", version: 1, data }`, where `data` is:
  - `node`: the agent node's name;
  - `counts`: per type (decision, question, answer, note, ref, state, effect, capture);
  - `ids`: at most 5 ids;
  - `auto`: true when the stand-in handoff was written this turn (the agent may also have written its own handoffs);
  - `empty`: true when nothing was stored.
- **The renderer** is a client contribution (`addTimelineRenderer`) that shows one muted line:
  - `awt · 1 decision d-9e01b2c3 · 1 note · handoff`
  - `awt · handoff [auto]`
  - `awt · 1 handoff · handoff [auto]` (the stand-in is always shown apart from the agent's own handoffs)
  - `awt · nothing stored this turn`
- **Setting:** `AWT_RECEIPT` defaults to on. `0` or `off` turns receipts off, and `changes` shows them only when something was stored.
- **Not seen by the model.** Plugin timeline items are UI-only and are not sent to the provider. The gated tier-2 test confirms this. If it turns out to be false, receipts default to off and this spec is revised.
- **Errors:** an append failure is logged and does nothing else. The plugin never fails a turn.

## R5. Context back after compaction

- **Standalone Claude Code:** already covered. The `SessionStart` hook that `init` writes has no matcher, so it runs on `compact` too and re-prints the brief. A test pins this (T-R5a).
- **Paseo agents:** Paseo does not let a plugin inject text into a turn, so this falls back to prompt text. The static block gets: "After your context is compacted, call awt_resume again."
  - Before writing that line, the build checks whether Paseo's Claude provider takes session hooks through `AgentSessionConfig`. If it does, the plugin adds a native `SessionStart` (matcher `compact`) hook running `awt resume --hook` with `AWT_DIR` set, and the prompt line is dropped.
  - The outcome is recorded in `SPEC.md` either way.

## Configuration summary

| Variable | Where | Default | Meaning |
|---|---|---|---|
| `AWT_RELATED` | agent env (the plugin forwards the daemon's value) | `3` | Related records after `decide` / `ask`. `0` turns them off |
| `AWT_RECEIPT` | daemon env | on | `0` or `off` off, `changes` only when something was stored |

Flags: `find --like TEXT [--limit N]`, `decide|ask --related N`, `list --since ISO8601 [--down] --json`.

## Tests (to be added to `tests/TEST-SPEC.md` and written before the code)

Core (`tests/test_recall.py`):

- **T-R1a:** `find --like` ranks a rare shared word above a common one.
- **T-R1b:** superseded decisions and `auto` states never match.
- **T-R1c:** hits from a sibling workspace show the correct node prefix from an agent node and from a cwd outside the tree.
- **T-R1d:** `rule` decisions get the boost.
- **T-R1e:** no hits prints `no related records` with exit 0.
- **T-R1f:** passing both `--like` and a TERM gives exit 2.
- **T-R1g:** 2,000-node tree with a time bound: under 2 s on CI hardware, as a chaos case.
- **T-R2a:** `decide` lists at most 3 related records by default and never the new row itself.
- **T-R2b:** `--related 0` and `AWT_RELATED=0` print only the id line.
- **T-R2c:** `--related 25` gives exit 2. `AWT_RELATED=abc` warns and uses 3; `AWT_RELATED=` (empty) is unset, no warning.
- **T-R2d:** `ask` shows the answer of an already-answered question elsewhere.
- **T-R2e:** a corrupt events file in another node still lets the write succeed with exit 0, and so does a fault injected inside the recall path (test hook).
- **T-R2f:** the 2 s budget is exceeded (simulated): the write stands and the stop line is printed.
- **T-R3a:** the `AGENTS.md` template contains the `find --like` line.
- **T-R3b:** the plugin block is at most 700 chars and contains `find --like`.
- **T-R4a:** `list --since` returns exactly the rows at or after the timestamp, with the fixed key set, and `node` with `--down`. `Z` (any case), `+HH:MM` and `+HHMM` offsets are accepted; naive times, bare dates and `""` are exit 2 with a fix.
- **T-R5a:** the `init` `SessionStart` hook has no matcher, so it covers `compact`.

Plugin (`paseo-plugin/test/`):

- **P15:** a turn that wrote a decision and a note appends one `awt.receipt` with matching counts and ids.
- **P16:** a turn that wrote nothing appends `empty: true`. With `AWT_RECEIPT=changes` nothing is appended. With `AWT_RECEIPT=0` nothing is appended.
- **P17:** the receipt comes after the stand-in handoff, with `auto: true`.
- **P18:** a timeline append that throws is logged and the turn is unaffected.
- **P19:** `AWT_RELATED` in the daemon env reaches the agent env from `agent.open.before`.
- **P20:** the renderer schema rejects an unknown version without crashing.
- **Tier 2 (gated, live daemon):**
  - receipts render;
  - receipts are absent from the provider's input;
  - the compaction-hook question in R5.

Existing suites must stay green: unittest, `tests/chaos.py`, `npm test`, `tsc --noEmit`.

## Docs to update in the same PR

- `SPEC.md`:
  - Distribution;
  - Verbs: the `find`, `decide`, `ask` and `list` rows;
  - Templates;
  - Node tree → Reading across nodes;
  - Paseo plugin: configuration, hooks table and prompt cost.
- `README.md`:
  - the Paseo bullets (the "one nudge" bullet is already out of date since PR #10);
  - one line on related records.
- `AGENTS.md`:
  - the work table gets `find --like`;
  - the Paseo settings table gets `AWT_RELATED` and `AWT_RECEIPT`;
  - the repository rule on distribution changes as above.
- `paseo-plugin/OVERVIEW.md`, `CHANGELOG.md` (Unreleased).

## Rollout

One PR. Merge only on the owner's go-ahead. Then release v0.3.0, and reinstall the CLI and the plugin on this Mac at the release ref.

## Open questions (defaults chosen; say if you want otherwise)

1. **Receipts default to on, every turn, including "nothing stored".** This answers "is anything being stored?" most directly. `changes` is available if it gets noisy.
2. **Receipts cover subagents too.** Each subagent's own timeline gets its own receipt.
3. **The default for related records is 3.** It is configurable from 0 to 20.
