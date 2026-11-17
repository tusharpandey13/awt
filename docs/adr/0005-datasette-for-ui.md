# ADR 0005: Datasette for `awt ui`

Status: proposed (phase 5 of ARCHITECTURE-v2; revised after the phase 5 review). The process in ARCHITECTURE-v2 section 9 still applies.

## Context

The owner needs to look at `store.db`: browse tables, facet, run the section 11 questions. ARCHITECTURE-v2 section 5 says buy before build, and section 4 says DuckDB UI is not the default (its server fetches the frontend from a remote site).

`store.db` holds every ingested conversation, unredacted by default (decision d-406f9482). Whatever can read it through the UI can read all of that. `ingest` also rewrites `store.db` in place, from the `SessionEnd` hook and the Paseo plugin, while a UI may be open.

## Decision

- `awt ui` starts Datasette when it is installed and prints the install command when it is not. awt vendors no web app and links no server code.
- The recipes in `docs/recipes` are the only canned queries; `awt ui` generates the metadata from them, so the SQL has one home and `sqlite3` and the UI run the same text.
- **The live file, read-only, not immutable.** awt serves `store.db` itself; Datasette opens a mutable file with `mode=ro`. Torn reads come only from `-i` (immutable), which tells SQLite the file never changes; awt never passes it. A normal read-only connection takes SQLite's shared locks and sees committed states only, and an in-place ingest waits for a running query at COMMIT. An earlier draft copied the store with the SQLite backup API (and rejected the live file by blaming torn reads on read-only access); that copy cost a full store of disk on every start (3 GB on the owner's machine, which has little free) and held a read lock for the whole copy, so it was dropped.
- **No database download, no raw `.db` route.** `--setting allow_download off`, and a small plugin awt writes into the temp directory refuses any path ending in `.db`.
- **Host check against DNS rebinding.** The same plugin answers 400 to any request whose `Host` header is not `127.0.0.1` or `localhost`. A page in the owner's browser can rebind a hostname to 127.0.0.1, but the browser still sends the attacker's hostname, so the request is refused.
- Read-only: the metadata grants no write permission. Bound to `127.0.0.1`. Foreground only, not a daemon; SIGINT, SIGTERM and SIGHUP stop Datasette and remove awt's temp directory (metadata and the Host-check plugin).
- **Datasette 0.x only.** On 1.x the `-m` canned queries are ignored, so the recipes would vanish silently; `awt ui` reads `datasette --version` and refuses 1.x with a fix (`pipx install 'datasette<1'`). **Old store refused:** `awt ui` reads the schema version and says `awt ingest --rebuild` when the store is older than the recipes need.
- **Port:** default 8777. A taken port is replaced by a free one and the URL printed is the one served. (The owner's own interim Datasette already listens on 8777; awt does not touch it.)
- Nothing from the owner's interim setup is copied: its write ops (saved queries, scratch tables in a second database) belong to a person's workspace, not to a derived store. Anyone who wants a scratch database can run Datasette themselves with `--crossdb`.

## Alternatives

- **DuckDB UI:** fetches its frontend from a remote site on each use. Rejected (section 4).
- **sqlite-web:** small, but write-capable by default, no canned-query forms or facets. Rejected.
- **Plain `sqlite3 -readonly`:** stays available for SQL (section 4), but gives no table browser, facets or forms for a person.
- **A Paseo screen:** phase 7, optional; reads through `awt ... --json`, not a replacement for ad hoc SQL.
- **Own web UI:** builds what exists. Rejected.

## What this does not protect

- **Other local users and processes.** Any process on the machine can connect to `127.0.0.1:<port>` while `awt ui` runs, and read everything in the store, including arbitrary read-only SQL (`/store.json?sql=...`). There is no token. Run it only on a machine you trust, and stop it when you are done.
- **A SIGKILL of awt** leaves the server running until you stop it, and a small `awt-ui-*` temp directory (metadata and the Host plugin, no data); remove it by hand.
- **Transcript content.** Secrets in transcripts are only flagged, not removed. Anyone who reaches the UI sees them.
- **Browsers.** The Host check blocks DNS rebinding; it does not stop a local page that already knows the port from reading cross-origin if Datasette allowed it (it sends no permissive CORS header by default), nor a malicious browser extension.

## Consequences

- The UI is as good as Datasette: tables, facets, canned queries with parameter forms. No charts, no per-agent screen (a Paseo screen stays open question 10).
- The page sees an ingest committed while it runs, on the next query; a running query delays that commit, not the reverse.
- The `fts_text` table is contentless, so Datasette's search box does not work on it; `awt find --sessions` and the FTS recipe in `docs/schema.md` do.
- Datasette 1.x moves canned queries to configuration; the metadata route is verified against 0.65 only.

## Rubric (ARCHITECTURE-v2 section 9)

Necessity 2, Layer fit 2, Host-native 2, Buy before build 2, Agent abstraction 2 (no agent use), Agent ergonomics 2, Human visibility 2, Failure semantics 2 (stale is stated), Data quality 1, Complexity 1 (one verb, one generated plugin), Honest security 1 (states the limits above; there is still no authentication). Total 19 of 22.
