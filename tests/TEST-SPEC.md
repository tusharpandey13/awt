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
- T-R3b The plugin block is at most 260 characters and names `BRIEF.md` and `awt_resume`; `find --like` moved to `help agents`.
- T-R4a `list --since` returns exactly the rows at or after the timestamp with the fixed keys, `node` (null for the own node) with `--down`; usage errors exit 2.
- T-R5a The `init` `SessionStart` hook has no matcher, so it covers `compact`.

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
- S7 `ingest --rebuild` gives a byte-identical file (SHA-256) and `.dump`, also with the provider directory gone; a from-scratch rebuild equals the incrementally built file.
- S8 A garbage `store.db` is replaced by `--rebuild` and by a normal `ingest`; no temp files remain.
- S9 A normal `ingest` with nothing new leaves `store.db` untouched (mtime); a new node record or new canonical rows update it.
- S10 `--rebuild` prints a `rebuilt store.db` line and no provider line; with `--hook` it is silent.
- S11 `find TERM` stays literal and never lists messages; `find --sessions TERM` adds `message:` and `tool_call:` hits; with no usable store it prints the one-line note and keeps the record hits; `--sessions` without a TERM or with `--like` is exit 2.
- S12 `find --like` output is identical with and without a store.
- S13 `doctor` is ok with FTS5 and exits 1 with `fail ... FTS5` when `AWT_TEST_NO_FTS5` simulates its absence; `ingest --rebuild` then exits 1 with a `fix:`.

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
| B13 | The standalone AGENTS block is short, names `BRIEF.md`, `decide`, `ask`, the subagent line, and has no handoff line |
| B14 to B16 | Tree: every node kind gets a brief at creation; a child write refreshes the parent; a task write refreshes the agents below it |
| B17 | The tree block names `$AWT_DIR/BRIEF.md` and `$AWT_DIR/out.md` |
| P2 | The plugin block is at most 260 chars, names `$AWT_DIR/BRIEF.md`, `awt_resume`, `decide`, `ask`; no `state`, no `find --like` |
| P2b | An agent opened through the plugin has `BRIEF.md` in `AWT_DIR` before any tool call, refreshed by an awt write |

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
