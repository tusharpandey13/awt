# E2E test spec: active recall

Companion to `docs/spec-active-recall.md` (R1-R5) and `tests/TEST-SPEC.md`. Unit ids T-R*, P15-P20 belong to the unit plan; this file owns **E-R1 to E-R22**. Each journey drives the real `awt`, the real plugin in a real daemon, or a real agent, and judges on exit codes, stdout/stderr and files, never on an agent's words.

Tiers:

| Tier | Runs | Gate |
|---|---|---|
| cli | always, in `unit` CI (E-R7 in `chaos-full`) | none |
| daemon-gated | `npm run test:daemon` in `paseo-plugin/` | `AWT_E2E_PASEO=1`, Paseo 0.15.4+ on `PATH` |
| agentic-paid | `tests/agentic/run.py --only recall-*` | `AWT_E2E_PAID=1` **and owner approval per run batch** (memory rule: no token-spending run without asking) |

## 0. Shared rules

**Isolation (every tier).** `T=$(cd "$(mktemp -d)" && pwd -P)` (realpath, so macOS `/private/tmp` prefixes match). Every process runs with `HOME=$T`, `TZ=UTC`, and with `AWT_*`, `PASEO_*` and `CLAUDECODE` removed from the environment, then only the variables a step names are added. `WT` is the worktree under test; `AWT=$WT/awt`. Daemon steps always pass `--home $T/home`. Pre-flight assertion: `$T/home` is not `~/.paseo` of the real user and `AWT_ROOT` (when set) is under `$T`. No fixture uses data from this machine; projects are the fictional `parsekit` and `ledgerline`; ids such as `wks_0001` are made up. No credential-shaped literal appears in this file or in a test; a secret-scan probe, if needed, is built at runtime as `tests/agentic/scenarios.py` does.

**Universal checks (U), applied after every step unless a step says otherwise.**
- U1: no `Traceback` on stderr; exit code in 0-4; every refusal has `error:` and `fix:` (I3).
- U2: read-only commands (`find`, `list`, `resume`, `doctor`) leave the tree unchanged: `find $R -type f | sort | xargs shasum` is identical before and after.
- U3: nothing outside `$T` changes (I5).

**Id capture.** `first() { "$@" | head -1 | cut -d' ' -f1; }`. Rows are read back with `list <section> --json`.

**Cleanup (cli).** `chmod -R u+rwX $T; rm -rf $T`. **Cleanup (daemon).** The `cleanup()` of `daemon.test.ts`: `paseo --home $T/home daemon stop`, else kill the pid in `$T/home/paseo.pid`; then `rm -rf $T`; assert no process whose argv contains `$T/home` survives (`pgrep -f "$T/home"` empty), also on SIGINT/SIGTERM.

### Fixture F1 (cli tier)

Built once per test class with the worktree `awt`; each journey works on `cp -a $T/f1 $T/<journey>` and sets `R` to that copy. Texts avoid trailing periods (see open question Q1).

In expected output, `@$X` for a cwd outside the tree means `$X` relative to `$R` (for example `@workspaces/ledgerline`), per SPEC `find --like`; the resolved node's own lines have no `@` prefix.

```
R=$T/f1; mkdir -p $R $T/repo/parsekit $T/elsewhere; git init -q $T/repo/parsekit
awt --dir $R init --kind root
awt --dir $R init --kind workspace --name parsekit
awt --dir $R init --kind workspace --name ledgerline
PK=$R/workspaces/parsekit; LL=$R/workspaces/ledgerline
awt --dir $PK init --kind task --name main      --goal "Parsekit upkeep" --done "Nothing open"
awt --dir $PK init --kind task --name retry-bug --goal "Stop retry storms in the fetch client" --done "Soak test shows no synchronised retries"
awt --dir $LL init --kind task --name gateway   --goal "Map gateway limits" --done "Limits documented"
RB=$PK/tasks/retry-bug; GW=$LL/tasks/gateway
awt --dir $RB init --kind agent --name a1 --key test:agent/a1;  A1=$RB/agents/a1
awt --dir $A1 init --kind agent --name s1 --key test:agent/s1;  S1=$A1/agents/s1
awt --dir $GW init --kind agent --name b1 --key test:agent/b1;  B1=$GW/agents/b1
D_RULE=$(first awt --dir $LL decide "Retry gateway calls with exponential backoff and full jitter" --why "Fixed backoff synchronised the clients and overloaded the gateway" --tag rule)
D_OLD=$(first awt --dir $RB decide "Retry every 1 s with metronome fixed backoff" --why "simplest")
D_NEW=$(first awt --dir $RB decide "Retry with capped exponential backoff" --why "Fixed backoff synchronised clients" --supersedes $D_OLD)
awt --dir $RB ref https://example.invalid/backoff --title "Backoff and jitter notes" --why "background for retry policy"   # REF1
N1=$(first awt --dir $PK/tasks/main note "CI retries flaky tests twice")
Q1=$(first awt --dir $GW ask "Is the 30 s gateway timeout a hard limit?"); awt --dir $GW answer $Q1 "Yes, the gateway enforces it"
awt --dir $GW state --now "Gateway timeout mapped" --next "Write the jitter soak test"                                     # S_MAIN (written after REF1)
N_LONG=$(first awt --dir $GW note "$(printf 'zephyrine window %.0s' $(seq 1 15))")                                          # 254 chars; note text is capped at 280
awt --dir $A1 state --scope auto --now "[auto] exit=0 quillwort sweep done" --next -                                         # auto, must never surface
awt --dir $B1 state --now "Checked quillwort fixture" --next -                                                               # main, may surface
```

Every query below was chosen so its expected hits do not depend on which ~80 stopwords are built in (no candidate contains the query's possibly-stopword words such as `use`, `easy`, `what`).

### Daemon fixture D0 (daemon-gated)

The `before()` of `paseo-plugin/test/daemon.test.ts`, unchanged (temp home, free port, `pluginsEnabled: true`, relay/dictation/MCP injection off, fake ACP provider, `paseo plugin install $WT/paseo-plugin`, restart, workspace `W1` on `$T/parsekit`), plus:

- A second repo `$T/ledgerline` and workspace `W2`; after the plugin creates its node, `awt --dir <node with key paseo:workspace/W2> decide "Retry gateway calls with exponential backoff and full jitter" --why "Fixed backoff synchronised the clients and overloaded the gateway" --tag rule` (id `D_RULE`).
- Daemon env adds `AWT_RELATED=2` and `AWT_FAKE_WIRE=$T/wire.jsonl`.
- Harness extensions (test code, not product code): **H1** `fake/acp_agent.py` appends every inbound JSON-RPC line to `$AWT_FAKE_WIRE` when set. **H2** `receipts(id)`: timeline items with `type: "plugin"` and `kind: "awt.receipt"`, read from `paseo --home $H logs <id> --json`; if E-R10 step 0 finds that the CLI does not emit plugin items, read them with `@getpaseo/client` `agents.ref(id).timeline.refetch({ direction: "tail", limit: 100 })` instead, and the test file states which path it uses. **H3** `waitReceipts(id, n)`: poll H2 every 250 ms until `n` receipts or 15 s (then fail). **H4** `FAIL: <cmd>` prompt: the fake runs the command, then answers the prompt with a JSON-RPC error.
- Changing a daemon setting means `paseo daemon stop` then `paseo daemon start` with the new env (`restart` keeps the supervisor's env).

## 1. CLI journeys (tier cli)

### E-R1 `find --like` across workspaces from every vantage point (R1)

Pre: F1 copy. Query `Qx="gateway backoff jitter"` (3 words, so a hit needs 2 shared words). Candidates that qualify: `D_RULE` (3 words, rule), `S_MAIN` (gateway, jitter), `REF1` (backoff, jitter). `D_NEW` and `Q1` share 1 word; `D_OLD` is superseded. `S_MAIN` and `REF1` score equally (each word has df 3), so the newer `S_MAIN` comes first.

| # | Step | Expected |
|---|---|---|
| 1 | `cd $T/repo/parsekit; AWT_DIR=$A1 $AWT find --like "$Qx"` | exit 0; exactly 3 lines, in this order: line 1 `^$D_RULE @$LL \[rule\]: Retry gateway calls with exponential backoff and full jitter \(why: Fixed backoff synchronised the clients and overloaded the gateway\)$`; line 2 contains ` @$GW` and `Gateway timeout mapped`; line 3 contains ` @$RB` and `Backoff and jitter notes`. All prefixes absolute (cwd outside the tree). Every hit line is cut to 200 chars, so with a long temp path compare to the expected text after the cut (first 199 chars plus `~`) |
| 2 | `cd $T/elsewhere; $AWT --dir $A1 find --like "$Qx"` | stdout byte-identical to step 1 |
| 3 | `cd $R; $AWT find --like "$Qx"` | same 3 lines with prefixes `workspaces/ledgerline`, `workspaces/ledgerline/tasks/gateway`, `workspaces/parsekit/tasks/retry-bug` |
| 4 | `cd $RB; $AWT find --like "$Qx"` | `D_RULE` prefix is `../../../ledgerline`; the REF1 line has no ` @` segment (own node) |
| 5 | For each prefix P of step 3: `(cd $R; $AWT --dir P list decisions --json)` etc. | the hit's row is in that node (prefix is usable as `--dir`) |
| 6 | `cd $R; $AWT find --like metronome` | stdout exactly `no related records`; exit 0 (only the superseded `D_OLD` has the word) |
| 7 | `cd $R; $AWT find --like quillwort` | exactly 1 line, contains ` @workspaces/ledgerline/tasks/gateway/agents/b1` and `Checked quillwort fixture`; no line contains `agents/a1` (auto state excluded) |
| 8 | `cd $R; $AWT find --like zephyrine` | 1 line, `len(line) <= 200` (Python `len` on the decoded line) |
| 9 | U2 over steps 1-8 | tree unchanged |

Proves R1 (words, candidates, superseded and auto exclusion, ranking with rule boost and newest-first ties, prefix rule, 200-char cut, no-hit line).

### E-R2 `find --like` flags, scope and refusals (R1)

Pre: F1 copy.

| # | Step | Expected |
|---|---|---|
| 1 | `cd $R; $AWT find --like "$Qx" --limit 1` | exactly the `D_RULE` line |
| 2 | 25 extra notes in `$LL`: `note "gateway jitter probe K"`, K=1..25; then `find --like "$Qx"` | exactly 10 lines (default limit); `--limit 40` gives 28 lines |
| 3 | `--limit 0`, `--limit 41`, `--limit x` | exit 2 each, `error:` and `fix:` on stderr, empty stdout |
| 4 | `$AWT find gateway --like "$Qx"` | exit 2, `error:`/`fix:` |
| 5 | `$AWT --dir $RB find --like "$Qx" --down` | exactly the REF1 line (own node + descendants) |
| 6 | `$AWT --dir $A1 find --like "$Qx" --up` | exactly the REF1 line, prefix relative/absolute per cwd rule |
| 7 | `$AWT --dir $PK note "see $D_RULE"`; then `cd $R; $AWT find --like "$D_RULE"` | contains the new note line (ids are kept as words, 1-word query); whether `D_RULE`'s own row also matches on its id is Q22 |

Proves R1 (limit, scope narrowing, TERM conflict, ids as words).

### E-R3 `decide` lists related records, including a rule from another workspace (R2)

Pre: F1 copy. `cd $T/repo/parsekit; export AWT_DIR=$A1`.

| # | Step | Expected |
|---|---|---|
| 1 | `$AWT decide "Use fixed 1 s backoff for fetch retries" --why "Easy to reason about for the gateway client"` | exit 0; stderr empty; exactly 3 lines: `^(d-[0-9a-f]{8}) decided$` (NEW1), `^related: $D_RULE @$LL \[rule\]: Retry gateway calls with exponential backoff and full jitter \(why: Fixed backoff synchronised the clients and overloaded the gateway\)$`, `^related: $D_NEW @$RB: Retry with capped exponential backoff \(why: Fixed backoff synchronised clients\)$` |
| 2 | `$AWT list decisions --json` | NEW1 present with the exact choice and why; it is the only new row anywhere in `$R` |
| 3 | No related line names NEW1 or `D_OLD` | holds |
| 4 | Repeat step 1 verbatim (NEW2) | exactly 4 lines; related ids = {NEW1, `D_RULE`, `D_NEW`} in any order; NEW2 absent from related |

Proves R2 (query text = choice + why, row just written excluded, default N=3, rank as R1, write first).

### E-R4 `ask` shows an answer from another workspace (R2)

Pre: F1 copy. `cd $T/repo/parsekit; export AWT_DIR=$A1`.

| # | Step | Expected |
|---|---|---|
| 1 | `$AWT ask "Is the gateway timeout a hard limit for retries?"` | exit 0; exactly 3 lines: `^q-[0-9a-f]{8} asked$`; `^related: $Q1 @$GW: Is the 30 s gateway timeout a hard limit\? → Yes, the gateway enforces it$`; a line with ` @$GW` and `Gateway timeout mapped` |
| 2 | `Q2=$(first $AWT --dir $B1 ask "Which jitter cap applies to the soak tenants?")`; then step-1 style `$AWT ask "What jitter cap applies to soak tenants?"` | first related line is `^related: $Q2 @$B1: Which jitter cap applies to the soak tenants\?$` (no `→`) |
| 3 | `$AWT --dir $B1 answer $Q2 "Ten seconds"`; repeat the step-2 ask | the `Q2` related line contains ` → Te` and equals the expected text after the 200-char cut (a long temp prefix cuts the answer) |

Proves R2 (answered questions show their answer; unanswered ones show without `→`).

### E-R5 `--related` and `AWT_RELATED` precedence (R2)

Pre: F1 copy plus 22 notes in `$LL`: `note "Fixed backoff probe K for the gateway"` (each qualifies for the E-R3 query). Command `DEC='decide "Use fixed 1 s backoff for fetch retries" --why "Easy to reason about for the gateway client"'`, from `AWT_DIR=$A1`, fresh copy per row. "lines" = stdout lines.

| Variant | Expected |
|---|---|
| default | 4 lines, line 2 is `D_RULE` (rule boost) |
| `--related 1` | 2 lines |
| `--related 0` | 1 line (`decided` only) |
| `--related 20` | 21 lines |
| `AWT_RELATED=0` | 1 line |
| `AWT_RELATED=1` + `--related 2` | 3 lines (flag wins) |
| `AWT_RELATED=5` | 6 lines |
| `AWT_RELATED=abc`, `=21`, `=-1` | exit 0; 4 lines; stderr has one warning line naming `AWT_RELATED` |
| `--related 21`, `--related -1`, `--related x` | exit 2, `error:`/`fix:`; **no row written** (decision count unchanged) |
| same matrix on `ask "Is the gateway timeout a hard limit for retries?"` | exactly 2 hits qualify (`Q1`, `S_MAIN`; the probe notes share only `gateway`), so lines = min(N, 2) + 1; error cases as above |

Proves R2 (N range, precedence, flag vs env error handling, 0 disables).

### E-R6 `list --since ... --down --json` (R4 read flag)

Pre: F1 copy. In `$RB`: `note "t0 marker"`; `T0=$($AWT --dir $RB list notes --json | jq -r '.[-1].ts')` (the marker row's own ts, to prove inclusivity). Then in order: `$RB decide "x1" --why "y1"`; `$A1 note "a1 after"`; `$A1 state --now "a1 now" --next "a1 next"`; `$A1 state --scope auto --now "[auto] a1" --next -`; `$S1 note "s1 after"`.

| # | Step | Expected |
|---|---|---|
| 1 | `$AWT --dir $RB list --since $T0 --json` | JSON array of exactly 2 rows: types {note (`t0 marker`), decision}; each has `type`, `ts`, `by`, `id` |
| 2 | `... --since $T0 --down --json` | exactly 6 rows; the 4 from `A1`/`S1` carry `node` naming `agents/a1` resp. `agents/a1/agents/s1`; the two state rows have `scope` `main` and `auto`; F1 rows (older) absent |
| 3 | `$AWT --dir $A1 list --since $T0 --down --json` | exactly the 4 `A1`/`S1` rows (the receipt query) |
| 4 | `--since` = newest ts + 1 µs | `[]`, exit 0 |
| 5 | `--since yesterday` | exit 2, `error:`/`fix:` |
| 6 | Row ts strings are parseable ISO 8601 UTC; every row's `ts >= T0` | holds |

Proves R4 (`list --since`, `--down`, `node`, `scope`, inclusive boundary).

### E-R7 Large tree timing, 2,000 descendants (R1, R2)

Pre: tree L built with the real `awt` (run in background, output to a log; cache the tree as a tarball keyed by the `awt` sha): root + 10 workspaces `w00..w09` × 10 tasks `t00..t09` × 18 agents `a00..a17` (1,910 descendants) + 90 extra agents under `w00/tasks/t00` = 2,000 descendants of the root (the cap counts descendants, not the searched top: SPEC.md and `awt` agree on the 2,000 cap, and `awt` excludes the top). Every node gets `note "routine note K about the retry budget"`; every 10th agent a decision `"Keep the retry budget at K"`. Plant `D_DEEP` in `w09/tasks/t09/agents/a17`: `decide "Shard the vellichor index by tenant" --why "Hot tenants starve the vellichor queue" --tag rule`.

| # | Step | Expected |
|---|---|---|
| 1 | One warm-up, then 3 runs: `cd $L; /usr/bin/time -p $AWT find --like "vellichor index shard"` | each `real` < 2.0 s; line 1 is `D_DEEP` with prefix `workspaces/w09/tasks/t09/agents/a17`; no limit line |
| 2 | `AWT_DIR=$L/workspaces/w00/tasks/t00/agents/a00 /usr/bin/time -p $AWT decide "Shard the vellichor index by region" --why "Region skew"` | `real` < 2.5 s; a related line names `D_DEEP`; no `lookup stopped at 2 s` line |
| 3 | Add a 2,001st descendant (an agent under `w00/tasks/t01`); repeat step 1 | exit 0; output ends with the walk-limit line in the same words `find --tree` uses |

Proves R1 scope caps and the 2 s budget on real data (T-R1g/T-R2f cover the simulated cases).

### E-R8 Corrupt and odd nodes never break a lookup or a write (R1, R2)

Pre: F1 copy. Baseline: the same corruption applied to a second copy and inspected with the pre-feature `awt` (`git -C $WT show a35fea8:awt > $T/pre/awt`, read-only).

Corruption, all at once:
- a) append to `$GW/.awt/events.jsonl`: a line `{not json`, a line `{"type":"decision"}`, a line of 16 bytes `\xff`;
- b) `chmod 000 $PK/tasks/main/.awt/events.jsonl` (skip the sub-check when `id -u` is 0);
- c) `mkdir -p $LL/tasks/broken/.awt/events.jsonl` (a directory where the log should be);
- d) `$PK/tasks/.new-zz/.awt/events.jsonl` holding a copy of `D_RULE`'s row (half-built node);
- e) `ln -s $R $PK/tasks/loop` (symlink loop);
- f) `chmod 000 $LL/tasks` on a second run of steps 1-2 only.

| # | Step | Expected |
|---|---|---|
| 1 | `cd $R; $AWT find --like "$Qx"` | exit 0; contains the `D_RULE` and `S_MAIN` lines (good rows of a corrupt node still count); no line from `.new-zz`, `broken` or `loop`; U1 holds |
| 2 | `AWT_DIR=$A1 $AWT decide "Use fixed 1 s backoff for fetch retries" --why "Easy to reason about for the gateway client"` | exit 0; line 1 `^d-[0-9a-f]{8} decided$`; the row is in `$A1` |
| 3 | `$AWT --dir $GW doctor` | the quarantined count equals the baseline count from `$T/pre/awt` |
| 4 | Under f): repeat 1-2 | exit 0 both; step 2 still writes its row |

Proves R2 ("write first, lookup errors swallowed") and R1 robustness.

## 2. Live Paseo daemon journeys (tier daemon-gated)

All run in D0 in this order, sharing one daemon except where a restart is stated. `run(title, prompt)` and `settle()` as in `daemon.test.ts`. `node(id)` = the `list nodes --all --json` entry with key `paseo:agent/<id>`.

### E-R9 Plugin from the worktree, prompt block, env forwarding (R3, R4 config, R2)

| # | Step | Expected |
|---|---|---|
| 1 | `paseo plugin ls` (and `--json` if supported) | `awt\s+running`; if a source path is reported, its realpath is `$WT/paseo-plugin` |
| 2 | `id=run("env1", "RUN: env \| grep -E '^AWT_(RELATED\|DIR\|BY)=' \| sort")` | log contains `AWT_RELATED=2`, `AWT_BY=<id>`, `AWT_DIR=` under `$AWT_ROOT` |
| 3 | `paseo send <id> 'RUN: awt decide "Use fixed backoff for gateway calls" --why "simplest for the gateway client"'` | log contains `decided`, at most 2 `related:` lines, one naming `D_RULE` (cross-workspace, through the forwarded env) |
| 4 | Prompt block: find `[awt]` in the `session/new` params in `$T/wire.jsonl`; else in `paseo inspect <id> --json` | the block is ≤ 700 chars, contains `find --like`; contains `call awt_resume again` **iff** SPEC.md records the prompt-line path for R5; byte-identical for agents `env1` and a second agent `env2` (cache-stable). If neither source exposes the system prompt the step is **SKIP** (not pass) and the evidence is P2/T-R3b only |
| 5 | Stop daemon; start without `AWT_RELATED`; `run("env3", "RUN: env \| grep -c ^AWT_RELATED=")` | output `exit=1 0` (nothing invented; see Q8) |

### E-R10 A turn that records a decision gets one receipt with the right counts (R4)

| # | Step | Expected |
|---|---|---|
| 0 | Probe H2 on any agent | the chosen timeline path returns items; record which |
| 1 | `id=run("rec1", 'RUN: awt decide "Retry with full jitter" --why "Fixed backoff synchronised the clients" ; awt note "soak run queued"')`; `waitReceipts(id, 1)` | exactly 1 receipt; `version` 1; `data.node == node(id).name`; `counts.decision == 1`, `counts.note == 1`, `counts.state == 1` (the stand-in); every other count 0 or absent; `auto == true`; `empty == false`; `ids` ⊇ {decision id, note id} parsed from the log, `len ≤ 5`; the receipt comes after the turn's last `assistant_message` |
| 2 | The same counts equal `awt --dir <node> list --since <ts of the decision row> --down --json` grouped by `type` | equal |
| 3 | `paseo send id 'RUN: awt state --now "jitter merged" --next "soak"'` | 2 receipts total; the new one: `counts.state == 1`, `auto == false`; `list state --all --json` gained no `auto` row |
| 4 | `paseo send id 'RUN: for i in 1 2 3 4 5 6 7; do awt note "n$i"; done'` | 3 receipts; the new one `counts.note == 7`, `len(ids) == 5` |
| 5 | Count receipts vs turns for `rec1` | exactly one receipt per turn (3 = 3) |

### E-R11 A turn that stores nothing gets an empty receipt (R4)

| # | Step | Expected |
|---|---|---|
| 1 | `id=run("quiet", "ping")` | 1 receipt: `auto == true`, `counts.state == 1`, `empty == false` |
| 2 | `paseo send id "ping"` (same reply, so the CLI refuses the unchanged auto state) | 2nd receipt: `empty == true`, all counts 0, `ids == []`, `auto == false`; `list state --all --json` still has 1 row |

### E-R12 `AWT_RECEIPT=changes`, `AWT_RECEIPT=0`, and no stand-in (R4)

Each block: stop daemon, start with the env shown, new agent.

| Env | Steps | Expected |
|---|---|---|
| `AWT_RECEIPT=changes` | `run("chg","ping")`; `send "ping"` | after turn 1: 1 receipt; after turn 2 (nothing stored), wait 15 s: still 1 |
| `AWT_RECEIPT=0` | `run("off", 'RUN: awt note "silent"')` | 0 receipts after 15 s; the note row and an `auto` state exist in the node (only the UI item is off) |
| `AWT_AUTO_HANDOFF=0` (receipts on) | `run("noauto","ping")` | 1 receipt, `empty == true`, `auto == false` |

### E-R13 Receipts for a subagent, and the parent counts its descendants (R4)

| # | Step | Expected |
|---|---|---|
| 1 | `boss=run("boss", "RUN: paseo --home $H run --provider fake --workspace $W1 --title kid --label paseo.parent-agent-id=$AWT_BY 'RUN: awt note \"kid finding\"' >/dev/null; awt note \"boss done\"")` (`$H`, `$W1` substituted by the harness) | the kid node sits under the boss node (E3) |
| 2 | `waitReceipts(kid, 1)` | kid: `counts.note == 1`, `counts.state == 0` (subagents get no stand-in), `auto == false`, `data.node == node(kid).name` |
| 3 | `waitReceipts(boss, 1)` | boss: `counts.note == 2` (own + descendant), `ids` contains the kid's note id, `counts.state == 1`, `auto == true` |

Fallback if a nested `paseo run` inside a turn is refused or deadlocks (record which): start `boss` with `--no-wait` and prompt `RUN: sleep 15; awt note "boss done"`, and while it runs the harness itself starts `kid` with the parent label. Same expectations.

### E-R14 Receipts for canceled and failed turns (R4 "any outcome")

| # | Step | Expected |
|---|---|---|
| 1 | `run --no-wait "cxl" 'RUN: awt note "before cancel"; sleep 30'`; poll the node until the note row exists; `paseo stop <id>` | 1 receipt within 15 s, `counts.note == 1`, `counts.state == 0` (no stand-in on non-completed turns) |
| 2 | `run("fail", 'FAIL: awt note "before fail"')` (H4) | the turn's outcome is `failed` (probe and record); 1 receipt, `counts.note == 1` |

### E-R15 Receipts are not in the provider's input, ACP path (R4)

Pre: E-R10 to E-R14 done.

| # | Step | Expected |
|---|---|---|
| 1 | `grep -c -E 'awt\.receipt\|awt ·\|nothing stored this turn' $T/wire.jsonl` | `0` |
| 2 | `paseo daemon restart`; `paseo send <rec1> "ping"` (resume / `session/load` path); repeat step 1 | `0` |

Limit: an ACP agent keeps its own history, so this proves Paseo does not forward plugin items to ACP agents, not that the Claude provider omits them. E-R17 covers that.

### E-R16 Receipts render (R4 renderer, manual)

Pre: the Paseo app connected to the D0 daemon only (never the user's daemon), agents from E-R10/E-R11. Expected muted lines, exactly: `awt · 1 decision <id> · 1 note · handoff` (E-R10 turn 1, see Q5), `awt · handoff [auto]` (E-R11 turn 1), `awt · nothing stored this turn` (E-R11 turn 2); a receipt with `version: 2` injected through the client API shows no line and no error (P20 live). Evidence: one screenshot per line stored in the test run dir. Manual until Paseo offers a headless render hook (Q13).

## Daemon gaps

Daemon-tier journeys not fully covered by `paseo-plugin/test/daemon-recall.test.ts` (E-R9 to E-R15 and E-R22 pass there; run with `npm run test:daemon`).

| Journey | Why not covered | What would cover it |
|---|---|---|
| E-R16 (receipt rendering) | Needs the Paseo app attached to the temp daemon and screenshots; Paseo has no headless render hook (Q13). The test is a named skip. | A headless render hook in Paseo, or a manual run on the D0 daemon only. |
| E-R9 step 4 (prompt block) | Covered through `paseo inspect`-style agent snapshot metadata (`persistence.metadata.systemPrompt`) read via `@getpaseo/client`, not `$T/wire.jsonl`: ACP does not forward the system prompt, so the wire is asserted to carry no `[awt]`. | Nothing further for ACP; a Claude-provider run is E-R17. |
| E-R15 step 2 | The test restarts with `paseo daemon stop` then `start` (same env) rather than `daemon restart`; the resumed turn is asserted to reach the provider, not that `session/load` specifically was used. | Assert `session/load` in the wire once the fake agent supports it. |
| E-R15 (receipts of agents opened before a plugin restart) | Receipt caches live in the plugin process, so receipts for agents opened before a daemon restart are lost; the test uses a fresh agent. | A spec decision on whether receipts survive a restart. |

## 3. Agentic journeys (tier agentic-paid)

**Need owner approval before any run, including pilots.** Harness: `tests/agentic/run.py` (cold `claude -p`, `MODEL = claude-haiku-5-5`, sandboxed settings, ≤ 25 turns, 300 s, judged by scripts) with these additions: a tree setup (F1 minus the `metronome`/quillwort rows), a per-arm `cwd`/env/`--append-system-prompt`, and an `awt` shim first on `PATH` that appends its argv as one JSON line to `$T/argv.jsonl` (outside every node) and execs `$AWT`. Cost is recorded per session from `total_cost_usd`.

**Cost estimate** (tokens; convert with the price table current at run time, never from memory): one session ≈ 8-20 turns, 150k-500k input tokens (mostly cache reads), ≤ 10k output. Batch sizes below: E-R17 ≈ 8 sessions, E-R18 30, E-R19 20; total ≈ 58 sessions. Run 1 pilot session per journey first, report its measured cost, then ask before the batch.

### E-R17 Claude provider: receipts not in input, context after compaction (R4, R5)

Pre: D0 with the Claude provider enabled; daemon env `CLAUDE_CONFIG_DIR=$T/claude` (fresh, never the real `~/.claude`) and authentication supplied by the owner through an environment variable at run time (never written to a file; check for a pending macOS SecurityAgent prompt before starting). Preferred observation: `ANTHROPIC_BASE_URL=http://127.0.0.1:<port>` pointing at a local recording proxy that forwards to the API and writes request bodies to `$T/requests/`. Fallback: the session transcript `$T/claude/projects/*/*.jsonl`.

| # | Step | Expected |
|---|---|---|
| 1 | `cc=paseo run --provider claude --model <cheapest Claude model> --workspace W1 --title cc1 'Run the shell command  awt note "cc probe"  and reply DONE'` | 1 receipt, `counts.note == 1` |
| 2 | `paseo send cc1 "Reply with the word NEXT"` | 2 receipts |
| 3 | grep `$T/requests/` (or transcript) for `awt.receipt\|awt ·\|nothing stored` | 0 matches. A match fails the journey and, per R4, flips the default to off |
| 4 | `paseo send cc1 "/compact"` | a `compaction` timeline item with `status: completed` |
| 5a | **Native-hook path** (if SPEC.md records it): request body / transcript after the compaction boundary | contains the brief header of `cc1`'s node (`# awt` brief first line) from a `SessionStart` hook; deterministic: 3/3 runs |
| 5b | **Prompt-line path** (if SPEC.md records it): `paseo send cc1 "Continue with the task"` | a tool call to `awt_resume` appears after the compaction item, before any other write to the node; ≥ 4/5 runs |

Both 5a and 5b are written; the one SPEC.md does not state is skipped with a reason. If SPEC.md states neither, the journey fails (R5 requires the outcome recorded either way).

### E-R18 Does an agent check related records before deciding? (R3, R1)

Scenario `recall-before-decide`. Prompt (identical for all arms): "Pick the retry policy for the parsekit fetch client's gateway calls and record it with awt decide. Then record a handoff." It never mentions other workspaces.

| Arm | Setup | Runs |
|---|---|---|
| A: AGENTS.md | `cwd=$RB` (task node, new template), no `AWT_DIR` | 10 |
| B: prompt block only | `cwd=$T/repo/parsekit` (no AGENTS.md), `AWT_DIR=$A1`, `--append-system-prompt "<static block from the built plugin>"` | 10 |
| C: control | arm B with the pre-feature block (`a35fea8`) and `AWT_RELATED=0` | 10 |

Rubric per run, from files only:
- **U** = 1 if `argv.jsonl` has a `find` call with `--like` before the first `decide` call; **U′** = 1 for `find --tree <term>` instead (reported, not passing).
- **C** = 1 if the new current decision's choice contains `jitter` (case-insensitive) and does not match `fixed\s+(\d+\s*s\s+)?backoff`.
- **R** = 1 if the decision's `why`, or a note/ref written in the run, contains `D_RULE`'s id or `ledgerline`.
- Hard fail: any edit under `.awt/` (raw-line diff), or a write outside the agent's node.

Pass: arms A and B each have U = 1 in ≥ 8/10 and C = 1 in ≥ 9/10 runs, and no hard fail. Arm C is reported (lift = A/B minus C on U and C), not gating. Infra failures (timeout, harness) are rerun, not scored; more than 2 infra failures in an arm voids the arm.

### E-R19 Does an agent read `related:` lines and change course on a conflict? (R2)

Scenario `recall-conflict`. Arm B setup. Prompt: "Record this decision: fixed 1 s backoff for the fetch client's gateway retries, why: easy to reason about. Then record a handoff."

| Arm | Runs |
|---|---|
| T: treatment (`AWT_RELATED` unset, default 3) | 10 |
| K: control (`AWT_RELATED=0`) | 10 |

Rubric per run, from files: the first `decide` writes NEW (expected: the agent does as told; its output lists `D_RULE`). Then **S** = 1 if a later decision supersedes NEW and contains `jitter`; **F** = 1 if a later `ask`, `note` or `state` contains `D_RULE`'s id, `ledgerline`, `jitter` or `conflict`. Course change = S ∨ F. Hard fail as E-R18.

Pass: T has course change in ≥ 7/10 runs and no hard fail. K is reported for lift. Report S and F rates separately.

## 4. Upgrade journeys (tier cli)

### E-R20 A tree written by v0.2.0 works unchanged; auto states never surface (R1, R2, I8)

Pre: binaries via read-only `git show`: `v0.2.0:awt`, `v0.2.0:migrate-paseo` → `$T/v020/`; `a35fea8:awt` (last pre-feature commit) → `$T/pre/awt`. Auto states first shipped after v0.2.0 (CHANGELOG Unreleased), so they are written as plain `state --scope auto` rows, exactly what the pre-feature plugin writes.

Build with `$T/v020` only: `init --kind root`; `migrate-paseo $R --from $T/snap.json`, a fictional snapshot in the format of `tests/test_migrate_paseo.py` (project `prj_0001` parsekit; workspaces `wks_0001` parsekit active, `wks_0002` ledgerline archived; agents `agt_0001` archived, `agt_0002` in `wks_0002`, `agt_0003` subagent of `agt_0001`), so `done` nodes exist; then in the imported nodes: one `rule` decision, one question + answer, two notes, a main state per workspace, and in `agt_0001` and `agt_0002` nodes `state --scope auto --now "[auto] exit=0 quillwort sweep" --next -` (assert exit 0; if v0.2.0 refuses, write them with `$T/pre/awt` and record that). Also a standalone task dir `$T/solo` (plain `init`, records of each type).

| # | Step | Expected |
|---|---|---|
| 1 | For every node and `$T/solo`: `resume`, `resume --json`, `list nodes --all --json`, `list <section> --json`, `find --tree quillwort`, `doctor` with `$T/pre/awt` and with `$AWT` | byte-identical outputs (I8); `doctor` shows `0 quarantined` |
| 2 | `$T/solo`: `resume` with `$T/v020/awt` vs `$AWT` | byte-identical |
| 3 | `cd $R; $AWT find --like quillwort` | `no related records`, exit 0 |
| 4 | `AWT_DIR=<agt_0002 node> $AWT decide "Quillwort sweep cadence" --why "quillwort runs nightly"` | exactly 1 line (`decided`), no `related:` |
| 5 | `find --like "<words of the rule decision>"` from the root | the rule decision appears (records in `done` nodes are candidates, as in `--tree`; see Q12) |
| 6 | U2 for steps 1-3, 5; step 4 adds exactly one row | holds |
| 7 | `list --since <oldest ts> --down --json` on the root | auto rows appear with `scope: "auto"` (receipts can count them; only `find --like` and related lists exclude them) |

### E-R21 Distribution stays stdlib (constraint change)

| # | Step | Expected |
|---|---|---|
| 1 | `python3 -I -S $AWT --help` and E-R1 step 3 under `python3 -I -S $AWT` | exit 0, same stdout as without `-I -S` |
| 2 | If `python3.9` is on `PATH`: E-R1 and E-R3 under it | same results |

### E-R22 Plugin upgrade over an existing daemon tree (R4, daemon-gated)

Pre: D0 started with the plugin built from `a35fea8` (`git show` into `$T/oldplugin`, `npm ci`), one agent `old1` with a turn; then `paseo plugin install $WT/paseo-plugin`, daemon restart.

| # | Step | Expected |
|---|---|---|
| 1 | `paseo send old1 'RUN: awt note "after upgrade"'` | same node (no duplicate key, E4); 1 receipt for this turn with `counts.note == 1`; no receipt for pre-upgrade turns |
| 2 | `doctor` on the root | `0 quarantined`; no `fail` |

## 5. Traceability

| Requirement | Journeys | Unit coverage beside them |
|---|---|---|
| R1 words, candidates, superseded/auto exclusion | E-R1, E-R2, E-R20 | T-R1a, T-R1b |
| R1 score, rule boost, ties | E-R1, E-R5 | T-R1a, T-R1d |
| R1 scope, prefixes, caps | E-R1, E-R2, E-R7, E-R8 | T-R1c, T-R1g |
| R1 output, limit, no hits, TERM conflict | E-R1, E-R2 | T-R1e, T-R1f |
| R2 related after decide/ask, self excluded | E-R3, E-R4, E-R9 | T-R2a, T-R2d |
| R2 N precedence and errors | E-R5, E-R9 | T-R2b, T-R2c |
| R2 write first, errors swallowed, 2 s stop | E-R7, E-R8 | T-R2e, T-R2f |
| R3 template / prompt block pointer, ≤700 | E-R9, E-R18 | T-R3a, T-R3b, P2 |
| R3 agents actually use it | E-R18, E-R19 | none |
| R4 `list --since --down --json` | E-R6, E-R10 | T-R4a |
| R4 receipt contents, one per turn | E-R10, E-R11, E-R14 | P15, P16, P17 |
| R4 subagents | E-R13 | P15 |
| R4 `AWT_RECEIPT` | E-R12 | P16 |
| R4 renderer | E-R16 | P20 |
| R4 not seen by the model | E-R15, E-R17 | none |
| R4 append failure harmless | (unit only) | P18 |
| R4 `AWT_RELATED` forwarded | E-R9 | P19 |
| R5 compaction | E-R17 | T-R5a |
| Distribution | E-R21 | none |
| Upgrade / I8 | E-R20, E-R22 | I8 suite |

## 5a. CLI-tier coverage and gaps

All CLI journeys (E-R1 to E-R8, E-R20, E-R21) have a test in `tests/test_e2e_recall.py`. Run it with `python3 -m unittest discover -s tests -p test_e2e_recall.py`. Daemon-gated (E-R9 to E-R16, E-R22) and agentic (E-R17 to E-R19) journeys are outside this file.

Gaps and partial coverage:

| Journey | Why not covered | What would cover it |
|---|---|---|
| E-R7 (default run) | The 2,000-descendant tree takes minutes to build, so the test is skipped unless `AWT_E2E_SLOW=1` (it passes with it; a cached tree makes reruns ~17 s) | Run it in `chaos-full` CI with `AWT_E2E_SLOW=1` |
| E-R8 b), f) | `chmod 000` has no effect for uid 0 | Run as a non-root user (the sub-checks run automatically then) |
| E-R21 step 2 | Runs only if `python3.9` is on `PATH` | Add python3.9 to the CI image |
| E-R1 step 8, E-R4 step 3 | Compared after the 200-char cut because temp paths are long; the "ends with `Ten seconds`" form is not asserted | None needed |
| U3 (nothing outside `$T` changes) | Not checked directly; each test uses a private HOME and temp dir | A before/after snapshot of a sentinel HOME |

## 6. Open questions (untestable or ambiguous in the feature spec)

1. **Tokenizer and punctuation.** `[a-z0-9][a-z0-9_./-]+` keeps a trailing `.` or `/`: `gateway.` and `gateway` would be different words, so sentence-final words stop matching. Strip trailing `./-`? (Fixtures here avoid trailing periods until this is decided.)
2. **Stopword list** is "about 80" and unpublished, so no test can predict hits for common words. Publish it (SPEC or a test-visible constant).
3. **Line format for rows without an id** (refs, states) in `find --like` and `related:` lines, and for hits in the current node (the R1 example always shows `@`; the existing rule prints no prefix).
4. **Receipt `ids`:** which 5 (first, newest, by type priority?); refs and states have no id.
5. **Receipt `auto`:** "the only state written was the stand-in" vs "the only row"; the first renderer example (`· handoff` without `[auto]`) suggests a stand-in plus other rows renders as plain `handoff`. Which?
6. **Receipt `counts`:** zero types present or omitted; are `node` rows (a subagent created during the turn), quarantined rows and plugin-written rows other than the stand-in (parent notes and refs) counted?
7. **Turn start** is taken on which clock and with what resolution, and do parent and child receipts double-count rows by design?
8. **`AWT_RELATED` forwarding** when the daemon has none (omit vs set 3), and when the daemon value is invalid (forward verbatim, so every `decide` warns, or drop with a log line).
9. **`AWT_RECEIPT` values** other than unset, `0`, `changes` (e.g. `off`, `1`). And with `changes`, does a turn whose only write is the stand-in count as a change? With the default stand-in on, that is nearly every turn.
10. **`nothing stored this turn` is rare by default**: with `AWT_AUTO_HANDOFF` on, a quiet turn usually stores the stand-in. Is the receipt still answering "was anything stored" as intended?
11. **`list --since`:** section allowed/required? `--since` without `--json`? timezone offsets other than `Z`? row order? the `node` value format and whether the node's own rows carry it?
12. **Lifecycle filters:** are records in `done`/`paused` nodes candidates for `--like` and `related:`? (E-R20 assumes yes, like `--tree`.)
13. **Renderer is not testable headless** on Paseo 0.15.4; is the manual E-R16 the accepted proof for "receipts render"?
14. **The 2 s stop line:** stdout or stderr, and are hits found before the stop printed? Real-time triggering is not reproducible e2e (T-R2f simulates).
15. **Unreadable nodes during `find --like`:** silent skip or a stderr warning, and exit 0?
16. **"Not seen by the model"** is only meaningful for providers whose history Paseo replays. E-R17 needs real tokens and either a recording proxy or transcript inspection; which counts as the proof, and is the proxy acceptable?
17. **R5 for subagents:** subagents skip resume, so should the native compaction hook (or the prompt line) apply to them?
18. **200-char cut:** does it include the `related: ` prefix in `decide`/`ask` output, and is it chars or bytes?
19. **v0.2.0 has no auto states** (they arrived after it), so "a v0.2.0 tree with auto states" is a v0.2.0 tree plus pre-feature plugin rows; E-R20 builds it that way.
20. **`--limit` without `--like`:** usage error or ignored?
21. **`data.node`** is the node's name or its path? (Names are not unique across the tree.)
22. **Is a row's own `id` part of its candidate text?** R1 keeps ids as words in TEXT but does not say whether candidates are matched on their own id.

## Resolutions (orchestrator, 2026-11-12)

These settle the open questions above. They have been sent to the implementation, and `SPEC.md` is authoritative once the build lands. When this document and `SPEC.md` disagree, `SPEC.md` wins.

1. **Tokens.** Leading and trailing `.`, `/`, `-` and `_` are stripped from each token, so `gateway.` matches `gateway`. The stopword list is a published constant in `awt`.
2. **Hit line format.** `<id or type> <@node, omitted for the current node> [rule]: text`. Refs and states, which have no id, use their row type. The 200-char cut counts the whole line, including `related: `, in characters.
3. **Candidates.** A record never matches itself. Records in `done` and `paused` nodes are candidates.
4. **Usage errors.** `--limit` without `--like` exits 2.
5. **The 2 s stop.** Hits found so far are printed, then the stop line, all on stdout. Unreadable or corrupt nodes are skipped silently.
6. **`list --since`.**
   - It requires `--json` and accepts no section argument.
   - It accepts ISO 8601 times with `Z` or an offset.
   - Rows come in ascending `ts` order.
   - With `--down`, `node` is the path relative to the queried node; the queried node's own rows have `node: null`.
7. **Receipt.**
   - `counts` includes only types with a non-zero count.
   - `node` rows, and rows the plugin writes other than the auto state, are not counted.
   - `ids` holds the first 5 by `ts`.
   - `auto` is true when the stand-in handoff was written during the turn.
   - `data.node` is the node's name.
   - The turn's start is the plugin's existing turn-start timestamp.
   - `AWT_RECEIPT=changes` hides receipts whose only row is the auto state.
   - An unknown `AWT_RECEIPT` value means on, with one warning logged.
   - A subagent's row appears in both its own receipt and its parent's. This is intended.
8. **`AWT_RELATED`.** It is forwarded only when set in the daemon's environment, and as is; `awt` validates it.
9. **Compaction.** The compaction line or hook applies to non-subagent agents only.
