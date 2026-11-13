# Changelog

## Unreleased

### Added
- `store.db` (SQLite, stdlib only) at `$AWT_STORE/store.db`: derived tables `projects`, `nodes`, `sessions`, `turns`, `messages`, `tool_calls`, `records`, `effects`, `ingest_sources`, `schema_meta`, `canonical` (the raw JSON) and the FTS5 table `fts_text`, built from the canonical JSONL and the node logs. `awt ingest` rebuilds it when its inputs changed; `awt ingest --rebuild` deletes it and rebuilds it from local files only (byte-identical for identical inputs). `docs/schema.md`, `docs/adr/0004-fts5-over-custom-scoring.md`.
- `find --sessions TERM`: adds message and tool-call hits from `store.db` ranked by FTS5 bm25; with no store, records only plus a one-line note.
- `doctor` fails when the Python's sqlite3 has no FTS5.
- `ingest [--source claude|all] [--hook]`: copies Claude Code transcripts (`~/.claude/projects`, override `AWT_CLAUDE_PROJECTS`) into a canonical raw JSONL store at `${AWT_STORE:-~/.local/share/awt-store}` (mode 700/600). One row per source line with the record verbatim, a `secret_flags` count, and no redaction or size cap. Incremental by (path, inode, offset), idempotent, crash safe and safe under concurrent runs. `--hook` is silent and exits 0. `init` adds it to the `SessionEnd` hook in `.claude/settings.json`. Design: `docs/adr/0003-canonical-raw-jsonl.md`.
- `doctor` checks the store (mode, sync folder, git work tree), ingest freshness (warns when never run or over 7 days) and the oldest Claude transcript against `cleanupPeriodDays`.
- `doctor --staged`: secret scan of staged blobs, for a git pre-commit hook.
- Project level in the node tree (`docs/adr/0008-project-level.md`): node kind `project` in a reserved `projects/` directory, root > project > workspace > task > agent. `awt init --kind project --name N [--key K]`. A workspace directly under the root stays readable; `doctor` warns once the root also holds a project.
- Paseo plugin: `workspace.create.after` creates the project node (`paseo:project/<id>`, or `unassigned`) from `workspace.projectId`, so new workspaces land under it. `workspace.archive.after` reads `archivedAt` from Paseo's `projects.json` (`AWT_PASEO_PROJECTS`, default `$PASEO_HOME` or `~/.paseo`, then `projects/projects.json`) and marks an archived project done, or paused when work below is open.
- `migrate-paseo` reads `projects.json`, makes the project nodes and `unassigned`, moves each workspace found directly under the root into `projects/<slug>/workspaces/` with one rename per node, and applies project `archivedAt` on every run. A rerun moves nothing.
- `find --like TEXT [--limit N]`: ranked related decisions, answers, notes, refs and states from every workspace in the tree.
- `decide` and `ask` print up to 3 `related:` records after the id line. `--related N` or `AWT_RELATED` sets the number; 0 turns it off. The lookup never fails the write and stops after 2 s.
- `list --since ISO8601 [--down] --json`: rows written since a time, for the Paseo plugin.
- Paseo plugin: a per-turn `awt.receipt` timeline line showing what was stored (`AWT_RECEIPT=0|changes`), `AWT_RELATED` forwarded to agents, and prompt lines for `find --like` and for calling `awt_resume` after compaction (Paseo has no session-hook field).
- The task `AGENTS.md` template points at `find --like`.

### Removed
- `save`: use `git commit`. Its secret check is now `awt doctor --staged` (for `.git/hooks/pre-commit`). `awt save` exits 2 with a `fix:`. The verb count stays 16 (decision #2 of ARCHITECTURE-v2-DECISIONS).
- `effect apply` and the `--run`, `--snapshot`, `--verify`, `--class` and `--timeout` flags (exit 2 with a `fix:` naming plan, begin and mark). `effect` no longer writes `.awt/runs/` or `.awt/blobs/` (`relay` still writes worker logs to `.awt/runs/`). Design: `docs/adr/0002-awt-never-executes.md`.

### Changed
- `find --like` and the `related:` lines rank with FTS5 bm25 over an in-memory index of the walked records instead of `log(1 + N/df)`; interface, output and the 2-word match rule are unchanged, and no store is needed.
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
