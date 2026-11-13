# awt test plan

Companion to `SPEC.md`. It covers the node tree, the Paseo plugin and `migrate-paseo`. Existing tests keep their meaning and must stay green.

## Principles

1. **End to end by default.** A test runs the real `awt`, `migrate-paseo` or plugin entry as a subprocess in a temp directory with `HOME` set to it. No test imports `awt` as a module or mocks a filesystem call. The first assertion layer is the process: exit code, stdout, stderr. The second is the files left behind.
2. **Fakes only at the outer edge.** The one thing that may be faked is Paseo itself, and only when `paseo` is not installed (see Plugin). Everything between the harness and the disk is real.
3. **Reads are checked against the filesystem.** After any write, a test rebuilds the tree by walking directories and compares it with `list nodes --json`. The two must agree (invariant I1).
4. **Red first.** Each rule in `SPEC.md` gets its test before its implementation. A pull request that adds behaviour without a test here is incomplete.
5. **No real data.** Fixtures use the fictional `parsekit` project. Paseo snapshots use made-up ids (`wks_0001`, `agt_0001`). Secret-shaped strings are built at runtime.

## Layout

| File | Covers | Runs |
|---|---|---|
| `tests/test_tree.py` | Node tree: init, resolution, reads, status, doctor | always |
| `tests/test_recall.py` | Active recall: `find --like`, related lines on `decide`/`ask`, `list --since`, the template and prompt pointers | always |
| `tests/test_migrate_paseo.py` | `migrate-paseo` against snapshots | always |
| `tests/test_docs.py` | Existing. Extended: every `awt` command shown in the docs and the tree-form `AGENTS.md` block uses real verbs and flags | always |
| `tests/chaos.py` | Existing. New attacks in groups `tree`, `migrate`; the plugin attacks (C30-C40) are in `paseo-plugin/test/resilience.test.ts` | `--quick` in CI, full nightly |
| `paseo-plugin/test/*.test.ts` | Plugin hooks, driven by recorded payloads against real `awt` | always (needs Node) |
| `paseo-plugin/test/daemon.test.ts` | Plugin in a real daemon with a scripted agent | gated: `AWT_E2E_PASEO=1` or auto when `paseo` is on `PATH` |
| `tests/agentic/scenarios.py` | Existing. New scenarios `tree-resume`, `subagent`, `cross-ref`, `switch-task` | on demand, spends tokens |
| `fixtures/paseo-v0/` | Snapshots in the format `migrate-paseo --from` reads, and `home/`, a made-up on-disk Paseo store | |

Commands, in the order a contributor runs them:

```
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/chaos.py --quick
(cd paseo-plugin && npm test)
(cd paseo-plugin && AWT_E2E_PASEO=1 npm run test:daemon)                  # optional, ~70 s
python3 tests/agentic/run.py                                              # when prompts or interfaces change
```

## Invariants

Every test and every chaos run ends by checking the ones that apply.

| ID | Invariant |
|---|---|
| I1 | The nodes found by walking the reserved directories equal the nodes in `list nodes --json`; paths unique; each node's kind and its parent directory are a legal pair |
| I2 | No node is visible half-built: a node listed has a complete `.awt/events.jsonl` whose first row is `node` (or a legacy `task`) |
| I3 | No traceback on any stderr; every refusal has `error:` and `fix:`; exit codes only 0 to 4 |
| I4 | A key appears at most once in the whole tree |
| I5 | No file outside the tree root changed, apart from the documented ones (Paseo metadata through the plugin, nothing else) |
| I6 | A brief is within its budget: 4,400 chars with no ancestors or children, 7,000 for an agent node, 5,200 otherwise |
| I7 | Re-running any idempotent operation (`init --key`, `migrate-paseo`) writes no row and changes no file in the tree, apart from rewriting `legacy/paseo-migration.md` |
| I8 | Existing standalone tests produce byte-identical output to before the change |

## Node tree (`test_tree.py`)

Names are scenario ids.

**Creating**
- T1 `init --kind root` in an empty dir: `AGENTS.md` is the tree form (`awt`, not `./awt`), 2 KB at most, `workspaces/` exists, exit 0.
- T2 Create workspace, task, agent, subagent by walking down with `AWT_DIR`. Each lands in the reserved directory with the layout for its kind. Only the task gets `AGENTS.md` (tree form) and `.claude/settings.json` (hook `awt resume --hook`); none gets `README.md`. Workspace and agent without `--goal` get the placeholder `task` row.
- T3 Illegal pairs are refused with a `fix:` naming legal kinds: task under root, workspace under task, agent under workspace, agent under root.
- T4 `--name` missing for a non-root kind, or only one of `--goal`/`--done`: exit 2. A task with neither: exit 1 with a fix. `--kind root` on an existing node: exit 1 with a fix.
- T5 Name collision with a different key: second node gets a numeric suffix. Same key: same path printed, exit 0, no new rows (I7).
- T6 Same key with a different name, or under a different parent anywhere in the tree, returns the existing node; nothing is renamed or moved.
- T7 Slug rules: names with spaces, unicode, `..`, `/`, a leading dot, only punctuation. The directory is always `[a-z0-9-]`, at most 50, never escapes the parent. A name over the 60-char cap is refused with a `fix:`.
- T8 A secret-shaped `--name` or `--key` is refused and nothing is created.
- T9 Standalone `init` without `--kind` is unchanged (I8), including inside a tree: at `w/tasks/x` it makes a legacy child task of `w`; at `w/foo` it makes a node with no parent (no lineage, not in `w`'s Children or `list nodes`) and `doctor` in `w` warns.
- T14 Converting: a standalone task moved into a workspace's `tasks/` becomes its child task with no other change; its log is untouched.
- T15 A later `node` row is quarantined; the first one stands.

**Resolution**
- T10 `cd` into any node resolves to it. `AWT_DIR` beats `cwd`. `--dir` beats `AWT_DIR`.
- T11 `AWT_DIR` pointing at a non-node: exit 4 with a fix.
- T12 Ancestor walk stops at 8 levels and says so, and stops after the first `root`: a root inside another tree's node shows no lineage above itself. A symlinked child dir is not followed, so a loop (child linking to an ancestor) terminates; `doctor` reports it.
- T13 `mv` of a subtree to another place in the tree: a `ref kind=node` to a keyed node resolves by key wherever it moved; one to an unkeyed node resolves when the move contains both ends, and shows `access: none` otherwise. Parents change as expected.

**Reading**
- T20 `resume` in a leaf task prints lineage (outermost first) and inherited `rule` decisions with their origin. Non-rule ancestor decisions do not appear.
- T20a `resume` in an agent node prints its task's goal, done-means, newest state, open questions, attention effects and non-rule decisions (section 10). A task node and a standalone node print no section 10.
- T21 `resume` in a task with 3 agent children prints one line per child with its newest `now`; active first; an agent with no state but an `out.md` shows its age and size; one with neither shows `no state`.
- T22 Budgets at maximum fill: 8 ancestors with goals at the 250-char cap and 300-char rules, 200 children with 700-char states; and an agent node whose task is full in every section. Results within 5,200 and 7,000 (I6); overflow is `+N more` lines, never a cut line.
- T23 A standalone node prints the same brief as the previous release, byte for byte (I8).
- T24 `list nodes`, `list tree`, `--all`, `--json` match each other and the filesystem (I1). A test pins every `--json` key listed in `SPEC.md`.
- T25 `find --down` finds text in a grandchild's `docs/` and events; `--up` finds it in an ancestor; without a flag, neither. `--tree` searches the whole tree under the nearest root (sibling tasks and their agents too; a standalone node falls back to ancestors plus descendants). Hits capped at 40 in total, prefixed by relative node path.
- T25d `find` hit prefixes work from the cwd: an agent whose cwd is a repo outside the tree (node via `AWT_DIR`) gets absolute node paths that `--dir` accepts; from inside the tree they stay relative.
- T26 `ref` on a directory with `.awt/` records `kind=node`, the target's key and a relative path; `ref paseo:agent/x` records `kind=paseo`.
- T27 A parent's own walks stop at child nodes: with a note and a file in `tasks/x`, the parent's `find` (no flag), `list misc`, resume section 5 and `save` see none of the child's files, and `tasks/` is not listed under `misc`.
- T28 In a tree node every command the brief prints is `awt`, not `./awt`; a standalone node still prints `./awt`. Section 5 of a task shows commits in its workspace's `repo` ref.

**Status**
- T30 `status done` on a task is refused while a child task is active, an agent has an open question, or an agent has an `unknown` effect. The refusal lists each with its path. Resolving them lets it pass.
- T31 Archiving flow: `done` refused, `paused` accepted.
- T32 `status done` on an agent node never blocks its parent.

**doctor**
- T40 One line per defect, at the level `SPEC.md` gives: `fail` for illegal nesting and a key used twice in the tree; `warn` for a misplaced or repeated `node` row, a node outside a reserved directory, a non-node entry in a reserved directory, a leftover `.new-*` directory, a symlinked child dir, an active child under a `done` parent, `awt` not on `PATH`. A clean tree gives no warnings.

**Agent contract**
- T50 Two agents write to their own nodes in parallel (20 processes, 50 writes each): no row lost, no row crosses nodes, each node's log is valid JSON lines (I3).
- T51 `AWT_BY` is stamped on every row written under it.

## Active recall (`test_recall.py`)

Spec: `docs/spec-active-recall.md`; normative text in `SPEC.md` (Reading across nodes, Paseo plugin).

- T-R1a `find --like` ranks a rare shared word above a common one; ties go to the newest row.
- T-R1b Superseded decisions and `auto` states never match.
- T-R1c Hits from a sibling workspace carry the right node prefix from an agent node and from a cwd outside the tree.
- T-R1d `rule` decisions get the x1.5 boost.
- T-R1e No hits: `no related records`, exit 0.
- T-R1f `--like` with a TERM, or `--limit` without `--like`: exit 2.
- T-R1g (chaos `tree-recall-2000`) A 2,000-node tree: `find --like` in 2 s or less and the 5-line cap holds; `decide` under 4.5 s.
- T-R1h `--limit` 1 to 40 (others exit 2); each line is cut to 200 characters.
- T-R1i `--up`/`--down` narrow the scope; answers, refs and ids match; paths and ids are words.
- T-R1j Trailing `.`, `/`, `-`, `_` are not part of a word.
- T-R2a `decide` prints at most 3 related lines by default and never the new row.
- T-R2b `--related 0` and `AWT_RELATED=0` print only the id line.
- T-R2c `--related 25` is exit 2; `AWT_RELATED=abc` warns on stderr and uses 3.
- T-R2d `ask` shows the answer of an already answered question elsewhere.
- T-R2e A corrupt events file in another node does not fail the write.
- T-R2f A simulated exceeded budget (`AWT_RELATED_MS`): the write stands, the stop line prints.
- T-R2g The 200-character cut of a `related:` line includes its prefix.
- T-R3a The task `AGENTS.md` template has the `find --like` line.
- T-R3b The plugin block is at most 700 characters and names `find --like`.
- T-R4a `list --since` returns exactly the rows at or after the timestamp with the fixed keys, `node` (null for the own node) with `--down`; usage errors exit 2.
- T-R5a The `init` `SessionStart` hook has no matcher, so it covers `compact`.

## Chaos (`tests/chaos.py`, groups `tree`, `migrate`, `plugin`)

Same style as today: seeded, one line per attack, a failure prints the seed and the commands. Quick mode picks small counts of each.

**tree**
- C1 *Racing creators.* 32 processes `init --kind task --key K`, half on one parent and half on another: exactly one node in the tree, all print the same path (I4, I7).
- C2 *Racing names.* 32 processes create tasks named `x` with distinct keys: 32 nodes, unique suffixes, no clobbering.
- C3 *Kill during init.* SIGKILL an `init --kind agent` at random moments, 200 times. Afterwards no half-built node is listed (I2), `.new-*` leftovers are reported by `doctor`, and a retry with the same key succeeds with one node.
- C4 *Kill during write.* SIGKILL writers in a child node; the torn tail heals on the next write as today, and the parent is unaffected.
- C5 *Tree mutation while reading.* `list tree`, `resume` and `find --tree` run in a loop while nodes are created, `mv`-ed and deleted. No traceback, output always a consistent snapshot of something that existed (I3).
- C6 *Hostile layout.* Symlinks to ancestors and to `/`, a 9-deep chain, 2,500 siblings, a node dir containing a file named like a reserved dir, a child dir without `.awt/`, a node whose first row is not `node`, a node with a corrupt first row, case-only name differences. All reads finish, quarantine what they must and say so.
- C7 *Status race.* `status done` on a task races with creation of a child task. Either the child exists and `done` is refused, or `done` wins and the child is created afterwards under a done parent, which `doctor` reports. Never a crash.
- C8 *Parallel agents.* 50 agent nodes under one task, each writing notes and states while the parent runs `resume` in a loop. Rollups only ever show rows that exist.
- C9 *Budget fuzz.* Random goals, rules and states of random length, including multi-byte text and control characters. I6 holds.
- C10 *Secret hygiene.* Secret-shaped text in `name` or `key` never reaches disk, in any node.

**migrate**
- C20 *Snapshot fuzz.* Missing fields, duplicate ids, parent cycles, a parent that is an archived or missing agent, 5,000 agents, unicode and 1,000-char titles, secret-shaped titles, ids that look like paths, a workspace with no agents, an agent with no workspace. The script finishes, imports or reports every item, exit code follows the `migrate-wt` invariant.
- C21 *Kill and resume.* SIGKILL `migrate-paseo` at random times; rerun; the final tree equals the tree of an uninterrupted run (I7, compared with timestamps masked).
- C22 *Concurrent runs.* Two runs against the same root: one exits 1 with a fix, the tree is valid.
- C23 *Moving target.* Snapshot changes between runs (agents added, archived, renamed). Second run adds the new ones, updates status only, never renames or duplicates.

**plugin** (against the recorded-payload harness, so it runs everywhere)
- C30 *Hook storm.* 100 `agent.create.*` and `agent.open.before` events at once, with duplicates: 100 nodes, no duplicates.
- C31 *Awt failing.* `awt` missing, hanging, exiting non-zero or writing garbage on stdout: every hook still returns, within the timeout, with the request unchanged (no prompt block either).
- C32 *Malformed payloads.* Missing `workspaceId`, `parentAgentId` pointing at an unknown agent, null metadata, huge titles: no throw.
- C33 *Replay.* Every hook delivered twice and out of order (`after` before `before`): the tree is the same as with one ordered delivery (I7).
- C34 *Nudge loop* (needs `AWT_NUDGE=1`; without it no prompt is ever sent). A completed turn without state triggers one follow-up; no further follow-up until the agent has recorded state, even if it records nothing again.
- C35 *No dir, no nudge.* An agent that never got an `AWT_DIR` is never nudged.
- C36 *Duplicate keys.* The same key on nodes at two depths: logged, the agent is untouched, other agents are unaffected.
- C37 *Slow but working awt.* Each call succeeds but the chain exceeds the deadline: `open.before` returns the request unchanged at the deadline.
- C38 *Cancel.* An aborted hook signal kills the running `awt` children.
- C39 *Env.* The harness environment reaches every `awt` child.
- C40 *Moved node.* A node moved or broken while the daemon runs is found again.

## Migration (`test_migrate_paseo.py`)

Snapshots live in `fixtures/paseo-v0/`: `basic.json` (2 projects, 3 workspaces, 6 agents, one subagent chain of depth 3), `ambiguous.json` (two workspaces sharing one cwd, agents with no workspace id), `archived.json`, `orphans.json` (missing parents, cycles), `hostile.json` (the C20 shapes, small).

- M1 `basic.json` into an empty root: the tree equals an expected tree committed next to the snapshot (paths, kinds, keys, statuses). Every Paseo id appears once in the keys.
- M2 Agents with an exact workspace id land under that workspace's task `imported`. Subagents nest under their parents.
- M3 `ambiguous.json`: agents with no workspace id on the shared cwd land in the `unassigned` workspace and the report lists them.
- M4 Archived agents are `done`; background agents are skipped and listed.
- M5 `--dry-run` prints the plan and writes nothing (tree hash unchanged).
- M6 Second run: nothing changes (I7). After editing the snapshot (new agent, archived agent): only those differences appear.
- M7 `legacy/paseo-migration.md` lists counts, ambiguities and skips; the exit code is 1 when an item is neither imported nor listed.
- M8 No agent timeline text is copied anywhere. A grep of the tree for a marker string placed in the snapshot's message fields finds nothing.
- M9 Secret-shaped titles are redacted in the node, named in the report, and never written raw.
- M10 On-disk source: `fixtures/paseo-v0/home/` (fictional `parsekit` data in Paseo's file layout) read with `--home` gives the same tree as `basic.json`, with no ambiguity even when workspaces share a cwd. Background workspaces and agents are skipped; archived workspaces are `done`. Unreadable or malformed files are skipped or refused cleanly.
- M11 (gated, `paseo-plugin/test/daemon.test.ts`): the on-disk store written by a real daemon in a temp `--home` (1 workspace, 2 agents made with the scripted agent) is read by `migrate-paseo --home`; every workspace and agent key is present, and a second run leaves the node count unchanged. It does not compare against an expected tree. Skipped unless `AWT_E2E_PASEO=1`.
- M12 A secret-shaped string (built at runtime) in a workspace name, cwd, provider, model, title, workspace id or agent id appears in no file under ROOT and in no output, including `--dry-run`, and drops no workspace. A user's `status` survives a rerun. Created and already-present counts are separate. A killed run leaves a "run in progress" report.

## Plugin (`paseo-plugin/test`)

Tier 1, always. A harness loads `index.server.ts`, feeds it payloads typed by the installed `@getpaseo/plugin` SDK (so `tsc` catches drift, P11; recordings from a real daemon come with tier 2), and lets it call the real `awt` binary against a temp root. Assertions are on the tree and on what the hooks return.

- P1 `workspace.create.after`: workspace node exists with key and refs (working directory, project, workspace) and a `main` task; the project's display name labels the workspace (P13); replay adds nothing.
- P2 `agent.create.before`: `systemPrompt` grows by the static block only, at most 700 chars, naming `find --like`; no brief text enters the prompt.
- P3 `agent.open.before` for a workspace with no task: task `main` is created once, even for several simultaneous agents.
- P4 `agent.create.after`: agent node under the right task; subagent under its parent's node, the parent read from `parentAgentId` or the label `paseo.parent-agent-id`; unknown parent: under the task with a `note`.
- P5 `agent.open.before`: `env` has `AWT_DIR` and `AWT_BY` and keeps the existing entries; an `awt_resume` tool is attached; `mcpServers` are untouched. Runs again on `reason: resume` with the same result.
- P6 `awt_resume` takes no input and returns the brief of the node found for the calling agent's key; an agent id with no node errors. A key on two nodes resolves to nothing (C36).
- P14 `agent.turn.after` without `AWT_NUDGE`: no message is sent; with no `main` state since the turn started, the last reply is recorded in scope `auto`; never replaces an agent's own handoff; unchanged replies add nothing; `AWT_AUTO_HANDOFF=0` records nothing.
- P7 (with `AWT_NUDGE=1`) `agent.turn.after`: nudge only for completed turns of non-subagents that have an `AWT_DIR`, with no newer state, at most once per stretch (C34, C35); not for failed or canceled turns.
- P8 `agent.permission.before` allows only requests whose every target resolves (realpath) inside the calling agent's own node dir; sibling or parent node, `../`, a symlink out, `AWT_ROOT`, globs, shell and unknown shapes are untouched. It never denies. `awt effect apply` requests are left to the person.
- P9 Archive hooks: `done` when allowed, `paused` when refused.
- P10 Background agents: not in this version (Paseo 0.15.4 does not report them); only `purpose: interactive` opens get a node, env or tool.
- P11 `tsc --noEmit` over the plugin and its tests passes against the installed `@getpaseo/plugin` (a drift check). The harness mocks of `paseo` are typed against `PaseoApi`. Recorded hook payloads (fictional `parsekit` data) live in `paseo-plugin/test/payloads/`, one per registered hook; `payloads.test.ts` type-checks each against `PluginHookPayload` and feeds them through the hooks. Run by `npm test`.
- P12 Every `resolved` URL in `package-lock.json` is on `registry.npmjs.org`.
- P15 A turn that wrote a decision and a note appends one `awt.receipt` with matching counts and ids; failed, canceled and subagent turns get one too; at most 5 ids; a subagent's rows count under its parent.
- P16 A turn that wrote nothing appends `empty: true`. `AWT_RECEIPT=changes` skips empty receipts and those whose only row is the auto state; `0` appends nothing; an unknown value shows receipts and logs one warning.
- P17 The receipt follows the stand-in handoff and has `auto: true`; a handoff the agent wrote is not `auto`.
- P18 An append that throws is logged and the turn is unaffected.
- P19 `AWT_RELATED` in the daemon env reaches the agent env from `agent.open.before`; unset, it is absent.
- P20 The renderer schema rejects an unknown version or bad data without throwing.
- P21 A plugin instance that never saw `agent.open.before` for an agent whose node exists gets the auto handoff and a receipt on its next full turn; an agent with no node gets neither; a turn whose `turn.before` was missed gets nothing.
- P13 The workspace label uses `projectDisplayName` from `projects.list`.

Tier 2, gated. The plugin is installed in a daemon with a temp `--home`. A scripted agent is configured as a custom ACP provider: `paseo-plugin/test/fake/acp_agent.py`, which runs the shell command in a `RUN: <cmd>` prompt in the environment Paseo launched it with, as an agent would, and echoes anything else. Checked on Paseo 0.15.4: a scripted ACP provider works, and the daemon needs `pluginsEnabled: true` in its config. Run with `npm run test:daemon` in `paseo-plugin/` (E0, E1, E2, E4, E7, E8 and M11). The daemon config turns the relay and dictation off, and the tests strip `PASEO_*` from the environment, so nothing leaves the temp home. Not covered yet: spawning a subagent, because the fake agent has no way to start one.

- E0 The plugin shows as running in the daemon.
- E1 Create workspace and agent with the CLI: nodes appear with their keys, agent's environment contains `AWT_DIR`.
- E2 The scripted agent runs `awt note`; the row is in its node, not the task's.
- E3 The scripted agent spawns a subagent (`paseo run --label paseo.parent-agent-id=<parent>`; the daemon test, gated by `AWT_E2E_PASEO=1`): the child node sits under the parent's node and gets the subagent block.
- E4 Restart the daemon, resume the agent: same node, no duplicate.
- E5 Archive the workspace: node `done` or `paused`; nothing deleted.
- E6 Disable the plugin: agents still start and run; nothing is written.
- E7 After a turn with no handoff the chat holds no extra prompt and the node has an `auto` state from the agent's last reply (P14 against a real daemon).
- E9 (gated) Receipts render in the chat.
- E10 (gated) Receipts are absent from the provider's input; if they are not, receipts default to off and the spec is revised.
- E11 (gated) Compaction: the prompt line is what brings the brief back; `AgentSessionConfig` has no hooks field (checked at build time, see SPEC.md).
- E8 A handoff recorded during the turn means no `auto` state.

Not covered by the daemon test: E3, E5, E6. E5 is covered at hook level by P9; E6 only by C31 (awt failing), which leaves requests unchanged.

## Agentic (spends tokens)

New scenarios in `tests/agentic/scenarios.py`, each run with a real agent in a generated tree:

- `tree-resume`: the agent starts in a task with a parent workspace rule; it must follow the rule without being told.
- `subagent`: a parent delegates; the subagent must write `out.md` and must not resume or write state.
- `cross-ref`: the agent needs a fact recorded in a sibling task; it finds it with `find --tree` and cites the path.
- `switch-task`: two tasks in one workspace; the agent writes to the right one after `AWT_DIR` changes.

Pass criteria are checked on the files, not on the agent's words.

## Provider journeys (E-P)

Gaps and sources: `docs/e2e-provider-gaps.md`. These journeys prove awt's real interaction with Paseo and with each provider (Claude Code `claude`, opencode `opencode`, pi `pi`). They reuse the isolation rules, universal checks U1-U3, the cleanup and the D0 fixture of `docs/e2e-active-recall.md` §0. Fixtures use the fictional `parsekit` project and made-up ids. No credential or token-shaped literal appears in a fixture, a prompt or this file; a secret probe is built at runtime.

Tiers:

| Tier | Runs | Gate |
|---|---|---|
| deterministic-fake | `npm test` (harness rows) or `npm run test:daemon` (daemon rows) in `paseo-plugin/`, or `unittest` for fixture rows | daemon rows: `AWT_E2E_PASEO=1`, Paseo 0.15.4 or later on `PATH`; no tokens |
| isolated-daemon-real-provider (paid) | `tests/agentic/paseo_run.py --only E-P…` (new) | `AWT_E2E_PAID=1` **and the owner's approval for each run batch**, because it spends tokens. One pilot session per journey first; report its measured cost, then ask before the batch |
| manual | a person, following the steps | none; read-only |

**Isolation for paid journeys.** They run **only against an isolated daemon home**:
- `paseo --home $T/home`, with `PASEO_*` stripped and relay, dictation and auto-update off. Never `~/.paseo`; the pre-flight fails if `realpath($T/home)` equals `realpath(~/.paseo)` or if any `PASEO_HOME` is set.
- Every process runs with `HOME=$T`.
- Provider state lives under `$T`: `CLAUDE_CONFIG_DIR=$T/claude`; `XDG_DATA_HOME=$T/xdg/data` and `XDG_CONFIG_HOME=$T/xdg/config` for opencode; `PI_CODING_AGENT_DIR=$T/pi`.
- Credentials are supplied by the owner at run time through the provider's environment variable. The harness never copies `~/.claude`, `~/.local/share/opencode`, `~/.pi/agent/auth.json` or any other credential or state file. Check for a pending macOS SecurityAgent prompt first.
- Post-flight: the size and mtime of `~/.paseo`, `~/.claude/projects`, `~/.local/share/opencode/opencode.db` and `~/.pi/agent/sessions` are unchanged (U3). If opencode ignores `XDG_DATA_HOME`, this check fails the journey before any result counts.

Use the cheapest model of each provider, at most 10 turns and 300 s per session. Judge from files, hook logs and timelines, never from the agent's words.

**Harness additions (test code only, never product code).**
- **H5 hook recorder.** A second plugin, `paseo-plugin/test/fake/recorder/`, installed beside awt in the temp daemon. It appends `{hook, ts, payload}` as one JSON line to `$AWT_HOOK_LOG` for every hook in `PluginHookEvents` and `PluginHookRequests`, returns requests unchanged, and redacts nothing (the data is fictional).
- **H6 fake ACP extensions** in `fake/acp_agent.py`:
  - it writes every inbound line to `$AWT_FAKE_WIRE` (H1 of active recall);
  - `MCP: list` and `MCP: call <tool> <json>` run JSON-RPC `tools/list` / `tools/call` against the `paseo` server URL and headers it received in `session/new` `mcpServers`, and reply with the result;
  - `PERMIT: <kind> <path>` sends `session/request_permission` with `toolCall {kind, locations:[{path}]}` and replies with the outcome it received, or `no answer` after 10 s.
- **H7 shim**: `awt` first on `PATH` appends `{argv, AWT_DIR, AWT_BY, cwd}` to `$T/argv.jsonl` and execs the real `awt`.

### Deterministic-fake

**E-P1 `awt_resume` is delivered and callable** (paseo-common, gap 3). Setup: D0 with `daemon.mcp.injectIntoAgents: true`, plus H6.
1. `id=run("tool1", "MCP: list")` → the reply lists `awt_resume`; `session/new` in the wire has an `mcpServers` entry named `paseo` whose URL carries `callerAgentId=<id>`.
2. `paseo send <id> 'MCP: call awt_resume {}'` → the result text starts with the brief header of the node keyed `paseo:agent/<id>`; `isError` is absent.
3. A second agent `tool2` calls it → it gets `tool2`'s brief, never `tool1`'s.
4. Restart the daemon with `injectIntoAgents: false`; new agent `tool3`, `MCP: list` → no `paseo` server in `session/new`. The journey records this as the documented default and asserts that `doctor` or the plugin log names it (see the follow-up in `docs/e2e-provider-gaps.md`).

Pass: steps 1-3 exact; step 4 recorded; U1-U3.

**E-P2 ACP permission to the agent's own node** (paseo-common, gap 2). Setup: D0 + H6.
0. Probe: `PERMIT: edit $AWT_DIR/scratch/notes.md` with the H5 recorder on → record the `request.detail` that `agent.permission.before` received. If it has no `filePath`, the journey states that ACP edits are not auto-allowed and steps 1-2 become a red test of the mapping.
1. The same request → outcome `selected` with the allow option, within 5 s.
2. `PERMIT: edit $T/parsekit/../outside.md` and `PERMIT: edit <sibling agent's AWT_DIR>/x.md` → `no answer` both times; `paseo permit ls` (or the client) shows them pending.

Pass: 1-2 exact; the plugin never sends a deny.

**E-P3 Hook sequence, `turnId` and parent** (paseo-common, gap 1). Setup: D0 + H5.
1. `run("seq1", "ping")`, `send seq1 "ping"`, a child with `--label paseo.parent-agent-id=<seq1>`, then `paseo agent archive <child>` and `paseo workspace archive W1` on a second workspace.
2. Read `$AWT_HOOK_LOG`.

Pass:
- per agent, `agent.create.before` comes first; the relative order of `agent.open.before` and `agent.create.after` is recorded (this settles `SPEC.md` "hook order unverified");
- every turn has exactly one `turn.before` and one `turn.after` with the same `turnId`, and that `turnId` is not null;
- the child's payload `agent.parentAgentId` equals `seq1` (or is null; record which; fact 2 of the gaps doc);
- `agent.archive.after` and `workspace.archive.after` each arrive once, with `archivedAt` set.

The payloads, with ids rewritten to the fictional ones, replace the hand-written files in `test/payloads/` (P11 becomes "recorded").

**E-P4 Archive in a daemon** (paseo-common, gap 8; today's E5). Setup: D0.
1. Agent `arch1` with a turn, then `paseo agent archive arch1` → node `done`.
2. Agent `arch2` runs `RUN: awt ask "who owns the parsekit tokenizer?"`; archive it → `paused`.
3. Archive workspace W1 → the workspace node is `paused` (`arch2` has an open question), and nothing under it is deleted (file count unchanged).

Pass: statuses exact; `doctor` shows `0 quarantined`.

**E-P5 Project `archivedAt`** (paseo-common, gap 8; decision 16). Tier: deterministic-fake (unittest + harness).
1. `fixtures/paseo-v0/home/projects/projects.json` gains project `prj_0002` `ledgerline`, `archivedAt: "2026-02-01T00:00:00.000Z"`, with one active and one archived workspace. `migrate-paseo --home` → project node `paused` (an active workspace below); once both workspaces are archived, `done`.
2. A second run is idempotent (I7), and a status the user set survives.
3. Plugin harness: `workspace.archive.after` for the last workspace of an archived project → the project node goes `done`. Because `projects.list` has no `archivedAt` in 0.15.4, the test pins the source the plugin uses and fails if it is the SDK list.

Pass: red until the project kind lands (phase 1), then green.

**E-P6 Permission shapes per provider** (claude, opencode, pi; gap 2). Tier: deterministic-fake (harness `hooks.test.ts`).
- Claude: `detail.type` of `read`, `edit` and `write` with `filePath` inside the node → allowed. `Bash` with `detail.type: "shell"` running `awt note x` → untouched.
- opencode legacy: `external_directory` with `input.patterns` → as P8. opencode 2.x: `name: "external_directory"`, no `input`, `description` listing `<node>/*` → today untouched (red). Decide the 2.x rule (parse `description`, or ask Paseo for structured resources) and make it green.
- pi: `kind: "question"`, name `Pi confirm` → untouched; nothing is answered.

Pass: `r.answered` exactly as listed; no log lines.

**E-P7 Transcript shape pins** (claude, opencode, pi; gap 7). Tier: deterministic-fake (unittest). Fixtures `fixtures/transcripts/{claude,opencode,pi}/` hold fictional `parsekit` sessions written from the key sets in the gaps doc (facts 12-14):
- Claude: a main file, a `subagents/agent-<id>.jsonl` with `isSidechain`, and a `compact_boundary` + `isCompactSummary` pair.
- opencode: an SQLite file created by the test from the 1.19.3 columns, with a child session (`parent_id`) and a `compaction` part.
- pi: a `version: 3` file with a `compaction` entry and a `toolCall`/`toolResult` pair.

A Paseo `agents/*.json` fixture per provider carries `persistence.sessionId`/`nativeHandle` that join to them. Phase 1 and phase 4 adapters must map each fixture to the same table rows, and the join to the agent node must be exact (`join_confidence` exact). A missing required key is a refusal naming the key, never a guess.

### Isolated-daemon-real-provider (paid; isolated home only; owner approval required)

Common setup for E-P8 to E-P16: the isolation rules above; D0, but with the real provider enabled instead of `fake`, `injectIntoAgents: true`, H5 and H7; workspace W1 on `$T/parsekit` (a git repo with one file `tokenizer.py`). Prompts name exact commands, so the judge reads files, not words.

**E-P8 Claude Code: env, tool, permissions, receipts** (claude; gaps 1-4).
1. `paseo run --provider claude --workspace W1 --title cc1 "Call the awt_resume tool, then run the shell command: awt note \"cc probe\". Then write the file \$AWT_DIR/scratch/plan.md with one line. Reply DONE."`
2. Within 120 s, no permission is pending for `awt_resume` or the `plan.md` write. A pending `Bash(awt …)` request is recorded as a finding (unverified fact 1), answered once by the harness, and the journey still continues.

Pass:
- H5 shows `create.before`, `open.before` and one `turn.before`/`turn.after` pair, `provider: "claude"`;
- the timeline has a tool call named `mcp__paseo__awt_resume` (or `awt_resume`) with a non-error result;
- `argv.jsonl` has `note` with `AWT_DIR` equal to the node keyed `paseo:agent/<cc1>` and `AWT_BY=<cc1>`;
- `plan.md` exists in that node;
- exactly 1 receipt with `counts.note == 1`.

**E-P9 Claude Code: native subagent** (claude; gap 5). Agent `cc2`: "Use the Task tool to start a subagent that runs: awt note \"from the subagent\". Then run: awt note \"from the parent\"."

Pass:
- H5 shows no `agent.create.*` for the subagent;
- the timeline has a `sub_agent` item;
- `argv.jsonl` shows both notes; record the `AWT_DIR`/`AWT_BY` the subagent used (expected: the parent's);
- `$CLAUDE_CONFIG_DIR/projects/*/<persistence.sessionId>/subagents/agent-*.jsonl` exists with `isSidechain: true`.

The finding decides whether native subagents need their own node (spec change), and the journey then pins the chosen behaviour.

**E-P10 Claude Code: compaction and transcript** (claude; gaps 6-7). Agent `cc3`: one turn running `awt note "before compact"`; then `paseo send cc3 "/compact"`; then `paseo send cc3 "Continue the parsekit task."`.

Pass:
- a `compaction` timeline item with `status: completed`;
- after it, an `awt_resume` call (or `awt resume` in `argv.jsonl`) before any other awt-backed write, in at least 4 of 5 runs (prompt-line path);
- the transcript `<persistence.sessionId>.jsonl` under `$CLAUDE_CONFIG_DIR/projects/<encoded $T/parsekit>/` has a `system`/`compact_boundary` row and an `isCompactSummary` row;
- no row anywhere in the transcript contains `awt.receipt` (E-R17 step 3).

**E-P11 opencode: env, tool, permissions, receipts** (opencode; gaps 1-4). As E-P8 with `--provider opencode`, plus: count `opencode serve` processes whose argv contains `$T` before and after starting 3 agents (fact: `AWT_DIR` forces a dedicated server). Record the count; more than agents + 1 fails.

Pass: as E-P8. The `plan.md` write is auto-allowed through `external_directory`; record whether Paseo took the legacy or the 2.x path (from the shape of `request` in H5) and the opencode version.

**E-P12 opencode: child session** (opencode; gap 5). Agent `oc2`: "Use the task tool to have a subagent run: awt note \"from the child\"."

Pass:
- no `agent.create.*` for the child;
- a `sub_agent` item;
- `$T/xdg/data/opencode/opencode.db` has a `session` row whose `parent_id` is the agent's `persistence.sessionId`;
- record which node the child's note landed in, and whether any child permission request reached `agent.permission.before` with the parent as `agent`.

**E-P13 opencode: compaction and transcript** (opencode; gaps 6-7). As E-P10 with opencode's `/compact`.

Pass:
- a `compaction` timeline item;
- a `part` with `data.type = "compaction"` and a set `session.time_compacting` for the agent's session;
- the brief comes back as in E-P10, at least 4 of 5 runs;
- record whether the plugin prompt block is still in the `system` of the next request (from the opencode request log, if one exists; otherwise SKIP with the reason).

**E-P14 pi: env, tool, permissions, receipts** (pi; gaps 1-4). Run twice: arm A, pi with no MCP adapter; arm B, pi with the `pi-mcp-adapter` extension installed under `$T/pi`.

Pass, both arms:
- `AWT_DIR`/`AWT_BY` reach the shell (`argv.jsonl`);
- no `agent.permission.before` fires for awt-backed writes;
- 1 receipt per turn.

Arm A: `awt_resume` is absent from the tool list and the agent falls back to `awt resume` (record which). Arm B: `awt_resume` is called and succeeds.

**E-P15 pi: subagent** (pi; gap 5). Only if a subagent extension is installed in `$T/pi` (otherwise SKIP with the reason). Ask the agent to delegate `awt note "from the pi child"`.

Pass:
- a `sub_agent` item;
- no `agent.create.*` for the child;
- record where the note landed;
- the child transcript named by `Output file:` exists under `$T`.

**E-P16 pi: compaction and transcript** (pi; gaps 6-7). As E-P10, using pi's manual compaction command.

Pass:
- `compaction` timeline items (start, then completed);
- the session file at `persistence.nativeHandle` (under `$T/pi/sessions/`) has a `compaction` entry with `firstKeptEntryId` and `tokensBefore`;
- the header `id` equals `persistence.sessionId`;
- the brief comes back as in E-P10;
- the plugin prompt block is present after compaction (it is re-appended each turn; check in the next turn's `system` message if pi records one).

**E-P17 Paseo-level subagent started by a real agent** (claude; gap 5; closes the E3 caveat). Agent `cc4`: "Use the Paseo create_agent tool to start a subagent in this workspace that runs: awt note \"kid via paseo\"."

Pass:
- the child is a Paseo agent with label `paseo.parent-agent-id=<cc4>`;
- its node sits under `cc4`'s node;
- the child's receipt has `counts.note == 1` and `counts.state == 0`;
- `cc4`'s next receipt counts it (E-R13).

### Manual

**E-P18 Store shape probe after a provider upgrade** (claude, opencode, pi, paseo; gap 7). A person runs a read-only script that prints **key names, types and counts only**, never values:
- for the newest 30 Claude transcripts;
- for `opencode.db`: `pragma_table_info` of `session`, `message` and `part`, plus `part.data.type` counts;
- for pi session files: entry types and `version`;
- for `~/.paseo/agents/*/*.json` `persistence`.

They compare the output with facts 10-14 in `docs/e2e-provider-gaps.md` and update E-P7's fixtures when anything changed. This journey reads real stores, so its output is reviewed before it is committed, and no value is ever copied into the repo.

**E-P19 Receipts and subagent cards render per provider** (claude, opencode, pi). The Paseo app is connected to the E-P8, E-P11 and E-P14 daemons only, never the owner's daemon. One screenshot per provider shows the receipt line and a `sub_agent` card, stored in the run dir.

### Traceability

| Gap (`docs/e2e-provider-gaps.md`) | Journeys |
|---|---|
| 1 hooks | E-P3, E-P8, E-P11, E-P14 |
| 2 permissions | E-P2, E-P6, E-P8, E-P11, E-P14 |
| 3 env and `awt_resume` | E-P1, E-P8, E-P11, E-P14 |
| 4 receipts | E-P8, E-P11, E-P14, E-P17 (+ E-R10 to E-R15) |
| 5 subagents | E-P9, E-P12, E-P15, E-P17 |
| 6 compaction | E-P10, E-P13, E-P16 |
| 7 transcripts | E-P7, E-P10, E-P13, E-P16, E-P18 |
| 8 archive | E-P3, E-P4, E-P5 |

## CI

| Job | Runs | Trigger |
|---|---|---|
| unit | unittest discover + docs test | every push |
| chaos-quick | `chaos.py --quick` | every push |
| plugin | `npm test` | every push touching `paseo-plugin/` or `awt` |
| chaos-full | `chaos.py` | nightly |
| e2e-paseo | Tier 2 and M11, with the installed Paseo pinned to the version in `paseo-plugin.json` | nightly, and on release tags |

## Definition of done

The Node tree is done when T, C (tree), M and P pass in CI, I1 to I8 hold in the nightly chaos run for 7 days, the existing suite is unchanged (I8), and `tests/agentic` shows no regression on the existing scenarios and passes the four new ones.
