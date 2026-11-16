# ADR 0005: Datasette for `awt ui`

Status: proposed (phase 5 of ARCHITECTURE-v2; revised after the phase 5 review). The process in ARCHITECTURE-v2 section 9 still applies.

## Context

The owner needs to look at `store.db`: browse tables, facet, run the section 11 questions. ARCHITECTURE-v2 section 5 says buy before build, and section 4 says DuckDB UI is not the default (its server fetches the frontend from a remote site).

`store.db` holds every ingested conversation, unredacted by default (decision d-406f9482). Whatever can read it through the UI can read all of that. `ingest` also rewrites `store.db` in place, from the `SessionEnd` hook and the Paseo plugin, while a UI may be open.

## Decision

- `awt ui` starts Datasette when it is installed and prints the install command when it is not. awt vendors no web app and links no server code.
- The recipes in `docs/recipes` are the only canned queries; `awt ui` generates the metadata from them, so the SQL has one home and `sqlite3` and the UI run the same text.
- **A snapshot, not the live file.** awt copies the store with the SQLite backup API into a `0700` temp directory and serves the copy with `-i`. `-i` (immutable) tells SQLite the file never changes; on the live file an in-place ingest would give torn reads (old and new pages mixed, wrong rows or "malformed" errors, with no warning). The copy cannot change, so `-i` is true. Cost: the page shows the moment `awt ui` started; awt says so, and a restart refreshes it. We chose the snapshot over opening the live file read-only without `-i` because a reader that is wrong without telling anyone is worse than one that is stale and says so, and because the backup API takes a consistent copy while a writer is active.
- **No database download, no raw `.db` route.** `--setting allow_download off`, and a small plugin awt writes into the temp directory refuses any path ending in `.db`.
- **Host check against DNS rebinding.** The same plugin answers 400 to any request whose `Host` header is not `127.0.0.1` or `localhost`. A page in the owner's browser can rebind a hostname to 127.0.0.1, but the browser still sends the attacker's hostname, so the request is refused.
- Read-only: the metadata grants no write permission. Bound to `127.0.0.1`. Foreground only, not a daemon; SIGINT, SIGTERM and SIGHUP stop Datasette and remove the copy.
- **Port:** default 8777. A taken port is replaced by a free one and the URL printed is the one served. (The owner's own interim Datasette already listens on 8777; awt does not touch it.)
- Nothing from the owner's interim setup is copied: its write ops (saved queries, scratch tables in a second database) belong to a person's workspace, not to a derived store. Anyone who wants a scratch database can run Datasette themselves with `--crossdb`.

## Alternatives

- **DuckDB UI:** fetches its frontend from a remote site on each use. Rejected (section 4).
- **sqlite-web:** small, but write-capable by default, no canned-query forms or facets. Rejected.
- **Plain `sqlite3 -readonly`:** stays available for SQL (section 4), but gives no table browser, facets or forms for a person.
- **A Paseo screen:** phase 7, optional; reads through `awt ... --json`, not a replacement for ad hoc SQL.
- **Own web UI:** builds what exists. Rejected.

## What this does not protect

- **Other local users and processes.** Any process on the machine can connect to `127.0.0.1:<port>` while `awt ui` runs, and read everything in the snapshot, including arbitrary read-only SQL (`/store.json?sql=...`). There is no token. Run it only on a machine you trust, and stop it when you are done.
- **The copy on disk.** The snapshot is a full copy of the store, mode 600 in a 700 directory, for as long as `awt ui` runs. A SIGKILL of awt leaves the copy and the server running until you stop them; remove `awt-ui-*` in the temp directory.
- **Transcript content.** Secrets in transcripts are only flagged, not removed. Anyone who reaches the UI sees them.
- **Browsers.** The Host check blocks DNS rebinding; it does not stop a local page that already knows the port from reading cross-origin if Datasette allowed it (it sends no permissive CORS header by default), nor a malicious browser extension.

## Consequences

- The UI is as good as Datasette: tables, facets, canned queries with parameter forms. No charts, no per-agent screen (a Paseo screen stays open question 10).
- The page does not see an ingest that happens while it runs; restart `awt ui`.
- The `fts_text` table is contentless, so Datasette's search box does not work on it; `awt find --sessions` and the FTS recipe in `docs/schema.md` do.
- Datasette 1.x moves canned queries to configuration; the metadata route is verified against 0.65 only.

## Rubric (ARCHITECTURE-v2 section 9)

Necessity 2, Layer fit 2, Host-native 2, Buy before build 2, Agent abstraction 2 (no agent use), Agent ergonomics 2, Human visibility 2, Failure semantics 2 (stale is stated), Data quality 1, Complexity 1 (one verb, one generated plugin), Honest security 1 (states the limits above; there is still no authentication). Total 19 of 22.
