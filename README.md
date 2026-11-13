# awt

**A memory for your AI agents that lives in plain files.**

Every new agent session starts cold. It doesn't know what was decided yesterday, which question is still open, or whether that Slack message already went out. `awt` turns a directory into a workspace where an agent can find all of that with one command, carry on where the last session stopped, and never send the same thing twice.

- **One file, no dependencies.** A single Python 3.9 script. No server, no database, no account.
- **Works with any agent** that reads `AGENTS.md` and runs shell commands: Claude Code, Codex, opencode and others.
- **Safe outbound work.** Messages, comments and updates are recorded before they go out, can be claimed only once, and are never silently retried.
- **Scales with the task.** A small brief for a small task, and a tree of workspaces, tasks and agents for a big one.
- **Plugs into Paseo.** One plugin gives every Paseo workspace and agent its own place in the tree, automatically.

## Quick start

```sh
curl -fsSLO https://github.com/tusharpandey13/awt/releases/latest/download/awt && chmod +x awt
./awt init --goal "Ship the parser rewrite" --done "Merged, announced, ticket closed"
./awt doctor
```

Now start your agent in that directory. `init` wrote an `AGENTS.md` that tells it what to do: run `./awt resume`, do the work, record what matters, and leave a handoff.

Existing files are never overwritten. If the directory already has an `AGENTS.md`, a marked block is appended to it. `./awt doctor` warns about the one common trap: a `CLAUDE.md` in the directory or a parent can stop Claude Code reading `AGENTS.md`. The fix is to add the line `@AGENTS.md` to that file.

Want `awt` on your `PATH`, checksums, or the Paseo plugin? [AGENTS.md](AGENTS.md) is the full install and usage guide. Hand it to your agent and it can set everything up.

## What a session looks like

```sh
./awt resume                         # the brief: goal, state, open questions, changes since the last handoff
./awt find "rate limit"              # is it already known?
./awt decide "Retry with jitter" --why "Fixed backoff synchronised the clients"
./awt ask "Is the 30 s timeout a hard limit?"
./awt state --now "Jitter patch in review" --next "Load test once CI is green"
```

You mostly talk to your agent. The commands you'll use yourself:

```sh
./awt resume                        # where things stand
./awt list                          # everything known about this task
./awt effect mark e-1a2b3c4d sent   # you sent something from outbox/
```

`./awt help` lists every verb. [docs/guide.md](docs/guide.md) walks through a full task, sending messages, and troubleshooting.

## What goes where

| Directory | Holds |
|---|---|
| `context/` | Inbound material that can't be linked: pasted Slack threads, meeting notes, research |
| `docs/` | Working docs: plans, ADRs, results |
| `outbox/` | Drafts going out: Slack messages, PR comments, Jira updates, docs to publish |
| `misc/` | Anything else worth keeping |
| `scratch/` | Throwaway work, ignored by git |

Drop files in by hand whenever you like. Agents find them with `./awt list` and `./awt find <term>`, with no registration step.

Links beat copies. `./awt ref <url> --title "..."` records a link, and `--no-access` marks one the agent can't open, so it knows to ask you to paste it.

## Why it holds up

- **One append-only record.** Decisions, questions, links and handoffs go through `./awt` into `.awt/events.jsonl`. Malformed input is refused on the way in, and a corrupt line is skipped and counted rather than breaking anything.
- **Skipped handoffs still show.** The brief lists the files and commits changed since the last handoff, so the next session sees what happened even if the last one recorded nothing.
- **The brief has a fixed size.** It stays under 4,400 characters however large the task grows (5,200 for a node in a tree). Everything else is one `./awt find` away.
- **Outbound work is recorded before it runs.** Each effect can be claimed only once. A send that times out becomes `unknown` and is never retried automatically, because it may have gone through.
- **Parallel agents are safe.** Every write is a single atomic append, with no locks to go stale.

## Big work: the node tree

When a task has parts, give each part a place instead of one huge directory or a pile of unconnected ones. A node is a directory with `.awt/`, and its parent is the nearest enclosing node.

```sh
mkdir ~/awt-root && cd ~/awt-root && awt init --kind root
awt init --kind workspace --name parsekit
cd workspaces/parsekit && awt init --kind task --name retry-bug --goal "Fix the retry storm" --done "Merged"
cd tasks/retry-bug && awt init --kind agent --name chat-1
awt list tree
```

`resume` in a node shows its ancestors' goals and `rule` decisions, plus a one-line rollup of its children. `awt find --up TERM` and `awt find --down TERM` search ancestors or descendants, and `awt find --tree TERM` searches the whole tree under the nearest root. `awt find --like "a sentence"` ranks related decisions, answers and notes from every workspace, and `decide` and `ask` print up to three `related:` records after they write (`--related N` or `AWT_RELATED` changes the number, 0 turns it off). An agent can run anywhere with `AWT_DIR` set to its node. The full contract is in [SPEC.md](SPEC.md#node-tree).

## Paseo

If you use Paseo, the `awt` plugin builds and maintains the tree for you:

- a workspace node per Paseo workspace, with a `main` task in each;
- an agent node per agent chat, with subagents nested under their parent agent;
- `AWT_DIR` in every agent's environment, plus an `awt_resume` tool, and a short prompt block that points agents at `awt find --like` and tells them to call `awt_resume` again after compaction;
- when an agent ends a turn without a handoff, its last reply is kept as a state in scope `auto` (no message in the chat, no extra model turn). An optional follow-up prompt is available with `AWT_NUDGE=1`, off by default;
- after every turn, one muted line in the chat shows what is stored in awt (`awt · 1 decision d-... · handoff`, or `nothing stored this turn`). `AWT_RECEIPT=changes` hides the empty ones, `0` turns it off;
- archived agents and workspaces marked done, or paused when work is still open.

Put `awt` on the daemon's `PATH`, then (Paseo 0.15.4 or later):

```sh
paseo plugin install git:tusharpandey13/awt:paseo-plugin --ref v0.2.0
```

The tree lives at `${XDG_DATA_HOME:-~/.local/share}/awt`. Set `AWT_ROOT` in the daemon's environment to move it. To bring in your existing Paseo history, see [Import Paseo history](AGENTS.md#import-paseo-history). Plugin details: [paseo-plugin/OVERVIEW.md](paseo-plugin/OVERVIEW.md).

## Long tasks without a long bill

Long tasks get expensive when one big agent holds everything: every turn re-reads the whole context, and any wait longer than the cache lifetime rewrites it. The optional `relay` script avoids that by keeping no big agent alive.

```sh
curl -fsSLO https://github.com/tusharpandey13/awt/releases/latest/download/relay && chmod +x relay
./relay run docs/relay.plan.json
```

Ask your agent to split the work and write the plan, then run it yourself. Each unit is a fresh `claude -p` session that starts from `./awt resume --scope <unit>` and reads only the files it needs. Units run in dependency order, in parallel where possible. A failed check retries once at higher effort, then blocks only the units that depend on it. Run it again after a fix or a plan edit, and finished units are skipped. Workers can't approve a send, so that stays with you. `./relay help` has the plan format.

The tradeoff is lost context between workers: each knows only what the files say. Work that needs one mind, such as a hard debugging session, should stay in one session. Workers run with the tools in the plan and no sandbox unless the plan's `settings` turns it on, so give them only what they need.

## Limits

- **It stops accidents, not a determined agent.** The `ask` rule that makes Claude Code prompt before `./awt effect apply` comes from `.claude/settings.json`, and Claude Code matches on command text. An agent that runs a script or `bash -c` isn't stopped by it, and neither is one in a tool that doesn't read that file. If an agent holds credentials to anything high-stakes, also use your harness's OS sandbox.
- **It can't record what an agent never mentions.** A decision made in chat and never written down stays in chat.
- **Secret scanning is pattern-based.** It catches common token formats and will miss others.
- **Use a local disk.** Atomic appends aren't guaranteed on network drives or synced folders, and `./awt doctor` warns about them.

## Keep task data private

A task directory often holds internal chats and documents. `./awt save "message"` commits it locally and never pushes. If you add a remote, make sure it is private; `./awt doctor` warns when a remote exists.

## Migrating from wt

If you have a `wt` tracker or task directory, convert it with the one-off `migrate-wt` script. Your old directory is only read, and the run fails if any file is unaccounted for. The commands are in [Migrate from wt](AGENTS.md#migrate-from-wt).

## Contributing

[SPEC.md](SPEC.md) is the contract. The rules for changing this repository are in [AGENTS.md](AGENTS.md#working-on-this-repository). To run the tests:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/chaos.py
```

## License

MIT
