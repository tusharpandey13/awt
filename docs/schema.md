# store.db schema

`$AWT_STORE/store.db` is SQLite, derived only: `awt ingest --rebuild` deletes it and builds it again from the canonical JSONL under `$AWT_STORE/log/` and the node logs (`.awt/events.jsonl`). Nothing is written to it that cannot be rebuilt. Read it with `sqlite3 -readonly`, DuckDB `ATTACH ... (TYPE sqlite, READ_ONLY)` or any SQLite client. Schema version 1 (`schema_meta.schema_version`); a version change means a rebuild, never a migration.

**Naming.** Where an OpenTelemetry GenAI attribute fits, the column is that attribute without the `gen_ai.` prefix, dots to underscores. **Semconv version pinned: 1.37.0** (`schema_meta.semconv_version`). The GenAI conventions are in development status; a column named for an attribute follows the pinned version, not later renames. Every other column is awt-specific.

**LOD** is the level of detail in ARCHITECTURE-v2 section 2: L0 root, L1 project, L2 workspace, L3 task, L4 agent node, L5 session, L6 turn, L7 message and tool call, L8 usage.

**Redaction and caps.** None in `canonical`, `messages`, `tool_calls` or `records`: text is stored whole. Only `fts_text` cuts: the first 262,144 characters of each indexed string.

## Tables

### schema_meta (key, value)
`schema_version`, `semconv_version`, `adapter` (claude adapter version), `inputs` (SHA-256 of the sorted list of input files and sizes; `awt ingest` rebuilds when it changes). No build clock, so a rebuild is byte-identical.

### projects (L1)
| column | note |
|---|---|
| `project_id` | primary key: the node key (`paseo:project/<id>`), else `path:<relpath>`; `unassigned` always exists |
| `node_id` | same as `project_id` for a project node; null for `unassigned` |
| `name`, `project_key`, `kind` | node name, node key, `project` |
| `root_path` | always null for now (no provider data to fill it) |
| `created_at`, `updated_at` | `ts` of the first and last row of the project node's log |
| `archived_at` | always null for now |

### nodes (L0-L4)
`node_id` (primary key: node key if unique, else `path:<relpath>`), `kind` (`root`, `project`, `workspace`, `task`, `agent`), `name`, `path` (relative to the tree top, `.` for it), `parent_id`, `project_id` (nearest project ancestor, else `unassigned`), `status` (`active`, `paused`, `done`), `goal` (the `task` row's goal).

### sessions (L5)
| column | OTel | note |
|---|---|---|
| `session_id` | | primary key: the canonical file name without `.jsonl` |
| `provider_name` | `gen_ai.provider.name` | `claude_code` |
| `conversation_id` | `gen_ai.conversation.id` | the provider's `sessionId` |
| `node_id` | | set only when `cwd` equals the real path of exactly one node, else null |
| `join_confidence` | | `cwd` when `node_id` is set, else null (decision 4) |
| `cwd` | | first `cwd` seen |
| `request_model` | `gen_ai.request.model` | first assistant `message.model` |
| `started_at`, `ended_at` | | first and last record timestamp |
| `source`, `adapter` | | `claude`, adapter version |

### turns (L6)
`turn_id` (`<session_id>:<n>`), `session_id`, `seq` (0-based), `started_at`, `ended_at` (last record timestamp inside the turn), `outcome` (null: not inferable from transcripts), `paseo_turn` (0: inferred from user-message boundaries).

### messages (L7)
Primary key `(session_id, message_id)`. `message_id` is the record `uuid`. `turn_id` is null before the first prompt. `seq` is the canonical row number. `role`, `ts`, `text` (text blocks joined by newline; whole), `parent_id` (`parentUuid`), `response_finish_reasons` (`gen_ai.response.finish_reasons`; a JSON array with the record's `stop_reason`, or null).

### tool_calls (L7)
Primary key `(session_id, tool_call_id)`. `tool_call_id` (`gen_ai.tool.call.id`), `message_id` (the assistant message that made the call), `tool_name` (`gen_ai.tool.name`), `args` (`gen_ai.tool.call.arguments`: JSON, sorted keys), `result_excerpt` (first 4,096 characters of the result), `result_sha256` (of the whole result), `is_error` (0/1), `started_at` (call message time), `ended_at` (result message time).

### records (any level)
One row per valid line of every node log. `record_id` (the row's own id, `d-`, `q-`, `n-`, when there is one and it is unused, else `<node_id>#<line index among valid rows>`; effect rows always use the second form), `node_id`, `type`, `ts`, `by`, `fields` (the whole row as JSON, `json_extract` reads any field), `session_id` (always null: no deterministic join exists), `origin` (`person` or `plugin` when `by` says so, else `agent`).

### effects (any level)
One row per effect id, folded from its rows: `effect_id`, `node_id`, `target`, `key`, `state` (`planned`, `begun`, `sent`, `unknown`, `dropped`), `attempt`, `origin` (`declared`; `detected` arrives with detection), `rule` (null until then), `begun_by`, `begun_at` (from the first `begun` row), `sent_ref` (`ref` of the last `sent` row), `tool_call_id` (null until detection).

### ingest_sources
A snapshot of `ingest/claude.offsets.json` taken at each build: `source`, `path` (relative to the projects directory), `inode`, `offset`, `adapter`, `last_run`, `errors` (canonical rows that were not JSON). It can lag the file until the next rebuild.

### canonical
`src`, `session`, `seq`, `file` (path under `log/`), `raw` (the provider record as compact JSON, verbatim). Primary key `(src, file, seq)`. Any field the tables lack is `json_extract(raw, '$.path')` away.

### fts_text (FTS5)
`text` is indexed; `kind` and `ref` are not. `kind` is `message`, `tool_call` or `record`; `ref` is the `rowid` in `messages`, `tool_calls` or `records`. Default `unicode61` tokenizer. Rank with `bm25(fts_text)` (lower is better):

```sql
SELECT m.session_id, m.seq, snippet(fts_text, 0, '[', ']', '...', 12)
FROM fts_text f JOIN messages m ON m.rowid = f.ref
WHERE fts_text MATCH '"tokenizer"' AND f.kind = 'message'
ORDER BY bm25(fts_text) LIMIT 10;
```

Not built yet (later phases): `permissions`, `usage`.
