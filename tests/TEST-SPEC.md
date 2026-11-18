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
| `tests/test_passive_recall.py` | Passive recall: the first-prompt hook, the framed brief's section, the `recall` row, scope, gate, budget, shadow, the Claude hook entries, the pi extension | always |
| `paseo-plugin/test/recall.test.ts` | Passive recall in the plugin: env forwarding, receipt `recalled` and `shadow` | always |
| `tests/test_migrate_paseo.py` | `migrate-paseo` against snapshots | always |
| `tests/test_detect.py` | Detected effects: rules, keys, resend `ask`, declared matching, secrets, silence | always |
| `tests/test_hooks.py` | Compaction context: settings merge, `AWT_DIR` gate, framing line, doctor, the opencode plugin and pi extension loaded by node against fake hosts | always (the node part needs Node) |
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

## Declared effects (`test_awt.py` TestEffects, TestLegacyEffects; `test_gaps.py` DoctorAskRule; chaos `effect-*`)

awt never executes commands (SPEC, Effects). Tests run the real verbs and check exit codes, rows and files.

- E1 Flow: `plan` (with `--body`, `--how`), `begin` (prints body, `--how`, the `mark` command; creates `.awt/claims/<key>.1`), `mark sent --ref`. Terminal states refuse every mark and `begin`. A repeated plan with the same key writes nothing.
- E2 A person can `mark sent` straight from `planned`. From `planned` only `sent` and `dropped` are legal; `not-sent` and `unknown` are refused. `dropped` re-plan needs `--again`.
- E3 `begin` wins once: 6 to 24 concurrent begins give one exit 0 and the rest exit 1, one `begun` row (chaos `effect-race-begin`). Begin racing `mark dropped` never does both (`effect-begin-vs-drop`). Concurrent marks leave no quarantined row (`effect-mark-race`).
- E4 `not-sent` (needs `--why`, else exit 2) returns to `planned` with `attempt+1`; the next `begin` creates `<key>.2`. `unknown` needs `--why`, resolves only to `sent` or `not-sent`, is not retried, and blocks a plan on the same target without `--again`.
- E5 `--after` ids must exist (exit 4) and be `sent` before `begin`. A changed body refuses `begin` with fix `plan again`.
- E6 Removed: `effect apply` and `--run`, `--snapshot`, `--verify`, `--class`, `--timeout` (also `--flag=value`; an option value such as `--why=--timeout` is not refused, `test_option_values_that_look_like_removed_flags_are_not_refused`) exit 2 with a `fix:` naming plan, begin and mark, write no row, and create no `.awt/runs/` or `.awt/blobs/`.
- E7 `status done` is refused while an effect is `planned` or `begun`, and passes once marked. `resume` lists `begun` and `unknown` effects; the `begun` line says to send only if you ran `begin` this session, else ask a person. A re-plan of a `sent` effect says it is already sent and names `--again`.
- E8 Crash semantics: a claim file with no `begun` row reads `begun`, refuses `begin` and `dropped`, and leaves `not-sent` and `sent` (`effect-crash-gap`). A `begin` killed at a random moment leaves `planned` or `begun`, never anything else, and a legal way out exists (`effect-kill-during-begin`). A month-old `begun` is still `begun` (`effect-begun-never-expires`). An `unknown` effect is never begun again (`effect-unknown-never-retried`).
- E9 Never executes: a command in `--how`, `--why`, a body or `--ref` is never run (`effect-never-executes`, canary files); static: no function reachable from an `eff_*` verb names `subprocess`, `os.system`, `os.exec*`, `os.spawn*` or `os.popen` (`test_no_code_path_runs_a_subprocess_for_an_effect`); dynamic: each verb (`begin`, `show`, `mark`, `plan`) runs in a child python under `sys.addaudithook` that fails on `subprocess.Popen`, `os.system`, `os.exec`, `os.posix_spawn`, `os.fork`, `os.spawn` (`test_effect_verbs_start_no_process_at_runtime`). The `git` calls of other verbs are not on these paths.
- E10a Quarantine (`test_second_begun_row_for_the_same_attempt_is_quarantined`, `test_quarantine_counts_for_illegal_transitions`, `test_illegal_rows_are_quarantined`): a second `begun` row, `sent` to `begun` or `unknown`, `dropped` to `begun` or `sent`, `unknown` to `begun` or `dropped`, a row for an unknown id, each counted in `resume` and `doctor`; state is unchanged.
- E10 Old trees (`TestLegacyEffects`): `claimed` reads `begun`; `unknown` stays; `show` prints `run` as `how`, `legacy class|snapshot|verify:` and `legacy file:` lines for `.awt/runs/<id>.*` and `.awt/blobs/*`; `list effects --json` has `how`; blobs are listed (tree-wide) only for an effect with `snapshot`; a re-plan of an old effect with the same target and body finds it by its legacy key (already sent, nothing written); two `claimed` rows read `begun` with `legacy conflict` in `show` and the brief; a planned `run` effect begins and marks like any other; reads and marks never rewrite earlier bytes of `events.jsonl` and never delete `runs/` or `blobs/`.
- E11 `init` writes no `ask` rule and no outbox/effect paragraph. `doctor` warns (exit 0) for an old `ask` rule, one line per matching settings line with its number and text, and never edits the file. A fresh `init` has nothing to warn about.

## Detected effects (`test_detect.py`; plugin `detect.test.ts`)

Classification only labels a call and the ledger rows are the same ones the declared path writes (SPEC, Detected effects). Python tests pipe real hook payloads into `awt ingest --event --hook`; plugin tests drive the hooks with typed payloads against the real `awt`.

- DE1 Rules table: every outbound form in SPEC gets its rule (`git push`, `gh pr|issue|release` writes, `gh api` with a method or fields, `curl`/`wget` writes, `ssh`/`scp`/`rsync` to remote hosts, `npm|cargo publish`, `twine upload`, through `cd x &&`, `sudo`, `VAR=1`, `bash -c`, a heredoc line); reads, dry runs, local hosts, `curl -G`, text in `echo`/`grep`/heredoc bodies get none. MCP tools match by name (`paseo`/`awt` servers do not). Garbage input never raises.
- DE2 The key ignores spacing and a leading `cd`, and does change with cwd, arguments and the content of a named body file.
- DE3 `PreToolUse` writes `planned` + `begun` (`origin: detected`, `rule`, `tool_call_id`, `seen: before`) with no agent call; `PostToolUse` writes `sent`. Non-outbound calls write nothing.
- DE4 An exact resend of a `sent` effect makes the hook print `permissionDecision: ask` naming the earlier id, and writes nothing; if the person approves, the `PostToolUse` records it after the fact (`seen: after`) as its own effect. A replayed event writes nothing. `PostToolUseFailure` and an interrupted result give `unknown`, and an `unknown` effect asks too. A duplicate of a merely `begun` effect is only recorded.
- DE5 A `PostToolUse` with no `PreToolUse` is recorded after the fact. The plugin shape pairs `before` and `after` by key although the ids differ.
- DE6 A declared effect whose `how` equals the command is not recorded twice, is never moved by detection, and a `sent` one makes a resend ask.
- DE7 A secret-shaped string in the command is not written to the log (the target says it was withheld) and the resend still matches. Owner lines in `$XDG_CONFIG_HOME/awt/outbound` add rules; a bad line is skipped.
- DE8 The hook is silent with exit 0 for bad JSON, a wrong shape, no task, a list; `ingest --source claude --hook` still reads no stdin.
- DE9 awt never runs what it detects (canary `git`, `gh`, `curl`, `npm` on `PATH` never run).
- DE10 Detected rows reach `store.db` (`origin`, `rule`, `tool_call_id`) and `resume` lists a `begun` one. `init` writes `PreToolUse`, `PostToolUse` and `PostToolUseFailure` hooks (matcher `Bash|mcp__.*`) next to `SessionStart` and `SessionEnd`.
- PD1 A shell permission request is recorded in the agent's node; the plugin answers nothing.
- PD2 The turn scan settles it `sent` (paired by key); the same page again adds nothing.
- PD3 A request repeating a `sent` effect appends an `awt-resend` row naming the effect; it never allows or denies; the repeat is recorded only if it goes ahead.
- PD4 An auto-allowed call with no request is recorded `seen: after`; non-outbound calls are not.
- PD5 `failed` and `canceled` calls are `unknown`; a non-zero exit is `unknown`; `running` calls wait for a later turn.
- PD6 MCP calls match by tool name and are keyed on input.
- PD7 Left alone without error: an opencode 2.x request (no `input`, no `detail`), an agent with no node, awt missing. The turn scan still sees the call.
- PD8 Known gap, pinned: a native subagent's calls inside a `sub_agent` item are not seen.
- PD9 `permissionEvent`, `callEvents` and `resendReason` read only what they understand.

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

**Project level** (`test_tree.py` Projects)
- PT1 `init --kind project --name N --key K` under a root makes `projects/<slug>/` with a `project` node row, `context/`, `docs/`, `misc/`; lineage of a node below it reads root, project, workspace, task; `list tree` shows it; `doctor` passes.
- PT2 Legal pairs: a project holds only workspaces; a project inside a project, workspace, task or agent is refused (exit 1, a fix naming what the parent may contain); a task or agent directly in a project is refused.
- PT3 A project key is found from anywhere in the tree and `init --key` is idempotent for it (no row written, no second directory).
- PT4 A workspace directly under the root still resolves, lists and takes tasks. `doctor` warns about it only when the root also holds a project, and never fails on it.
- PT5 `status done` on a project is refused while a workspace below is active (the refusal names it), and so is `status done` on the root while a project is active; once the workspace is done, the project can be done.
- PT6 `doctor` warns when a done project still has an active workspace.
- PT7 A project in `workspaces/` is a warning (it does not match its node row), not a failure.
- PT8 A workspace moved by `rename` under a project: a `ref kind=node` made before the move still resolves, and `init --key` for the workspace returns the moved path.
- PT9 `--kind project` needs `--name` (exit 2).

## Child nodes (`test_child.py`; chaos `child-*`; spec `docs/spec-child-nodes.md`, SPEC Node tree, Child nodes)

Written before the code. Offline; stdlib; temp dirs; fake hook payloads; no network, no model.

- CN-1 `init --child scan-1` under a task makes `agents/scan-1` with `kind agent, name scan-1, run scan-1`, no key; stdout is exactly `AWT_DIR=<realpath> AWT_BY=sub:scan-1`.
- CN-2 The same call again exits 0, prints the same line, adds no row, notes `child node agents/scan-1 already exists` on stderr.
- CN-3 Invalid keys (`Scan`, `../x`, `a/b`, `-x`, 41 characters, empty) exit 2 with the slug fix, even where no parent node resolves; nothing is created.
- CN-4 Under a `workspace` or `root`: exit 1 with the legal-kinds fix. In a standalone legacy task: works.
- CN-5 A non-child node, a file, a non-empty plain directory or a symlink at `agents/<key>`: exit 1 `pick another RUN_KEY`. An empty directory is taken over. A symlinked `agents/` is refused.
- CN-6 `--child` with `--kind`, `--name`, `--key` or `--hooks`: exit 2.
- CN-7 Two children write `out.md` and `note` with `AWT_DIR` at their own node and the parent's `AWT_BY` in the environment: each `out.md` is intact; the notes carry `sub:a` and `sub:b`.
- CN-8 `--by hook` and `--by person` in a child node are kept; every verb is stamped `sub:<run>`; outside child nodes `AWT_BY` works as before.
- CN-9 `doctor` on a parent with two active children has no `fail`; a child directory renamed by hand is a `fail`; a `run` row outside `agents/` is a `fail`, a `run` row that is not an agent is a `warn`.
- CN-10 `resume` on the parent shows both children; `find --down` returns their notes with the node path.
- CN-11 The v0.3.1 `awt` reads a child node as an agent: `resume`, `list nodes`, `list notes`, `doctor`, no quarantined row.
- CL-1 A Claude `PreToolUse` `Agent` (and `Task`) payload with `RUN_KEY` on line 2 and `tool_use_id`: `ingest --event --hook` makes the child and one ref `tool-call:<id>`, prints nothing, writes no effect; a replay changes nothing; a second call under the key adds a second link.
- CL-2 No `RUN_KEY` line, a `RUN_KEY` on line 7, an invalid, quoted or trailing-text one, a non-string prompt, a `workspace` parent, a tool other than a launch tool: nothing written.
- CL-3 A pi plugin-shape `before` for `subagent` with `task` makes the same; `action: "status"` is ignored; `action: "resume"` with a `task` counts; each `tasks[].task` with a `RUN_KEY` gets a node linked to the one call id.
- CL-4 `find --tree <call id>` and `find --tree <RUN_KEY>` both hit the child; records in nodes without the ref are listed as before.
- CL-5 `PostToolUse` `Agent` with `status: completed`: child `done`; with an open question: `paused`; `isAsync`, other statuses, `PostToolUseFailure` and an async pi call: unchanged; no node: no write; a symlinked `agents/` or slot: the node it points at is unchanged.
- CL-6 `status done` on the parent turns its active children `done`; open work in a child still refuses it and changes nothing; a non-active child and a plain agent node are left alone; a child of a child node is signed `sub:<parent run>`, not `AWT_BY`.
- CL-7 `init --hooks claude` adds the two `# awt:child` entries and the `# awt:child-guard` entry once; a rerun changes nothing; `--uninstall` removes only them and keeps a sibling hook in the same matcher; the command is silent without `AWT_DIR` and its prefilter does not start `awt` for a call without `RUN_KEY:`.
- CL-8 The generated pi extension has the `tool_call` handler and the child-side switch; a node script runs it against a fake pi API and checks the node it made and the `process.env` it sets; nothing happens in a child process, without `AWT_DIR`, or when `awt` fails.
- CL-9 A Claude `PreToolUse` `Bash` payload `awt note x` with `agent_id` and no `--dir`: `additionalContext` with a `fix:` line, exit 0, no decision. With `--dir`, without `agent_id`, with `AWT_DIR` unset, a read verb or a non-awt command: silent. `--by=X` and `--model=X` before the verb still warn.
- CL-10 A pi child with a first prompt holding `RUN_KEY` and `MODEL: m1` sets `AWT_MODEL` to `m1`; without a `MODEL:` line, or with one that is not a model id (over 200 characters, non-ASCII, `;`), it is unchanged. A slot that is a symlink to another child node is not adopted.
- ST-1 A Claude parent transcript with two launch calls (one with the ref, one by its `RUN_KEY` line), their subagent transcripts, a Paseo agent that joins the session to the parent node: after a plain `ingest`, `docs/recipes/child-runs.sql` returns both rows with `link` `ref` and `run_key`, the right `tool_call_id`, `session_id`, `tool_name`, and joins to the Paseo node; a ref plus a `RUN_KEY` line is one row.
- ST-2 `child_session_id` is the subagent session of each child; `sessions.node_id` and `join_confidence` are as before.
- ST-3 `--rebuild` is byte-stable with child nodes present; an incremental ingest after a new ref equals a rebuild; the schema version is unchanged.
- ST-4 A second ingest asks for no rebuild; `records.fields` holds `run` and the link target.
- CH-1 20 processes race `init --child k`: one node, all exit 0, one line, no `.new-*`.
- CH-2 Parallel `init --child` for 20 keys plus hook events for the same keys: 20 nodes, one ref each.
- CH-3 SIGKILL during creation: a `.new-*` leftover or a whole node; a rerun succeeds; `doctor` reports the leftover.
- CH-4 Garbage hook payloads (not JSON, wrong types, a 9 MiB prompt, lone surrogates, a secret-shaped tail): exit 0, silent, nothing half-written, no secret in a row.
- CH-5 `agents/` replaced by a symlink to another node: refused, nothing written through it, hook silent.
- CH-6 A torn last line in the child's log, then a launch hook: the link lands, `doctor` names the quarantined row.
- CH-7 The parent's log held by another writer for 3 s while `status done` finishes its children: it succeeds and each child has one status row.
- CH-8 More child nodes than the walk limit: `find --down` and `doctor` report it in the standard words.

Gated (real providers; they spend tokens or need a live daemon; not run by the suite):

- G-1 pi's `bash` tool passes the `process.env` changes an extension makes in `before_agent_start` to its commands (C11). If not, pi falls back to the `awt-node:` brief line.
- G-2 pi awaits a `tool_call` handler before running the call, and the event's `toolCallId` is the id Paseo shows as the row's `toolCallId`.
- G-3 Under Paseo a Claude agent's `Agent` call fires the user-level `PreToolUse` hook with the `tool_use_id` Paseo shows.
- G-4 Two parallel paseo-pi-async-agents children with child nodes write their own `out.md` and notes (that repo's E7 rerun).

## Active recall (`test_recall.py`)

Spec: `docs/spec-active-recall.md`; normative text in `SPEC.md` (Reading across nodes, Paseo plugin).

- T-R1a `find --like` ranks a rare shared word above a common one (FTS5 bm25, in memory, no store needed); ties go to the newest row.
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
- T-R3a `awt help agents` has the `find --like` line; the task `AGENTS.md` template no longer does (it shrank to about 250 chars; `decide` and `ask` print related records anyway).
- T-R3b The plugin block is at most 360 characters and names `BRIEF.md`, `awt_resume` and `awt_find`. T-R3c The brief footer is `./awt find --like "topic" | ./awt list`; `help agents` states search-first once.
- T-R4a `list --since` returns exactly the rows at or after the timestamp with the fixed keys, `node` (null for the own node) with `--down`; usage errors exit 2.
- T-R5a The `init` `SessionStart` hook has no matcher, so it covers `compact`.

## Passive recall (`test_passive_recall.py`, `paseo-plugin/test/recall.test.ts`, chaos `recall-*`)

Spec: `docs/spec-passive-recall.md`; normative text in `SPEC.md` (Passive recall). Fixtures: fictional `parsekit` and `ledgerline` workspaces, made-up ids, filler notes so the idf gate has a corpus (the gate counts `N` over all candidates). Rules PR1 to PR24 of the spec; each has a test, written first.

Core (`test_passive_recall.py`):
- T-PR1 Only `find --like - --hook` and `resume --hook --framed` print recall lines; `decide`, `ask` and plain `find --like` write no `recall` row.
- T-PR2 No `AWT_DIR`, a task node, `AWT_RECALL=0` and `off`, a subagent: nothing printed, no row; the parent still gets recall.
- T-PR3 The first call prints and writes a `prompt` row; the second prints nothing and writes nothing, also after `every` rows; a framed brief writes a `compact` row and the next prompt prints nothing.
- T-PR4 A read-only log: nothing printed, exit 0.
- T-PR5 JSON `prompt`, raw text and malformed JSON; words after char 2,000 never match; two words give `result: none`; an `[awt]` prompt writes no row; B's query uses the `auto` state.
- T-PR6 Refs, states and superseded decisions never appear. T-PR7 Scope: project (project node, the `unassigned` project is not one, and the legacy fallback through `paseo` refs to `paseo:project/*` only), `workspace`, `tree`, an unknown value is `project`. T-PR8 Own node, subagent, an id in the brief, `no-recall` (and its undoing, and `find --like` ignoring it), identical text once.
- T-PR9 Two shared words, and three common words, are not shown; three rare words are; no hit prints nothing. T-PR10 12 qualifying records give 5 lines, the `rule` first, at most 1,200 chars. T-PR11 Frame and line shape, a forged heading, frame and control characters, B's heading after the brief and no second frame.
- T-PR12 `AWT_RECALL_MS=0`: `stopped`, used up. T-PR13 `AWT_TEST_RECALL_FAULT`: nothing, exit 0, `error` row; the hook command strings end `2>/dev/null; exit 0 # awt:context`. T-PR14 `AWT_STORE` that is a file is never touched.
- T-PR15 Row fields, quarantine of a bad `ids`, `BRIEF.md` untouched, hidden from `list`, `find`, `resume`, present in `list --since --json`. T-PR16 Shadow is the default: row `shadow`, nothing printed. T-PR17 Plain `resume` unchanged. T-PR22 `ingest --rebuild` puts the rows in `records`; `l7-recall-use` returns the hand-worked M1 to M3 and M5 counts on `fixtures/recipes-v0` (one shown id used, one not, one shadow id used unaided), and the work-record recipes do not count `recall` rows.
- T-PR18 `init --hooks claude`: `UserPromptSubmit` entry and `compact|clear` matcher, a foreign `clear` hook untouched, idempotent, `--uninstall` removes only awt's; the fake pi sets `awt_recall` at the first prompt, repeats it byte-identically and drops it at `session_compact`; in shadow it sets nothing. T-PR19 `doctor` writes no row and warns on a missing `UserPromptSubmit`. T-PR23 The installed `SessionStart` command prints the framed brief.
- T-PR24 Shadow: one `prompt` row then `every` rows, ids equal to `on`'s, no text, nothing written at `AWT_RECALL_MS=0`; `on` writes no later row.

Plugin (`recall.test.ts`, named PRP1 to PRP7 so they do not clash with the pipe tests PP1 to PP9):
- PRP1 `AWT_RECALL` and `AWT_RECALL_SCOPE` reach the agent env, unset stays unset. PRP2 A receipt has `recalled`, no `recall` in `counts`, `empty` true. PRP3 `AWT_RECEIPT=changes` shows a recall-only receipt. PRP4 Shadow and `every` rows: `would recall ... (shadow)`. PRP5 Old receipts render, new keys strip under the old schema. PRP6 The prompt block says nothing about recall. PRP7 `{id, text}` with text at most 80 chars, never stored; a failing fetch leaves the id.

Chaos (`recall-*`): `recall-2000` (a big tree: a valid block or `stopped`), `recall-corrupt` (corrupt, symlinked and `.new-*` nodes), `recall-readonly`, `recall-forge` (frame, headings, 4 KB lines, control characters), `recall-shadow-volume`, `recall-race`, `recall-old-awt` (v0.3.2 reads a log with `recall` rows), `recall-hook-exit` (a missing awt and an awt that exits 2: the hook command exits 0).

Not run here: D-PR1 to D-PR3 (live Paseo daemon) and E-PR1 to E-PR5 (spend tokens; owner approval per batch), as in the spec.

## Compaction context (`test_hooks.py`; SPEC, Context after compaction)

| ID | Proves |
|---|---|
| H1 | `init --hooks claude` creates one `SessionStart` entry with `matcher: compact`, an `AWT_DIR` gate and `resume --hook --framed`; no backup for a new file, no temp left |
| H2 | A second install changes nothing and makes no backup |
| H3 | Other keys, other `SessionStart` hooks and other events are kept as they were |
| H4 | An existing file is backed up before the change |
| H5, H5b | `--uninstall` removes only awt's entry, leaves no empty `hooks`, and is idempotent |
| H6, H6b | A file that is not JSON is refused untouched; a moved `awt` updates the entry in place |
| H7 | With `HOME` and the config variables in a temp dir, nothing else is written |
| H8 | `--hooks` with `--goal` etc., and `--uninstall` alone, are exit 2 |
| G1 | Running the hook command without `AWT_DIR`, even inside a task directory, prints nothing |
| G2 | With `AWT_DIR` it prints the frame line, then exactly `resume`; the frame has no instruction words |
| G3 | At max fill the output is at most 4,400 plus the frame line |
| G4 | A missing node or a missing `awt` binary: exit 0, no output, no stderr |
| G7, G8 | The framed hook leaves `BRIEF.md` unwritten and the record has no next-step hints (no `No handoff yet`, no `effect begin`); the plain brief keeps them |
| M1, M2, M3 | A symlinked `settings.json` stays a link, its target is written with its mode; a mixed entry keeps the sibling hook and uninstall restores it; the pinned path is the invoked path (not a resolved symlink) and `doctor` warns when it is gone |
| L1b, L7, L8 | Two runs in one second keep two backups, only 5 are kept; `doctor` survives odd or non-UTF-8 settings; a foreign `awt-context.js` is never overwritten or removed |
| G5, G6 | `--framed` without `--hook` is exit 2; plain `resume --hook` is unchanged |
| L2, L2b | An awt writer waits while the settings directory is locked; 12 concurrent installs and uninstalls leave one valid file, other keys and hooks intact, no temp |
| G9, G9b, G9c | The framed record lists the newest 5 notes as `- ` items (newest first, cut so all 5 fit) then `+N more` with the true count and no command; 5 long notes all show; the plain brief has none; at max fill the total stays 4,400 plus the frame line |
| G10 | Hostile notes, state, question, decision and effect text (newlines, `##`, the frame line) yield no forged heading and no second frame line |
| L9, L10 | `--uninstall` creates no provider directory; a failing `flock` (EBADF, ENOTSUP, ENOLCK) does not stop `init --hooks` (note on stderr) |
| X2, X3 | An inline `[hooks]` in the Codex `config.toml` gets a `warn` line; a reinstall from another awt path replaces the single entry |
| X1 | `--hooks codex` merges the same entry into `${CODEX_HOME}/hooks.json`, keeps other keys and events, is idempotent, `doctor` reports it, uninstall removes only ours |
| D0 | `doctor` outside a task root exits 0 with the skipped-checks line; `--dir` at a non-task exits 1; D0b a missing `AWT_DIR` exits 1 |
| D1, D2 | `doctor` warns for each detected provider without the hook (none for absent providers, never `fail`), and says `ok` after install |
| P1, P2 | The opencode plugin exposes only `experimental.session.compacting`, pushes the framed brief (with a decision's text), and pushes nothing without `AWT_DIR` |
| P3, P4, P5 | The pi extension adds `awt_record` only after `session_compact` (or a resumed branch with a `compaction` entry), keeps the text stable across turns, and does nothing without `AWT_DIR` |
| Gap | The opencode and pi e2e use a fake model that answers "OK summary", so they prove the record reaches the model, not that it survives in a real summary |
| L1 (`test_hooks_e2e.py`, `AWT_E2E_LOCAL=1`) | Real opencode 1.19.3 with the plugin installed, a fake OpenAI-compatible model (`tests/fake/openai-compat.mjs`), `POST /session/:id/summarize`: the one request made carries the frame and the decision token; the session's messages hold no awt text and only opencode's own compaction pair |
| L2 (same) | Real pi 1.5.0 over RPC: after `compact`, the next request's system message carries the frame and the token, one request was made by the compaction itself, and no user message carries the record |

Gated (not run by default): L1 and L2 (`AWT_E2E_LOCAL=1`, unpaid, need opencode or pi installed; opencode fetches its provider package), a real model compacting and continuing through opencode or pi, and the Claude Code journey on Haiku (`AWT_E2E_PAID=1`, `paseo-plugin/test/paid.test.ts`, scenarios W, C and the controls).

## Ingest (`test_ingest.py`; chaos `ingest-*`, `save-removed-and-staged-scan`)

Fictional `parsekit` transcripts written by hand into a temp `AWT_CLAUDE_PROJECTS`; `AWT_STORE` and `AWT_CLAUDE_SETTINGS` point into the temp dir. Token-shaped strings are built at runtime.

- N1 Round trip: every source line becomes one row; `raw` equals the parsed line; `v`, `src`, `adapter`, `session`, contiguous `seq`, `src_ref`, month directory.
- N2 Modes: store dirs 700 and files 600, also under `umask 000`.
- N3 Idempotent: a rerun writes no rows and leaves every canonical file byte- and mtime-identical. Appended source lines add only the new rows.
- N4 Secrets: matches are counted in `secret_flags` and the text is unchanged; a 600 KB string is stored whole.
- N5 Read-only: the transcript's hash, mtime and inode are unchanged; no file appears beside it.
- N6 Torn source tail (partial last line) waits for its newline. Torn canonical tail is healed. Offsets file lost after rows were appended: no duplicates.
- N7 Truncated source: nothing duplicated and later rows continue the `seq`. Rotated source (new inode) with the same content writes nothing; with new content appends.
- N8 Subagent transcripts and several sessions land in separate files. A non-JSON line is kept as `_unparsed`.
- N9 Concurrent ingests (8 processes, growing source, SIGKILLed runs): seqs are exactly 0..n-1.
- N10 `--hook` prints nothing and exits 0 even when the store cannot be created; without it that is exit 1 with a `fix:`. `--source pi` exits 2. A missing source directory is not an error. Store location follows `AWT_STORE`, `XDG_DATA_HOME`, then `~/.local/share`.
- N11 `save` exits 2 naming `git commit` and `awt doctor --staged`; the parser has `ingest`, no `save`, at most 16 verbs. `init` writes a `SessionEnd` hook running `ingest --source claude --hook`.
- N12 `doctor`: never-run and stale ingest warn; fresh is ok; store mode, loose file mode, git work tree and sync folder warn; oldest transcript age against `cleanupPeriodDays` (default 30, read from the settings file); doctor never creates the store.
- N14 Robustness: a record with a lone surrogate (built at runtime) is stored (escaped, file valid UTF-8) and later files are still ingested; a file whose append fails is recorded under `errors`, the rest ingested, `last_run` saved, doctor warns, and the error clears when the file works again.
- N15 `src_ref` is the physical line (blank lines counted) while `seq` stays dense. A same-inode in-place rewrite longer than the offset is rescanned (head hash).
- N16 `CLAUDE_CONFIG_DIR` is the default source and settings dir. Missing parents of the store keep the default mode, the store and its subdirectories are 700, an existing loose store dir is not chmodded. `doctor` reports store size and files; a git-ignored store in a work tree does not warn.
- N13 `doctor --staged`: clean index ok; a staged secret exits 1 naming file and pattern but not the secret; a type change is scanned and a textconv filter does not hide a secret; the staged blob counts, not the working copy; runs from a hook with no `--dir`; outside a repo exits 1 with a `fix:`.

## Store (`test_store.py`)

Fictional `parsekit` transcripts and a temp `AWT_STORE`, as in Ingest. Nothing reads real data.

- S1 `ingest` builds `store.db` (mode 600) with every table and `schema_meta`; sessions, turns (a `tool_result` record is not a boundary), messages, tool calls (args, result excerpt and sha256, error flag, times) are exactly the fixture's.
- S2 `canonical.raw` equals each source record; a token-shaped string is not redacted; a 300,000-character message is whole in `messages.text` and `canonical.raw`, while FTS finds its start and not its tail (the cap is only in the index).
- S3 `fts_text` finds message text and tool-call arguments with the right `kind`.
- S4 Records, effects (one row per effect folded from its steps), nodes and projects come from the node logs; record ids are unique.
- S5 A session joins a node only on an exact `cwd`, with `join_confidence = 'cwd'`; otherwise null.
- S6 Unparsed canonical rows count in `ingest_sources.errors`; no canonical files still builds an empty db.
- S7 an in-place update equals a rebuild (same rows and search hits; rowids may differ), and `ingest --rebuild` gives a byte-identical file (SHA-256) and `.dump`, also with the provider directory gone. Review fixes (tests/test_p2fix.py): H1 a bare-directory or other-tree ingest keeps the records; H2 a node-log change leaves canonical tables alone and a canonical change re-derives only that file; H3 a SIGKILLed build's temp file is swept and `doctor` warns; M1 a write during a build is not marked fresh; M2 a write runs git once; M3 a re-opened agent gets a brief; M5 contentless FTS and indexes; M6 `find --like` and `decide` work without FTS5; M7 a pre-phase-2 node gets the `.gitignore` line.
- S8 A garbage `store.db` is replaced by `--rebuild`; a normal `ingest` leaves it and warns `awt ingest --rebuild`; no temp files remain.
- S9 A normal `ingest` with nothing new leaves `store.db` untouched (mtime); a new node record or new canonical rows update it.
- S10 `--rebuild` prints a `rebuilt store.db` line and no provider line; with `--hook` it is silent.
- S11 `find TERM` stays literal and never lists messages; `find --sessions TERM` adds `message:` and `tool_call:` hits; with no usable store it prints the one-line note and keeps the record hits; `--sessions` without a TERM or with `--like` is exit 2.
- S12 `find --like` output is identical with and without a store.
- S13 `doctor` is ok with FTS5 and exits 1 with `fail ... FTS5` when `AWT_TEST_NO_FTS5` simulates its absence; `ingest --rebuild` then exits 1 with a `fix:`.

### PR #23 review fixes (`test_p23fix.py`, `test_ui.py`)
- S14 (H1) A store of an older schema is left byte-identical by `--hook`, `--stdin` and a plain `ingest` (the last warns `store schema 5 < 7` and `awt ingest --rebuild`; the first two are silent); `find` still reads it; `doctor` warns; `--rebuild` replaces it, with the canonical rows that arrived meanwhile. A broken file is treated the same.
- S15 (H1) A hook builds a missing store only while the canonical logs are under 64 MB. `--rebuild` refuses with a `fix:` line when free disk (`AWT_TEST_FREE_BYTES`) is under 1.2 x the larger of the store and the logs plus 256 MB; a hook skips silently; the need grows with the store.
- S16 (H1) An exclusive lock held on `store.db` (`AWT_TEST_BUSY_S=1`) makes `ingest` warn `not updated` and `--hook` stay silent; the store is untouched, no temp file, no rebuild; the next ingest updates it.
- S17 (H1) A rebuild of 6 files of 5 MB peaks within 60 MB of a rebuild of 1 file (max RSS of the child): one file's rows in memory at a time.
- S18 (M2) Integers of 10^20, 2^63 and below -2^63 in a transcript, and in ccusage output, are stored as null; under `--hook` the build completes. A file whose derivation raises (`AWT_TEST_DERIVE_RAISE`) is rolled back alone, counted in `build_state.errors`, its raw rows kept.
- S19 (M3) The `supersede` hint, run in a temp tree, works without `docs/_superseded/` and refuses to replace an earlier file there; `AGENTS.md`, the ADR and `help agents` carry the same text.
- S20 (L1) `fixtures/ccusage-v0/real-20.0.51/`: real `ccusage session --json --offline` output (20.0.51) on synthetic parsekit transcripts (a parent, a subagent, a resumed copy). awt's tokens (1107) and cost (0.003321) equal ccusage's totals; no transcript data is real. Regenerate by running that ccusage on `projects/` with `HOME` and `CLAUDE_CONFIG_DIR` pointed at a temp dir.
- S21 (L3) A conversation past the last ccusage import keeps its message tokens and its ccusage cost as one `ccusage_stale` row; the l1 cost recipe still counts it; a computed cost (pi, opencode) is not added to it.
- S22 (M1, L2, L4) `awt ui` starts Datasette on the live `store.db` (no `-i`, no copy; a later ingest is visible), refuses Datasette 1.x with `datasette<1`, and refuses an older store with `awt ingest --rebuild` (a fake `datasette` records its arguments).
- S23 (N1) A store of schema 99 is byte-identical after every ingest mode (`--hook`, `--source all --hook`, plain, `--rebuild`, `--rebuild --hook`, `--stdin`); plain and `--rebuild` print `store schema 99 > 7: this awt is older than the store` and `install the newer awt`; hooks are silent; canonical rows are still copied; `doctor` warns; `awt ui` refuses.
- S24 (N2) `human(4053296742)` is `3.8 GB`.
- S25 (N3) In a full `--rebuild`, a file whose derivation raises after writing rows (`AWT_TEST_DERIVE_RAISE_AFTER`) leaves zero rows in messages, turns, tool_calls, usage and sessions; `fts_text` count equals `fts_ref`, no dangling message refs, `integrity_check` ok.
- S26 (N4) SIGTERM and SIGHUP to a `--rebuild` (`AWT_TEST_BUILD_SLEEP`) remove the temp file and leave the old store byte-identical.
- S27 (N5) `update_store` on a store whose schema is not this awt's raises `StoreChanged` (a skip with a warning), leaves the file byte-identical and never stamps the version.
- N6 is documentation only (SPEC, CHANGELOG): restart `awt ui` after a rebuild.

## BRIEF.md and the short prompt (`test_brief.py`; plugin P2, P2b)

| ID | Proves |
|---|---|
| B1 | `init` writes `BRIEF.md` equal to `resume` plus the trailing `Generated` line |
| B2 | Every write verb (`note decide ask state ref status`) regenerates it |
| B3 | `list`, `find`, `resume` do not touch it (same inode, same text) |
| B4 | Written by rename: new inode, no temp left in the node or `.awt/` |
| B5 | Never read back: a forged `BRIEF.md` changes nothing in `resume`; `list` and `list misc` do not show it |
| B6 | It is not a "file newer than state" |
| B7 | `BRIEF.md` is in `.gitignore` |
| B8 | A directory named `BRIEF.md` does not fail the write |
| B9, B10 | `resume --hook` refreshes it; outside a node it prints and writes nothing |
| B11 | Agent fixture with no `AGENTS.md`: running the `SessionStart` command from its `settings.json` (as the host would) prints the brief, and `BRIEF.md` matches |
| B12 | The settings template has `SessionStart` with no `matcher` (runs after compaction) |
| B13 | The standalone AGENTS block is short, names `BRIEF.md`, `decide`, `ask`, the subagent line, says what the plugin and the Claude Code hooks record, and asks for a `state` handoff without claiming everything is recorded |
| B14 to B16 | Tree: every node kind gets a brief at creation; a child write refreshes the parent; a task write refreshes the agents below it |
| B17 | The tree block names `$AWT_DIR/BRIEF.md` and `$AWT_DIR/out.md` |
| P2 | The plugin block is at most 360 chars, names `$AWT_DIR/BRIEF.md`, `awt_resume`, `awt_find`, `decide`, `ask`; no `state` |
| P2b | An agent opened through the plugin has `BRIEF.md` in `AWT_DIR` before any tool call, refreshed by an awt write |

## Chaos (`tests/chaos.py`, groups `tree`, `migrate`, `plugin`, `child`)

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

**Project level** (`test_migrate_paseo.py` ProjectLevel; chaos `migrate-kill-mid-move`)
- MP1 A fixture with two projects (`parsekit`, `docs-site`) and an unassigned workspace migrates to `projects/parsekit`, `projects/docs-site` and `projects/unassigned` (key `paseo:project/unassigned`), each workspace under its project's `workspaces/`; a rerun changes nothing (I7) and says `0 projects created, 0 workspaces moved`.
- MP2 A project node has the name `customName ?? displayName` (`projects.json` through `--home`), key `paseo:project/<id>`, and `ref`s to `rootPath` and to its own key.
- MP3 `customName` wins over `displayName`, in the project name and its directory.
- MP4 A tree in the earlier layout (workspaces directly under the root) is moved: project from the workspace's `ref paseo:project/<id>`, else `workspaces.json`, else `unassigned`; each subtree moves whole (its records are byte-identical); a workspace made by hand with no key stays; the output counts the moves.
- MP5 A rerun after the move moves and creates nothing.
- MP6 A `ref kind=node` to a moved workspace resolves to the new place.
- MP7 A name taken in the project's `workspaces/` gets a numeric suffix; the existing node is not replaced.
- MP8 A run that left the project made and one node moved is finished by the next run; keys stay unique; the second run changes nothing.
- MP9 Archived project: `done`, or `paused` when a workspace below is still active (the report notes it).
- MP10 Archive is applied on a later run, not only the first. A paused (archived) project becomes `done` on the run after its last open work closes, and stays paused until then.
- MP11 `--dry-run` on a legacy tree writes nothing and prints each move and project.
- MP12 `--dry-run` without a root names the projects.
- MP13 Hostile project rows (secret in id, duplicate id, non-object, null id, secret in name and path): no secret in output, report or tree; one node per key.
- C24 *Kill mid-move.* A pre-project tree is migrated while the process is SIGKILLed over and over; after every kill each workspace key exists once, and after the final run the tree equals an uninterrupted run, no workspace is left in `workspaces/`, and a further rerun changes nothing.

## Plugin (`paseo-plugin/test`)

Tier 1, always. A harness loads `index.server.ts`, feeds it payloads typed by the installed `@getpaseo/plugin` SDK (so `tsc` catches drift, P11; recordings from a real daemon come with tier 2), and lets it call the real `awt` binary against a temp root. Assertions are on the tree and on what the hooks return.

- P1 `workspace.create.after`: workspace node exists with key and refs (working directory, project, workspace) and a `main` task; the project's display name labels the workspace (P13); replay adds nothing.
- P2 `agent.create.before`: `systemPrompt` grows by the static block only, at most 260 chars, naming `$AWT_DIR/BRIEF.md`; no brief text enters the prompt.
- P3 `agent.open.before` for a workspace with no task: task `main` is created once, even for several simultaneous agents.
- PJ1 `workspace.create.after` creates the project node from `workspace.projectId` (key `paseo:project/<id>`, refs to the root path and to its own key) and the workspace under it.
- PJ2 Two workspaces of one project share one project node, also under concurrent and replayed hooks and after a plugin restart.
- PJ3 The project name is `customName ?? displayName` from `projects.json`, which beats the SDK listing.
- PJ4 A workspace with no `projectId` goes under project `unassigned`; an agent with no workspace goes to `unassigned--<cwd>` under it.
- PJ5 An agent opened before its workspace exists still gets a workspace under the right project.
- PJ6 `workspace.archive.after`: when `projects.json` has `archivedAt` for the workspace's project, the project is `done`, or `paused` while work below is open; without `archivedAt` it stays active.
- PJ7 Project `done` when nothing below is open.
- PJ8 A missing, malformed, wrong-shaped or deeply nested `projects.json` gives no archive information and no log line of failure.
- PJ9 A symlinked `projects.json` is ignored.
- PJ10 A workspace moved under a project by `migrate-paseo` while the plugin runs: cached paths that are gone are dropped, the agent's next open finds the moved node by key, and nothing is duplicated.
- PJ11 A workspace still directly under the root is found and used; no copy is made.
- PJ12 Hostile project names and root paths never escape the tree or reach disk as secrets.
- P4 `agent.create.after`: agent node under the right task; subagent under its parent's node, the parent read from `parentAgentId` or the label `paseo.parent-agent-id`; unknown parent: under the task with a `note`.
- P5 `agent.open.before`: `env` has `AWT_DIR` and `AWT_BY` and keeps the existing entries; an `awt_resume` tool is attached; `mcpServers` are untouched. Runs again on `reason: resume` with the same result.
- P6b `awt_find` takes `{query, limit?}`, runs `find --like` for the calling agent's node, passes `--limit`, and returns one-line error results (bad limit, no node). Per-provider names (`mcp__paseo__awt_find`, `awt_find`) are auto-approved like `awt_resume`; look-alikes are not (P8).
- P6 `awt_resume` takes no input and returns the brief of the node found for the calling agent's key; an agent id with no node errors. A key on two nodes resolves to nothing (C36).
- P14 `agent.turn.after` without `AWT_NUDGE`: no message is sent; with no `main` state since the turn started, the last reply is recorded in scope `auto`; never replaces an agent's own handoff; unchanged replies add nothing; `AWT_AUTO_HANDOFF=0` records nothing.
- P7 (with `AWT_NUDGE=1`) `agent.turn.after`: nudge only for completed turns of non-subagents that have an `AWT_DIR`, with no newer state, at most once per stretch (C34, C35); not for failed or canceled turns.
- P8 `agent.permission.before` allows only requests whose every target resolves (realpath) inside the calling agent's own node dir; sibling or parent node, `../`, a symlink out, `AWT_ROOT`, globs, shell and unknown shapes are untouched. It never denies. `awt effect apply` requests are left to the person.
- P9 Archive hooks: `done` when allowed, `paused` when refused.
- P10 Background agents: not in this version (Paseo 0.15.4 does not report them); only `purpose: interactive` opens get a node, env or tool.
- P11 `tsc --noEmit` over the plugin and its tests passes against the installed `@getpaseo/plugin` (a drift check). The harness mocks of `paseo` are typed against `PaseoApi`. Recorded hook payloads (fictional `parsekit` data) live in `paseo-plugin/test/payloads/`, one per registered hook; `payloads.test.ts` type-checks each against `PluginHookPayload` and feeds them through the hooks. Run by `npm test`.
- P12 Every `resolved` URL in `package-lock.json` is on `registry.npmjs.org`.
- P15 A turn that wrote a decision and a note appends one `awt-receipt` with matching counts and ids; failed, canceled and subagent turns get one too; at most 5 ids; a subagent's rows count under its parent.
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

Pass: as E-P8, except that the `awt_resume` tool call is not required: Paseo 0.15.4 does not offer plugin tools to opencode, so a missing call is a recorded finding and the agent falls back to `BRIEF.md` or `awt resume`. The `plan.md` write is auto-allowed through `external_directory`; record whether Paseo took the legacy or the 2.x path (from the shape of `request` in H5) and the opencode version.

**E-P12 opencode: child session** (opencode; gap 5). Agent `oc2`: "Use the task tool to have a subagent run: awt note \"from the child\"."

Pass:
- no `agent.create.*` for the child;
- a `sub_agent` item;
- `$T/xdg/data/opencode/opencode.db` has a `session` row whose `parent_id` is the agent's `persistence.sessionId`;
- record which node the child's note landed in, and whether any child permission request reached `agent.permission.before` with the parent as `agent`.

**E-P13 opencode: compaction and transcript** (opencode; gaps 6-7). As E-P10 with opencode's `/compact`.

Pass:
- a `compaction` timeline item;
- a `part` with `data.type = "compaction"` (opencode 1.19.3 does not set `session.time_compacting` for `/compact`; the column is recorded as a note, not a check);
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
