# ADR 0004: SQLite FTS5 bm25 instead of hand-rolled scoring

Status: proposed (phase 2 of ARCHITECTURE-v2). The process in ARCHITECTURE-v2 section 9 still applies.

## Context

PR #11 ranks `find --like` and the `related:` lines of `decide` and `ask` with its own scorer: tokens, a stopword list, `log(1 + N/df)` per shared word. Phase 2 adds `store.db`, which needs full-text search over messages and tool calls anyway. A second ranking implementation to maintain beside it is complexity with no benefit (ARCHITECTURE-v2 section 5: buy before build).

## Decision

- Ranking is FTS5 `bm25`. `store.db` has an FTS5 table `fts_text` for sessions (`find --sessions`, SQL).
- `find --like` and the related lines **do not read `store.db`**. They build an in-memory FTS5 index over the records they just walked and rank with `bm25` there. Reasons: they must work with no store and before any ingest; records change on every write, so a store copy would be stale or need a freshness check on the hot path of `decide`; the index is small (at most 2,000 nodes of notes); and the same records give the same order, which the tests rely on. `find --sessions` is the only reader of `store.db`; with no store it prints a note.
- The interface and output format of PR #11 are unchanged, and its tests (T-R1a to T-R2g, ER1 to ER5) pass unedited.
- A rule decision keeps its x1.5 factor (applied to the bm25 score) and ties go to the newest row, as before.
- `store.db` is derived and rebuilt in full (`awt ingest --rebuild`, and by `awt ingest` when its inputs' sizes changed). No incremental update: turn inference and tool-result pairing span rows, one tested code path is worth more than the saved time, and a rebuild reads only local files. The file is byte-identical for identical inputs on one SQLite version.

## What did not go away

The architecture note expected the stopword list and token rule to disappear. They did not, for one reason: the *match gate*. PR #11's tests (ER3 to ER5) pin which records qualify, not only their order: a long query must share 2 informative words with a record, and `the` plus one real word must not qualify. FTS5 alone matches on any one term, so a bare OR query returns every record that contains "the" or "for", ranked last but returned, and a `decide` would print three irrelevant `related:` lines whenever nothing relevant exists. Two alternatives were tried and dropped: counting only terms present in at most half the candidates (it breaks on small corpora, where every term is common) and the same with a size threshold (a magic number that still failed ER3 to ER5). So the word list and the 2-word rule stay as a precision gate in `SPEC.md`; **ranking** moved to bm25, and the `log(1 + N/df)` code is gone.

## Consequences

- bm25 normalises by record length, so a short note outranks a long decision with the same words more often than the old scorer did. The PR #11 tests do not pin such a case; the x1.5 rule boost is the only counterweight.
- FTS5 must exist in the Python's sqlite3. `doctor` fails without it; `find --like` and the store need it. Python from python.org and Homebrew have it; some distro builds do not.
- bm25's inverse document frequency is floored near zero for a word in more than half the records, so in tiny corpora the order among such records is decided by length and then by age. Fine: those records match on common words only.
- Semantic (embedding) search stays a separate, gated phase.
