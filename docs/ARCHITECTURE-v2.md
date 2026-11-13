# awt architecture v2

Status: draft for owner review. Nothing here is built. Once accepted, each part goes into `SPEC.md` and `tests/TEST-SPEC.md` together with its code, and each major choice gets an ADR (see section 9). Examples use the fictional `parsekit` project.

## 1. Job statement

**awt exists to give open, free access to the data of agentic sessions, at every level of detail.** "Open" means a documented schema in plain files that any tool can read without awt. "Free" means owner-held, local, no account, no paid service. Everything else in awt (the brief, records, effects, the tree, the Paseo plugin) is a component that produces or serves that data.

| User | Their job | What they need from awt |
|---|---|---|
| **Agent mid-task** | Continue work without re-asking or re-deciding, and never send the same thing twice | A small fixed-size brief, ranked search over past records and sessions, a ledger for outbound actions. Cheap in tokens; refusals with a `fix:` line |
| **Owner** | See what agents did and why, find anything from any session, decide on outbound work, keep the data after providers prune it | One local store across Claude Code, opencode and pi; a browsable UI on demand; honest limits |
| **Analytics** (owner or a script) | Answer questions about cost, latency, tool use, failure and rework across sessions | Stable tables, SQL with DuckDB or SQLite, Parquet for bulk; field names that match OTel GenAI where they fit |

Non-jobs: running commands for agents (section 6), being a permission system, hosting a service, sending data anywhere.

### Design principle: zero abstraction cost for agents

**Agents should get the value of awt without learning awt.** An agent that never reads the awt prompt block and never runs an awt verb must still have its sessions, turns, tool calls, handoffs and outbound actions recorded, and must still be able to read its task's history. Every awt concept an agent has to remember is a cost paid in prompt tokens, in forgetting, and in wrong use. Reasons: agents are hurried (rule 1) and forget instructions under load; providers differ, but tool calls and files are the same everywhere; the auto handoff (PR #10) already showed that host-side capture beats asking.

What follows from it:

1. **Capture is passive and host-side.** The Paseo plugin and the transcript adapters record sessions, turns, tool calls, permission requests and handoffs. The `auto` state that the plugin writes after a turn without a handoff is the model for everything else.
2. **Outbound actions are detected, not declared.** The plugin (and, for standalone Claude Code, a `PreToolUse`/`PostToolUse` hook) sees tool calls and permission requests such as `git push`, `gh pr comment` or `curl -X POST`, and writes the effect ledger itself. Agents use their normal tools. Explicit `effect plan|begin|mark` stays as an optional path for multi-step or retry-sensitive sends (section 6).
3. **Reading uses what agents already know.** Plain files (a generated `BRIEF.md` per node), `grep`, SQL over SQLite. The brief arrives through host mechanisms (session start and compaction hooks, the plugin's `awt_resume` tool), not through the agent remembering a verb.
4. **Intentional records are the one place agent intent matters.** A decision's reason or a question for a person cannot be reliably inferred. At most two agent-facing verbs: `decide` and `ask`. Optional post-turn extraction of decisions and questions from transcripts can fill gaps (section 3.9), measured before it is relied on.
5. **The agent-facing prompt shrinks** from the current ~700-char block to about 250 chars: where the brief is, the two verbs, and "everything else is recorded for you".

Tensions, stated plainly:
- **Detection is fallible.** A pattern list misses unusual senders (a script, an MCP tool, a browser) and can flag harmless commands. A miss is a missing ledger row, visible in analytics, not a security hole; but "never sent twice" becomes "a resend is noticed" unless the host can gate it (section 6).
- **Extraction vs. intent.** An extracted decision is a guess about what the agent meant. It is always marked as inferred and never overrides a record the agent wrote.
- **Cost.** Extraction with a model spends tokens on every turn. Paid extraction needs owner approval.
- **Privacy.** Extraction with a hosted model sends transcript text off the machine, which breaks "local only". Only a local model, or explicit owner approval per source, is acceptable.
- **Rule 4 (views are never written).** A generated `BRIEF.md` is a written view. It is allowed as a derived file, regenerated on ingest and never read back as state; rule 4 is amended to say that.

## 2. Levels of detail (LOD)

Records (decision, question, answer, note, ref, capture, state, effect) can attach at any level. The backbone sources are the Paseo plugin (uniform across providers), provider transcripts on disk, and awt's own records. Provider OTel is optional enrichment, never required.

The ladder below adds **project** between root and workspace, so every level from workspace down moves one number from the earlier L0-L7 draft.

| LOD | Unit | Backbone source | Optional enrichment |
|---|---|---|---|
| L0 | Tree (root) | awt node logs | |
| L1 | Project (groups workspaces) | awt node (`paseo:project/<id>`); plugin's `workspace.projectId`; `~/.paseo/projects/projects.json` | |
| L2 | Workspace | awt node (`paseo:workspace/<id>`), Paseo `workspace.*` hooks | |
| L3 | Task | awt node | |
| L4 | Agent (chat, subagent) | awt node (`paseo:agent/<id>`), Paseo `agent.*` hooks, parent label | |
| L5 | Session (one provider conversation) | Claude `~/.claude/projects/*/<session-id>.jsonl`; opencode `~/.local/share/opencode/opencode.db`; pi `~/.pi/agent/sessions/*/*.jsonl` | Claude Code OTel (native); opencode `openTelemetry` config |
| L6 | Turn (one user prompt to the end of the reply) | Paseo `agent.turn.before/after` (start, outcome); transcripts (user message boundaries) | OTel spans |
| L7 | Message, tool call, permission request | Transcripts (messages, tool use and results); Paseo `agent.permission.before` and timeline | OTel tool events |
| L8 | Tokens, cost, latency | Transcript usage blocks and timestamps; ccusage for priced cost | OTel metrics |
| any | Records | `.awt/events.jsonl` of each node | |

### 2.1 Project level in the tree

Today `SPEC.md` maps a Paseo project to "not a node: a `ref kind=paseo` on each workspace node" with key `paseo:project/<id>`, and the plugin already reads `workspace.projectId` when it creates a workspace node. v2 makes the project a node:

- **Tree:** root > project > workspace > task > agent. New kind `project`, reserved directory `projects/` under the root; a project contains `workspace`. A `workspace` directly under the root stays readable as a legacy placement; `doctor` warns and the migration moves it.
- **Key:** `paseo:project/<id>`. **Name:** `customName ?? displayName`. A `ref` to the project's `rootPath` is recorded, as a workspace records its working directory.
- **No project:** a workspace with no `projectId` (and every `unassigned--*` workspace) goes under one project `unassigned`, key `paseo:project/unassigned`.
- **Archive:** an archived project (`archivedAt` set) becomes `done`, or `paused` when work below it is open, exactly like workspaces. Whether Paseo has a project archive hook is unverified; if not, the plugin checks `archivedAt` on `workspace.archive.after` and `migrate-paseo` applies it on each run.
- **Standalone use:** `awt init --kind project --name N` for people who do not use Paseo. Optional: a tree without projects behaves as today.
- **Migration** of existing trees: section 8.

pi: the `pi-telemetry` package defines contracts but ships no exporter, so pi has no OTel source; its transcripts are the source.

## 3. Data architecture

### 3.1 Flow

```
provider transcripts ─┐                       ┌─> store.db  (SQLite + FTS5, derived)
Paseo plugin events  ─┼─> adapters ─> redact ─> canonical JSONL ─┤
awt node logs ────────┘   (read-only)          (append-only)     └─> *.parquet (derived, by a DuckDB recipe)
```

- **Adapters** read sources read-only and never modify them. One adapter per source, each with a version number written on every row it produces.
- **Canonical** is the only state the store owns. Derived files can be deleted at any time and rebuilt.
- awt node logs stay where they are and stay canonical for records. The store indexes them; it does not copy them.

### 3.2 Adapters

| Source | Read how | Incremental by | Notes |
|---|---|---|---|
| Claude Code | JSONL lines under `~/.claude/projects/`; fields `sessionId`, `uuid`, `parentUuid`, `timestamp`, `cwd`, `message.content[]` (text, `tool_use`, `tool_result`), `message.usage` | (path, inode, byte offset) per file | **Pruned after 30 days by default** (fact 1 below). Ingest must run at least weekly; better, on every session end |
| opencode | SQLite opened `mode=ro` | per-session max updated time | Schema not yet verified against a live DB. The adapter checks for the tables and columns it knows and refuses (warns, skips) on anything else rather than guessing |
| pi | JSONL under `~/.pi/agent/sessions/` | (path, inode, offset) | Format to be pinned from a real file at build time |
| Paseo | The plugin pipes hook events into `awt ingest --source paseo` on stdin; `migrate-paseo` reads `~/.paseo/projects/projects.json` and `workspaces.json` | event id | Turn start, outcome, tool calls, permission requests and how they were answered, project/workspace/agent ids, parent. The only uniform L6/L7 source across providers, and the source of detected effects (section 6) |
| awt records | `load()` per node over the tree walk | (node, line count) | Quarantined rows are counted, not ingested |
| ccusage | `ccusage session --json` (pinned version) | session id | Priced cost for Claude Code, Codex, opencode, pi |
| OTel (optional) | OTLP/JSON from a local file exporter | file offset | Enrichment only. Phase 6 |

Triggers, host-native first: Claude Code `SessionEnd` hook runs `awt ingest --source claude --hook`; the Paseo plugin runs it after `agent.turn.after` (detached, never awaited); otherwise the owner schedules it (launchd/cron). Every trigger is incremental and idempotent.

**Joining a session to an agent node.** Paseo knows the agent id; the transcript knows the provider session id. The join is the provider's session id as recorded by Paseo for that agent, if Paseo exposes it; otherwise (cwd, first timestamp within 60 s). Which of the two is available is not yet verified (open question 4). An unjoined session is still ingested, with `node_id` null.

### 3.3 Canonical JSONL

`$AWT_STORE/log/<source>/<YYYY-MM>/<session-or-stream>.jsonl`, `AWT_STORE` default `${XDG_DATA_HOME:-~/.local/share}/awt-store`. Separate from `AWT_ROOT` on purpose: the tree may be committed to a private repo; the store holds full conversation text and should not be.

One row per source record:

```json
{"v":1,"src":"claude","adapter":1,"session":"3f0c…","seq":41,"ingested":"2026-11-13T09:12:03.120Z","src_ref":"projects/-Users-x-parsekit/3f0c….jsonl:41","redactions":0,"raw":{ … the provider record, redacted … }}
```

- `raw` is the **redacted provider record, otherwise verbatim**. Reason: adapters will be wrong in v1, and a new adapter version must be able to re-derive tables after the provider has pruned the source. Normalizing at ingest would make that impossible.
- Writes reuse awt's rules: single `O_APPEND` write per row, torn tail healed, no locks except `flock` around the per-source offset file.
- A string over 256 KB inside `raw` (large tool output) is cut, with `{"cut":true,"sha256":…,"bytes":…}` beside it. The cap is an open question (5).

### 3.4 Derived tables (`store.db`)

Column naming: where an OTel GenAI attribute fits, the column is that attribute without the `gen_ai.` prefix, dots to underscores (`gen_ai.usage.input_tokens` → `usage_input_tokens`). Everything else is plain and listed as awt-specific in `docs/schema.md`. The semconv version used is pinned in that file.

| Table | Grain (LOD) | Key fields |
|---|---|---|
| `projects` | L1 | `project_id` (`paseo:project/<id>` or `unassigned`), `node_id`, `name` (`customName ?? displayName`), `project_key`, `root_path`, `kind`, `created_at`, `updated_at`, `archived_at` |
| `nodes` | L0-L4 | `node_id` (key, e.g. `paseo:agent/…`, else path), `kind`, `name`, `path`, `parent_id`, `project_id`, `status`, `goal` |
| `sessions` | L5 | `session_id`, `provider_name` (`claude_code`, `opencode`, `pi`), `conversation_id` (provider id), `node_id`, `cwd`, `request_model`, `started_at`, `ended_at`, `source`, `adapter` |
| `turns` | L6 | `turn_id`, `session_id`, `seq`, `started_at`, `ended_at`, `outcome` (`completed`, `failed`, `canceled`, null), `paseo_turn` (bool: from hooks or inferred) |
| `messages` | L7 | `message_id`, `turn_id`, `session_id`, `role`, `ts`, `text` (redacted), `parent_id`, `response_finish_reasons` |
| `tool_calls` | L7 | `tool_call_id`, `message_id`, `session_id`, `tool_name`, `args` (JSON, redacted), `result_excerpt`, `result_sha256`, `is_error`, `started_at`, `ended_at` |
| `permissions` | L7 | `request_id`, `session_id`, `tool_name`, `target` (path or command, redacted), `decision` (`allow`, `deny`, `ask`, unanswered), `decided_by` (`host_rule`, `person`, `plugin`), `ts` |
| `usage` | L8 | `message_id` or `turn_id`, `request_model`, `response_model`, `usage_input_tokens`, `usage_output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `cost_source` (`ccusage`, `computed`, null), `latency_ms` |
| `records` | any | `record_id` (awt id or node+line), `node_id`, `type`, `ts`, `by`, `fields` (JSON), `session_id` (when `by` or time window joins it), `origin` (`agent`, `person`, `plugin`, `inferred`) |
| `effects` | any | `effect_id`, `node_id`, `target`, `key`, `state`, `attempt`, `origin` (`detected` or `declared`), `rule` (the detection pattern that matched), `begun_by`, `begun_at`, `sent_ref`, `tool_call_id` |
| `ingest_sources` | — | `source`, `path`, `inode`, `offset`, `adapter`, `last_run`, `errors` |
| `fts_text` | — | FTS5 over `messages.text`, `tool_calls.args`, record text fields, with `kind` and `rowid` back-pointers |
| `schema_meta` | — | `schema_version`, `semconv_version`, built-at |

Raw `raw` JSON stays queryable: `store.db` keeps a `canonical` table (`src`, `session`, `seq`, `raw` JSON) so any field the tables lack is one `json_extract` away.

### 3.5 Rebuild

`awt ingest --rebuild` deletes `store.db` and rebuilds it from canonical JSONL plus node logs. It never re-reads providers for rebuild, so a rebuild is always possible and always the same. A schema or adapter version change means rebuild; no migrations of derived data.

Parquet is produced by a documented DuckDB recipe (`docs/recipes/parquet.sql`: `ATTACH 'store.db' (TYPE sqlite); COPY … TO '….parquet'`), not by awt code. Reason: DuckDB already does this well; linking it into awt adds a dependency for one command.

### 3.6 Retention

- Canonical: kept forever by default. The owner holds it because providers do not.
- No automatic deletion anywhere. `doctor` reports store size and the oldest Claude transcript age vs. `cleanupPeriodDays`, and warns when ingest has not run within 7 days.
- Deleting data is the owner's act (delete files by month directory; then `--rebuild`). Whether to add a `--forget` command is open question 6.

### 3.7 Redaction

- Every string in `raw`, recursively, passes awt's existing secret scan before the write. A match becomes `[REDACTED:<pattern>]`, counted in `redactions`. Irreversible by design: the secret never reaches the store.
- An optional owner pattern file `${XDG_CONFIG_HOME:-~/.config}/awt/redact` (one regex per line) adds patterns.
- Honest limit: pattern-based scanning misses secrets it has no pattern for, and conversations contain whatever was pasted into them. The store is as sensitive as the transcripts it copies.

### 3.8 Privacy

Local only. No network calls in awt's ingest, store or UI paths. Store directory mode `0700`, files `0600`. `doctor` warns when `AWT_STORE` is on a synced or network path, or inside a git work tree. `awt ui` binds `127.0.0.1` only and opens the database read-only.

### 3.9 Inferred records (optional)

Post-turn extraction of decisions and questions from transcripts, for agents that never call `decide` or `ask`.

- Runs after ingest on new turns only. Writes `decision` or `question` rows with `by: extractor`, `origin: inferred`, and a pointer to the message it came from. Never supersedes or edits a record an agent or person wrote; a duplicate of one is dropped.
- Shown in the brief under its own label ("inferred, unconfirmed"), so a person or agent can confirm (`decide --supersedes`) or ignore it.
- **Off by default.** A local model costs no tokens but needs the owner's go-ahead for the download. A hosted model costs tokens on every turn and sends transcript text off the machine: owner approval per source, recorded in config.
- **Measure before relying on it:** precision and recall on a hand-labelled sample of past turns (fictional fixtures in the repo; the owner's own data only on the owner's machine). Below the bar the owner sets, it stays off.

## 4. Access

All access is to the same files; awt is never required to read them.

| Path | For | How |
|---|---|---|
| SQL | Owner, analytics, scripts | `sqlite3 -readonly $AWT_STORE/store.db`; DuckDB `ATTACH '…/store.db' (TYPE sqlite, READ_ONLY)` or `read_parquet('…/*.parquet')`. `docs/schema.md` and `docs/recipes/*.sql` are the documentation |
| Plain files | Agent, owner | `$AWT_DIR/BRIEF.md` in every node: the `resume` brief, regenerated on ingest and after every awt write (a derived file; never read back as state). Records stay greppable in `.awt/events.jsonl`. An agent needs only `cat` and `grep` |
| Host delivery | Agent | The brief arrives without the agent asking: Claude Code `SessionStart` hook (no matcher, so it also runs after compaction); the Paseo plugin's `awt_resume` tool and its prompt pointer to `BRIEF.md` |
| CLI | Owner, agent (optional) | `awt resume`, `awt find` (FTS5-ranked, records by default; `--sessions` adds messages and tool calls), `awt list`. Useful, never required for an agent |
| Agent SQL | Agent (optional) | Read-only `sqlite3` with the agent's own tools, under host permissions. Optional `awt_find` plugin tool with the same output as `awt find` |
| `awt ui` | Owner | Starts Datasette on `127.0.0.1` against `store.db` in immutable mode, with canned queries from `docs/recipes`. Exits with the terminal. Not a daemon |
| Paseo screen (optional) | Owner in Paseo | A plugin screen showing per-agent sessions, turns, cost and records, reading through `awt … --json`. Phase 6 |

DuckDB UI is not the default UI: its local server fetches the frontend from `ui.duckdb.org` (fact 2 below). Queries stay local, but the code that can read the loaded data is fetched from a remote site on each use. Datasette serves its own assets from the installed package.

## 5. Buy before build

Verified 2026-11-13. The stdlib-only rule is lifted; each dependency below has its reason.

| Need | Choice | License | Decision | Reason |
|---|---|---|---|---|
| Usage and cost | ccusage | MIT | **Buy** | Covers Claude Code, Codex, opencode, pi; keeps model prices current; we would otherwise maintain a price table |
| Owner UI | Datasette | Apache-2.0 | **Buy**, on demand | Generic SQLite browser with facets, FTS and canned queries; local; nothing to build |
| Search ranking | SQLite FTS5 (bm25) | public domain | **Buy** (built into Python's sqlite3 on common builds) | Replaces PR #11's hand-rolled `log(1+N/df)` scoring; `doctor` fails if FTS5 is missing |
| Meaning search | sqlite-vec | MIT/Apache-2.0 | **Later, gated** | Only if measurement shows a gap (section 10, phase 7) |
| Bulk analytics | DuckDB (owner's install) | MIT | **Use, not link** | Reads SQLite and writes Parquet; a recipe, not code |
| Ingest, schema, redaction, effects ledger | awt | MIT | **Build** | Nothing existing normalizes three providers plus Paseo into an open local schema |
| Tracing UI | Phoenix | ELv2 | Rejected | Not OSS |
| Tracing platform | Langfuse | MIT core | Rejected | Postgres + ClickHouse + Redis to run for one person |
| Task graph | Beads | MIT | Rejected | Dolt-only storage |
| Session memory | claude-mem | Apache-2.0 | Rejected | Claude Code only; awt is provider-neutral |
| Durable execution | DBOS, Temporal | MIT | Rejected | awt no longer executes anything (section 6); far too heavy |

## 6. Effects redesign

**Glossary line:** an effect is a record of one thing leaving your machine, tracked so it is never sent twice or retried blindly.

**Rule: awt never executes commands.** It keeps the ledger; the agent sends with its own tools, so the host's permission system (Claude Code rules and auto mode, opencode permissions, Paseo permission hooks) sees the real command.

There are two ways a row enters the ledger. Both write the same `effect` rows and the same states.

### 6.1 Detected (default; the agent does nothing)

The host side recognises an outbound action and writes the ledger itself.

| Where | Sees | Writes |
|---|---|---|
| Claude Code `PreToolUse` hook (`awt ingest --hook`) | Every `Bash` / MCP call before it runs | `planned` + `begun` for a match. If the same key is already `sent` or `unknown`, the hook returns `permissionDecision: ask` with the earlier effect's id and `--ref`, so the host asks the person. This is the host's own gate, not awt's |
| Claude Code `PostToolUse` hook | The result | `sent` on success; `unknown` on error, timeout or interruption (it may have gone out) |
| Paseo `agent.permission.before` | Calls the provider asks about | `planned` + `begun`; a resend is left for the person, with a timeline note naming the earlier effect. The plugin still never denies |
| Paseo timeline / `agent.turn.after`, transcript ingest | Every tool call, after it ran (including auto-allowed ones that raised no permission request) | `sent` or `unknown`, after the fact |

- **Detection rules:** a short built-in list of outbound patterns (`git push`, `gh pr|issue create|comment|edit|merge|close`, `gh release create`, `gh api` with a write method, `curl`/`wget` with a body or a write method to a non-local host, `ssh`/`scp` to a non-local host, `npm|cargo|twine publish`, MCP tools whose names match `send|post|create|comment|publish`), plus owner lines in `${XDG_CONFIG_HOME:-~/.config}/awt/outbound`. Each row records the `rule` that matched.
- **Key:** `sha256(tool, normalized command or tool input, sha of any file it names as a body, cwd)`. Same key twice is a resend.
- **This is labelling, not a permission system.** A wrong match costs one wrong ledger row; a miss costs a missing row, which analytics surfaces (outbound-looking calls with no effect). It never decides whether anything runs. That is the difference from 7b25143's classifier.
- **Honest limit:** where the host gives no pre-execution hook for a call (auto-allowed under Paseo, opencode, pi), the duplicate is noticed after the fact, not prevented. Prevention needs either a host gate (Claude Code `PreToolUse`) or the explicit path below.

### 6.2 Declared (optional; multi-step or retry-sensitive sends)

For sends where a blind retry is costly (a release announcement, a ticket transition, a send that must wait for another), the agent or person declares it:

```
planned --begin--> begun --mark sent--------> sent
   |                 |--mark not-sent-------> planned (attempt+1)
   |                 +--mark unknown--------> unknown --mark sent|not-sent
   +--mark dropped--> dropped
```

- `effect plan --target T [--body FILE] [--how TEXT] [--after ID]... [--again] [--why T]`. `key = sha256(target, body sha, nonce)`. Same key: print the existing id and state, write nothing. `--how` is the intended command as text (cap 400), shown to people and used to match the detected tool call to this effect (so it is not recorded twice). It is never run and is not in the key. An open `unknown` on the same target refuses a new plan unless `--again`.
- `effect begin ID`: refuses unless `planned`, every `--after` is `sent`, and the body sha still matches. Creates `.awt/claims/<key>.<attempt>` with `O_EXCL` (losing means someone else is sending: exit 1), emits `step: begun`. Prints the body path, `--how`, and the `mark` command.
- The agent or person sends with their own tools. Detection, if it fires, attaches to the begun effect instead of opening a new one.
- `effect mark ID sent [--ref URL] | not-sent --why T | unknown --why T | dropped`. Legal only as drawn. `begun` with no mark stays `begun`, needs attention in the brief, and blocks `status done`. No timeout changes it: only the sender knows.
- `effect show ID` unchanged apart from the removed fields.

### 6.3 Removed, lost, gained

Removed: `effect apply`, `--run`, `--snapshot`, `--verify`, `--class`, `--timeout`, writes to `.awt/runs/` and `.awt/blobs/`, the `ask` rule in `.claude/settings.json`, and the outbox/plan/apply paragraph of the agent prompt. An `overwrite` send that needs the prior state saved: save it into `context/` before sending and name it in `--why`.

Lost: awt no longer holds the claim *during* the run by pid, and cannot verify. Crash semantics stay safe: a crash after `begin` (or after a detected `begun`) leaves `begun`, never retried, shown to a person. Verification is the sender's job, recorded with `mark sent --ref` or by `PostToolUse`.

Gained: agents need no effect concept at all for ordinary sends; the host's permission check sees the real command; and analytics can audit every outbound-looking call against the ledger.

**Why the 7b25143 branch (action policy) must not be merged.** It reasons correctly that one gate, in the host, beats two, and it removes the `ask` rule; both conclusions are kept here. But its fix keeps awt executing commands and then rebuilds a permission system inside awt to compensate: a shlex-based shell classifier, hand-kept subcommand and option lists for `git`, `gh` and `curl`, CIDR tables, a `dest` derivation, an allowance file with `owner`/`allow` grammar, and `via: hand` marks. That is a second permission system after all, weaker than the host's (static parsing of shell is bypassable and needs upkeep with every CLI release), and its own text concedes it is not a sandbox. It also keeps the core defect: the host sees `awt effect apply <id>`, never the command. Removing execution removes the problem the policy was written to contain, with about 80 lines of spec and the code behind it deleted rather than added.

## 7. What stays, changes, is removed

Rule 8 stays: **16 top-level verbs maximum**. v2 adds `ingest` and `ui` and removes `save` and `supersede`, so the count stays 16. `help`/`--help`/`--version` do not count, as today.

| Verb | v2 | Note |
|---|---|---|
| `init` | Stays | Drops the `ask` rule from the settings template; adds a `SessionEnd` ingest hook to the template |
| `resume` | Stays | Budgets unchanged. Section 4 shows `begun` and `unknown` effects |
| `list` | Stays | Adds `--since ISO8601 --json` (from PR #11 R4) |
| `find` | **Changes** | FTS5 bm25 ranking over records; `--like TEXT` keeps PR #11's interface and output, ranked by FTS5; `--sessions` adds messages and tool calls from the store. Literal search stays the default. Store absent: records-only, with a one-line note |
| `state` | Stays | |
| `note` | Stays | |
| `decide` | Stays | Prints related records (PR #11 R2), via FTS5 |
| `ask` | Stays | Same as `decide` |
| `answer` | Stays | |
| `ref` | Stays | |
| `capture` | Stays | |
| `status` | Stays | `done` also refused while an effect is `begun` |
| `effect` | **Changes** | `plan | begin | mark | show`. `apply` removed (section 6) |
| `doctor` | **Changes** | Drops the `ask` rule check; adds FTS5 present, store path checks, ingest freshness, Claude retention vs. ingest age, obsolete `ask` rule found (warn with the fix; never edits) |
| `ingest` | **New** | `awt ingest [--source claude|opencode|pi|paseo|records|all] [--hook] [--rebuild]`. Incremental, idempotent; `--hook` is silent and exits 0 on any error, like `resume --hook` |
| `ui` | **New** | Starts Datasette as in section 4. Not installed: prints the install command and exits 1 |
| `save` | **Removed** | Host-native: the agent or person runs `git commit` with host permissions. Its secret check moves to `doctor --staged`, which a git pre-commit hook can call |
| `supersede` | **Removed** | Host-native: `mv docs/old.md docs/_superseded/` and `awt note "docs/new.md replaces docs/old.md: why"`. Listing already hides `docs/_superseded/` |

Other parts: the node tree stays; the Paseo plugin stays and gains the ingest pipe and, later, a screen; `relay` stays (its "workers never approve effects" becomes "workers plan and mark, and send only when their unit says so"); `migrate-wt` and `migrate-paseo` stay as one-offs. The "one file, stdlib only" rule becomes: core verbs stay stdlib Python 3.9+; `ui` and cost import call external tools that are optional.

### Documentation plan

The gap: there are a spec, a guide and a README, but no concept or reference docs.

- `docs/concepts.md`: the glossary (node, record, state, handoff, effect, ingest, canonical, derived, LOD), one or two sentences each, starting with the effect line above.
- Per-verb reference: one source file (`docs/verbs/*.md` or a table embedded in `awt`; decide at build) from which `awt help`, `awt <verb> --help`, the man page (`awt.1`) and the website reference are generated. `tests/test_docs.py` fails when they differ.
- `docs/schema.md`: every table and column, its LOD, its OTel name if any, generated from the schema definition.
- `docs/recipes/`: SQL for the analytics questions in section 11.

## 8. Migration path

**Existing trees.**
- Node logs are unchanged and stay valid. No rewrite of any `.awt/events.jsonl`.
- `load()` keeps reading old effect rows: `claimed` reads as `begun`; `run`, `class`, `snapshot`, `verify`, `timeout` are accepted and shown by `show` as legacy fields (the `run` text is shown as `--how`). A `planned` `--run` effect becomes an ordinary planned effect.
- `.awt/runs/` and `.awt/blobs/` are left on disk and listed by `show`; awt stops writing them and never deletes them.
- `effect apply` and the removed flags exit 2 with a `fix:` that names the plan/begin/mark path.
- `.claude/settings.json` with the old `ask` rule: `doctor` warns with the exact lines to remove. awt never edits it.

**First ingest is urgent.** Claude Code deletes transcripts after 30 days by default, so every day before phase 1 lands loses a day of history. Until then the owner can raise `cleanupPeriodDays` (for example to `3650`) in `~/.claude/settings.json`; that is the owner's setting to change (open question 1).

**PR #11 (active recall).** Do not merge it as written; split it.
- R1 `find --like` and R2 related records: keep the interface, output format and tests (T-R1a to T-R2f), but replace the hand-rolled scoring with FTS5 bm25. The stopword list and token rule go away. Lands in phase 2.
- R3 pointers, R4 turn receipts (`list --since --json`), R5 compaction: independent of the store. They can merge now, with the R3 text referring to `find --like` only once phase 2 lands.
- Its "Constraint change: distribution" section is superseded by section 7 here.

## 9. Review rubric and process

Every design change and every PR that adds a verb, flag, dependency, table or hook is scored 0-2 on each line. 0 on any line blocks; a total under 15 of 20 needs a written reason.

| Criterion | 2 | 1 | 0 |
|---|---|---|---|
| Necessity | Serves the job statement directly, with a named user | Serves it indirectly | Nice to have |
| Layer fit | In the layer that owns it (source, ingest, store, access) | Crosses one layer | Duplicates another layer |
| Host-native first | Uses the host's mechanism (permissions, hooks, git) | Wraps it thinly | Reimplements it |
| Buy before build | Uses a maintained OSS tool, or none exists (stated) | Builds with a reason | Builds what exists |
| Agent ergonomics | One call, fixed output size, `fix:` on refusal | Two calls or variable output | Needs prompt text to work |
| Human visibility | Owner can see the result in the brief, `ui` or SQL | Only in logs | Invisible |
| Failure semantics | Failure is visible, never silent, never retried blindly | Visible but unclear | Silent or retried |
| Data quality | Provenance on every row (source, adapter, offset) | Partial | None |
| Complexity cost | Removes or keeps code | Small addition | Large addition, new state |
| Honest security | States what it does not protect | Vague | Claims protection it lacks |

Process:
1. The author writes or updates the ADR (`docs/adr/NNNN-title.md`: context, decision, alternatives, consequences, rubric scores).
2. Two independent Opus reviews, each given the ADR and the diff, not the other's review or the author's scores. Each returns scores and findings.
3. The author resolves every 0 and every score where the reviews differ by 2, in the ADR.
4. The owner decides. Accepted ADRs are never edited, only superseded.

First ADRs: 0001 data access is the job; 0002 awt never executes; 0003 canonical redacted raw JSONL; 0004 FTS5 over custom scoring; 0005 Datasette for `ui`; 0006 verb swap (`ingest`, `ui` for `save`, `supersede`).

## 10. Phased plan

Smallest useful first. Each phase ships alone and leaves the tree working.

| Phase | Delivers | Done when |
|---|---|---|
| 0 | Effects ledger (section 6) and the doc fixes (`ask` rule, plugin prompt). Removes code | Old trees read correctly; chaos suite green; no code path runs a subprocess for an effect |
| 1 | `awt ingest --source claude` to canonical JSONL with redaction; `SessionEnd` hook; `doctor` retention check | A fictional parsekit transcript round-trips; a rerun writes nothing; secrets in fixtures are redacted |
| 2 | `store.db` with `sessions`, `turns`, `messages`, `tool_calls`, `records`, `effects`, FTS5; `--rebuild`; `find` ranking, `--like`, `--sessions`; PR #11 R1/R2 | Rebuild is byte-stable; PR #11 tests pass on FTS5 |
| 3 | Paseo pipe (turn outcomes, permissions, node join); opencode and pi adapters | One session per provider in fixtures lands in the same tables |
| 4 | ccusage import into `usage`; `awt ui` with canned queries; `docs/schema.md`, `docs/recipes/` | Every question in section 11 marked phase 4 has a recipe that runs |
| 5 | Docs: concepts, generated help and man page, per-verb reference | `test_docs.py` checks help, man page and reference agree |
| 6 | Optional: Paseo screen, `awt_find` tool, OTel enrichment, Parquet recipe | Each optional, behind its own setting |
| 7 | **TODO, gated:** meaning-based search (sqlite-vec) | See below |

**TODO before any meaning-based search (phase 7 gate).** Measure from past data whether it would be used and would help. Build sqlite-vec only if step 2 or 3 shows a meaningful gap.
1. **Usage:** how often agents run `find` / `find --like`, and whether they act on hits (a later tool call or record that cites a hit's id or path). Source: `tool_calls` joined to `records`.
2. **Paraphrase misses:** cases in past history where an agent re-decided or re-asked something already recorded in different words, which keyword/FTS5 search did not surface. Source: `records` pairs by time and node, candidate pairs reviewed by a person or a local model.
3. **Eval:** on a sampled set of past decisions and questions, compare the FTS5 hit rate with an embedding search hit rate.
- **Needs owner approval before running** if any step spends paid tokens (embeddings from an API, or a model labelling pairs in step 2). A local embedding model costs no tokens but still needs the owner's go-ahead for the download size.

## 11. Analytics questions (draft for the owner to edit)

Each names the tables that answer it.

**L0-L3 tree, workspace, task, agent**
- Which workspaces and tasks had the most agent sessions and cost this month? `nodes`, `sessions`, `usage`
- Which tasks are `active` with no session in 14 days? `nodes`, `sessions`
- How deep do subagent chains go, and how often does a subagent's `out.md` get used? `nodes`, `tool_calls`
- How many agents ended without any handoff, or only with an `auto` one? `nodes`, `records`

**L4 session**
- Sessions per provider and model per week. `sessions`
- Session length (turns, wall time) distribution by provider. `sessions`, `turns`
- Which sessions are not joined to any node? `sessions` (`node_id` null)
- How much history was at risk: sessions ingested within 3 days of the Claude retention cutoff. `sessions`, `ingest_sources`

**L5 turn**
- Share of turns `failed` or `canceled`, by provider and model. `turns`, `sessions`
- Turns between a user's prompt and the first record written. `turns`, `records`
- Turns after which the person re-asked the same thing (rework). `messages`, `turns`

**L6 message, tool call, permission**
- Most used tools, error rate per tool. `tool_calls`
- Permission requests by tool and outcome; how many waited on a person, and for how long. `permissions`
- Outbound-looking tool calls with no effect `begin`/`mark` around them. `tool_calls`, `effects`
- How often agents run `find` / `find --like`, and whether a hit is used afterwards (phase 7 gate, step 1). `tool_calls`, `records`
- Re-decisions and re-asked questions that repeat an earlier record in other words (phase 7 gate, step 2). `records`, `fts_text`

**L7 tokens, cost, latency**
- Cost per task, per workspace, per provider and model, per day. `usage`, `sessions`, `nodes`
- Cache read share of input tokens, by model; sessions with low cache share. `usage`
- Time to first token and turn latency percentiles by model. `usage`, `turns`
- Cost of turns that ended `failed` or `canceled`. `usage`, `turns`

**Records**
- Decisions superseded within 7 days (churn). `records`
- Open questions by age; median time to answer. `records`
- Effects by state; `begun` or `unknown` older than a day. `effects`
- Records per session: which agents record and which do not. `records`, `sessions`

## 12. Open questions for the owner

1. **Claude transcript retention.** Raise `cleanupPeriodDays` in your `~/.claude/settings.json` now (for example `3650`) so history survives until phase 1 ships? Default is 30 days.
2. **Verb swap.** Remove `save` and `supersede` to make room for `ingest` and `ui` under the 16-verb limit? Alternative: fold `ui` into `ingest --ui` and keep `supersede`.
3. **Raw copies.** Canonical keeps the redacted provider record. Also keep an unredacted copy (more faithful, more dangerous)? Recommendation: no.
4. **Session join.** Does Paseo expose the provider session id per agent (to be checked in `~/.paseo/agents/*.json` and the SDK)? If not, accept the (cwd, time) join with its error rate?
5. **Size caps.** 256 KB per string in canonical; tool results above it cut with a hash. Different cap, or keep tool outputs whole?
6. **Deletion.** Should awt ever delete store data (`ingest --forget BEFORE`), or is deletion always a manual file delete?
7. **Store location.** `~/.local/share/awt-store`, separate from the tree. Or inside `AWT_ROOT/.store` so one directory holds everything?
8. **`effect begin` for people.** Require `begin` for a person sending by hand too (two commands), or allow `mark sent` straight from `planned` for a person, recorded as unclaimed?
9. **PR #11 split.** Merge R3-R5 now and R1/R2 on FTS5 in phase 2, as recommended?
10. **Paseo screen.** Worth building in phase 6, or is `awt ui` enough?
11. **Phase 7.** Approve a budget for the embedding eval, or a local embedding model only?

## Verified facts

1. **Claude Code transcript retention.** `cleanupPeriodDays`: "Set how many days Claude Code keeps session transcripts and other application data before deleting them … The sweep deletes transcripts without showing a message." Default `30`, minimum `1`; `0` fails validation. Source: Claude Code settings reference, https://code.claude.com/docs/en/settings-reference (section `cleanupPeriodDays`), read 2026-11-13.
2. **DuckDB UI assets.** "The local HTTP server fetches the files for the UI from a remote HTTP server so they can be kept up-to-date. The default URL for the remote server is https://ui.duckdb.org." Also: "By default, the DuckDB UI runs your queries fully locally: your queries and data never leave your computer." Source: DuckDB UI extension docs, https://duckdb.org/docs/2.0/core_extensions/ui.html, read 2026-11-13.
