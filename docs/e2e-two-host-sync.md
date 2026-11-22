# E2E and chaos test spec: one task tree on two hosts

Companion to `docs/spec-two-host-sync.md` (HS1-HS62) and `tests/TEST-SPEC.md`. Unit ids T-HS* belong to the unit plan. This file owns the end-to-end journeys **E-HS1 to E-HS15**, the chaos cases **C50 to C59** (chaos group `sync`) and the invariants **IS1 to IS7**.

Two hosts are simulated on one machine:

- two temporary directories, each with its own home, store and clone of the tree;
- one bare git repository as the remote.

No real host, no ssh, no real GitHub and no network are used. Every journey judges on exit codes, stdout and stderr, files and git objects, never on an agent's words.

| Tier | Runs | Gate |
|---|---|---|
| cli | `tests/test_sync_e2e.py`, in `unit` CI | `git` on `PATH` (else skipped with a reason) |
| chaos | `python3 tests/chaos.py --only sync` (quick counts in CI, full counts in `chaos-full`) | same |
| manual-linux | C56 (d) only: a real full filesystem | Linux, a 2 MB `tmpfs` the tester mounts; never run by CI |

## 0. Shared rules

**Isolation.**

- `T=$(cd "$(mktemp -d)" && pwd -P)` gives the real path, so macOS `/private` prefixes match.
- Every process runs with:
  - `TZ=UTC`;
  - `AWT_*`, `PASEO_*`, `CLAUDECODE`, `GIT_*` and `SSH_*` removed;
  - `GIT_CONFIG_GLOBAL=$T/gitconfig` (user name and email of the fictional `parsekit` bot, `init.defaultBranch=main`, `protocol.file.allow=always`) and `GIT_CONFIG_NOSYSTEM=1`.
- Pre-flight:
  - every path a step names is under `$T`;
  - no remote URL starts with anything but `$T/`;
  - `AWT_TEST_GITHUB_BASE` is `http://127.0.0.1:<port>` whenever `doctor` runs on a remote whose normalised host is `github.com`.
- Projects use the fictional `parsekit` and `ledgerline`. No real task data, no data from this machine, no credential-shaped literal: a secret probe is built at runtime.

**Fixture H2 (two hosts).**

```
$T/remote.git                 bare repo, the "private sync remote"
$T/A/home  $T/A/store  $T/A/tree     host A: HOME, AWT_STORE, the tree clone
$T/B/home  $T/B/store  $T/B/tree     host B
```

- `runA` runs a command with `HOME=$T/A/home AWT_STORE=$T/A/store AWT_HOST=host-a AWT_ROOT=$T/A/tree`. It adds `AWT_TEST_CLOCK_SKEW_S=$SKEW_A` when set. `runB` does the same for B.
- `syncA` is `runA $WT/awt-sync --dir $T/A/tree`, and `syncB` likewise.
- `cutover` is `syncA; syncB; syncA`: three runs that converge both hosts when nothing else writes.

Setup:

1. `runA awt init --kind root` in `$T/A/tree`, with projects `parsekit` and `ledgerline` and one task under each.
2. `git init`. Write `.gitattributes` with `events.jsonl merge=union`, and the root `.gitignore` lines of HS15.
3. Install `.git/hooks/pre-commit` as `#!/bin/sh\nexec $WT/awt doctor --staged`.
4. `runA awt ref $T/remote.git --kind sync --title "private sync remote"`. Commit and push to `main`.
5. `git clone $T/remote.git $T/B/tree` and install the same hook.

**Store fixture S2.** The fictional Claude transcripts from `tests/fixtures` are placed in `$T/A/home/.claude/projects` and a different set in `$T/B/home/.claude/projects`. Their `cwd` fields point at repos under `$T/repos/parsekit` (a `Cargo.toml` and a 3-file git repo) and `$T/repos/ledgerline` (a `package.json` only). Some `Bash` tool calls run `cargo test`, `adb devices` and `ffmpeg -i x y`. "rsync" in this file means a test helper that copies `log/` files from one store to the other:

- it never deletes;
- it copies a file only when the target is missing or a byte prefix of the source;
- it can stop after K bytes of a chosen file, to simulate a partial transfer.

**Universal checks (U), after every step.**

- U1: no `Traceback` on any stderr. Exit codes are in 0-4, and every refusal has `error:` and `fix:`.
- U2: nothing outside `$T` changed. The real `~/.local/share/awt-store` and `~/.claude` are hashed before and after.
- U3: no output line contains `$T/remote.git` with userinfo, or any row's text from a refused commit (HS24).

**Masking.** Brief ages and `built` timestamps are masked when comparing hosts. `ts` values are never masked: their order is what is under test.

## Invariants

| ID | Invariant |
|---|---|
| IS1 | **Convergence.** After `cutover` with no writes in flight, for every node, both hosts have the same multiset of ledger lines. `list --all --json` and the masked `resume` are byte-identical on A and B. |
| IS2 | **No lost row.** Every row whose `emit` exited 0 (the test logs the printed id and `ts`) is in both hosts' ledgers after convergence, and is read exactly once. |
| IS3 | **Causality.** A row that a host wrote after a sync that brought row R sorts after R, on both hosts. |
| IS4 | **Clean commits.** Every `.awt/events.jsonl` blob in every commit of `remote.git` ends with `\n`. Its first parent's blob is a byte prefix of it, or, for a merge commit, contains both parents' lines. `git fsck --strict` passes. |
| IS5 | **Store equals rebuild.** After any sequence of pulls, rsyncs and incremental ingests on a host, `sqlite3 store.db .dump` (rowids masked) equals the dump after `ingest --rebuild` of the same inputs on that host. |
| IS6 | **Legacy unchanged.** A ledger with no `v: 2` row produces byte-identical `resume`, `list --all --json` and `doctor` output under this awt and under v0.4.1 (`git show v0.4.1:awt`), apart from new doctor lines that HS15-HS17 and HS32 add only at a declared sync top. |
| IS7 | **No force.** The fake-`git` argv log (when used) never contains `--force`, `-f` on push, `--force-with-lease`, `reset --hard` or `push +`. |

## 1. Journeys (tier cli)

### E-HS1 Bootstrap and a clean doctor on both hosts (HS12, HS14-HS17, HS30-HS32)

1. Run H2 setup.
2. `runA awt doctor` and `runB awt doctor` at the tree top. Expect:
   - `ok git remote origin: declared private sync remote`;
   - no `warn` from HS15, HS16 or HS17;
   - no probe line, because the remote is local.
3. `syncB` with nothing new. Exit 0 and `synced ...: committed 0 files, merged 0 commits, no push`.
4. IS1.

### E-HS2 Disjoint nodes (homelab AT-03) (HS4, HS12)

1. Both hosts start converged. A writes `note`, `state`, `decide` and `ask` in `parsekit/task`; B writes the same set in `ledgerline/task`.
2. `syncA`, then `syncB`, then `syncA`.
3. Expect:
   - no merge conflict;
   - 0 quarantined rows (`doctor` `ok 0 quarantined rows`);
   - `status` and `resume` identical on both hosts (IS1);
   - IS2.

### E-HS3 Same node, interleaved, faked clocks (homelab AT-04) (HS2, HS3, HS4, HS8)

1. `SKEW_A=0`, `SKEW_B=+5`. Without syncing, A and B alternate 20 rounds on one task: `state --now "a<i>"` and `--now "b<i>"` on scope `main`, a `note`, and `effect plan`/`begin`/`mark sent` on effects created on their own host.
2. Then `cutover`.
3. Expect:
   - the current `state` on both hosts is the row with the greatest `ts`, which is B's last (B's clock is ahead);
   - `list state --all --json` holds all 40 states in `(ts, host)` order;
   - 0 quarantined rows, 0 duplicates;
   - every effect is `sent`;
   - IS1, IS2, IS4.
4. Record (for homelab AT-04):
   - which state each host shows;
   - the quarantine count;
   - whether git kept any identical line twice (expected none: rows differ by `ts` and `host`).

### E-HS4 Causality under heavy skew (HS2, HS9)

1. `SKEW_B=-3600`. A writes `state --now A1`. `cutover`.
2. B writes `state --now B1`. `cutover`.
3. Expect:
   - B1 is current on both hosts, though B's wall clock is an hour behind;
   - B1's `ts` is A1's `ts` + 1 µs (IS3);
   - `runB awt doctor` warns `rows up to 3600 s ahead of this clock (host host-a)` (± 5 s);
   - the brief on B shows no negative age.
4. Repeat with `SKEW_A=+7200` and `SKEW_B=0`. The same holds.

### E-HS5 Effects across hosts (HS8)

1. A runs `effect plan` then `effect begin`. `cutover`. B runs `effect mark ID sent --ref r1`. `cutover`.
2. Expect: the state is `sent` on both hosts and nothing is quarantined.
3. Next, on a converged tree, A and B each run `effect begin` on a second planned effect, attempt 1, before syncing. `cutover`.
4. Expect:
   - exactly one `begun` row is quarantined on both hosts, the same one on each;
   - `doctor` on both prints `effect e-…: begun on host-a and host-b (attempt 1)`.

### E-HS6 Concurrent supersede and answer (HS8)

1. On a converged tree, A runs `decide X --supersedes d-1` and B runs `decide Y --supersedes d-1`. A and B each `answer q-1`.
2. `cutover`.
3. Expect:
   - both new decisions are current on both hosts;
   - the answer shown is the first by `(ts, host)`;
   - `doctor` warns about both conflicts on both hosts, with the same lines.

### E-HS7 Legacy ledgers need no migration (HS5, IS6)

1. Build a task tree with v0.4.1 `awt` from `git show v0.4.1:awt`: notes, states, decisions, effects, captures, a child node. Record its outputs.
2. Switch to this awt. Expect IS6: identical outputs, no file changed.
3. Make it the tree of H2: `git init` plus the setup from step 2 on. Write new rows on A and B, then `cutover`.
4. Expect:
   - the legacy rows come first in `list --all --json` on both hosts, in their original order;
   - every new row is `v: 2`;
   - IS1.

### E-HS8 The commit check (HS20-HS24)

1. On A, append `{"v":2,"ts":"2026` with no newline to a node's ledger. Run `git add -A && git commit -m x`.
2. Expect: the commit is refused with the HS21 fix, and the remote is unchanged.
3. `syncA`. Expect: it heals, commits and pushes. The committed blob ends with `\n`. `doctor` warns about one quarantined row (the fragment). The fragment line is in the commit only as a warned line (HS24).
4. On a fresh copy, change one byte in the middle of a committed row and commit. Expect: refused (HS22).
5. On a fresh copy, append a line `=======` and commit. Expect: refused (HS23).
6. IS4 over the whole history.

### E-HS9 Remotes (HS30-HS34)

1. Start a local `http.server` stub on 127.0.0.1 that answers `HEAD /parsekit-bot/awt-data` with a configurable status. Set `AWT_TEST_GITHUB_BASE` to it.
2. Add a remote `extra` = `git@github.com:parsekit-bot/other.git` (never fetched) to A. Expect `warn git remote extra: not declared ...`.
3. Declare it with `ref https://github.com/parsekit-bot/other --kind sync`. Expect `ok ... declared` and a probe.
4. Stub 200: `fail git remote extra is public` and exit 1. 404: no probe line. 503: `warn ... visibility not checked (HTTP 503)`. Stub stopped: `warn ... (OFFLINE)`.
5. Withdraw with `ref ... --kind link`. Expect the warning again.
6. Expect:
   - no request carries an `Authorization` or `Cookie` header (the stub logs headers);
   - `doctor --staged` made no request.

### E-HS10 The store after a pull and an rsync (HS40-HS43; homelab AT-09, AW-9, AW-10)

1. Use S2. Run `runA awt ingest` and `runB awt ingest`.
2. "rsync" A's `log/` to B and B's to A. `cutover` the tree.
3. Run a plain `awt ingest` on each host. Expect:
   - each `store.db` holds both hosts' sessions, and the node records from both;
   - `awt find --sessions <word in a B-only transcript>` on A returns a hit;
   - IS5 on both hosts;
   - a second `ingest` on each host prints 0 rows and changes no byte of `store.db` (HS42).

### E-HS11 Profiles on two hosts (HS50-HS57)

1. Use S2 after E-HS10. Make `$T/repos/ledgerline` exist only for A (B sets a different `$T/B/repos` with no ledgerline).
2. Expect:
   - `$T/A/store/views/profiles.json` has `parsekit` as `build-heavy`/`observed` (cargo test calls) and `ledgerline` as `light`/`default`;
   - B's file has no `repos` entry for the ledgerline path, but its project entry still counts A's sessions;
   - files are mode 600;
   - no command argument from S2 appears in either file.
3. On B, run `decide "ledgerline is media work" --why x --tag profile:media-device` in the ledgerline project node. `cutover`, then `ingest` on both hosts.
4. Expect: both files show `ledgerline` `media-device`/`override`.

### E-HS12 A sync in flight blocks writers, not hooks (HS10, HS11, HS13)

1. A helper takes `LOCK_EX` on `$T/A/tree/.awt` for 3 s, with `AWT_TEST_SYNC_WAIT_S=5`.
2. During it:
   - `runA awt note x` returns after the release with exit 0;
   - `runA awt resume --hook` returns within 2.5 s with exit 0;
   - with `AWT_TEST_SYNC_WAIT_S=1`, `runA awt note y` exits 1 with the HS11 fix.
3. Also, a writer that opened the ledger before a `git merge` run under the lock has its row present afterwards. This is the scratch-run loss case, now prevented.

### E-HS13 Conflicting push (HS12)

1. A and B each write and commit. `syncA` pushes.
2. `syncB`: the merge succeeds and the push succeeds. Exit 0.
3. Next, make B's push lose a race: a fake remote hook makes the first push from B fail as non-fast-forward. Expect `push rejected` and exit 0. The next `syncB` converges.
4. IS1, IS2, IS7.

### E-HS14 An older awt on one host (HS6; homelab AT-02)

1. B writes 3 rows with v0.4.1 `awt` after A wrote `v: 2` rows. `cutover`.
2. Expect:
   - both hosts read the `v: 1` rows before every `v: 2` row;
   - `doctor` on both prints the HS6 warning with the line numbers;
   - nothing is quarantined.

### E-HS15 A full disk during a write and a git merge (HS21, HS25, HS45)

1. `runA AWT_TEST_SHORT_WRITE=10 awt note x`. Expect exit 1 and `short write` with its fix.
2. `syncA` heals and commits. IS4.
3. Simulate git dying with ENOSPC mid-checkout: truncate A's working ledger to half its length.
4. `runA awt doctor` fails with the HS25 line. `git checkout -- PATH` restores the file, and `doctor` is clean.
5. `AWT_TEST_FREE_BYTES=1 awt ingest --rebuild` exits 1 with `fix:`. The old `store.db` and every ledger are untouched.

## 2. Chaos (`tests/chaos.py`, group `sync`)

Same style as the existing groups: seeded, one line per attack, and a failure prints the seed and the commands. Every case runs on H2 (plus S2 where it says so) and ends with `cutover`, then IS1-IS5 and IS7. Quick counts are in brackets.

- **C50 Kill mid-sync.** Writers on both hosts (4 processes each, notes, states and effects, 20 rows/s) run while `awt-sync` on each host is SIGKILLed at a random moment, 200 times [30]. The moments cover:
  - during `fetch`;
  - right after taking the lock;
  - during heal, during `git add`, during the hook, during `git merge`;
  - before `push`.

  Expect:
  - every later sync completes, or reports `.git/index.lock` with its fix, which the case then applies like a person would;
  - IS1, IS2 and IS4 hold at the end;
  - no lock is left: a `LOCK_EX` attempt right after the kill succeeds.
- **C51 Kill mid-write.** SIGKILL writers at random, 300 times [40], while each host runs `awt-sync` every 200 ms.

  Expect:
  - no commit ever holds a blob without a final newline (IS4);
  - every healed fragment is at most one quarantined line, and it is the same on both hosts;
  - no traceback on reads during the run.

  This covers homelab AT-05: a 1,000 rows/s burst from one host while the other syncs, with the same checks.
- **C52 Clock skew.** Each round, every host gets a random `AWT_TEST_CLOCK_SKEW_S` in [-7200, +7200], and sometimes a step back of up to 600 s within a round (an NTP step). 50 rounds [8] of write, sync, write.

  Expect:
  - IS3 for every causal pair the harness recorded;
  - within one host, `ts` in file order is strictly increasing for `v: 2` rows;
  - no negative brief age;
  - `doctor` warns exactly when a row is over 300 s ahead.
- **C53 Divergent `log/` file.** On S2, give both stores a canonical file with the same name and different content (A's and B's versions of `log/paseo/<agent>.jsonl`, and of one Claude session file). Do not copy it (the rsync helper reports it). Ingest on both hosts.

  Expect:
  - no crash;
  - each host derives its own copy;
  - no session holds rows from the other host's copy;
  - IS5 on both hosts.

  Then grow one copy so that the other is a prefix, copy it, and ingest. IS5 holds.
- **C54 Conflicting push storm.** Both hosts write and run `awt-sync` in tight loops for 60 s [10 s], racing for the remote.

  Expect:
  - pushes are only rejected, never forced (IS7, with the fake-`git` argv log);
  - after the storm, `cutover` gives IS1 and IS2;
  - `git log --merges` shows only merges, no rebases.
- **C55 Partial rsync.** On S2, copy a random prefix of each of A's canonical files to B (cut mid-line in 50% of cases), then ingest on B. Repeat with longer prefixes up to the full file, 100 times [15].

  Expect:
  - every ingest exits 0;
  - no error is counted for an unterminated tail;
  - after the full copy, IS5 holds on B;
  - B's own sessions are unchanged by every step.
- **C56 Disk full.**
  - (a) `AWT_TEST_SHORT_WRITE` at random byte counts on random writes. Each fails with `fix:`, and the next `awt-sync` heals and commits.
  - (b) `AWT_TEST_FREE_BYTES` low during an `ingest` after a pull. Exit 1 with `fix:`, the store is stale but readable, and the next ingest with space is fresh.
  - (c) The working ledger truncated at a random byte, as a git write killed by ENOSPC. `doctor` fails (HS25), `git checkout -- PATH` restores it, and the pre-commit refuses to commit the truncated file (HS22).
  - (d) manual-linux only: the tree on a 2 MB `tmpfs` filled to the last byte; `awt note`, `awt-sync` and `git merge` each fail with a message and leave a readable ledger; after freeing space, `cutover` gives IS1 and IS2.
- **C57 Reads during merges.** `resume`, `list --all --json` and `find --like` loop on B while `syncB` merges large batches from A, 100 merges [15].

  Expect:
  - no traceback;
  - every output is the read of either the pre-merge or the post-merge ledger. The harness keeps both and compares. The only exception is a run that printed the HS11 partial note.
- **C58 Duplicate import.** The same commits are merged twice through a second branch, a ledger commit is cherry-picked onto the other host, and the union duplicates of E-HS3 are forced by identical hand-made rows.

  Expect:
  - every row reads once;
  - `records` has one row per ledger row id;
  - IS1 and IS5.
- **C59 Lock-order stress.** 100 rounds [20] of `effect begin`/`mark` (log lock, then sync lock), keyed `init --kind task --key K` (top log lock) and `awt-sync` (sync lock only), all at once on one host. Every process ends within 15 s, with no deadlock and no lost row.

## Traceability

| Spec | Journeys and chaos |
|---|---|
| HS1-HS7 (order, clock, host) | E-HS3, E-HS4, E-HS7, E-HS14, C52, C58 |
| HS8, HS9 (concurrent edits, skew) | E-HS3-E-HS6, C52 |
| HS10-HS14 (lock, contract, `awt-sync`) | E-HS1, E-HS12, E-HS13, C50, C54, C57, C59 |
| HS15-HS17 (ignores, attribute, hook) | E-HS1 |
| HS20-HS25 (commit check, working ledger) | E-HS8, E-HS15, C51, C56 |
| HS30-HS34 (remotes) | E-HS1, E-HS9 |
| HS40-HS45 (store) | E-HS10, E-HS15, C53, C55, C56 |
| HS50-HS58 (profiles) | E-HS11 |
| Homelab AT-03, AT-04, AT-05 | E-HS2, E-HS3, C51 |
| Homelab AT-02, AT-06, AT-08, AT-09 | E-HS14, E-HS12, E-HS13, C53, C55, E-HS10 |
