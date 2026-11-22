# Spec: one task tree on two hosts (ledger order, sync lock, private remote, profiles)

Status: implemented in v0.5.0 (22-Nov-2026); this file is the design record, and the normative text is in `SPEC.md` (Two hosts, Project profiles, Reading, doctor). The owner approved `awt` spec, code and test changes for this on 22-Nov-2026 (homelab `docs/paseo-box/SPEC-paseo-box.md` section 12, Q12-3 and Q12-4). The normative text moves into `SPEC.md` and `tests/TEST-SPEC.md` in the implementation PR ("Docs to update"). The end-to-end and chaos rubric is `docs/e2e-two-host-sync.md`.

Requirement ids: **HS1-HS62**. Unit and integration tests: **T-HS1-T-HS44**. End-to-end journeys: **E-HS1-E-HS15**. Chaos cases: **C50-C59**. Invariants: **IS1-IS7**. `[unverified]` marks a claim not checked against awt's code or a run.

## Problem

One task tree is used from two hosts, a Mac and an always-on Linux box. The tree is a git work tree with a private remote, at the same path on both hosts. The `awt` store's `log/` is copied between the hosts by rsync, and each host builds its own `store.db`.

1. **Merge order.** `awt` reads "latest = last line of the file" (SPEC, Events, Reading). With `merge=union`, rows that two hosts appended to one node come back as "ours, then theirs". The latest `state`, `status` or `task` can then be a stale row, and an effect whose steps ran on two hosts can be quarantined.
2. **Remotes.** `doctor` warns about any git remote. A remote that the owner declared private should pass. Unexpected or public remotes must still warn.
3. **Project profiles.** Auto-tagging needs a per-project profile: a placement class plus the commands seen. An inferred profile is machine-knowable, so storing it as events breaks Rule 3. It has to be a derived view.
4. **Sync safety.** `awt` has to state what it guarantees when two hosts write and then sync. That covers re-import, `store.db` after a pull, a sync in flight, and a check before every commit.

## Facts this design rests on

| Fact | Source | Consequence |
|---|---|---|
| `load()` keeps file order and never sorts. Latest `state` per scope, `task`, `status` and `ref` per target is the last row in the file. `answer` uses the first. Effects fold in file order and a bad transition is quarantined. | `awt` `load()`, `fold_effect()` (read 22-Nov) | Problem 1 is real. Order must come from row content. |
| `emit()` makes one `O_APPEND` write and heals a torn tail by putting a newline before the row. It takes no lock. `host` is `socket.gethostname()`. | `awt` `emit()`, `HOST` | Two simulated hosts on one machine need a host override (HS7). |
| Union merge keeps an identical line added on both sides **twice**. It joins the hunks as ours, then theirs. | Scratch run, git on this Mac, 22-Nov | Reads must ignore duplicate rows (HS3). |
| A row written through an fd opened before `git pull` is **lost**: git replaces the file with a new one, so the write goes into the unlinked inode. | Scratch run, 22-Nov | Writes and work-tree-changing git steps need mutual exclusion (HS10). |
| A committed torn tail (`TORN` with no newline) that is later completed on the other host comes back twice after a union merge. | Scratch run, 22-Nov | Never commit a ledger that does not end in a newline (HS21). |
| `flock(LOCK_SH)` on a directory fd blocks `LOCK_EX` from another fd, on macOS. | Scratch run with Python `fcntl`, 22-Nov; again by `tests/test_sync.py` T-HS16 and T-HS20 (verified, implementation run 22-Nov). On Linux 6.18 (box, tmpfs and btrfs, `flock(1)`): verified 22-Nov; shared+shared granted, exclusive blocks shared | The lock can be the tree top's `.awt/` directory, with no lock file (Rule 5). |
| macOS has no `flock(1)`. | `which flock` on this Mac | Ship a sync script that locks through Python `fcntl` (HS14). |
| `doctor` checks remotes only when the node **is** the git top level (`rev-parse --show-toplevel == ROOT`). It prints the first remote's name. | `awt` `cmd_doctor` | With the tree top as the repo root, one node warns, not every node. Homelab AW-6 overstates this. |
| `ref --kind` is free text (cap 40). `ref --kind sync` already works. | `awt` `cmd_ref`, `CAPS` | Declaring a remote needs no new flag. |
| `store.db` freshness is the size of each input. `store_inputs()` walks all of `log/` and every node log. A new or grown file is derived again by a plain `awt ingest`. | `awt` `store_inputs`, `sync_into` | Rows that arrive by rsync are indexed incrementally. This answers homelab AW-9 [U] from the code. E-HS10 confirms it by a run. |
| `file_rows()` skips a canonical line that does not parse. That includes an unterminated last line from a partial copy. | `awt` `file_rows` | A partial rsync leaves the store stale, never wrong. The next growth derives the file again. |
| `derive_nodes()` reads `load_at(p)["rows"]` in order. The fallback `record_id` is `<node>#<index>`. | `awt` `derive_nodes` | The store follows the new read order automatically. Ids stay deterministic. |
| `valid()` accepts any integer `v`. No reader in `awt`, the plugin or `migrate-paseo` checks `v == 1`. | grep, 22-Nov | v0.4.1 reads `v: 2` rows without quarantine, in file order. |
| `node_info()` and the pi extension read only the **first line** of a node log. | `awt` `node_info`, the pi extension in `awt` | A union merge keeps the common first line. No change is needed there. |

## Design choices

### 1. Merge order: writer streams ordered by a per-node monotonic clock (a variant of (b), with (a)'s semantics, in one file)

- **Chosen.** The file stays `.awt/events.jsonl` and union merge stays the transport. Read order no longer depends on line position:
  - every row from this release on is `v: 2`;
  - its `ts` is never earlier than any row already in that node's log;
  - `load()` reads legacy `v: 1` rows first, in file order, then `v: 2` rows sorted by `(ts, host, line bytes)`.
- **Why.** No path, reader, lock target or plugin changes. No migration: a single-host log reads exactly as before. No per-clone git config is needed. Causal order survives any clock skew.
- **(a) Per-host files** give the same semantics but change every reader:
  - the first-row node lookup and the pi extension;
  - the `flock` targets of keyed init and effects;
  - `store_inputs`, `migrate-paseo` and the doctor probes.
  
  Merged at read time they still need an order between the files, which is this same clock.
- **(c) A merge driver** needs `git config merge.<name>.driver` in every clone. A clone that lacks it silently falls back to a text merge with conflict markers. That breaks Rule 6 ("forgetting must be harmless") and Rule 7.

### 2. Remotes: the owner declares the sync remote as a `ref` of kind `sync` in the git top-level node

- **Chosen.** `doctor` accepts a remote whose URLs all match a declared target. It still warns for any other remote. For a `github.com` remote it probes visibility with one unauthenticated request and fails when the repo is public.
- **Why.** Whether a remote is private is something only the owner knows, so Rule 3 says to record it. A `ref` row syncs to both hosts through the same repo, carries `by` and `model`, and needs no new verb, flag or settings file.

### 3. Profiles: a per-host derived file, `$AWT_STORE/views/profiles.json`, rebuilt by `ingest`

- **Chosen.** Inputs:
  - store facts: shell commands from `tool_calls`, joined to projects;
  - filesystem facts: manifests and the tracked-file count of repos that exist on this host.
  
  It is not synced. Owner overrides are ordinary `decision` rows tagged `profile:<class>`, and those sync with the tree.
- **Why.** It is kept out of `store.db` because filesystem facts are not store inputs: putting them there would break the byte-stable rebuild guarantee. A file is what the homelab hook reads. Deleting it loses nothing.

### 4. Sync safety

- **A kernel lock on the tree top's `.awt/` directory.**
  - Every `awt` ledger access takes it shared.
  - A sync takes it exclusive while git changes the work tree, and while it heals and stages.
- **An append-only check of staged ledgers in `doctor --staged`.** This is the pre-commit check, and is the "`--strict` or equivalent".
- **A shipped stdlib script, `awt-sync`.** It runs the documented procedure. It is a script like `relay`, not a verb.
- **Why.** These close the two data-loss paths verified above: a write lost across a pull, and a torn tail that gets committed. They add no lock file, flag sprawl or verb.

## Requirements

Each requirement ends with its acceptance tests.

### Ledger order (problem 1)

- **HS1. Row version.** `emit` writes `v: 2`. A `v: 2` row whose `ts` does not match `^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$` is quarantined. `v: 1` rows and rows without `v` are legacy and keep today's rules. Accept: T-HS1, T-HS2.
- **HS2. Monotonic `ts`.** The `ts` of a new row is the larger of the wall clock and (the greatest well-formed `ts` among the node's valid rows, plus 1 microsecond). Both `v: 1` and `v: 2` rows count.
  - The greatest `ts` is taken from the log as this process last read it. A process that has not read the node's log reads it first.
  - Within one host, concurrent writers need no lock for this: rows written concurrently are concurrent.
  - In `effect begin` and other check-then-write paths, the `ts` is computed while the log lock is held.
  
  Accept: T-HS3, T-HS4, C52.
- **HS3. Duplicates.** `load()` reads a non-blank line that is byte-identical to an earlier line of the same file once. It counts the repeats in `D["dups"]`. A duplicate is not quarantined. It is safe to drop because a row carries `ts` to the microsecond, `host` and random ids. Accept: T-HS5, C58.
- **HS4. Read order.**
  - `D["rows"]` is the valid legacy rows in file order, followed by the valid `v: 2` rows sorted by `(ts, host, the raw line bytes)`.
  - Every "latest" rule in SPEC Reading applies to this order. That includes "latest" `state` per scope, `task`, `status` and `ref` per target, superseding, the first `answer`, and the effect fold.
  - The order is a function of the set of rows, not of their positions. Two files holding the same lines in any order read identically.
  - SPEC Reading changes from "file order is canonical" to this rule.
  
  Accept: T-HS6, T-HS7, E-HS3, IS1.
- **HS5. Legacy logs are unchanged.** A log with no `v: 2` row reads exactly as in v0.4.1: same `rows`, the same brief, the same `list` output and the same `store.db` (I8). There is no migration step. Existing single-file ledgers are read in place, and new rows are appended as `v: 2`. Accept: T-HS8, E-HS7.
- **HS6. Late legacy rows.** A `v: 1` row physically after a `v: 2` row means an older `awt` wrote to a synced node. It still reads in the legacy part, before every `v: 2` row. `doctor` warns `N v1 rows after v2 rows (lines ...): a host runs an older awt; install the same version on every host`. Accept: T-HS9, E-HS14.
- **HS7. Host name.** `host` is `AWT_HOST` when it is set and matches `[A-Za-z0-9._-]{1,64}`. Any other value is ignored with one stderr warning. Otherwise it is `socket.gethostname()`. Tests use `AWT_HOST` to simulate two hosts on one machine. Accept: T-HS10.
- **HS8. Concurrent edits to one node from two hosts.** The result is deterministic and the same on both hosts after convergence:
  - `state` (per scope), `task`, `status`, `ref` (per target): the latest by HS4 wins, which is last-writer-wins by the clock in HS2. Both rows stay in `list state --all`.
  - Two decisions superseding the same id: both stay current. `doctor` warns `decision X superseded by two rows (d-a@hostA, d-b@hostB): supersede one of them`.
  - Two answers to one question: the first by HS4 is the answer. `doctor` warns `question q-x answered twice (hosts A, B)`.
  - Effects:
    - a transition from another host that arrives after a pull applies normally;
    - two `begun` rows for one attempt from different hosts: the second is quarantined as today, and `doctor` names it a cross-host conflict: `effect e-x: begun on hostA and hostB (attempt N); check the target and mark it`;
    - claim files (`.awt/claims/`) are per host and ignored by git, so an effect that is `begun` only through a claim shows `begun` only on that host.
  
  Accept: T-HS11-T-HS14, E-HS5, E-HS6.
- **HS9. Clock skew.** HS2 keeps causal order whatever the skew: a row written after a pull sorts after every row the pull brought.
  - Concurrent rows, with neither host having seen the other's, are ordered by `ts`. A host whose clock runs ahead wins those ties.
  - `doctor` warns when any row in the node has a `ts` more than 300 s ahead of this host's clock: `rows up to S s ahead of this clock (host H): check NTP on both hosts`.
  - Brief ages are never negative. A future `ts` reads as age 0 (verified 22-Nov: `ago()` clamps at 0, so the brief prints `just now`; T-HS15).
  
  Accept: T-HS15, E-HS4, C52.

### Sync lock and the sync procedure (problem 4)

- **HS10. The sync lock.** It is `flock` on an fd of the **tree top's `.awt/` directory**, opened `O_RDONLY`. That is the `.awt` of `tree_top(ROOT)`; for a standalone task it is the task itself. No file is created.
  - `emit`, and every read of a node log through `load()`, `node_info()` or `store_inputs()`, holds it `LOCK_SH`. A process takes it at its first ledger access and keeps it to exit.
  - `ingest` takes it only while it reads node logs.
  - `ui` and `doctor --staged` never take it.
  - Lock order is the sync lock first, then any node-log lock (keyed init, `lock()`, `node_flock`). A process that already holds a node-log lock and does not hold the sync lock may only try the sync lock without blocking, inside its existing wait.
  
  Accept: T-HS16, T-HS17.
- **HS11. Waits.**
  - **Writes** wait up to 10 s, then exit 1 with `error: a sync of TOP is in progress` and `fix: rerun in a few seconds`.
  - **`--hook` paths** (`resume --hook`, `ingest --event`, `find --like - --hook`) wait up to 2 s. Then a read goes on unlocked and prints nothing extra, and a write is dropped as for the detected-effects lock. Exit 0.
  - **Plain reads** wait up to 2 s, then read unlocked with `note: TOP is being synced; output may be partial` on stderr.
  
  Accept: T-HS18, E-HS12.
- **HS12. The sync contract.** A tool that changes the tree's work tree from git does it in this order:
  1. `git fetch` without the lock.
  2. Take `LOCK_EX` on the tree top's `.awt/`, waiting up to 30 s. If that fails, skip this run.
  3. Heal: for each tracked or new `**/.awt/events.jsonl` whose last byte is not `\n`, append `\n`. Under `LOCK_EX` no `awt` write is in flight, so the tail is torn for good. This is the heal `emit` already does.
  4. `git add -A`, then `git commit` if anything is staged. The pre-commit hook runs `awt doctor --staged`. A refused commit stops the run, releases the lock and reports.
  5. `git merge --no-edit FETCH_HEAD` (merge, never rebase). If it fails, run `git merge --abort` and stop.
  6. Release the lock.
  7. `git push` without the lock. If it is rejected because the other host pushed first, leave it to the next run. Never force.
  8. If step 5 changed any file, run `awt ingest --hook` (HS40).
  
  Accept: E-HS1, E-HS13, C50, C54.
- **HS13. Mid-flight guarantees.** While a sync holds `LOCK_EX`:
  - no `awt` process writes a node log, so no row can be lost to git replacing a file (fact above);
  - no `awt` read sees a half-replaced file, except after the HS11 timeout, which says so.
  
  A sync killed at any step leaves the ledger either as before or as after the merge. The kernel releases the lock. The next run completes, after `git merge --abort` when `MERGE_HEAD` exists. Git's own `.git/index.lock` after a kill is git's: `awt-sync` reports it with `fix: remove .git/index.lock if no git process is running` and does not delete it. Accept: C50, C57.
- **HS14. `awt-sync` script.** A stdlib Python 3.9+ script at the repo top level, next to `relay`. It is not a verb: `awt-sync [--dir TOP] [--remote NAME] [--branch B] [--wait S] [--no-push] [--quiet]`.
  - It runs HS12 exactly. The lock is taken through `fcntl`, because macOS has no `flock(1)`.
  - It prints one summary line: `synced TOP: committed N files, merged M commits, pushed|push rejected|no push`.
  - Exit codes: 0 ok, including a skip because the lock was busy (stderr says so); 1 a step failed (`error:` and `fix:`); 2 usage; 4 TOP is not a tree top in a git work tree.
  - It never prints remote URLs with credentials: userinfo is stripped.
  - The homelab timers and SessionStart and SessionEnd hooks call it.
  
  Accept: T-HS19-T-HS22, E-HS1.
- **HS15. Ignored per-host files.** The tree top's `.gitignore` covers what every node's does (`scratch/`, `.awt/claims/`, `.awt/runs/`, `BRIEF.md`, `.awt/*.tmp`). `doctor` at a tree top with a declared sync remote (HS30) warns when `git check-ignore` does not ignore one of `BRIEF.md`, `scratch/x`, `.awt/claims/x`, `.awt/runs/x` or `.awt/x.tmp`, naming the missing line. Accept: T-HS23.
- **HS16. Union attribute.** At a tree top with a declared sync remote, `doctor` warns when `git check-attr merge -- .awt/events.jsonl` is not `union`. The fix is `add the line 'events.jsonl merge=union' to TOP/.gitattributes`. A missing attribute does not lose data, because git refuses a conflicted merge and HS12 aborts it. It does stop concurrent edits to one node from merging. Accept: T-HS24.
- **HS17. Pre-commit hook present.** At a tree top with a declared sync remote, `doctor` warns when the effective pre-commit hook (`core.hooksPath`, else `.git/hooks/pre-commit`) is missing, is not executable, or does not contain `awt doctor --staged`. Accept: T-HS25.

### The check before each commit (problem 4)

- **HS20. Ledger checks in `doctor --staged`.** They run in addition to the secret scan. They apply to every staged path named `.awt/events.jsonl` (added, copied, modified, renamed, type-changed). They read staged blobs only. They take no lock and write nothing.
- **HS21. Fail: no final newline.** The staged blob is non-empty and its last byte is not `\n`. The message is `error: PATH: ledger does not end with a newline (torn tail)` with `fix: run awt-sync, or printf '\n' >> PATH while no awt is writing, then git add PATH`. Accept: T-HS26, C51.
- **HS22. Fail: not append-only.** The `HEAD` blob of that path exists and is not a byte prefix of the staged blob. The message is `error: PATH: ledger rows were changed or removed since HEAD` with `fix: git restore --staged PATH; the ledger is append-only`. This also catches a truncated working file. A merge commit is not checked here: the hook git runs for it is `pre-merge-commit`, and HS12 commits local rows before merging. Accept: T-HS27.
- **HS23. Fail: conflict markers.** An added line (after the HEAD prefix) that starts with `<<<<<<< `, `>>>>>>> ` or is exactly `=======`. The fix is `git checkout --theirs/--ours is wrong for ledgers; abort the merge and add 'events.jsonl merge=union' to .gitattributes`. Accept: T-HS28.
- **HS24. Warn only.** Added lines that are not valid rows, or are duplicates, print `warn: PATH:LINE: row would be quarantined` and do not refuse the commit. A torn fragment that `emit` already healed stays in the log forever, so refusing would block every future commit (Rule 6). The output names neither row content nor secrets. Exit 0 when only warnings. Accept: T-HS29.
- **HS25. Working ledger vs HEAD.** Plain `doctor` in a node that sits in a git work tree with a declared sync remote fails when the node's working `events.jsonl` does not have its `HEAD` blob as a byte prefix and no merge is in progress. The message is `fail ledger is not an extension of the committed one (rows lost?)` with `fix: git diff -- PATH; git checkout -- PATH restores the committed rows`. This is the check for a truncation by a full disk during a git write. Accept: T-HS30, C56.

### Private sync remote (problem 2)

- **HS30. Declaring.** The owner runs `awt ref URL --kind sync --title "private sync remote"` in the node that is the git top level. That is the tree top in the homelab setup.
  - The latest `ref` for that target with `kind` `sync` and `access` `ok` declares the remote.
  - A later `ref` of the same target with another kind withdraws it (latest per target wins).
  - The secret scan refuses a URL with an embedded token as for any field. `ref` adds `kind` `sync` to its help text.
  
  Accept: T-HS31.
- **HS31. URL matching.**
  - A URL normalises to `host/path`:
    - drop the scheme (`https`, `ssh`, `git`, `git+ssh`) and the userinfo;
    - turn scp syntax `user@host:path` into `host/path`;
    - lowercase the host;
    - remove a trailing `/` and `.git`;
    - for `github.com`, also lowercase the path.
  - A local path or `file://` URL normalises to its real path.
  - A remote is **declared** when every URL of it, fetch and push (`git remote get-url --all NAME` and `--push --all`, which apply `insteadOf` and `pushInsteadOf`; verified on git 2.54, 22-Nov: `--all` lists every fetch URL, `--push --all` every push URL, so the union covers all of them), normalises to a declared target.
  
  Accept: T-HS32.
- **HS32. Doctor lines.** These run at the git top-level node only, as today. One line per remote, naming the remote by name, never by URL:
  - `ok git remote NAME: declared private sync remote`.
  - `warn git remote NAME: not declared; task data would be pushed if committed; if it is private: awt ref URL --kind sync --title "private sync remote"`. Today's warning, with the fix.
  - A declared target that no remote uses gives `warn declared sync remote not configured in git: URL-host/path`. The normalised form contains no userinfo.
  
  Accept: T-HS33, E-HS9.
- **HS33. Public probe.** For each remote whose normalised host is `github.com`, declared or not, `doctor` makes one unauthenticated `HEAD` request to `https://github.com/<owner>/<repo>`. It sends no credentials and no cookies, uses a 5 s timeout, does not follow redirects, and uses the `User-Agent` `awt-doctor`.
  - `200`: `fail git remote NAME is public: task data must not go there`.
  - `404`: private or missing, no extra line.
  - Anything else, or no network: `warn git remote NAME: visibility not checked (OFFLINE or HTTP N)`.
  - Other hosts: `warn git remote NAME: visibility not checked (only github.com is probed)`, for undeclared remotes only. A declared non-GitHub remote is the owner's word.
  - `AWT_TEST_GITHUB_BASE` replaces `https://github.com` in tests. No test reaches the real GitHub.
  - This is the only network call in awt. `doctor --staged` never makes it.
  
  Accept: T-HS34, E-HS9.
- **HS34. Nested git work trees.** A node that is the top of its own git work tree is checked the same way. A node inside the tree's repo is not checked, as today.

### `store.db` after a pull or an rsync (problem 4)

- **HS40. Rebuild trigger.**
  - No new mode. After a pull that changed node logs, or an rsync that brought canonical files, a plain or `--hook` `awt ingest` updates `store.db` incrementally. Freshness is by size, and `store_inputs()` walks every file under `log/` and every node log.
  - The update equals a rebuild (SPEC, store.db). `awt-sync` runs `awt ingest --hook` after a merge that changed files. The homelab store sync runs it after an rsync that copied files.
  - `--rebuild` is needed only where SPEC already says so (an old store, another schema, adapter or tree). There is no schema change here.
  
  Accept: T-HS35, E-HS10, IS5.
- **HS41. Same-size rewrites.** Freshness by size misses a node log rewritten to the same size. HS22 forbids that in commits and HS25 reports it in the work tree. The fix for a store made stale that way is `awt ingest --rebuild`. Accept: covered by T-HS27, T-HS30.
- **HS42. Idempotent re-import.**
  - A pull that brings nothing changes no file and no store row.
  - Duplicate ledger rows read once (HS3), so `records` gets one row each.
  - A canonical file copied again, unchanged, is not derived again.
  - A canonical file that grew is derived again whole, giving the same rows as a rebuild.
  - Re-running `ingest` with nothing new writes nothing (SPEC, ingest).
  
  Accept: T-HS36, C58.
- **HS43. Partial copy.** A canonical file that ends in an unterminated line (a partial rsync) is derived without that line, as `file_rows()` already does: the line is skipped and not counted as an error. When the file grows, it is derived again. After the full copy, a plain `ingest` gives the same rows as a rebuild from the full files. Accept: T-HS37, C55.
- **HS44. One writer per canonical file.**
  - `awt` names canonical files by provider session (`log/<src>/<YYYY-MM>/<session>.jsonl`), Paseo agent (`log/paseo/<agent id>.jsonl`) or ccusage `<agent>_<period>`. Each has one writing host when sessions and agents stay on their host.
  - A file that both hosts wrote is **divergent**. `awt` derives whatever the local copy holds and never merges two copies.
  - Detecting divergence needs both copies, so it belongs to the rsync side, which keeps both and reports them (homelab AW-8).
  - awt's guarantee: a divergent file never stops an ingest or a build, and never puts rows from one file under another file's session.
  - [unverified: that a ccusage `period` from the `session` report is unique per host's session.]
  
  Accept: C53.
- **HS45. A full disk during a build** is handled as today: the free-space check, exit 1 with `fix:`, the old file kept. The ledger is never touched by `ingest`. Accept: C56.

### Project profiles (problem 3)

- **HS50. Where.** `$AWT_STORE/views/profiles.json`, mode 600, with the directory at mode 700 as for every store file. It is written to a temporary name and renamed into place. It is derived only: deleting it loses nothing. It is never synced, and each host builds its own. It is not in `store.db`, so a store rebuild stays byte-stable.
- **HS51. When.** At the end of every `awt ingest` (plain, `--hook` or `--rebuild`) that built or updated `store.db`, and also when the file is missing or older than 24 h and `store.db` is usable.
  - A `--hook` run has a 5 s budget for this step. Over budget, it keeps the old file and records `errors["profiles"]`. `doctor` warns about that like any ingest error.
  - A store that is old (other schema, tree) gives no profile build.
  
  Accept: T-HS38.
- **HS52. Projects and repos.** A project is a `projects` row of `store.db`. Its repos are:
  - the `path` of every current `ref` of kind `repo` in the project node and its descendants;
  - the git top level of the `cwd` of every session whose `node_id` is in the project;
  
  each kept only when the path exists **on this host**. Sessions with no node (`unassigned`) form one entry per git top level of their `cwd` that exists on this host, with `project` null.
- **HS53. Observed commands.**
  - Source: `tool_calls` rows of the project's sessions whose tool is `Bash` (Claude) or `bash` (pi, opencode), from the last 90 days by `started_at`. The command is the `command` field of `args`.
  - Each command is split into segments on `&&`, `||`, `;`, `|` and newlines. In each segment, leading `VAR=value`, `sudo`, `env`, `command`, `time`, `nohup` and `exec` are dropped, and `cd` segments are skipped. The first two words form the **head**.
  - A head is classed by the table below. The first match wins; anything else is `other`.
  - Only class counts and the 10 most frequent heads (`[a-z0-9._+-]` words only, else `other`) are exported, never command text. This keeps arguments, paths and secrets out of the file.

  | Class | Heads |
  |---|---|
  | `device` | `adb`, `emulator`, `fastboot`, `xcrun simctl`, `xcrun devicectl`, `idevice*`, `ios-deploy`, `maestro` |
  | `media` | `ffmpeg`, `ffprobe`, `magick`, `convert`, `sips`, `sox` |
  | `test` | `pytest`, `python -m` with `pytest` or `unittest`, `cargo test`, `go test`, `jest`, `vitest`, `playwright`, `swift test`, `npm\|pnpm\|yarn\|bun test`, `npm\|pnpm\|yarn\|bun run test*`, `gradle*`/`./gradlew` with a `*test*` task, `xcodebuild test` |
  | `build` | `make`, `cmake`, `ninja`, `bazel`, `cargo build\|run\|check\|clippy`, `go build`, `gradle*`, `./gradlew`, `mvn`, `xcodebuild`, `swift build`, `tsc`, `webpack`, `vite build`, `docker build`, `npm\|pnpm\|yarn\|bun run build*` |
  | `install` | `npm\|pnpm\|yarn\|bun install\|ci\|add`, `pip install`, `uv sync\|pip`, `cargo install`, `brew install`, `apt\|apt-get install`, `pod install`, `bundle install` |

  Accept: T-HS39, T-HS40.
- **HS54. Filesystem facts** (per repo on this host):
  - `manifests`: which of these exist at the repo top: `package.json`, `Cargo.toml`, `build.gradle`, `build.gradle.kts`, `settings.gradle*`, `*.xcodeproj`, `Package.swift`, `Dockerfile`, `node_modules/`, `target/`, `.gradle/`;
  - `tracked_files`: the count from `git ls-files -z`, run with a 10 s timeout, else null.
  
  Symlinks are not followed. Nothing in the repo is written.
- **HS55. Class.** `class` is one of `light`, `build-heavy` or `media-device`. `source` says which rule set it. The first rule that applies wins:
  1. `override`: the current (not superseded) decision tagged `profile:<class>` in the project node or its nearest ancestor that has one. The latest by HS4 wins.
  2. `observed`: `media-device` when `device + media >= 3`.
  3. `observed`: `build-heavy` when `build + test + install >= 5` and that is at least 10% of the shell calls.
  4. `manifest`: `build-heavy` when any of `Cargo.toml`, `build.gradle*`, `settings.gradle*`, `*.xcodeproj`, `Package.swift`, `Dockerfile`, `node_modules/`, `target/` or `.gradle/` is present, or `tracked_files > 5000`.
  5. `default`: `light`.
  
  A repo takes its project's override and observed counts, plus its own manifests. A project's own class uses the union of its repos' manifests. Accept: T-HS41, T-HS42, E-HS11.
- **HS56. Override row.** `decide` refuses a tag `profile:X` with X not one of the three classes, with `fix: use --tag profile:light|build-heavy|media-device`. No new event type, verb or field is added. The override is "what no machine can know" (Rule 3), syncs through the tree and wins on both hosts. Accept: T-HS43.
- **HS57. Shape.** The file is:

  ```json
  {"v":1,"built":"<ts>","host":"<host>","window_days":90,
   "projects":{"<project_id>":{"class":"build-heavy","source":"observed","repos":["/abs"],"commands":{"build":12,"test":30,"install":2,"device":0,"media":0,"other":80},"heads":[["cargo test",25]],"sessions":7,"last_seen":"<ts>"}},
   "repos":{"/abs/path":{"project":"<project_id>|null","class":"...","source":"...","manifests":["Cargo.toml"],"tracked_files":812,"commands":{...},"heads":[...],"sessions":3,"last_seen":"<ts>"}}}
  ```

  - Keys are sorted.
  - A consumer looks up the longest `repos` key that is a path prefix of its cwd.
  - A repo `awt` has never seen is absent, and the consumer applies its own default.
  
  Accept: T-HS44.
- **HS58. Not a classifier contract.** The table in HS53 is coarse and self-contained. Agreeing with any placement classifier outside awt (homelab corral, PL-3) is that consumer's job. It may read `heads` and `manifests` and decide for itself.

### Docs, help and limits

- **HS60.** No new verb (16 stay). New: `awt-sync` script, `AWT_HOST`, test seams `AWT_TEST_CLOCK_SKEW_S` (added to the clock in `now()`), `AWT_TEST_SHORT_WRITE` (emit writes that many bytes, then fails as a short write), `AWT_TEST_SYNC_WAIT_S` (replaces the 10 s and 2 s waits of HS11) and `AWT_TEST_GITHUB_BASE`. `doctor` gains lines and no flags.
- **HS61.** `SPEC.md` Rules: Rule 5 adds "flock on the tree top's `.awt/` directory (the sync lock)". Rule 4 adds the profiles file as a second derived artifact, in the store and not in the tree.
- **HS62.** The guide and agent text tell agents nothing new. Sync is the host's job, and agents keep using `awt` as before.

## What `awt` guarantees with two writing hosts

| Situation | Guarantee | Requirements |
|---|---|---|
| Both hosts append to different nodes, then sync | Both hosts read every row. Merges are clean and nothing is quarantined. | HS4, HS12 |
| Both append to one node, then sync | Same rows, same order and same "latest" on both hosts. Last writer by HS2's clock wins. Conflicts that need a person are named by `doctor`. | HS4, HS8 |
| Clock skew between hosts | A causal chain (write, sync, write on the other host) is always in order. Concurrent rows are ordered by clock. Skew over 300 s is reported. | HS2, HS9 |
| The same rows arrive twice (union duplicates, a re-merge, a cherry-pick) | Read once and indexed once. | HS3, HS42 |
| A pull or rsync brings data | The next `awt ingest` (run by `awt-sync`) brings `store.db` up to date, equal to a rebuild. | HS40 |
| A sync runs while agents write | Writes wait, up to 10 s, or a hook drops one row. No row is lost to git replacing the file. | HS10, HS11, HS13 |
| A sync or a writer is killed | No torn line is ever committed. The ledger reads, the lock is gone with the process, and the next sync completes. | HS12, HS13, HS21 |
| A full disk | A short write fails with `fix:`. The torn tail is healed before the next commit. A truncated working ledger is reported by `doctor`. The store build refuses. | HS21, HS25, HS45 |
| Existing single-file ledgers | Read exactly as before. There is nothing to migrate. | HS5 |
| An older awt on one host | Its rows read, before newer rows, and `doctor` names it. | HS6 |

## Tests (unit and integration; to be added to `tests/TEST-SPEC.md` before the code)

New file `tests/test_sync.py`. It uses the stdlib, temp dirs, `git` (skip the class when `git` is absent) and a local bare repo. There is no network: HS33 runs against a local `http.server`.

| Id | Test |
|---|---|
| T-HS1 | `emit` writes `v: 2`. A hand-made `v: 2` row with `ts` `2026-11-22T10:00:00Z` (no microseconds) is quarantined. The same row as `v: 1` is not. |
| T-HS2 | v0.4.1 `awt` (from `git show v0.4.1:awt`) reads a log holding `v: 2` rows with 0 quarantined. |
| T-HS3 | With `AWT_TEST_CLOCK_SKEW_S=-3600` and a log whose greatest `ts` is now: the new row's `ts` is greatest + 1 µs. With `+3600`: the wall clock is used. |
| T-HS4 | `effect begin` computes `ts` under the log lock. 20 concurrent `effect` steps on one effect fold with no quarantine. |
| T-HS5 | A log with each of 50 lines doubled reads the same `rows` as the undoubled log. `dups` is 50, `bad` is 0. |
| T-HS6 | The lines of a two-host log, shuffled 100 times (legacy prefix fixed): `rows`, `states`, `task`, `status`, `refs`, `ans`, `eff` and the brief (ages masked) are identical. |
| T-HS7 | `(ts, host, bytes)` tie-break: two `v: 2` rows with equal `ts` order by `host`, then by bytes. |
| T-HS8 | Every fixture log in `tests/fixtures` and every log made by the existing suites: `rows` equals the v0.4.1 order. The brief and `list --all --json` are byte-identical with v0.4.1 (I8). |
| T-HS9 | A `v: 1` row after `v: 2` rows reads before them, and `doctor` warns with the line number. |
| T-HS10 | `AWT_HOST=box-1` stamps `host` `box-1`. `AWT_HOST='a b'` warns once and uses the hostname. |
| T-HS11 | Two hosts set `state` on one scope concurrently. The one with the greater `ts` is current on both. `list state --all` has both. |
| T-HS12 | Two decisions supersede `d-x`: both current, and the `doctor` warning names both. |
| T-HS13 | Two answers to `q-x`: the first by HS4 wins, and `doctor` warns. |
| T-HS14 | Effect `begun` on host A, then `sent` on B after a pull: state `sent`, no quarantine. `begun` on both for attempt 1: one quarantined, and `doctor` prints the cross-host line. |
| T-HS15 | A row 600 s ahead of the clock: `doctor` warns with the host. The brief age is not negative. |
| T-HS16 | With `LOCK_EX` held on `TOP/.awt` by the test: `note` blocks, then exits 1 after 10 s with the fix (`AWT_TEST_SYNC_WAIT_S` shortens the wait); `resume --hook` returns within 2.5 s, exit 0; `list` prints the partial note. After release, a write succeeds at once. |
| T-HS17 | No deadlock: `effect begin` (log lock, then sync lock) racing an `awt-sync` (sync lock only) 100 times completes every time. |
| T-HS18 | `ingest --event --hook` with the sync lock held drops the row silently, exit 0, within 2.5 s. |
| T-HS19 | `awt-sync` on two clones of a bare repo, the whole HS12 sequence: commit, merge and push happen, and the summary line is right. |
| T-HS20 | `awt-sync` with the lock held by another process exits 0, skipped, with a stderr note. |
| T-HS21 | `awt-sync` heals a torn tail before staging. The commit passes HS21. |
| T-HS22 | `awt-sync` after a rejected push: exit 0, `push rejected`, and the next run converges. It never runs `--force` (checked by a fake `git` wrapper that logs its argv). |
| T-HS23 | HS15: remove `BRIEF.md` from the top `.gitignore`: `doctor` warns, naming the line. |
| T-HS24 | HS16: no union attribute: warn. `events.jsonl merge=union`: ok. |
| T-HS25 | HS17: hook absent, not executable, or without `awt doctor --staged`: warn. `core.hooksPath` is honoured. |
| T-HS26 | `doctor --staged` with a staged ledger with no final newline: exit 1 and the HS21 fix. |
| T-HS27 | A staged ledger with a changed middle byte, or with the last row removed: exit 1 (HS22). A new file (no HEAD blob): no prefix check. |
| T-HS28 | Staged conflict markers: exit 1 (HS23). |
| T-HS29 | A staged torn fragment followed by a healed row: warn with the line number, exit 0. No row text in the output. |
| T-HS30 | Truncate the working ledger: `doctor` fails (HS25). During a merge with `MERGE_HEAD`: no fail. |
| T-HS31 | `ref URL --kind sync` declares. A later `ref URL --kind link` withdraws. A URL with a token-shaped userinfo (built at runtime) is refused by the secret scan. |
| T-HS32 | Normalisation table: `git@github.com:Owner/Repo.git`, `ssh://git@github.com/owner/repo`, `https://github.com/owner/repo/`, `git+ssh://…` are equal. A different host or owner is not. Local paths compare by real path. |
| T-HS33 | `doctor` lines for a declared remote, an undeclared remote, a declared target with no remote, and a remote with one undeclared push URL. Output never holds a URL with userinfo. |
| T-HS34 | Probe against a local server: 200 fail, 404 no line, 500 warn, refused connection warn, 5 s timeout respected (server sleeps 6 s). No request carries `Authorization` or `Cookie`. `doctor --staged` makes no request. |
| T-HS35 | Store: host A's canonical files copied into host B's store, then a plain `ingest` on B: A's sessions are in B's `store.db`. A `.dump` equals that of `ingest --rebuild` (rowids masked). |
| T-HS36 | Re-import: the same pull twice and the same rsync twice: `build_state` and every table unchanged. Ingest prints 0 rows. |
| T-HS37 | Partial copy: a canonical file cut mid-line. `ingest` gives no error count, then the full file plus `ingest` equals a rebuild. |
| T-HS38 | Profiles are written after `ingest` with mode 600, written by rename, refreshed when over 24 h old, and kept on a hook timeout with `errors["profiles"]`. A store with another schema writes none. |
| T-HS39 | Head extraction: `FOO=1 sudo env cargo test --all && cd x \| tee log` gives heads `cargo test` and `tee`. Secrets and paths in arguments never reach the file. |
| T-HS40 | Class table: one case per row of HS53, plus `other`. |
| T-HS41 | Class rules in order: override beats observed, which beats manifest, which beats default. Thresholds at 2/3 device+media calls and at 4/5 and 9%/10% build calls. |
| T-HS42 | A repo path missing on this host is not in `repos`, but its sessions still count for the project. An unassigned session cwd gives a `project: null` entry. |
| T-HS43 | `decide --tag profile:heavy` is refused with the fix. `profile:build-heavy` is accepted and becomes `source: override`. A superseding decision with `profile:light` wins. |
| T-HS44 | Shape: sorted keys, `v` 1, `heads` at most 10, no command text (a grep for a fixture argument finds nothing). |

Existing suites stay green: unittest, `tests/chaos.py`, `cd paseo-plugin && npm test`.

## Docs to update in the implementation PR

- `SPEC.md`:
  - Rules 4 and 5 (HS61);
  - Events: envelope `v` 2 and the monotonic `ts` (HS1, HS2, HS7);
  - Reading: replace "file order is canonical" with HS3, HS4 and HS6;
  - Verbs: the `ref` and `decide` rows (`sync` kind, `profile:` tags);
  - doctor: HS15-HS17, HS20-HS25, HS30-HS34, the HS8 and HS9 warnings;
  - ingest and store.db: HS40-HS45, HS50-HS57;
  - a new section "Two hosts" with HS10-HS14 and the guarantee table;
  - Distribution: `awt-sync`.
- `tests/TEST-SPEC.md`: a section "Two hosts (`test_sync.py`; chaos group `sync`; e2e `docs/e2e-two-host-sync.md`)" with T-HS*, C50-C59 and IS1-IS7.
- `CLI_HELP` for `ref`, `decide` and `doctor`, then `python3 tools/gen_docs.py`.
- `docs/schema.md`: a note that profiles are not in `store.db`.
- `AGENTS.md` (the repo's): "Install the CLI" gains `awt-sync` for two-host setups, with a short "Two hosts" section: declare the remote, `.gitattributes`, the pre-commit hook, `awt-sync` from a timer.
- `README.md` one line.
- `CHANGELOG.md`.

## Rollout

1. One PR, merged only on the owner's go-ahead. Release v0.5.0, a minor bump: new envelope version and a new script.
2. Install the same release on both hosts (homelab AW-1).
3. No `store.db` rebuild is needed for this change: there is no schema change. The box still does its first full build per homelab AW-9.
4. Then, in the tree top:
   - `awt ref <awt-data URL> --kind sync --title "private sync remote"`;
   - add `events.jsonl merge=union` to `.gitattributes` (homelab AW-2 already plans `*.jsonl merge=union`, which also matches);
   - install the pre-commit hook;
   - run `awt doctor` until it is clean;
   - homelab AT-03 to AT-05 are then expected to pass by construction. E-HS2 to E-HS6 are their offline twins.

## Open questions (defaults chosen; say if you want otherwise)

1. **`doctor` makes one network request** (HS33) to detect a public GitHub repo. Default: yes. It is unauthenticated, has a 5 s timeout, and `doctor --staged` never makes it. The alternative is no probe, with privacy taken purely on the owner's declaration.
2. **`awt` ships `awt-sync`** rather than each host scripting HS12 itself. Default: yes, because macOS has no `flock(1)` and the procedure has ordering traps. The homelab timers call it instead of their own script.
3. **Profile classes and thresholds** (HS53, HS55) are awt's own coarse table. Default: as written. Corral may refine from `heads` and `manifests`.
4. **Last-writer-wins for concurrent `state`/`status`/`task`** with a `doctor` note only for decisions, answers and effects. Default: yes. A concurrent `state` from two hosts is normal (two agents), not a conflict.

## Traceability (homelab `SPEC-paseo-box.md` section 12 and `SPEC-tests.md` 5.9)

| Homelab | Here |
|---|---|
| AW-2 (tree in git, union, ignores) | HS4, HS15, HS16 |
| AW-3 (pull and push, `flock`, pre-commit `doctor --staged`) | HS10-HS14, HS20-HS24 |
| AW-4 (a)-(d), Q12-3 | HS2-HS4 (a), HS3 (b), HS8 (c), HS21 and HS24 (d) |
| AW-6, Q12-4 | HS30-HS34. Note: today only the git top-level node warns, not every node |
| AW-8 (`log/` rsync, divergent files) | HS43, HS44 |
| AW-9 [U] (incremental ingest of rsynced rows) | HS40: yes, from the code. E-HS10 confirms it |
| AW-10 | HS40, E-HS10 |
| PL-21 (profiles) | HS50-HS58 |
| AT-03, AT-04, AT-05 | E-HS2, E-HS3 and E-HS4, C51 |
| AT-06 | E-HS12, E-HS13, C50 |
| AT-08, AT-09 | E-HS10, C53, C55 |

## Implementation notes (v0.5.0)

Where the code differs from the text above, on purpose:

- **HS9.** The "rows ahead of this clock" warning ignores rows written by this host itself. After a pull, HS2 raises a host's own rows past a fast peer's, so they are ahead of its clock by causality, not by its clock. The warning names the other host (E-HS4).
- **HS10.** `ingest` holds the shared sync lock from its first ledger access to exit, not only while it reads node logs. A long rebuild therefore delays `awt-sync` (it waits 30 s, then skips the run).
- **HS11.** `AWT_TEST_SYNC_WAIT_S` sets the write wait and caps the 2 s waits at its value, so one setting serves a write test and a hook test (E-HS12).
- **HS51.** The profile error of a hook run over budget is kept in `ingest/profiles.offsets.json` (`errors["profiles"]`), the file `doctor` already reads for the other sources.
- **HS53.** A head is the first word, plus a subcommand for tools that have them (`cargo`, `go`, `npm`, `pnpm`, `yarn`, `bun`, `swift`, `xcrun`, `xcodebuild`, `docker`, `git`, `uv`, `pip`, `brew`, `apt`, `apt-get`, `pod`, `bundle`, `vite`, `gh`, `kubectl`, `make`) and `python -m MODULE`, so `tee log` is `tee` (T-HS39).
- **Tests.** `list --all --json` without a section is a usage error, so the legacy comparisons (T-HS8, E-HS7) use `list SECTION --all --json`. T-HS17 runs 30 rounds, not 100. The store is compared with a rebuild without rowids and without the `ingest_sources` snapshot, which holds the run time.
