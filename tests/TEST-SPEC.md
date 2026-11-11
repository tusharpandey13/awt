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
| `tests/test_migrate_paseo.py` | `migrate-paseo` against snapshots | always |
| `tests/test_docs.py` | Existing. Extended: every `awt` command shown in the docs and the tree-form `AGENTS.md` block uses real verbs and flags | always |
| `tests/chaos.py` | Existing. New attacks in groups `tree`, `migrate`, `plugin` | `--quick` in CI, full nightly |
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
- T4 `--name` missing for a non-root kind, or `--goal`/`--done` missing for a task: exit 2. `--kind root` on an existing node: exit 1 with a fix.
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
- T22 Budgets at maximum fill: 8 ancestors with 600-char goals and 300-char rules, 200 children with 700-char states; and an agent node whose task is full in every section. Results within 5,200 and 7,000 (I6); overflow is `+N more` lines, never a cut line.
- T23 A standalone node prints the same brief as the previous release, byte for byte (I8).
- T24 `list nodes`, `list tree`, `--all`, `--json` match each other and the filesystem (I1). A test pins every `--json` key listed in `SPEC.md`.
- T25 `find --down` finds text in a grandchild's `docs/` and events; `--up` finds it in an ancestor; without a flag, neither. Hits capped at 40 in total, prefixed by relative node path.
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
- C34 *Nudge loop.* A completed turn without state triggers one follow-up; no further follow-up until the agent has recorded state, even if it records nothing again.
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
- P2 `agent.create.before`: `systemPrompt` grows by the static block only, at most 700 chars; no brief text enters the prompt.
- P3 `agent.open.before` for a workspace with no task: task `main` is created once, even for several simultaneous agents.
- P4 `agent.create.after`: agent node under the right task; subagent under its parent's node; unknown parent: under the task with a `note`.
- P5 `agent.open.before`: `env` has `AWT_DIR` and `AWT_BY` and keeps the existing entries; an `awt_resume` tool is attached; `mcpServers` are untouched. Runs again on `reason: resume` with the same result.
- P6 `awt_resume` takes no input and returns the brief of the node found for the calling agent's key; an agent id with no node errors. A key on two nodes resolves to nothing (C36).
- P7 `agent.turn.after`: nudge only for completed turns of non-subagents that have an `AWT_DIR`, with no newer state, at most once per stretch (C34, C35); not for failed or canceled turns.
- P8 `agent.permission.before` never returns an approval. `awt effect apply` requests are left to the person.
- P9 Archive hooks: `done` when allowed, `paused` when refused.
- P10 Background agents: not in this version (Paseo 0.15.4 does not report them); only `purpose: interactive` opens get a node, env or tool.
- P11 `tsc --noEmit` over the plugin and its tests passes against the installed `@getpaseo/plugin` (a drift check). The harness mocks of `paseo` are typed against `PaseoApi`. Run by `npm test`.
- P12 Every `resolved` URL in `package-lock.json` is on `registry.npmjs.org`.
- P13 The workspace label uses `projectDisplayName` from `projects.list`.

Tier 2, gated. The plugin is installed in a daemon with a temp `--home`. A scripted agent is configured as a custom ACP provider: `paseo-plugin/test/fake/acp_agent.py`, which runs the shell command in a `RUN: <cmd>` prompt in the environment Paseo launched it with, as an agent would, and echoes anything else. Checked on Paseo 0.15.4: a scripted ACP provider works, and the daemon needs `pluginsEnabled: true` in its config. Run with `npm run test:daemon` in `paseo-plugin/` (E0, E1, E2, E4, E7, E8 and M11). The daemon config turns the relay and dictation off, and the tests strip `PASEO_*` from the environment, so nothing leaves the temp home. Not covered yet: spawning a subagent, because the fake agent has no way to start one.

- E0 The plugin shows as running in the daemon.
- E1 Create workspace and agent with the CLI: nodes appear with their keys, agent's environment contains `AWT_DIR`.
- E2 The scripted agent runs `awt note`; the row is in its node, not the task's.
- E3 The scripted agent spawns a subagent: the child node sits under the parent's node and gets the subagent block.
- E4 Restart the daemon, resume the agent: same node, no duplicate.
- E5 Archive the workspace: node `done` or `paused`; nothing deleted.
- E6 Disable the plugin: agents still start and run; nothing is written.
- E7 After a turn with no handoff the agent is nudged exactly once (C34 against a real daemon).
- E8 A handoff recorded during the turn suppresses the nudge.

Not covered by tests yet: E3, E5, E6.

## Agentic (spends tokens)

New scenarios in `tests/agentic/scenarios.py`, each run with a real agent in a generated tree:

- `tree-resume`: the agent starts in a task with a parent workspace rule; it must follow the rule without being told.
- `subagent`: a parent delegates; the subagent must write `out.md` and must not resume or write state.
- `cross-ref`: the agent needs a fact recorded in a sibling task; it finds it with `find --tree` and cites the path.
- `switch-task`: two tasks in one workspace; the agent writes to the right one after `AWT_DIR` changes.

Pass criteria are checked on the files, not on the agent's words.

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
