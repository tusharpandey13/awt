# ADR 0002: awt never executes commands

Status: proposed (phase 0 of ARCHITECTURE-v2). Scores below are the author's; the process in ARCHITECTURE-v2 section 9 (two independent reviews, then the owner) still applies.

## Context

Until now an effect could carry a command (`--run`). `awt effect apply ID` ran it under `sh -c`, with an optional snapshot and verify, logs in `.awt/runs/` and blobs in `.awt/blobs/`. To keep that safe, `init` wrote an `ask` rule into `.claude/settings.json` so Claude Code would prompt before `awt effect apply`.

That design has three problems:

1. The host sees `awt effect apply <id>`, never the command that goes out. Its permission system (Claude Code rules and auto mode, opencode permissions, Paseo permission hooks) cannot judge what it cannot see. The `ask` rule matches command text, so a script or `bash -c` around it is not stopped.
2. awt becomes a second executor: pid-based claims, timeouts with a 30 s margin, a `conflict` state, process-group kills, snapshots. All of that is code that exists only to supervise a process awt should not own.
3. The agent prompt has to teach an outbox/plan/apply protocol, which every agent pays for whether or not it sends anything.

A branch (`7b25143`, "action policy") fixed the gate by adding a shell classifier, option tables, CIDR tables and an allowance grammar inside awt: a weaker copy of the host's permission system that needs upkeep with every CLI release. It is not merged.

## Decision

awt keeps the effect ledger and never executes anything. The sender (agent or person) sends with their own tools, so the host's permission check sees the real command.

- Verbs: `effect plan --target T [--body FILE] [--how TEXT] [--after ID]... [--again] [--why T]`, `effect begin ID`, `effect mark ID sent [--ref URL] | not-sent --why T | unknown --why T | dropped`, `effect show ID`.
- State machine: `planned -begin-> begun -> sent | planned (attempt+1) | unknown`; `unknown -> sent | not-sent`; `planned -> dropped`; and `planned -> sent` for a person who sent it without `begin` (decision 8).
- `begin` claims `.awt/claims/<key>.<attempt>` with `O_EXCL`; losing exits 1. `--how` is text, never run, not in the key.
- A `begun` effect never times out and blocks `status done`: only the sender knows what happened. A crash after `begin` leaves `begun`, never retried, shown to a person.
- Removed: `effect apply`, `--run`, `--snapshot`, `--verify`, `--class`, `--timeout`, writes to `.awt/runs/` and `.awt/blobs/`, the `ask` rule in the settings template, and the outbox/plan/apply paragraph of the agent prompt. Removed verbs and flags exit 2 with a `fix:` naming plan, begin and mark.
- Old trees: `claimed` reads as `begun`; `run` shows as `how`; `class`, `snapshot`, `verify` show as legacy fields; `events.jsonl` is never rewritten and `runs/` and `blobs/` are never deleted. `doctor` warns, with the exact lines, about an old `ask` rule and never edits the file.

Detection of sends by host hooks (so agents declare nothing) is a later phase; this ADR covers the declared ledger only.

## Alternatives

- **Keep `apply`, add a policy layer (branch 7b25143).** Rejected: a second, weaker permission system, static shell parsing that can be bypassed, and the host still never sees the real command.
- **Keep `apply`, keep the `ask` rule.** Rejected: the prompt shows the id, not the command; matching is by text.
- **Remove the ledger entirely.** Rejected: de-duplicating and never retrying a send that may have gone out is a real need, and costs only a few rows.
- **Time out `begun` into `unknown`.** Rejected: without a process awt owns, a clock proves nothing, and a wrong guess either blocks a finished send or invites a duplicate.

## Consequences

- Net code shrinks: the executor, pid liveness, snapshot and verify handling and the `conflict` state go; the verbs are four short functions.
- Lost: awt no longer holds the claim during the run by pid and cannot verify a send. Verification is the sender's job, recorded with `mark sent --ref`. An `overwrite` send that needs the prior state saved: save it into `context/` first and name it in `--why`.
- Gained: the host's own gate sees the real command; the prompt shrinks; no subprocess is reachable from an effect verb (tested statically and with canary files).
- Risk: a `begun` effect forgotten by its sender blocks `status done` until someone marks it. That is deliberate and visible in the brief and in `doctor`.
- Honest limit: awt does not protect against a send nobody declares; it labels and de-duplicates. It never decides whether anything runs.
- Compatibility: while a replayed log has a claim file for the current attempt, a forged or old row could be replayed order-blind (the crash-gap rule). Rows are still checked against the transition table and quarantined otherwise.

## Rubric (ARCHITECTURE-v2 section 9, 0-2 each)

| Criterion | Score | Why |
|---|---|---|
| Necessity | 2 | Serves the job statement (never send twice) for the owner's agents |
| Layer fit | 2 | Ledger in awt; execution in the host |
| Host-native first | 2 | Uses the host's permission system for the real command |
| Buy before build | 2 | Builds nothing that exists; removes what duplicated it |
| Agent abstraction cost | 1 | The declared path is an optional verb set; ordinary sends need none |
| Agent ergonomics | 2 | One call per step, fixed output, `fix:` on every refusal |
| Human visibility | 2 | `begun` and `unknown` show in the brief; `show` prints history, `how`, legacy fields |
| Failure semantics | 2 | A crash leaves `begun`, never retried; marks are legal only as drawn |
| Data quality | 1 | Rows carry ts, host, by, attempt; no source offset yet |
| Complexity cost | 2 | Removes code and a state (`conflict`) |
| Honest security | 2 | States that it labels and de-duplicates, not protects |

Total 20 of 22. No zeros. The two 1s: the declared path is optional vocabulary for agents, and effect rows have no adapter provenance until detection lands.
