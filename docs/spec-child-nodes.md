# Spec: child nodes and the subagent-row link

Status: draft for review (issues #27 and #28). Nothing here is built. Once approved, the normative parts move into `SPEC.md` (Node tree, Detected effects, store.db) and `tests/TEST-SPEC.md` in the same PR as the code, tests first.

## Problem

1. **Shared node (#27).** A child that a parent agent launches with its own tool (Claude Code's `Agent` tool, pi's `subagent` tool from pi-subagents) inherits the parent's `AWT_DIR` and `AWT_BY`. Two parallel children overwrite `$AWT_DIR/out.md`, and their notes carry the parent's `by`. paseo-pi-async-agents (`docs/SPEC.md` section 10, item 4) calls this the largest risk for awt and works around it by hand: a per-run output path and `--by sub:<RUN_KEY>` in every brief. The Paseo plugin already gives every Paseo agent its own node, but children started by a provider's own tool are invisible to it.
2. **No link (#28).** Paseo shows each child as a subagent row whose descriptor carries `toolCallId` (`docs/PASEO-PARITY.md` there). A child's notes and output are named by its `RUN_KEY`. Nothing joins the two.

The two are one design. A child node named by the `RUN_KEY` can hold the `toolCallId` of the call that launched it.

## Facts this design rests on

| Fact | Source | Consequence |
|---|---|---|
| Paseo's row `toolCallId` is the launching tool call's id: Claude's `tool_use` id (`toolu_...`) for `Agent`/`Task`, pi's `call.callId` for `subagent` | Paseo 0.16.1 `providers/claude/subagents/live-source.js` (`toolCallId: id`, the `tool_use_id`), `providers/pi/extensions/pi-subagents/index.js` (`toolCallId: call.callId`) | The id is already in `store.db` as `tool_calls.tool_call_id` after `awt ingest --source claude|pi` |
| A Claude `PreToolUse` hook gets `tool_name`, `tool_input` (`description`, `prompt`, `subagent_type`, `name`, `run_in_background`) and `tool_use_id`. It fires before the subagent starts | Claude Code hooks reference, read 2026-11-18 | The launch is visible, with its id, before the child can write |
| No Claude Code hook can set env for one subagent. `CLAUDE_ENV_FILE` exists only for `SessionStart`, `Setup`, `CwdChanged` and `FileChanged`, and applies to the whole session. Subagents run in the parent's process | Same | A Claude child cannot get its own `AWT_DIR`. It must be told its node in text |
| `SubagentStart` gets `agent_id` and `agent_type`, but no `tool_use_id` and no prompt. It can only add `additionalContext` | Same | It cannot tell two parallel children apart, so it cannot tell each one its node. Not used |
| A `PreToolUse` `updatedInput` on a tool other than Bash, Edit, Write and the like can be denied in auto mode ("a hook changed this call's input after auto mode reviewed it") | Same | The hook does not rewrite the `Agent` prompt (open question 2) |
| The `Agent` tool result's `toolUseResult.agentId` names the child transcript `<session>/subagents/agent-<agentId>.jsonl` | A local transcript, checked 2026-11-18 | The store can attach the child's own session to the child node |
| pi-subagents 0.88.1 spawns the async runner with `env: {...process.env, ...}` of the parent pi process. A call cannot set env per child | `bundle/chunk-ZJ2BT5TI.js`, `runnerEnv` | The parent cannot hand a pi child its node through env |
| Ambient pi extensions load in pi-subagents children (pcg's hooks do; paseo-pi-async-agents `docs/SPEC.md` section 3) and the child process has `PI_SUBAGENT_CHILD=1` | paseo-pi-async-agents dev probe | awt's own pi extension (`awt init --hooks pi`) runs inside the child, where it can set its own process env |
| Every paseo-pi-async-agents brief has `RUN_KEY: <key>` on line 2 (D14); Paseo makes a row only for single `subagent` calls (D13) | paseo-pi-async-agents `docs/SPEC.md` | `RUN_KEY` is a machine-readable name in the launch input, for both providers |

## Interface: one flag

`init --child RUN_KEY`. Nothing else is added to the CLI. Everything else reuses something that exists: the `agent` kind, the `ref` row, the `ingest --event` hook entry point and the hook files that `init --hooks` installs.

Why a flag on `init`. The verb limit (16) is real, and `init` is already the verb that makes nodes (`--kind`, `--name`, `--key`). `resume --child` would make a read-only verb write. A new `spawn` verb would cost a verb. `--kind agent --name K` alone is not enough: it suffixes names on collision (`k-2`), so the path cannot be known before the call, and it does not mark the node as a child (see C3). The link (#28) needs no flag at all: it is an ordinary `ref` row whose target is `tool-call:<id>`.

## Rules

### Child nodes (#27)

- **C1. Creation.** `init --child RUN_KEY` makes an `agent` node at `<parent>/agents/<RUN_KEY>`, where the parent is the resolved node (`--dir` > `AWT_DIR` > script dir > walk up). The parent must be a `task` or an `agent`, as for any `agent` node; otherwise exit 1 with the `LEGAL` fix. `--child` cannot be combined with `--kind`, `--name`, `--key` or `--hooks` (exit 2). `--goal`/`--done` are optional; without them the goal is the `RUN_KEY`. It works in a standalone task directory too (a legacy node reads as a `task`).
- **C2. Name and path.** `RUN_KEY` must match `[a-z0-9][a-z0-9-]{0,39}` (else exit 2 with `fix: use lowercase letters, digits and -`), so it is its own slug. The directory is exactly `agents/<RUN_KEY>`, with no numeric suffix. The child's path is therefore known before it exists, by the parent and by any script.
- **C3. Marker.** The node row gets one new optional field, `run` (string, cap 40), equal to the `RUN_KEY`: `{"type":"node","kind":"agent","name":"scan-1","run":"scan-1"}`. A node is a **child node** exactly when its node row has `run`. No `key` is written: keys are unique across the whole tree, and a `RUN_KEY` is unique only within its parent. The identity of a child is its path.
- **C4. Idempotent, no lock.** The node is built in `agents/.new-<random>/` and renamed onto `agents/<RUN_KEY>`, as for every node. When the target already is a child node with the same `run`, the call succeeds and changes nothing; this covers a retry, a second hook and a race, where the loser of the `rename` re-reads the target. An existing empty directory is taken over, as today. A target that is anything else (a node without that `run`, a file, a non-empty non-node, a symlink) is exit 1 with `fix: pick another RUN_KEY`. `agents/` itself being a symlink is refused, as today.
- **C5. Output.** One line on stdout, shell-quoted values: `AWT_DIR=/abs/path/agents/scan-1 AWT_BY=sub:scan-1`. When the node already existed, stderr gets `note: child node agents/scan-1 already exists`. The exit code is 0 in both cases. The value of `AWT_DIR` is the real path.
- **C6. The child's `by`.** In a child node, a write without `--by` is stamped `by: sub:<run>`, and `AWT_BY` is ignored. The `AWT_BY` a child sees was set for its parent, so trusting it is exactly the bug in #27. `--by` still wins, so a hook (`--by hook`) or a person (`--by person`) is named as before. The rule lives in `emit`, so it holds for every verb.
- **C7. What the child does.** The child node follows the existing subagent contract (Node tree, Agent node contract): it does not run `resume` or write `state`, it writes its result to `out.md` in its node, and it may `note`, `ask`, `decide`, `ref` and `effect plan`. Its `BRIEF.md` is written at creation like every node's.

### How each provider's child gets its node

- **C8. The launch hook.** `ingest --event` (Claude `PreToolUse` payload, or the plugin shape `{phase: "before", tool, input, id, cwd}`) learns one more kind of call: a launch. A launch is a `before` event whose tool is `Agent` or `Task` (Claude) or `subagent` (pi) with a launch input: `prompt` (Claude) or `task` (pi, a call with no `action`, or `action: "resume"` with a `task`). The `RUN_KEY` is the first line among the first 5 lines of that text matching `^RUN_KEY: ([a-z0-9][a-z0-9-]{0,39})\s*$`. For a launch with a `RUN_KEY`, under the resolved node, the C1 creation runs, then writes the link (L1). A launch with no `RUN_KEY` line, or an invalid one, gets no node and nothing is written: the child shares the parent's node, as today. A launch is never a detected effect. The hook never blocks, rewrites or answers the call, is silent with `--hook` and exits 0 on any error. The same rule covers each `tasks[].task` of a pi parallel call (open question 3).
- **C9. Claude Code.** The `PreToolUse` entry that `init` writes into a task's `.claude/settings.json` gets matcher `Bash|mcp__.*|Agent|Task`. Its `sh` prefilter also passes a payload that holds `RUN_KEY:`. `awt init --hooks claude` adds one more entry to the machine-level settings (matcher `Agent|Task`, the same prefilter, marked `# awt:child`). Under Paseo this is the entry that runs, because Paseo-launched Claude agents load user settings but not a node's. Like the compaction hook, it does nothing unless `AWT_DIR` is set. Install and uninstall work like the `# awt:context` entry: only awt's own hook object is touched. **Honest limit:** Claude Code cannot give a subagent its own env (see Facts), so the child's `AWT_DIR` stays the parent's. The brief must carry the node: the launching skill writes `awt-node: $AWT_DIR/agents/<RUN_KEY>` and "pass `--dir <that path>` on every call of awt", and its output path is `<that path>/out.md`. C6 makes the `by` right without an `AWT_BY` in the brief. A child that leaves out `--dir` writes into the parent's node under the parent's `by` (open question 1).
- **C10. pi, parent side.** awt's pi extension (`awt init --hooks pi`, `extensions/awt-context.ts`) adds a `tool_call` handler. For tool `subagent` in a process with `AWT_DIR` set and `PI_SUBAGENT_CHILD` unset, it pipes `{phase: "before", tool: "subagent", input, id: toolCallId, cwd}` to `awt ingest --event --hook` and waits for it, with a 3 s limit, before the call runs. A failure or timeout is ignored and the call goes ahead.
- **C11. pi, child side.** In a process with `PI_SUBAGENT_CHILD=1` and `AWT_DIR` set, the same extension reads the first prompt in `before_agent_start`. When its first 5 lines hold a valid `RUN_KEY` line and `$AWT_DIR/agents/<RUN_KEY>` is a child node with that `run`, it sets `process.env.AWT_DIR` to that path and `process.env.AWT_BY` to `sub:<RUN_KEY>`, before the child's first tool call. Every `awt` call the child's `bash` tool starts then writes to the child node without any flag. Otherwise it changes nothing. It never creates a node: C10 already did, before the child process existed. Its compaction record then reads the child node.
- **C12. A harness without hooks** (relay, a script, a person) calls `init --child RUN_KEY` itself and puts the printed `AWT_DIR` and `AWT_BY` into the child's environment. That is the whole contract the issue asks for. paseo-pi-async-agents may also call it before a launch: it is idempotent with C8, and it makes the node exist even where no hook is installed.

### The link (#28)

- **L1. The row.** The link is a `ref` row in the child node: target `tool-call:<id>`, title the `RUN_KEY`, kind `tool-call`, access `ok`. `ref` infers kind `tool-call` from that prefix, as it infers `paseo` from `paseo:`. A person can write the same row with `awt --dir <child> ref tool-call:<id> --title <RUN_KEY>`. Latest per target wins, as for every ref, so a repeat changes nothing. A child launched again under the same `RUN_KEY` (paseo-pi-async-agents U12 uses a fresh one) gets a second `tool-call:` ref, so both rows link to the one node.
- **L2. Finding.** `awt find --tree <toolCallId>` and `awt find --tree <RUN_KEY>` both hit the child: the ref's target and title are event text. `awt --dir <child> list refs --json` shows it. Records without the ref, and nodes without `run`, are unchanged.
- **L3. Who writes it.** C8, at launch time, whenever the launch hook runs. Nothing else writes it: the Paseo plugin sees subagent rows only after the turn, which is too late to give the child a node.
- **L4. Store (`ingest`).** `store.db` gets a view `child_runs(node_id, run_key, tool_call_id, session_id, tool_name, link)`, one row per (child node, launching call). `session_id` and `tool_name` come from `tool_calls`. `link` is `ref` when the child's `tool-call:` ref names a `tool_calls` row. Otherwise it is `run_key`, for a `tool_calls` row of `Agent`, `Task` or `subagent` whose launch text has that `RUN_KEY` line (as in C8) in a session whose `node_id` is the child's parent. That covers a launch whose hook was not installed: "when both values are present" in the issue. No node log is written by ingest. Because a Paseo agent's session already joins to its node (`join_confidence = 'session_id'`), an ingested Paseo session shows the `RUN_KEY` of every row it launched with one join. The recipe for it is `docs/recipes/child-runs.sql`.
- **L5. The child's own transcript.** A Claude subagent session `<session>.agent-<agentId>` whose `agentId` is the `toolUseResult.agentId` of a call in `child_runs` gets `node_id` = the child and `join_confidence = 'tool_call'`. It is checked before the `cwd` join. pi child sessions are left as they are today (open question 6).
- **L6. Schema.** The view and the new `join_confidence` value bump `SCHEMA_VERSION` to 8. As for every bump, a plain `ingest` warns `run awt ingest --rebuild once`, and the old store keeps serving until then.

### Reading a tree with children

- **T1. resume.** The parent's Children section (section 9) already lists `agent` children with their `out.md` age and size when they have no state. Child nodes need nothing new there. The child itself does not resume (C7).
- **T2. find.** `--down` and `--tree` already walk `agents/`, so child records are found from the parent. The `@node` prefix shows `agents/scan-1`.
- **T3. doctor.** A child node is an ordinary `agent` node, so every existing check applies. `doctor` on a parent with live children passes (#27 acceptance). Two checks are added. `fail`: a node row with `run` whose directory name is not `run`, or that sits outside an `agents/` directory (it was moved by hand, and C4 would make a second one). `warn`: a node row with `run` that is not an `agent`.
- **T4. list.** `list nodes --json` adds the key `run` (`null` for non-child nodes). Adding a key is compatible.
- **T5. Older awt.** A node row with an extra `run` field reads as a plain `agent` node in awt 0.3.x (unknown fields are not checked). This is checked by a test against the v0.3.1 script.

### Cleanup

- **K1. Nothing is deleted.** A child node and its data are never deleted, like every other node. A child node holds a few KB: `.awt/`, `BRIEF.md` and `out.md`.
- **K2. Done on a finished call.** When the launch hook sees a launch end, it sets the child's status to `done`, or `paused` when the child has open questions or effects (the plugin's rule). Ending means a Claude `PostToolUse` for `Agent`/`Task` whose `tool_response.status` is `completed`, or an `after` event with `ok: true` for a pi `subagent` call that was not async. The same `PostToolUse`/`PostToolUseFailure` matcher as C9 carries it. An async launch (`isAsync`, or pi `async`) returns at once, so it changes nothing here.
- **K3. Done with the parent.** When a node is set to `done` (by `status done`, or by the Paseo plugin's archive), each of its direct child nodes that is still `active` is set to `done` in the same call, or to `paused` when it has open work. This finishes async children. It does not change when the parent may be done: an `active` agent node already does not block `status done`, and open questions or effects in a child still do.
- **K4. Bounded.** Child nodes count toward the existing 2,000-node walk limit, and `doctor` reports reaching it. The Children section's 500-character budget and the `+N more: awt list nodes` overflow keep a parent with many runs readable.

### What changes outside awt

- paseo-pi-async-agents. The output path becomes `$AWT_DIR/agents/<RUN_KEY>/out.md`. "First `n` whose output file does not exist" becomes "first `n` with no `agents/<key>`". The preamble drops `--by sub:<RUN_KEY>` (C6 does it) and "Never write `$AWT_DIR/out.md`": in a pi child `$AWT_DIR/out.md` is now its own file. Claude-provider briefs get the `awt-node:` line of C9. Section 10 item 4 can then close.
- The Paseo plugin needs no change. A Claude child's writes to `<child>/out.md` arrive as its parent's permission requests, and the target is inside the parent's node dir, which the plugin already allows. Paseo agents made with `create_agent` already get their own nodes.

## Tests (offline unless marked; to be added to `tests/TEST-SPEC.md` before the code)

Offline (`tests/test_child.py`, stdlib, temp dirs, fake hook payloads; no network, no model):

| Id | Test |
|---|---|
| CN-1 | `init --child scan-1` under a task makes `agents/scan-1` with node row `kind agent, name scan-1, run scan-1` and no key; stdout is exactly one line `AWT_DIR=<realpath> AWT_BY=sub:scan-1` |
| CN-2 | The same call again exits 0, prints the same line, adds no row and writes the stderr note |
| CN-3 | Invalid keys (`Scan`, `../x`, `a/b`, `-x`, 41 characters, empty) exit 2; nothing is created |
| CN-4 | Under a `workspace` or `root`: exit 1 with the legal-kinds fix. In a standalone legacy task: works |
| CN-5 | `agents/scan-1` already a non-child node, a file, a non-empty plain dir or a symlink: exit 1 `pick another RUN_KEY`. An empty dir is taken over |
| CN-6 | `--child` with `--kind`, `--name`, `--key` or `--hooks`: exit 2 |
| CN-7 | Two children `a` and `b` write `out.md` and `note` with `AWT_DIR` set to their own nodes and the parent's `AWT_BY` still in env. Each `out.md` is intact, and the notes carry `sub:a` and `sub:b` (#27 acceptance 1 and 2) |
| CN-8 | `--by hook` and `--by person` in a child node are kept (C6); outside child nodes `AWT_BY` works as before |
| CN-9 | `doctor` on a parent with two active children: no `fail` (#27 acceptance 3). A child dir renamed by hand: `fail` (T3) |
| CN-10 | Parent `resume` shows both children in Children with `out.md` age and size; `find --down` returns their notes with `@agents/<k>` |
| CN-11 | The v0.3.1 `awt` script reads a child node as an `agent`: `resume`, `list nodes`, `doctor` with no quarantine (T5) |
| CL-1 | Claude `PreToolUse` `Agent` payload with `RUN_KEY: scan-1` on line 2 and `tool_use_id toolu_X`: `ingest --event --hook` creates the child and the ref `tool-call:toolu_X`, prints nothing, writes no effect |
| CL-2 | The same with no `RUN_KEY` line, a `RUN_KEY` on line 7, or an invalid one: nothing written, exit 0 |
| CL-3 | pi plugin-shape `before` for `subagent` with `task` and `id call_Y`: same result as CL-1. `action: "status"`: ignored |
| CL-4 | `find --tree toolu_X` and `find --tree scan-1` both hit the child (#28 acceptance 1). A note in a node without the ref is listed exactly as before (#28 acceptance 3) |
| CL-5 | `PostToolUse` `Agent` with `status: completed`: child `done`. With an open question in the child: `paused`. With `isAsync`: unchanged (K2) |
| CL-6 | `status done` on the parent turns its active children `done`, and one with an open effect `paused` (K3) |
| CL-7 | `init --hooks claude` adds the `# awt:child` entry once; a rerun changes nothing; `--uninstall` removes only it; a sibling hook in the same entry survives |
| CL-8 | The generated pi extension (`awt-context.ts`) holds the `tool_call` handler and the child-side switch; a node script runs it against a fake pi API and checks the stdin it sends and the `process.env` it sets (C10, C11) |
| ST-1 | Fixture: a Claude parent transcript with two `Agent` calls (one with the ref, one without) and their `subagents/agent-<id>.jsonl`, a Paseo agent file joining the session to the parent node, and two child nodes. After `ingest`: `child_runs` has two rows with `link` `ref` and `run_key`, the right `run_key` and `tool_call_id`; the recipe lists both for the Paseo session (#28 acceptance 2) |
| ST-2 | The subagent sessions get `node_id` = their child and `join_confidence = 'tool_call'` (L5) |
| ST-3 | Rebuild byte-stability holds with child nodes present; an incremental ingest after a new ref equals a rebuild |
| ST-4 | A schema 7 store prompts for one rebuild (L6) |

Chaos (`tests/chaos.py`, group `child`):

| Id | Fault |
|---|---|
| CH-1 | 20 processes race `init --child k` on one parent: one node, all exit 0, all print the same line, no `.new-*` left |
| CH-2 | 20 different keys in parallel, plus 20 hook events for the same keys: 20 nodes, one ref each |
| CH-3 | SIGKILL during creation at random points: only a `.new-*` remains or the node is whole; a rerun succeeds; `doctor` reports the leftover |
| CH-4 | Garbage hook payloads (not JSON, wrong types, a 9 MiB prompt, lone surrogates, a `RUN_KEY` with a secret-shaped tail): `--hook` exits 0 silently, nothing half-written |
| CH-5 | `agents/` replaced by a symlink to another node between runs: refused, nothing written through it |
| CH-6 | A torn last line in the child's log, then a launch hook: the ref still lands (torn-tail heal), and `doctor` names the quarantined row |
| CH-7 | Parent log locked for 3 s by another writer during K3: the parent write succeeds or exits with the existing lock fix; no child is left half-marked (each child's status is one row) |
| CH-8 | 2,000 children under one parent: `find --down` and `doctor` report the walk limit in the standard words |

Gated (real providers; listed here, not run by this spec; they spend tokens or need a live daemon):

| Id | Verifies |
|---|---|
| G-1 | pi's `bash` tool passes `process.env` changes made by an extension in `before_agent_start` to the commands it starts (C11). If not, C11 falls back to the C9 brief line for pi too |
| G-2 | pi awaits a `tool_call` handler before running the call, and the event carries the `toolCallId` Paseo shows as the row's `toolCallId` (C10, L4) |
| G-3 | Under Paseo, a Claude agent's `Agent` call fires the user-level `PreToolUse` hook with the `tool_use_id` that the Paseo row shows (C9) |
| G-4 | Two parallel paseo-pi-async-agents children with sub-nodes write their own `out.md` and notes. This is paseo-pi-async-agents E7 rerun against the new layout |

## Traceability

| Requirement | Rules | Tests |
|---|---|---|
| #27: a parent can create a sub-node and get back `AWT_DIR`/`AWT_BY` | C1, C2, C4, C5, C12 | CN-1, CN-2, CN-3, CN-4, CN-5, CN-6, CH-1, CH-3 |
| #27: sub-node nested under the parent and labelled with the run key | C1, C2, C3 | CN-1, CN-10 |
| #27: resume, note, doctor treat it like a plugin node | C6, C7, T1, T2, T3, T4, T5 | CN-8, CN-9, CN-10, CN-11 |
| #27 acceptance 1: two children write `out.md` without overwriting | C2, C9, C11 | CN-7, G-1, G-4 |
| #27 acceptance 2: notes carry the child's own `by` | C6, C11 | CN-7, CN-8 |
| #27 acceptance 3: `doctor` passes on a parent with two live sub-nodes | T3 | CN-9 |
| pi children get it | C8, C10, C11 | CL-3, CL-8, G-1, G-2 |
| Claude Code children get it | C8, C9, C6 | CL-1, CL-2, CL-7, G-3 |
| #28: a field stores `toolCallId` with the RUN_KEY | L1, L3 | CL-1, CL-3, CH-2, CH-6 |
| #28 acceptance 1: found by either value | L2 | CL-4 |
| #28 acceptance 2: an ingested Paseo session shows each row's RUN_KEY | L4, L5, L6 | ST-1, ST-2, ST-3, ST-4 |
| #28 acceptance 3: records without the field unchanged | L2, T5 | CL-4, CN-11 |
| #28: document the field | Docs below | `tests/test_docs.py` |
| Cleanup of finished children | K1, K2, K3, K4 | CL-5, CL-6, CH-7, CH-8 |

Docs in the same PR: the `init` and `ref` rows of `CLI_HELP`, then `python3 tools/gen_docs.py` (regenerates `docs/reference/init.md`, `ref.md` and `docs/awt.1`); `SPEC.md` Node tree (child nodes, the `run` field, C6), Detected effects (launch events), store.db (`child_runs`, `tool_call` join); `docs/schema.md`; `docs/recipes/child-runs.sql`; the agent reference (`awt help agents`): "a subagent with `awt-node:` in its brief passes `--dir` to it". #28 asked for the field in `docs/reference/note.md`. Notes get no field here, because the link sits on the child node and covers every record in it. The ref kind is documented in `ref.md`, and `note.md` is generated, so it is not hand-edited.

## Open questions (defaults chosen; say if you want otherwise)

1. **Claude children that forget `--dir`.** Default: accept the brief-line limit. The option is a `PreToolUse` `Bash` guard that denies an `awt` write from inside a subagent (`agent_id` present) when the command has no `--dir`. Its reason would be a `fix:` line. That puts the rule in a script, at the price of one denied call and one more hook.
2. **Rewrite the `Agent` prompt instead.** The `PreToolUse` hook could append the `awt-node:` line itself through `updatedInput`, so briefs need no text about awt. Default no: auto mode can deny the changed call, and a launch must never fail because of awt.
3. **pi parallel and workflow calls** (`tasks:[]`, `workflow`). Default: give each `tasks[].task` with a `RUN_KEY` its own node, linked to the one shared call. Paseo shows no row for them (D13), so the link only helps the store.
4. **The `by` format.** Default `sub:<RUN_KEY>`, which matches today's preamble. `<parent by>/<RUN_KEY>` would say whose child it is, but the path already says that.
5. **Keep the store fallback** (`link = run_key`, for launches whose hook was missing)? Default yes: it is what #28 asks of `ingest`, and it is one `UNION` arm. Dropping it makes the link hook-only.
6. **pi child sessions.** pi-subagents keeps the child's session file path in its run status (`status.json` steps). Joining it to the child node (as L5 does for Claude) needs that path in the store. Default: out of scope until a pi-subagents ingest exists.
7. **`AWT_MODEL` for pi children.** The child extension could also set `AWT_MODEL` from the child's own model in C11. Default yes, if G-1 shows env changes reach `bash`; otherwise children keep the parent's model id (the store has the truth per message).
8. **Schema bump.** The `child_runs` view could be left out of `store.db` (a recipe-only query), which avoids the version 8 rebuild. Default: bump, so that `ui` and the recipes can rely on the view.
