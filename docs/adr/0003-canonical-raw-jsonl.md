# ADR 0003: a canonical raw JSONL store, unredacted

Status: proposed (phase 1 of ARCHITECTURE-v2). The process in ARCHITECTURE-v2 section 9 (two independent reviews, then the owner) still applies.

## Context

Claude Code deletes transcripts after `cleanupPeriodDays` (30 by default). Every other awt feature that needs history (search across sessions, joining a session to a node, usage, detected effects) reads transcripts that the provider will remove. opencode and pi hold their data in their own formats. awt needs one place that keeps what the providers drop, in a form that survives a wrong adapter.

## Decision

`awt ingest` copies each provider record, whole, into `${AWT_STORE:-~/.local/share/awt-store}/log/<source>/<YYYY-MM>/<session>.jsonl`, one row per source line, wrapped in a small envelope (`v`, `src`, `adapter`, `session`, `seq`, `ingested`, `src_ref`, `secret_flags`, `raw`).

- **Canonical is the raw record.** Adapters will be wrong in v1. If the store held normalized fields, a better adapter could not re-derive them once the provider pruned the source. Derived tables (phase 2) are rebuilt from this store, never from the provider.
- **Unredacted, by decision `d-406f9482` (ARCHITECTURE-v2-DECISIONS #3).** The first draft redacted secrets before the write. That was dropped: pattern scanning misses what it has no pattern for, a redacted copy is not the record, and the owner wants the store to be the raw copy. Ingest counts secret matches in `secret_flags` and leaves the text alone. The cost is plain: the store is as sensitive as the transcripts, so it is a separate directory (not the task tree, which may be committed), mode 700/600, and `doctor` warns when it sits in a sync folder, a network mount or a git work tree. Optional masking for a reader on a different provider may come later and is off by default.
- **No size cap** in the raw store (decision #5). Only the derived FTS index will cap strings.
- **No delete verb** (decision #6). awt never deletes store data; the owner removes files by hand.
- **Incremental by (path, inode, byte offset)** in an offsets file under `flock`; one `O_APPEND` write per row; a torn tail is closed with a newline; `seq` already present in the canonical file marks rows to skip, so a crash between the append and the offset save duplicates nothing. A rotated or truncated source is rescanned and only unseen rows are appended.
- **Triggers are the host's:** the `SessionEnd` hook that `init` writes runs `awt ingest --source claude --hook`, which is silent and exits 0 on any error. `doctor` warns when ingest has not run for 7 days or when the oldest transcript is near the retention limit.
- **`save` is removed to keep 16 verbs** (decision #2); its secret check lives on as `doctor --staged`.

## Alternatives rejected

- Redact on ingest: lossy and incomplete (see above).
- Read providers live instead of copying: breaks when the provider prunes, and leaves no raw copy for a new adapter.
- A database as the canonical store: a JSONL file survives a bad build, diffs, greps and is the same shape awt already writes.

## Consequences

A second copy of every conversation exists on disk, readable by the account that owns it. Backups and disk cleanup of the store are the owner's job. Rebuilding derived data (`--rebuild`, phase 2) never needs the provider again.

## Rubric (ARCHITECTURE-v2 section 9, 0-2 each)

The author did not score this ADR when it was written. Opus review of the whole phase 1 diff (ADRs 0003 and 0008 together):

| Criterion | Author | Reviewer | Why (reviewer) |
|---|---|---|---|
| Necessity | not scored | 2 | |
| Layer fit | not scored | 2 | |
| Host-native first | not scored | 2 | |
| Buy before build | not scored | 1 | |
| Agent abstraction cost | not scored | 2 | |
| Agent ergonomics | not scored | 2 | |
| Human visibility | not scored | 1 | |
| Failure semantics | not scored | 1 | one bad record or file stopped ingest (fixed: per-file errors, doctor) |
| Data quality | not scored | 1 | src_ref line numbers were wrong after blank lines (fixed) |
| Complexity cost | not scored | 1 | |
| Honest security | not scored | 2 | |

Reviewer total 17 of 22, no zeros. The author's scores and a second independent review are still owed (section 9 steps 2 and 3).
