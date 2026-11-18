# Changelog

## Unreleased

### Added
- Passive recall (spec: `docs/spec-passive-recall.md`, contract: `SPEC.md` Passive recall). At an agent's first prompt (Claude `UserPromptSubmit`; pi's system prompt before the first request) and in the framed brief after a compaction or `/clear` (a `## Related elsewhere` section), up to 5 related records (at most 1,200 chars) are put in front of the agent with no call. Only decisions, questions and notes of the same project qualify, with at least 3 shared words and an idf sum of at least 12; nothing is printed when nothing does. New flag `awt find --like - --hook` (no new verb), new event type `recall` (ids only), `AWT_RECALL` (default `shadow`: computes and logs, never injects; `on`; `0`/`off`), `AWT_RECALL_SCOPE` (`project`, `workspace`, `tree`) and the `no-recall` decision tag. The hook stops at 800 ms, never reads `store.db`, and always exits 0.
- `awt init --hooks claude` also installs the `UserPromptSubmit` hook and widens the `SessionStart` matcher to `compact|clear`, so `/clear` gets the brief back; run it again to upgrade. `awt doctor` warns when the `UserPromptSubmit` hook is missing.
- The Paseo plugin forwards `AWT_RECALL` and `AWT_RECALL_SCOPE` to agents. The turn receipt gains `recalled` (ids and a short local text) and `shadow`: `awt · recalled d-7f3a9c21 "Retry with jitter" · nothing stored this turn`.
- New recipe `docs/recipes/l7-recall-use.sql`: recall rows per trigger and result, and how many shown (or shadow) ids were used afterwards.

### Changed
- `l7-awt-verb-use`, `rec-records-by-origin`, `rec-records-per-session` and `l6-prompt-to-first-record` no longer count `recall` rows (a hook writes them, not the agent).
- `list --since --json` rows carry `ids` and `result` (`null` except on `recall` rows). `awt find TERM` and `awt list` never show `recall` rows. An older `awt` quarantines `recall` rows as an unknown type until it is upgraded.
- `tests/agentic/` catches up with v2. The harness drops the caller's `AWT_*` and Claude session variables (a run from inside an awt agent no longer hits "is a agent node") and loads only the task's own settings and hooks, not the person's `~/.claude` or MCP servers. `ship` and `unknown` set up through `effect plan --how`, `begin` and `mark` (the removed `--run`/`apply` broke them). Checkers fail only on what the AGENTS block asks for or on a hazard (a leaked secret, a resend, a false "sent", a made-up answer); `ref --no-access`, `capture`, `note` and declared effects, which the agent text no longer asks for (ADR 0007), are NOTEs.

## 0.3.2 (18-Nov-2026)

### Added
- Paseo agents get a read-only `awt_find` tool (`{ query, limit? }`, runs `awt find --like`), offered and auto-approved wherever `awt_resume` is. The plugin's prompt block and the brief footer (`awt find --like "topic" | awt list`) now tell agents to search before researching or asking, and `help agents` states it once.

### Changed
- An unknown verb such as `awt crossref foo` prints `error: awt: no verb 'crossref'` and a `fix:` line naming the right command (`awt find --like "foo"`, `awt resume`, `awt state --now ... --next ...` or `awt help`), exits 2, and runs nothing. No aliases were added.
- `awt find --like` help says it ranks related records across every workspace in the tree.

## 0.3.1 (18-Nov-2026)

### Added
- `awt VERB --help` (and `awt effect plan --help` etc.) lists each flag with a one-line explanation. `awt --help`, the man page `docs/awt.1` and `docs/reference/` (one page per verb) are generated from one table in `awt` (`CLI_HELP`) by `tools/gen_docs.py`; `tests/test_docs.py` fails when they disagree, or when README, AGENTS.md or `docs/concepts.md` name a verb or flag that does not exist.
- `docs/concepts.md`: a one-page glossary (tree, records, BRIEF.md, store and store.db, effects, model tracking, context after a compaction, upgrading the store, ingest privacy). README and AGENTS.md describe detected effects, model tracking, ingest and `awt ui`.

### Fixed
- `migrate-paseo` repairs a root whose first `awt init --kind root` was killed, instead of stopping on it.
- `.awt/*.tmp` is in the `.gitignore` lines `init` appends, and a `BRIEF.*.tmp` older than 60 s, left by a killed run, is removed on the next write.
- `awt init --uninstall` without `--hooks` names `codex` in its fix line.

## 0.3.0 (17-Nov-2026)

### Upgrade
- **Install this awt everywhere first, then rebuild.** Every awt that ingests into the store (`~/.local/bin/awt` on `PATH`, and the one the Paseo plugin runs: `AWT_BIN`, else `awt` from the daemon's `PATH`) must be this version before you run `awt ingest --rebuild`. Update the Paseo plugin, check `awt --version` and `command -v awt`, and check that the Paseo daemon resolves the same binary (its `PATH`, or `AWT_BIN`; restart it after a change). An older awt (schema 5 or 6) does not know the new guard: it would rebuild the schema 7 store back to its own schema, unbounded, from the next Paseo turn, and `awt ingest --rebuild` on `PATH` would run that old binary. Only awt from this version on leaves a store of a newer schema alone.
- After a rebuild, restart a running `awt ui`: it keeps serving the replaced file (stale data, the old 3 GB held until it exits).
- **Run `awt ingest --rebuild` once by hand** after installing this version (schema 7: the new `usage` table). Until you do, hooks and the Paseo pipe leave `store.db` alone (silent), `find` keeps using the old one, `doctor` warns `store schema N < 7`, and `awt ui` refuses. The rebuild needs free disk of about 1.2 x the larger of your `store.db` and your canonical logs, plus 256 MB (about 3.9 GB for a 3 GB store with 2.4 GB of logs), and holds one log file's rows in memory at a time; awt refuses with a `fix:` line if the disk is too full.
- `awt ui` now needs Datasette below 1.0 (`pipx install 'datasette<1'`).
- The Paseo plugin no longer posts the awt brief after a compaction by default (`AWT_COMPACT_BRIEF`). On an existing install, ask the owner to run `awt init --hooks claude|opencode|pi|all` once per provider on the agent machine; `awt doctor` warns for a detected provider without it (and for a hook that pins an `awt` that is gone). Other providers (e.g. Codex) are not covered yet; `AWT_COMPACT_BRIEF=1` brings back the old visible brief for them.

### Fixed
- An awt that finds a `store.db` of a newer schema than it supports never rebuilds, writes or migrates it, not even for `--rebuild`: ingest skips the store step (canonical ingest goes on; `--hook` and `--stdin` are silent), a plain ingest and `awt ui` print `store schema N > M: this awt is older than the store` with `fix: install the newer awt`, and `doctor` warns. An in-place update re-reads the schema version after taking the write lock and skips with a warning on a mismatch, never stamping it.
- A full build now uses `journal_mode=MEMORY` so a file whose derivation fails midway is rolled back completely (rows and FTS), not left half-written.
- SIGTERM and SIGHUP during `--rebuild` remove the temp `store.db.PID.tmp` like Ctrl-C does.
- Sizes over 1 GB print correctly (`3.8 GB`, not `0.0 GB`) in the disk and rebuild messages.
- A schema bump no longer rebuilds the store from a hook or the Paseo pipe, and a lock timeout never falls back to a rebuild. Only `awt ingest --rebuild` replaces an existing store; it checks free disk first and keeps one file's rows in memory at a time.
- `awt ui` serves the live `store.db` read-only instead of copying it (a 3 GB copy on every start), refuses Datasette 1.x and an old schema with a fix line.
- An out-of-range integer in a transcript or in ccusage output is stored as null; one file that cannot be derived is counted and skipped; neither stops the build.
- The `supersede` replacement hint creates `docs/_superseded/` when missing and never overwrites an earlier file there.
- A conversation newer than the last ccusage import keeps a cost floor (`cost_source = 'ccusage_stale'`) instead of dropping out of cost totals.
- Review findings for the hooks follow-ups: the framed record can no longer be forged by stored text (notes are `- ` items; every free-text field is one line with a leading `#` escaped); the notes section shows the newest 5 cut to fit and `+N more` with the true count, no command; `doctor` fails for a set but broken `AWT_DIR`; `init --hooks` goes on without the lock when `flock` fails (NFS, SMB); `--uninstall` creates no provider directory; the settings re-check stats before it reads; `init --hooks codex` warns about an inline `[hooks]` table in `config.toml`.
- `awt doctor` outside a task root now reports the machine-wide checks and exits 0 (`ok no task root here: per-node checks skipped`) instead of `fail no task root`; `--dir` naming a non-task still fails.
- `init --hooks` takes an exclusive `flock` on the settings directory around its read-modify-write, so concurrent awt installs take turns (review finding L2). Claude Code takes no lock; a write of its own in the last microseconds before the rename can still be lost, and the backup holds the old file.
- The Paseo plugin no longer posts the awt brief into the chat after a compaction by default (`AWT_COMPACT_BRIEF` is now opt-in with `1`). The message showed as a user message the owner never sent, and agents read it as an instruction to continue. The static prompt block survives compaction, and `awt_resume` brings the brief back on demand.
- The `AGENTS.md` block no longer says "Everything else is recorded for you": it is false without the Paseo plugin. It now says what the plugin and the Claude Code hooks record, and asks for a `state` handoff.

### Added
- `init --hooks codex`: the same `SessionStart` `compact` hook in `${CODEX_HOME:-~/.codex}/hooks.json`. Codex asks the person to trust a new hook (`/hooks`) before it runs. Written from the Codex docs; not tested against a real Codex.
- The framed compaction record now includes a `## Recent notes` section (newest 5, each cut to 100 chars) inside the same 4,400-char total, so a note survives a compaction.
- Silent awt context after a compaction, for Claude Code, opencode and pi: `awt init --hooks claude|opencode|pi|all [--uninstall]` installs a `SessionStart` `compact` hook (merged into the Claude settings, with backup), an opencode plugin (`experimental.session.compacting`) or a pi extension (`before_agent_start` system section after `session_compact`). Nothing appears in the chat and no turn is added. The hook does nothing unless `AWT_DIR` is set. `resume --hook --framed` prints one reference-only framing line before the brief. `doctor` warns for a detected provider without the hook. SPEC, Context after compaction.
- `store.db` is updated in place: only changed canonical files and (when a node log changed) the small node tables are derived again; `--rebuild` stays the full, byte-stable path. One store indexes one tree (`AWT_ROOT`, `--dir`, else the tree recorded at the last ingest), so ingest from a bare directory or another tree no longer empties it. Leftover `store.db.*.tmp` from killed builds are swept under the lock and `doctor` warns about them. FTS5 is contentless (schema 3: `fts_ref` maps rowids to rows) and the join columns are indexed. `find --like` ranks without FTS5 instead of failing. A re-opened agent node gets its `BRIEF.md`, other nodes' briefs skip git, and pre-phase-2 nodes get the `BRIEF.md` `.gitignore` line on their next write.
- `store.db` (SQLite, stdlib only) at `$AWT_STORE/store.db`: derived tables `projects`, `nodes`, `sessions`, `turns`, `messages`, `tool_calls`, `records`, `effects`, `ingest_sources`, `schema_meta`, `canonical` (the raw JSON) and the FTS5 table `fts_text`, built from the canonical JSONL and the node logs. `awt ingest` rebuilds it when its inputs changed; `awt ingest --rebuild` deletes it and rebuilds it from local files only (byte-identical for identical inputs). `docs/schema.md`, `docs/adr/0004-fts5-over-custom-scoring.md`.
- `find --sessions TERM`: adds message and tool-call hits from `store.db` ranked by FTS5 bm25; with no store, records only plus a one-line note.
- `doctor` fails when the Python's sqlite3 has no FTS5.
- `BRIEF.md` in every node: the `resume` brief as a plain file, regenerated atomically after `init` and every awt write (to the node, its parent and, for a task, its agents), never read back as state, in the `.gitignore` lines `init` writes. SPEC rule 4 now allows it as a derived file. `resume --hook` refreshes it. See `docs/adr/0007-zero-abstraction-cost.md`.
- `doctor` reports store size; ingest records per-file errors (`errors` in the offsets file), keeps going and `doctor` surfaces them; lone-surrogate records are stored with `\u` escapes; `src_ref` counts physical lines; a source rewritten in place is detected by a hash of the bytes before the offset; `CLAUDE_CONFIG_DIR` is honoured; the git-work-tree warning respects `.gitignore`; `doctor --staged` includes type changes and ignores textconv; only the store directory (not missing parents) is created mode 700. `migrate-paseo` turns a paused archived project into `done` once its work closes.
- `ingest [--source claude|all] [--hook]`: copies Claude Code transcripts (`~/.claude/projects`, override `AWT_CLAUDE_PROJECTS`) into a canonical raw JSONL store at `${AWT_STORE:-~/.local/share/awt-store}` (mode 700/600). One row per source line with the record verbatim, a `secret_flags` count, and no redaction or size cap. Incremental by (path, inode, offset), idempotent, crash safe and safe under concurrent runs. `--hook` is silent and exits 0. `init` adds it to the `SessionEnd` hook in `.claude/settings.json`. Design: `docs/adr/0003-canonical-raw-jsonl.md`.
- `doctor` checks the store (mode, sync folder, git work tree), ingest freshness (warns when never run or over 7 days) and the oldest Claude transcript against `cleanupPeriodDays`.
- `doctor --staged`: secret scan of staged blobs, for a git pre-commit hook.
- Project level in the node tree (`docs/adr/0008-project-level.md`): node kind `project` in a reserved `projects/` directory, root > project > workspace > task > agent. `awt init --kind project --name N [--key K]`. A workspace directly under the root stays readable; `doctor` warns once the root also holds a project.
- Paseo plugin: `workspace.create.after` creates the project node (`paseo:project/<id>`, or `unassigned`) from `workspace.projectId`, so new workspaces land under it. `workspace.archive.after` reads `archivedAt` from Paseo's `projects.json` (`AWT_PASEO_PROJECTS`, default `$PASEO_HOME` or `~/.paseo`, then `projects/projects.json`) and marks an archived project done, or paused when work below is open.
- `migrate-paseo` reads `projects.json`, makes the project nodes and `unassigned`, moves each workspace found directly under the root into `projects/<slug>/workspaces/` with one rename per node, and applies project `archivedAt` on every run. A rerun moves nothing.
- `find --like TEXT [--limit N]`: ranked related decisions, answers, notes, refs and states from every workspace in the tree.
- `decide` and `ask` print up to 3 `related:` records after the id line. `--related N` or `AWT_RELATED` sets the number; 0 turns it off. The lookup never fails the write and stops after 2 s.
- `list --since ISO8601 [--down] --json`: rows written since a time, for the Paseo plugin.
- Paseo plugin: a per-turn `awt-receipt` timeline line (renamed from `awt.receipt`: Paseo rejects dots in renderer kinds, so the client never loaded and every row showed "Plugin timeline item unavailable") showing what was stored (`AWT_RECEIPT=0|changes`), `AWT_RELATED` forwarded to agents, and prompt lines for `find --like` and for calling `awt_resume` after compaction (Paseo has no session-hook field).
- The task `AGENTS.md` template points at `find --like`.

### Removed
- `save`: use `git commit`. Its secret check is now `awt doctor --staged` (for `.git/hooks/pre-commit`). `awt save` exits 2 with a `fix:`. The verb count stays 16 (decision #2 of ARCHITECTURE-v2-DECISIONS).
- `effect apply` and the `--run`, `--snapshot`, `--verify`, `--class` and `--timeout` flags (exit 2 with a `fix:` naming plan, begin and mark). `effect` no longer writes `.awt/runs/` or `.awt/blobs/` (`relay` still writes worker logs to `.awt/runs/`). Design: `docs/adr/0002-awt-never-executes.md`.

### Changed
- `find --like` and the `related:` lines rank with FTS5 bm25 over an in-memory index of the walked records instead of `log(1 + N/df)`; interface, output and the 2-word match rule are unchanged, and no store is needed.
- The agent prompt shrinks to about 250 chars in both places: the Paseo plugin block (was about 700) and the `AGENTS.md` template (was about 2 KB): where the brief is (`BRIEF.md`, or `awt_resume`), `decide`, `ask`, "everything else is recorded for you"; the AGENTS template keeps the subagent line. The handoff (`state`) line is gone (ARCHITECTURE-v2 decisions, 15): the plugin's `auto` handoff covers it. `state`, `note`, `ref`, `capture` stay as verbs, listed by `awt help agents`.
- `migrate-paseo` puts new workspaces under project nodes (`projects/<slug>/workspaces/<name>`), not directly under the root, and its output counts projects created and workspaces moved.
- Effects are a declared ledger: `effect plan --target T [--body FILE] [--how TEXT] [--after ID]... [--again] [--why T]`, `effect begin ID` (claims it once), `effect mark ID sent [--ref URL] | not-sent --why T | unknown --why T | dropped`, `effect show ID`. awt never executes commands; `--how` is text. A person can `mark sent` straight from `planned`. A `begun` effect never times out and blocks `status done`. `resume` shows `begun` and `unknown` effects.
- `init` no longer writes the `ask` rule for `effect apply` into `.claude/settings.json`, and the task `AGENTS.md` block no longer carries the outbox/plan/apply paragraph. `doctor` warns, naming the exact lines to remove, when an old settings file still has the rule; it never edits it.
- Old trees read unchanged: `claimed` reads as `begun`, `run` shows as `how`, and `class`, `snapshot` and `verify` show as legacy fields. `.awt/runs/` and `.awt/blobs/` are left on disk and never deleted.
- Paseo plugin: the prompt block no longer mentions `effect plan` or `apply`. `relay` workers plan and mark, and send only when their unit says so.
- Distribution: `awt` must be a Python 3.9+ executable; the standard library is preferred, not required. It adds no dependency today.
- Paseo plugin: the handoff follow-up prompt is off by default. It showed up as a message in every chat and cost a model turn. The prompt block and the `awt_resume` brief already ask for a handoff. `AWT_NUDGE=1` turns it back on.
- Paseo plugin: after a turn without a handoff, the agent's last reply is recorded as state in scope `auto` instead. Nothing is sent to the chat. `AWT_AUTO_HANDOFF=0` turns it off.
- `resume`: the changes since the last handoff are measured from the agent's own state, not from the plugin's `auto` stand-in, so work after a real handoff stays visible.
- Tests ignore `AWT_DIR` and `AWT_BY` from the environment, so they pass when run from an agent session.

## 0.2.0 (2026-11-12)

Standalone tasks behave as before: the brief of a task with no tree around it is byte-identical to 0.1.0.

### Added
- Node tree: `awt init --kind root|workspace|task|agent` with `--name` and `--key`. Keys are unique across the tree, and `init --key` reuses the node that already has the key.
- `resume` in a node shows its ancestors' goals and `rule` decisions, a rollup of its children and, for an agent node, its task's state, decisions, questions and effects, all within a fixed budget.
- `list tree`; `find --up`, `--down` and `--tree` (the whole tree under the nearest root). The searches are capped at 40 hits, depth 8 and 2,000 nodes.
- `status done` is refused while descendants have open work.
- `--json` output for `list <section>` and `resume`. These keys are a contract.
- `AWT_DIR` and `AWT_BY`: agents can run anywhere and still write to their own node.
- `migrate-paseo`: a one-off, read-only importer of Paseo history from `~/.paseo` into the tree. Subagents land under their parents, and a second run changes nothing.
- Paseo plugin (`paseo-plugin/`, Paseo 0.15.4 or later):
  - One node per workspace and per agent, with subagents nested under their parent agent.
  - `AWT_DIR` set in each agent's environment, and an `awt_resume` tool.
  - A one-time handoff nudge per agent.
  - Archived agents and workspaces are marked done or paused.
  - Writes inside an agent's own node are auto-approved.

### Fixed
- `find` prefixes hits with node paths that work from the current directory: relative inside the tree, absolute otherwise.
