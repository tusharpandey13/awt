# ADR 0005: Datasette for `awt ui`

Status: proposed (phase 5 of ARCHITECTURE-v2). The process in ARCHITECTURE-v2 section 9 still applies.

## Context

The owner needs to look at `store.db`: browse tables, facet, run the section 11 questions. ARCHITECTURE-v2 section 5 says buy before build, and section 4 says DuckDB UI is not the default (its server fetches the frontend from a remote site).

## Decision

- `awt ui` starts Datasette when it is installed and prints the install command when it is not. awt vendors no web app and links no server code.
- The recipes in `docs/recipes` are the only canned queries; `awt ui` generates the metadata from them, so the SQL has one home and `sqlite3` and the UI run the same text.
- Read-only twice: Datasette opens the file with `-i` (immutable), and the metadata grants no write permission. Bound to `127.0.0.1`. Foreground only; it is not a daemon.
- Nothing from the owner's interim setup is copied: its write ops (saved queries, scratch tables in a second database) belong to a person's workspace, not to a derived store. Anyone who wants a scratch database can run Datasette themselves with `--crossdb`.

## Consequences

- The UI is as good as Datasette: tables, facets, canned queries with parameter forms. No charts, no per-agent screen (a Paseo screen stays open question 10).
- `-i` means Datasette does not see an ingest that happens while it runs; restart `awt ui`.
- The `fts_text` table is contentless, so Datasette's search box does not work on it; `awt find --sessions` and the FTS recipe in `docs/schema.md` do.
