# Spec: passive recall

Status: built (unreleased). The normative parts are in `SPEC.md` (Passive recall) and `tests/TEST-SPEC.md`; this document keeps the rationale, calibration and decisions. Owner decisions of 18-Nov-2026 are recorded in Decisions. Deviations from this text are listed in the pull request.

Builds on `docs/spec-active-recall.md` (built and released in v0.3.x) and on two open branches: `feat/find-tool` (the `awt_find` agent tool and a search clause in `AWT_BLOCK`) and `fix/unknown-verb` (the unknown verb `crossref` and similar words map to `awt find --like`). Those make search easy to call. This spec is the next step: related records are pushed to the agent at the start of a context window, so it never has to search.

Design principle, decision d-25a992be: near-zero abstraction for agents; capture passively on the host side, detect outbound actions, read through plain files and SQL. Its reason: agents underuse the verbs, so value must not depend on agents learning or calling them.

## What exists already

| Piece | State | Where |
|---|---|---|
| `find --like TEXT [--limit N]`: words, stopwords, FTS5 bm25 over an in-memory index, `rule` x1.5, gate of 2 shared words | built | `SPEC.md` Reading across nodes; `awt` `recall()`, `words()`, `bm25_scores()` |
| `decide` / `ask` print up to `AWT_RELATED` (3) `related:` lines; 2 s budget; errors swallowed | built | `SPEC.md` Verbs; `show_related()` |
| Turn receipt timeline row `awt-receipt` v1 from `list --since --down --json` | built | `paseo-plugin/server/hooks.ts`, `shared/receipt.ts`, `client/receipt.tsx` |
| Framed brief after compaction: Claude `SessionStart` matcher `compact`, opencode `experimental.session.compacting`, pi `session_compact` + `before_agent_start` system section | built | `SPEC.md` Context after compaction; `awt` `OC_PLUGIN`, `PI_EXT`, `hook_command()` |
| Pointer to `find --like` in the brief's `## More` line and the plugin block | in `feat/find-tool` | that branch |
| Pushing records to an agent with no call | **not built** | this spec |

`spec-active-recall.md` listed "injecting search results into every prompt" as a non-goal because it fills context. This spec keeps that non-goal: it adds one bounded injection per context window, not one per prompt (see Triggers).

## Problem

1. Agents do not search. Only an agent that is told about `find --like`, or that writes a `decide`/`ask`, sees earlier work. The calibration below found that most first prompts in this tree have no related record, but when one exists the agent has to decide to look for it.
2. The ranking we have is tuned for an agent that asked. It returns its top 10 for any 2 shared words. Run passively, that is mostly noise (next section).
3. The person cannot see what an agent was shown. Nothing records it.

## Calibration (local, $0)

Calibration only, no model tokens. 120 first user prompts of Paseo sessions since 2026-11-01, sampled from `store.db`, were scored by awt's own `recall_rows()` and `bm25_scores()` against the live tree (259 nodes, 812 candidate records). Records written after the prompt and the agent's own node were excluded. A hit counts as "same project" when its workspace has the same `paseo:project/*` ref as the agent's.

| Gate | Top-5 hits | Same project | Prompts with any hit |
|---|---|---|---|
| Today's `find --like` gate (2 shared words) | 167 | 26% | 34 / 120 |
| idf sum of shared words >= 20 | 25 | 40% | 15 / 120 |
| Same project only, today's gate | 71 | 100% | 27 / 120 |
| **Same project, >= 3 shared words, idf sum >= 12** | 42 | 100% | 22 / 120 |
| The same, records with an id only (decisions, questions, notes) | 25 | 100% | 17 / 120 |

Findings:

- **No score threshold fixes cross-project noise.** At every bm25 or idf cut-off, 50 to 75% of hits came from another project. Scope does what thresholds cannot.
- **Cross-project hits are a privacy problem, not only noise.** The query "passive recall inject related records into agent prompt" run from an awt agent today returns, in its top 8, a health-records workspace's state line that names a PHI directory, and an unrelated cycling workspace.
- **Inside the project the gate matters.** By eye, hits with at least 3 shared words and an idf sum of at least 12 were mostly on topic: a prompt reviewing awt PR #16 got `n-d165e6b9` "E2E provider audit ... see docs/e2e-provider-gaps.md"; router prompts got the router notes. Hits below it were mostly off topic: a VLM research prompt got a router decision on 2 shared words; a "phase 2 brief" prompt got a note about Paseo permission modes.
- **Passive recall is rare, which is the point.** With the chosen gate, 14% of first prompts get anything, 1.5 lines on average.
- **It is fast.** `awt` starts in 0.10 s; a full `find --like` walk of this tree takes 0.16 to 0.20 s.

The thresholds are calibrated on one tree of about 800 candidates. `idf = ln(N/df)` grows with N, so they are constants to revisit at the shadow review after one week and again when the record count roughly doubles (Decisions).

## Goals

- An agent gets the few records most related to its work, with no call, at the start of each context window: its first prompt, and after a compaction or `/clear`.
- Nothing is injected when nothing clears the gate. No hit beats a noise hit.
- A hard budget per injection: at most 5 lines and 1,200 chars (about 300 tokens, never above 400).
- Never blocks or fails a turn. Never busts a prompt cache.
- Stays inside the agent's project by default, with opt-outs per node, per agent and globally.
- The person sees what was injected in the existing receipt row.
- Whether it helps is measurable from `store.db`, with a shadow mode as the control.

## Non-goals

- Injection on every prompt (see Triggers for the reasons). Only a shadow log of every prompt is in v1 (PR24).
- Recall for subagents. A subagent gets its brief from its parent (PR2).
- States and refs as candidates in v1.
- Embeddings or semantic search. Word overlap, scoped and gated, is enough for v1.
- New verbs. Everything is a flag on `find` or `resume`, a hook template, a plugin change, or one new event row type.
- Reading `store.db`, transcripts or files for recall. Only event records, which passed the secret scan when written, are candidates.
- A plugin-side injection. Paseo gives plugins no hidden context and no prompt hook (E11); the plugin's part is env forwarding and the receipt.
- opencode at session start. Its plugin API offers no verified hidden-context hook for a first prompt; it gets recall after compaction only (Decisions).

## Design

### Triggers

| Trigger | Mechanism | Query text | Chosen | Why |
|---|---|---|---|---|
| A. First prompt of an agent | Claude `UserPromptSubmit` (plain stdout is added to context, appended to the user turn); pi `before_agent_start` system section, set before the first request | the prompt, plus the agent's goal and its task's goal | **yes** | The best query there is: what the person just asked. It runs before any request, so no cache exists to bust. 14% of first prompts get lines |
| B. After compaction or `/clear` | the framed brief (`resume --hook --framed`) gets a `## Related elsewhere` section: Claude `SessionStart` (matcher `compact`, plus `clear` from this spec), opencode `experimental.session.compacting`, pi `session_compact` | the agent's goal, its task's goal, its newest `main` state and its newest `auto` state | **yes** | The context was just emptied, and the brief is re-injected anyway. Adding up to 1,200 chars to a 7,000-char brief costs little. The cache is already gone |
| C. Agent create, before any prompt | `agent.create.before` system prompt, or Claude `SessionStart` matcher `startup` | goal (the Paseo title) only | no | The plugin gets no prompt text at create. Dynamic text in the system prompt breaks the cache-stable block. A is the same moment with a much better query |
| D. Every later prompt | Claude `UserPromptSubmit`, pi `before_agent_start` | each prompt | no | Claude: each injection stays in context for the rest of the session, so noise accumulates. pi: the only silent channel is the system prompt, and changing it mid-session re-writes the whole cached context, the largest cost there is. Mid-session topic changes are what `awt_find` and the `decide`/`ask` related lines are for. Shadow mode logs every prompt's would-recall ids (ids only, never injected) to measure D later (PR24) |
| E. `decide` / `ask` | `related:` lines | the record text | already built, unchanged | The agent is writing; the related lines are about that record, so they are not deduplicated against A or B |

### One recall per context window

A **recall row** (new event type, below) is written in the agent's own node each time A or B runs. That row gives three things at once: the rule for when A runs, visibility, and measurement.

- **A runs only while the agent's node has no `recall` row.** That is the first prompt of the agent: a reopened or resumed Paseo agent continues its conversation and gets nothing.
- **B always runs** on a framed brief, and always writes a row (with no ids when nothing cleared the gate). A compaction or `/clear` empties the context, so B never deduplicates against earlier rows.
- **Shadow mode also writes a `trigger: every` row for each later prompt** (PR24). These rows never count for A and are never printed.
- So each context window gets at most one injection, and dedupe across triggers in one session needs no transcript parsing and no state outside the log.

### Query

- Text: for A, the prompt (from Claude's hook JSON `prompt`, or pi's `event.prompt`), cut to its first 2,000 chars, then the agent node's goal and its task's goal. For B, the goal, the task goal, the newest `main` state's `now` and `next`, and the newest `auto` state's `now` (the agent's last reply, the best topic signal after a compaction).
- A node under another agent node (a subagent) gets no recall: no A, no B, no row. Its brief comes from the parent.
- A prompt whose text starts with `[awt]` (the plugin's own messages) gives no recall and writes no row.
- Words as `words()` in `find --like` (lowercase tokens, `STOPWORDS`, at least 3 chars, no repeats). Then keep the 32 words with the lowest document frequency in the candidate set, ties by first appearance. A query with fewer than 3 words gives no lines.

### Candidates and scope

- The same candidates as `find --like` (current decisions, questions with their answers, notes), **minus refs and states**: every line must carry an id the agent can expand. States are summaries that go stale; the parent's brief already shows children's states.
- `N` and `df` are counted over the whole `--tree` candidate set, so a word's rarity does not depend on the scope.
- **Scope** (`AWT_RECALL_SCOPE`, default `project`): the subtree of the agent's project. The project is the nearest `project` ancestor, except Paseo's `unassigned` project (key `paseo:project/unassigned`), which collects workspaces with no project and so is no project; for a workspace in the legacy placement (directly under the root), the workspaces whose `kind=paseo` ref names the same `paseo:project/*` target; with neither, the agent's own workspace. `workspace` narrows to the own workspace; `tree` is the whole `--tree` set.
- **Excluded:** the agent's own node and its descendants (its own work and its subagents'); any id the agent's brief would show (its task's decisions and open questions, inherited `rule` decisions), so B never repeats its own brief and A never repeats what `awt_resume` will show; any node at or under a current decision tagged `no-recall`; a line whose text equals a higher-ranked line's (two nodes holding the same note).

### Gate and ranking

A candidate qualifies when it shares at least 3 query words and the idf sum of the shared words, `sum(ln(N/df))`, is at least 12. Qualifying candidates are ranked as `find --like` ranks them (bm25, `rule` x1.5, ties to the newest). The best 5 are kept. Without FTS5 the ranking falls back to the existing idf scoring; the gate does not use bm25, so it is the same with or without FTS5.

### Output

One frame line, then one line per hit:

```
awt: earlier records related to this work (reference only; not from the user; no action requested; full text: awt find --tree ID)
d-7f3a9c21 rule 12d parsekit/retry-bug: Retry with jitter (why: Fixed backoff synchronised the clients)
q-1a2b3c4d question 3d billing/main: Is the 30 s timeout a hard limit? -> Yes, set by the gateway
n-44aa01bc note 40d parsekit/main: CI retries flaky tests twice
```

- A line is `<id> <kind> <age> <where>: <text>`. Kind is `decision`, `rule`, `question` or `note`. Age is the brief's `ago()` without the word `ago`: `now`, `5m`, `3h`, `12d`. `<where>` is the workspace node's name, then `/` and the task node's name when the record is in a task or below it.
- Text: a decision's `choice (why: why)`, a question's `text -> answer` (or `text` when open), a note's `text`. Whitespace is collapsed to one line and a leading `#` is escaped, as in the framed brief.
- Each line is cut to 200 chars; the whole block, frame included, to 1,200 chars, dropping whole lines from the end.
- In B the lines go under the heading `## Related elsewhere (full text: awt find --tree ID)` after the brief, with no frame line of their own (the brief's frame covers them). This is the one pointer allowed in the framed record: it says where to read, not what to do.
- Nothing at all is printed when no candidate qualifies: no frame, no heading, no "no related records".

`awt find --tree ID` already finds a record by id across the tree (it searches event text literally). Whether `awt_find` should also accept an id is a question for `feat/find-tool`.

### The recall row

New event type `recall`, written by `emit()` like any row, in the agent's own node:

| Field | Meaning |
|---|---|
| `trigger` | `prompt` (A), `compact` (B; `/clear` included) or `every` (shadow-only log of a later prompt, PR24) |
| `result` | `hits`, `none` (nothing cleared the gate), `stopped` (deadline), `error`, `shadow` (hits computed, not shown; also used for every `every` row, with `ids: []` when nothing cleared the gate) |
| `ids` | the ids shown, or that would have been shown in shadow mode; at most 5; `[]` otherwise |
| `chars` | chars printed (0 when nothing was) |

- It holds ids only, no record text, so it adds nothing for the secret scan to catch.
- Written **before** anything is printed. If the write fails, nothing is printed, so a read-only log cannot turn A into an injection on every prompt.
- A recall write does not regenerate `BRIEF.md` (it changes nothing a brief shows).
- Never shown by `resume`, `list SECTION`, `find TERM` or `find --like`. It is in `list --since --json` (new keys `ids` and `result`, `null` on other rows), in `store.db` `records` (type `recall`), and counted by nothing else.
- Rule 3 ("record only what no machine can know"): what an agent was shown is only recoverable from provider transcripts, which are not ingested for opencode before a session ends and not at all without ingest. The row is the one place it is known. The alternative (no row: dedupe by reading transcripts, no Paseo visibility) was rejected by the owner (Decisions 1).

### Latency and failure

- `AWT_RECALL_MS` (a test hook like `AWT_RELATED_MS`) is the recall budget, default 800 ms, counted from the start of the recall step. At the deadline the step prints nothing and writes `result: stopped`, which also uses up A for this agent, so a slow tree cannot add a delay to every prompt.
- Every error prints nothing and exits 0. The Claude hook command ends `2>/dev/null; exit 0` and has a 5 s `timeout`: a `UserPromptSubmit` hook that exits 2 would block the user's prompt, so no exit code but 0 may reach Claude.
- No FTS5: ranking by idf, gate unchanged. Old or missing `store.db`: not read, so no effect. Unreadable or corrupt node logs: skipped, as in `find --like`. Walk limits (depth 8, 2,000 nodes): the walked part is used.
- An older `awt` reading a log with `recall` rows quarantines them as an unknown type (its brief shows "N quarantined rows" and `doctor` warns). Upgrading the CLI with the plugin and hooks avoids it; this is the same as the `node` row was.
- A new hook with an old `awt` (`find --hook` unknown): exit 2 on stderr, swallowed by the hook. Nothing is printed.
- After A ran, each later prompt still starts `awt` once to read the agent's own log and exit: about 0.10 s, measured.

### Privacy and scoping

- Default scope is the project. The calibration shows why: cross-project hits are mostly noise, and they carry another project's private details into a context that is often sent to a different model, provider or person.
- The store and all reads stay unredacted by design (d-406f9482). Recall reads only event records, which the write path already secret-scans (high-confidence patterns refuse the write). It never reads transcripts or files, which may hold secrets.
- **Opt-out:**
  - global or per agent: `AWT_RECALL=0` (or `off`) in the daemon's environment, forwarded to every agent like `AWT_RELATED`, or in one agent's environment; `awt init --hooks PROVIDER --uninstall` removes the hooks.
  - per node: a current decision tagged `no-recall` in a node or any ancestor, for example `awt decide "No passive recall in this workspace" --why "client data" --tag no-recall` on a workspace. That node and everything below it get no passive recall, and their records are never passive candidates for any other node. Superseding the decision undoes it. `find --like` and `related:` lines ignore the tag: a search someone asked for still works.
- `AWT_RECALL=shadow` computes and records everything and prints nothing (rollout, below). It also logs every later prompt, ids only (PR24).

### Visibility

- The receipt row is reused. `data` gets two optional keys: `recalled` (this turn's `recall` rows with `result` `hits` or `shadow` and non-empty `ids`, own node only: a list of at most 5 `{id, text}`, where `text` is a short form of the record, at most 80 chars, fetched by the plugin with `awt find --tree ID`) and `shadow` (true when they were not shown). A version 1 renderer ignores unknown keys (zod strips them), so the version stays 1.
- The line gains a leading part: `awt · recalled d-7f3a9c21 "Retry with jitter", n-44aa01bc "CI retries flaky tests twice" · 1 decision d-9e01b2c3`, or `awt · would recall d-7f3a9c21 "Retry with jitter" (shadow) · nothing stored this turn`.
- The text is local only: it is fetched at render time from the node logs, kept in the receipt row (UI-only), never written to a `recall` row or `store.db`, and never sent to the provider. A fetch that fails or is slow (about 0.1 s per id, 1 s in all) leaves the id without text.
- `recall` rows are not counted as stored: they are not in `counts`, and alone they leave `empty` true. `AWT_RECEIPT=changes` still shows a receipt that has `recalled`.
- A receipt is UI-only and not sent to the provider (tier-2 checked for v1 receipts), so showing would-recall ids and text in shadow mode does not leak them to the agent.
- Standalone Claude Code shows `UserPromptSubmit` output in its transcript view. The full text of a hit is `awt find --tree ID`.

### Measurement

No new verb. `store.db` already has `records` (with `node_id`), `sessions.node_id`, `messages`, `tool_calls` and `usage`.

- **M1 volume:** recall rows per trigger and result; the share of context windows with hits; chars per session against the session's input tokens (`usage_best`).
- **M2 use:** a shown id is used when, later in a session joined to the same node, an assistant message or a tool call's arguments contain it, or a later record in the node names it (`supersedes`, or in its text). Modelled on `docs/recipes/l7-find-use.sql`.
- **M3 control:** the same use measure for `shadow` ids. The agent never saw them, so their use rate is how often agents find those records unaided. Passive recall helps when M2 is well above M3.
- **M4 duplicates:** `docs/recipes/l7-redecisions.sql` pairs, widened from one node to one project, in context windows with and without recall hits. Still needs a person's judgment of meaning (the recipe is `partial`).
- **M5 per prompt:** from the `every` rows, the share of later prompts that would have had hits, and the use rate of their ids (M2 measure), to decide later whether a per-prompt trigger D is worth building. No model tokens are spent.
- One new recipe, `docs/recipes/l7-recall-use.sql` (M1 to M3, M5), and a cross-node variant of `l7-redecisions.sql` (M4). Both run in `awt ui`.

## Rules

Each rule has a test (Test plan). Constants live in one `RECALL` table in `awt`: lines 5, line 200, block 1,200, prompt cut 2,000, query words 32, minimum query words 3, minimum shared words 3, minimum idf sum 12, deadline 800 ms.

- **PR1 Triggers.** Passive recall runs only from (A) `find --like TEXT --hook` called by a first-prompt hook and (B) `resume --hook --framed`. No other verb, hook or plugin path injects records.
- **PR2 Needs a primary agent node.** Both print nothing and write nothing unless `--dir` or `AWT_DIR` names an `agent` node in a tree with no `agent` ancestor (a node under another agent is a subagent and gets nothing), and `AWT_RECALL` is not `0` or `off`.
- **PR3 Once per window.** A prints nothing and writes nothing when the node already has a `recall` row with trigger `prompt` or `compact` (`every` rows do not count). B always runs and always writes one row.
- **PR4 Write first.** The recall row is written before any line is printed; if the write fails, nothing is printed and the exit code is 0.
- **PR5 Query.** A: the stdin prompt (the `prompt` string of a JSON object, else the raw stdin), cut to 2,000 chars, plus the node's goal and its task's goal. B: goal, task goal, newest `main` state `now` and `next`, newest `auto` state `now`. Words as `find --like`, then the 32 rarest. Fewer than 3 words: no lines (`result: none`). A prompt starting `[awt]`: nothing, no row.
- **PR6 Candidates.** Current decisions, questions with their answers, and notes only. Never refs, states, effects, `node` or `recall` rows.
- **PR7 Scope.** `project` by default as defined in Candidates and scope; `workspace` and `tree` as named; any other `AWT_RECALL_SCOPE` value is `project`.
- **PR8 Exclusions.** No line names the agent's own node or a descendant, an id the node's `resume` brief contains, or a record at or under a current `no-recall` decision; no two lines have the same text.
- **PR9 Gate.** A line needs at least 3 shared words and an idf sum of at least 12 over the `--tree` candidate set. No candidate qualifies: no output at all.
- **PR10 Rank and cap.** bm25 order as `find --like`, at most 5 lines, each at most 200 chars, block at most 1,200 chars with whole lines dropped from the end.
- **PR11 Format.** Frame line exactly as in Output; lines `<id> <kind> <age> <where>: <text>`; one line each, leading `#` escaped. In B, the heading `## Related elsewhere (full text: awt find --tree ID)` after the brief and no frame line of its own.
- **PR12 Deadline.** At `AWT_RECALL_MS` (default 800) the step prints nothing and writes `result: stopped`.
- **PR13 Never fails.** Any error: nothing printed, exit 0, `result: error` when it can still be written. Every installed hook command ends `2>/dev/null; exit 0`.
- **PR14 Read sources.** Recall reads node event logs only, never `store.db`, transcripts or files.
- **PR15 Row.** `recall` has `trigger`, `result`, `ids` (at most 5 strings), `chars` (int); it does not regenerate `BRIEF.md`, is hidden from `resume`, `list SECTION`, `find TERM` and `find --like`, and is in `list --since --json` with keys `ids` and `result`.
- **PR16 Shadow.** With `AWT_RECALL=shadow` nothing is printed and A's and B's rows have `result: shadow` with the ids that would have been shown.
- **PR17 Brief unchanged elsewhere.** Plain `resume`, `resume --json`, `awt_resume` and `BRIEF.md` are byte-identical to today.
- **PR18 Hooks.** `init --hooks claude` adds one `UserPromptSubmit` entry (no matcher, `timeout` 5, marked `# awt:context`) and the `SessionStart` entry (see PR23); `--uninstall` removes only awt's marked objects. The pi extension calls A once, at the first `before_agent_start` of a session with no earlier user message, puts non-empty output in `systemPromptOptions.sections.awt_recall`, never changes it afterwards, and drops it at `session_compact`. The opencode plugin is unchanged.
- **PR19 doctor.** `doctor` runs its hook check with `AWT_RECALL=0` (a check writes nothing) and warns when an installed Claude hook set lacks the `UserPromptSubmit` entry.
- **PR20 Plugin env.** `agent.open.before` forwards `AWT_RECALL` and `AWT_RECALL_SCOPE` from the daemon's environment when set, as it does `AWT_RELATED`.
- **PR21 Receipt.** The receipt has `recalled` (a list of at most 5 `{id, text}` from this turn's own-node recall rows with `hits` or `shadow`; text at most 80 chars, local only, never stored in a row) and `shadow`; recall rows are not in `counts` and do not clear `empty`; `AWT_RECEIPT=changes` shows a receipt with `recalled`; the line is as in Visibility. Version stays 1.
- **PR22 Store.** `store.db` `records` holds `recall` rows like any other row; the recipes M1 to M4 run on it.

- **PR23 Clear matcher.** The `awt` tool owns the Claude `SessionStart` `clear` matcher: `awt init --hooks claude` installs the installed entry with matcher `compact|clear`, so `/clear` gets the framed brief and B (row trigger `compact`). Re-running `init` upgrades a `compact`-only install and changes nothing otherwise. It never edits or removes another tool's hook on `clear`. pcic (a separate tool) skips its own `clear` hook when awt's marked entry is present; that check is pcic's, and it only keeps the `# awt:context` marker stable so it can be found.
- **PR24 Shadow log of every prompt.** Only with `AWT_RECALL=shadow`, the first-prompt hook runs on every later prompt of a primary agent (the same hook, the same PR2 conditions) and writes one `recall` row with `trigger: every`, `result: shadow`, `ids` (what the same query, scope, exclusions and gate would show; `[]` when none), `chars: 0`. Nothing is printed. With `on`, later prompts write nothing. The row has ids only and obeys PR4, PR12 to PR14.

## Interface changes

| Where | Change |
|---|---|
| `awt` `find` | New flag `--hook`, only with `--like` (else exit 2). `--like -` reads stdin (JSON `prompt` or raw text). Hook mode: rules PR2 to PR16 |
| `awt` `resume --hook --framed` | Appends `## Related elsewhere` (B) and writes a `compact` recall row. Framed maximum grows by 1,200 chars (7,000 to 8,200 for an agent node) |
| `awt` events | New type `recall` (triggers `prompt`, `compact`, `every`; `REQ`, `load()` type checks: `ids` list of strings, `chars` integer) |
| `awt` `list --since --json` | Keys `ids` and `result` (null on other rows); adding keys is compatible |
| `awt` `find TERM`, `find --like`, `list SECTION`, `resume` | Never show `recall` rows |
| `awt` decision tags | `no-recall` has a meaning (PR8); no validation change |
| `awt` env | `AWT_RECALL` (`on`, `0`/`off`, `shadow`; shadow also logs every later prompt), `AWT_RECALL_SCOPE` (`project`, `workspace`, `tree`), `AWT_RECALL_MS` (test hook) |
| `awt` `init --hooks claude` | `UserPromptSubmit` entry; `SessionStart` matcher `compact` to `compact|clear` (PR23; pcic defers to it). Re-running `init --hooks claude` upgrades an existing install (it replaces only awt's marked objects) |
| `awt` `PI_EXT` | First-prompt recall section `awt_recall`; dropped at `session_compact` |
| `awt` `OC_PLUGIN`, Codex hook | Unchanged (B arrives through the framed brief) |
| `awt` `doctor` | `AWT_RECALL=0` in the hook check; warn on a missing `UserPromptSubmit` entry |
| `awt` `CLI_HELP` | `find --hook` text; `tools/gen_docs.py` regenerates the man page and reference |
| `store.db` | `records.type = 'recall'`; `docs/schema.md` lists it |
| `docs/recipes/` | `l7-recall-use.sql` (new); `l7-redecisions.sql` cross-node variant |
| Plugin `agent.open.before` | Forward `AWT_RECALL`, `AWT_RECALL_SCOPE` |
| Plugin receipt (`server/receipt.ts`, `shared/receipt.ts`, `client/receipt.tsx`) | Optional `recalled` (`{id, text}`), `shadow`; text fetched with `awt find --tree ID`; line text; `changes` rule |
| Plugin `AWT_BLOCK` | Unchanged. Passive recall adds no prompt text |
| `SPEC.md` | Verbs (`find`), Events (type table), Context after compaction (matcher, pi, framed budget), Reading across nodes (`list --since` keys), Paseo plugin (configuration, receipt), store.db |
| `README.md`, `AGENTS.md` | Paseo settings table gets `AWT_RECALL`, `AWT_RECALL_SCOPE`; the hooks section names `UserPromptSubmit` |

## Failure modes

| Failure | Effect |
|---|---|
| Recall exceeds 800 ms | Nothing printed; `stopped` row; A used up |
| No FTS5 | idf ranking; same gate |
| `store.db` old, missing, locked | None; not read |
| Corrupt or unreadable node logs | Skipped |
| Own log unwritable | Nothing printed, exit 0 (PR4) |
| Old `awt` with the new hook | Unknown flag, swallowed; nothing printed |
| New rows read by an old `awt` | Quarantined as unknown type; brief shows the count; `doctor` warns |
| Hook JSON malformed | Treated as raw text (pi passes raw text) |
| A subagent opens | Nothing printed, no row; the parent's brief covers it |
| `/clear` with pcic's own hook also present | pcic skips its hook when awt's marker is found; if it did not, two briefs, which is harmless |
| A huge pasted prompt | Cut to 2,000 chars and 32 words |
| A record whose text tries to pass for an instruction | One line, `#` escaped, after an id, under a "reference only" frame; scope limits who can write it. The same exposure as `find --like` today |
| Two Claude sessions on one `AWT_DIR` | At worst two A injections; Paseo gives each agent its own node |
| Claude `UserPromptSubmit` not loaded under Paseo | No A on Claude; B still works. Settled by the gated check D-PR1 |
| pi awaits no async `before_agent_start` | Section missing on the first request; settled by the fake-pi test T-PR18b and D-PR2 |

## Cost per session

Tokens only; convert with the price table in force when it matters, not from memory.

- **A, first prompt:** with the calibrated gate, 14% of first prompts get lines, 1.5 lines on average: about 100 tokens when it fires, 13 tokens expected per agent. Ceiling 1,200 chars, about 300 tokens. The text is added once, then read from cache on each later request: with 50 requests, at most 15k cache-read tokens in the worst case, about 650 expected.
- **B, per compaction:** at most 1,200 chars added to a framed brief of at most 7,000 chars, once per compaction, after the cache is already gone.
- **pi:** the section is set before the first request and never changed, so no cache re-write. This is why D is not offered on pi.
- **Latency:** A about 0.16 to 0.20 s on this tree, never more than the 800 ms budget plus startup. Each later prompt about 0.10 s (start `awt`, read own log, exit).
- **Writes:** one small row per agent plus one per compaction; in shadow mode also one per later prompt (ids only, about 150 bytes). No `BRIEF.md` regeneration.
- For comparison, an agent that searches by itself spends a tool call and a model round trip, and reads up to 10 lines from the whole tree.

## Rollout

1. **PR 1 (this spec, docs only).** Owner review; decisions recorded below.
2. **PR 2 (code, tests first).** Everything above, with `AWT_RECALL` defaulting to `shadow` in this release.
3. **Install** on this Mac: CLI, plugin, `awt init --hooks claude` and `--hooks pi` again (the owner runs these). Run `migrate-paseo` first so legacy workspaces sit under their projects (the ref fallback covers them either way).
4. **Shadow week.** Shadow mode also logs every prompt (PR24) so M5 is measured. The owner reviews at least 30 would-recall receipts or `l7-recall-use.sql` rows by eye. Go if at least 70% of shadow ids are on topic. The thresholds are revisited at this review, and again when the record count roughly doubles.
5. **Flip the default to `on`** in the next release. After two weeks of `on`, compare M2 with M3 and check M1 chars stay under 0.5% of session input tokens. If M2 is not clearly above M3, go back to `shadow` and revisit the gate.

**Recommendation: default on, after the shadow week.** The gate is strict, scope is the project, injection happens once per window, and the worst case is about 300 tokens. Shadow first because the thresholds come from one tree and the owner has not yet seen what would be injected.

## Decisions (owner, 18-Nov-2026)

1. **The recall row: kept.** The `recall` event type gives dedupe, the receipt and the shadow measurement.
2. **`/clear`: gets the brief and recall back.** The `awt` tool owns the Claude `SessionStart` `clear` matcher; `awt init --hooks claude` adds it next to `compact` (PR23). pcic, a separate tool, skips its own `clear` hook when awt's is present.
3. **Scope default `project`: accepted,** with the legacy `paseo:project` ref fallback. awt and pcg sharing one Paseo project is acceptable. `tree` is available.
4. **Thresholds** (3 shared words, idf sum 12): revisit at the shadow review after one week, and again when the record count roughly doubles.
5. **States and refs stay out in v1** so every line has an id.
6. **No recall for subagents in v1;** they get their brief from the parent (PR2).
7. **opencode: nothing at start** is acceptable for now; it gets B after compaction.
8. **Shadow mode logs every prompt, ids only,** to measure per-prompt recall later. It is not injected (PR24). D stays out of v1.
9. **Receipt: ids plus a short text,** local only (Visibility, PR21).

## Test plan

Tests are written before the code. Core tests go in `tests/test_passive_recall.py`, plugin tests in `paseo-plugin/test/recall.test.ts`, chaos cases in `tests/chaos.py`. Fixtures use the fictional `parsekit` project and made-up ids, extending F1 of `docs/e2e-active-recall.md` with a second project `ledgerline` and a `no-recall` workspace.

### Offline tests ($0)

Core:

- **T-PR1** Only `find --like --hook` and `resume --hook --framed` print recall lines; `decide`, `ask`, plain `find --like` output is unchanged (byte compare with fixtures).
- **T-PR2a** No `AWT_DIR`/`--dir`: nothing printed, no row. **T-PR2b** A task node (not an agent): nothing. **T-PR2c** `AWT_RECALL=0` and `off`: nothing, no row. **T-PR2d** A node under another agent node (subagent): A and B print nothing and write nothing; its parent still gets recall.
- **T-PR3a** First `find --like - --hook` writes a `prompt` row; a second call prints nothing and writes nothing (also after `every` rows exist). **T-PR3b** A framed brief after that prints the section and writes a `compact` row; the next prompt call prints nothing.
- **T-PR4** Log made read-only after the tree is built: nothing printed, exit 0, no partial output.
- **T-PR5a** Claude hook JSON on stdin uses `prompt`; raw text works; malformed JSON is raw text. **T-PR5b** A 50 KB prompt is cut; only the first 2,000 chars count (a word only after char 2,000 never matches). **T-PR5c** Two-word prompt: `result: none`. **T-PR5d** `[awt] ...` prompt: no row. **T-PR5e** B's query uses the `auto` state (a record matching only the auto state's words is recalled).
- **T-PR6** Refs, states, effects and superseded decisions never appear even when they share every word.
- **T-PR7a** Default scope: a `ledgerline` record sharing every word is absent; a sibling `parsekit` workspace's record is present. **T-PR7b** Legacy placement: two workspaces under the root with the same `paseo:project/*` ref recall each other; a third with another ref does not. **T-PR7c** `workspace` and `tree` scopes.
- **T-PR8a** Own node and subagent records absent. **T-PR8b** An id in the node's brief (task decision) absent. **T-PR8c** A `no-recall` decision on a workspace: its records are absent from another node's recall, and an agent below it gets nothing; after superseding it, both come back. **T-PR8d** `find --like` still returns `no-recall` records. **T-PR8e** Two identical notes in two nodes give one line.
- **T-PR9a** A record with 2 shared words is never shown. **T-PR9b** 3 shared common words (idf sum under 12) not shown; 3 shared rare words shown. **T-PR9c** No qualifying candidate: stdout empty (not `no related records`), row `none`.
- **T-PR10** 12 qualifying records: 5 lines in bm25 order with the `rule` boost; every line at most 200 chars; block at most 1,200 chars at maximum fill (long `why`, long node names).
- **T-PR11a** Exact frame line and line regex `^[dqn]-[0-9a-f]{8} (decision|rule|question|note) (now|\d+[mhd]) \S+: `. **T-PR11b** A note with a newline and a leading `#` cannot forge the frame or a heading. **T-PR11c** B: heading text, position after the brief, no second frame line.
- **T-PR12** `AWT_RECALL_MS=0`: nothing printed, row `stopped`; the next prompt call prints nothing.
- **T-PR13a** `AWT_TEST_RECALL_FAULT` inside the passive path: nothing printed, exit 0, row `error`. **T-PR13b** Every hook template's command string ends `2>/dev/null; exit 0`.
- **T-PR14** With `store.db` deleted, corrupt, or of a newer schema, output is identical; recall opens no file under `AWT_STORE` (checked with an `AWT_STORE` that is a file, not a directory).
- **T-PR15a** `recall` row fields and types; quarantine of a row with `ids` not a list. **T-PR15b** `BRIEF.md` mtime unchanged after a recall write. **T-PR15c** `list`, `resume`, `find d-...` and `find --like` never show it; `list --since --json` has `ids` and `result`.
- **T-PR16** `AWT_RECALL=shadow`: stdout empty, row `shadow` with the ids a normal run shows.
- **T-PR23a** `init --hooks claude` on an empty file, on a `compact`-only install and on one with a foreign `SessionStart` `clear` hook: awt's entry has matcher `compact|clear` and the `# awt:context` marker; the foreign hook is byte-identical; a second run changes nothing; `--uninstall` removes only awt's. **T-PR23b** Running the installed `SessionStart` command as a `clear` source: framed brief with `## Related elsewhere` and one `compact` row (fake Claude hook runner).
- **T-PR24a** `AWT_RECALL=shadow`, first prompt then three more: one `prompt` row and three `every` rows, `result: shadow`, nothing on stdout; a later prompt with no hit still writes an `every` row with `ids: []`. **T-PR24b** The `every` ids equal what `on` mode prints for the same prompt and tree. **T-PR24c** `AWT_RECALL=on`: later prompts write no row. **T-PR24d** `every` rows hold no record text, and `AWT_RECALL_MS=0` or a read-only log writes nothing and prints nothing.
- **T-PR17** Plain `resume`, `resume --json` and `BRIEF.md` byte-identical with and without recall data in the tree.
- **T-PR18a** `init --hooks claude` on an empty and on an existing settings file: one `UserPromptSubmit` entry, matcher `compact|clear`; a second run changes nothing; `--uninstall` leaves sibling hooks. **T-PR18b** Fake pi (as in the existing pi tests): first `before_agent_start` sets `awt_recall`; the second leaves it byte-identical; `session_compact` drops it; with no node nothing is set.
- **T-PR19** `doctor` writes no row; warns on a missing `UserPromptSubmit` entry.
- **T-PR22** `awt ingest --rebuild` puts `recall` rows in `records`; `l7-recall-use.sql` runs on a fixture store and returns the expected M1 to M3 counts (one used id, one unused, one shadow id used unaided).

Plugin:

- **PP1** `AWT_RECALL` and `AWT_RECALL_SCOPE` in the daemon env reach the agent env from `agent.open.before`; unset stays unset.
- **PP2** A turn with a `prompt` recall row gives a receipt with `recalled` and no `recall` in `counts`; `empty` stays true when nothing else was written.
- **PP3** `AWT_RECEIPT=changes` shows a recall-only receipt; a turn with neither recall nor writes shows none.
- **PP4** Shadow row: `shadow: true`, line `would recall ... (shadow)`; an `every` row shows the same way.
- **PP7** `recalled` entries carry `{id, text}` with text at most 80 chars from `awt find --tree ID`; a failing fetch leaves the id without text; the text appears in no `recall` row and no `store.db` record.
- **PP5** A version 1 receipt without the new keys still renders; a receipt with them parses under the old schema (keys stripped).
- **PP6** `AWT_BLOCK` byte-identical to `main` (passive recall adds no prompt text).

### Chaos cases

- **recall-2000** 2,000-node tree: A finishes under 800 ms on CI hardware or writes `stopped`; never prints a partial block.
- **recall-corrupt** A corrupt, a symlinked and a half-created (`.new-*`) node in scope: no crash, good rows still count.
- **recall-readonly** Own log read-only, then a directory named `events.jsonl`: nothing printed, exit 0.
- **recall-forge** Records crafted with the frame line, `## ` headings, 4 KB lines and control characters: the output stays within PR10 and PR11.
- **recall-shadow-volume** 200 prompts in shadow mode: 200 `every` rows, none printed, each call under the budget.
- **recall-race** Two concurrent first-prompt calls on one node: at most two rows, every printed block valid.
- **recall-old-awt** A v0.3.1 `awt` reads a log with `recall` rows: reads work, quarantine counted, writes succeed.
- **recall-hook-exit** The Claude hook command with a missing `awt` binary, with an `awt` that exits 2, and with one that sleeps past its timeout: exit 0 every time.

### Daemon-gated checks (live Paseo, no paid model; fake or local providers)

- **D-PR1** Claude provider under Paseo loads the `UserPromptSubmit` hook from user settings and the injected text reaches the request (wire capture, as E-R15).
- **D-PR2** pi under Paseo: the first request's system message has `awt_recall`; the second request's system message is byte-identical (cache-stable).
- **D-PR3** The receipt renders `recalled` with text; the receipt is absent from the provider's input.

### Agentic journeys (spend tokens; not run; owner approval per batch)

Harness `tests/agentic/run.py` with the F1 tree. Pilot one session per journey first and report its measured cost before a batch.

- **E-PR1 Conflict avoided.** A prompt asks for fixed-backoff retries; the project has a `rule` decision for jitter. Arms: `AWT_RECALL=on` against `shadow`, 10 sessions each. Pass: the on arm names the rule id or follows it more often than shadow by at least 4 of 10. About 20 sessions.
- **E-PR2 Answered question not re-asked.** A prompt raises a question answered in a sibling workspace. Measure: `ask` calls on the same question, on against shadow. About 20 sessions.
- **E-PR3 No noise harm.** A prompt with no related record in the project but strong word overlap with another project: no lines injected, and the transcript never names the other project's ids. About 5 sessions.
- **E-PR4 After compaction and `/clear`.** A long session compacted by `/compact`, and one cleared by `/clear`; the next turn names the recalled record. About 5 sessions.
- **E-PR5 Cost.** Recall chars per session against `usage_best` input tokens over all the sessions above; pass under 0.5%.

Estimate: about 50 sessions of 8 to 20 turns. Token counts per session as in `docs/e2e-active-recall.md` section 3.

### Traceability

| Rule | Tests |
|---|---|
| PR1 | T-PR1 |
| PR2 | T-PR2a, T-PR2b, T-PR2c, T-PR2d |
| PR3 | T-PR3a, T-PR3b, recall-race |
| PR4 | T-PR4, recall-readonly |
| PR5 | T-PR5a to T-PR5e |
| PR6 | T-PR6 |
| PR7 | T-PR7a, T-PR7b, T-PR7c |
| PR8 | T-PR8a to T-PR8e, E-PR3 |
| PR9 | T-PR9a, T-PR9b, T-PR9c, E-PR3 |
| PR10 | T-PR10, recall-forge |
| PR11 | T-PR11a, T-PR11b, T-PR11c, recall-forge |
| PR12 | T-PR12, recall-2000 |
| PR13 | T-PR13a, T-PR13b, recall-hook-exit, recall-corrupt |
| PR14 | T-PR14 |
| PR15 | T-PR15a, T-PR15b, T-PR15c, recall-old-awt |
| PR16 | T-PR16, PP4 |
| PR17 | T-PR17, PP6 |
| PR18 | T-PR18a, T-PR18b, D-PR1, D-PR2 |
| PR19 | T-PR19 |
| PR20 | PP1 |
| PR21 | PP2, PP3, PP4, PP5, PP7, D-PR3 |
| PR23 | T-PR23a, T-PR23b, T-PR18a, E-PR4 |
| PR24 | T-PR24a, T-PR24b, T-PR24c, T-PR24d, recall-shadow-volume, PP4 |
| PR22 | T-PR22, E-PR5 |
| Goals (helps at all) | E-PR1, E-PR2, E-PR4 |
