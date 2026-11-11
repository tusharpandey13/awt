# awt

Turn one directory into a workspace where an AI agent can find everything about a task, pick up where the last session stopped, and never send something twice.

`awt` is one Python file. There is nothing to install, no service and no dependency beyond Python 3.9.

## Setup

In the directory for your task:

```sh
curl -fsSLO https://raw.githubusercontent.com/tusharpandey13/awt/main/awt && chmod +x awt
./awt init --goal "Ship the parser rewrite" --done "Merged, announced, ticket closed"
```

That adds an `AGENTS.md` and a `README.md`. Existing files are never overwritten: an existing `AGENTS.md` gets a marked block appended. Start your agent in the directory; it reads `AGENTS.md` and takes it from there.

Run `./awt doctor` to check the setup. It warns about the one common trap: a `CLAUDE.md` in the directory or a parent can stop Claude Code reading `AGENTS.md`. The fix is to add the line `@AGENTS.md` to that file.

## What goes where

| Directory | Holds |
|---|---|
| `context/` | Inbound material that can't be linked: pasted Slack threads, meeting notes, research |
| `docs/` | Working docs: plans, ADRs, results |
| `outbox/` | Drafts going out: Slack messages, PR comments, Jira updates, docs to publish |
| `misc/` | Anything else worth keeping |
| `scratch/` | Throwaway work, ignored by git |

Drop files in by hand whenever you like. Agents find them with `./awt list` and `./awt find <term>` with no registration step.

Links are preferred over copies. `./awt ref <url> --title "..."` records a link, and `--no-access` marks one the agent can't open, so it knows to ask you to paste it instead.

## Using it

You mostly talk to your agent. These are the commands you'll use yourself:

```sh
./awt resume                # where things stand
./awt list                  # everything known about this task
./awt find "rate limit"     # search all of it
./awt effect mark e-1a2b3c4d sent   # you sent something from outbox/
```

`./awt help` lists the rest. [docs/guide.md](docs/guide.md) walks through a full task, sending messages, and troubleshooting.

## How it works

- **One record file.** Decisions, questions, links and handoffs go through `./awt` into an append-only `.awt/events.jsonl`. The tool refuses malformed input on the way in, and a corrupt line is skipped and counted rather than breaking anything.
- **Skipped handoffs are visible.** The resume brief shows the files and commits changed since the last handoff, so the next session sees what happened even if the last one recorded nothing.
- **The brief has a fixed size.** It stays under 4,400 characters however large the task grows (5,200 for a node in a tree, see below). Everything else is one `./awt find` away.
- **Outbound work is recorded before it runs.** Each effect can only be claimed once. A send that times out becomes `unknown`, and is never retried automatically, because it may have gone through.
- **Parallel agents are safe.** Writes are single atomic appends, with no locks to go stale.

## Tasks with parts: the node tree

When a task has parts, give them a place instead of one huge directory or a pile of unconnected ones. A node is a directory with `.awt/`; its parent is the nearest enclosing node.

```sh
mkdir ~/awt-root && cd ~/awt-root && awt init --kind root
awt init --kind workspace --name parsekit
cd workspaces/parsekit && awt init --kind task --name retry-bug --goal "Fix the retry storm" --done "Merged"
cd tasks/retry-bug && awt init --kind agent --name chat-1
awt list tree
```

`resume` in a node shows its ancestors' goals and `rule` decisions and a one-line rollup of its children. `awt find --tree TERM` searches up and down. Agents run anywhere with `AWT_DIR` set to their node. The full contract is in [SPEC.md](SPEC.md#node-tree).

## Big tasks and cost

Long tasks get expensive when one big agent holds everything: every turn re-reads the whole context, and any wait over the cache lifetime rewrites it. The optional `relay` script avoids that by keeping no big agent alive.

```sh
curl -fsSLO https://raw.githubusercontent.com/tusharpandey13/awt/main/relay && chmod +x relay
```

Ask your agent to split the work. It writes a plan, and you run it:

```sh
./relay run docs/relay.plan.json
```

Each unit is a fresh `claude -p` session that starts from `./awt resume --scope <unit>` and reads only the files it needs. Units run in dependency order, in parallel where possible. A failed test retries once at higher effort, then blocks only the units that depend on it. Run it again after a fix or a plan edit, and finished units are skipped. Workers can't approve a send, so that stays with you. `./relay help` has the plan format.

The tradeoff is lost context between workers: each knows only what the files say. Work that needs one mind, such as a hard debugging session, should stay in one session.

Workers run with the tools in the plan and no sandbox unless the plan's `settings` turns it on, so give them only what they need.

## Limits

- **It stops accidents, not a determined agent.** The `ask` rule that makes Claude Code prompt before `./awt effect apply` comes from `.claude/settings.json`, and Claude Code matches on command text. An agent that runs a script or `bash -c` isn't stopped by it, and neither is one in a tool that doesn't read that file. If an agent holds credentials to anything high-stakes, also use your harness's OS sandbox.
- **It can't record what an agent never mentions.** A decision made in chat and never written down stays in chat.
- **Secret scanning is pattern-based.** It catches common token formats and will miss others.
- **Use a local disk.** Atomic appends aren't guaranteed on network drives or synced folders, and `./awt doctor` warns about them.

## Keep task data private

A task directory often holds internal chats and documents. `./awt save "message"` commits it locally and never pushes. If you add a remote, make sure it is private. `./awt doctor` warns when a remote exists.

## Migrating from wt

If you have a `wt` tracker or task directory:

```sh
git clone https://github.com/tusharpandey13/awt.git
awt/migrate-wt --dry-run ~/work ~/work-awt   # shows the plan
awt/migrate-wt ~/work ~/work-awt
```

Your old directory is only read. The new one must be empty or absent. Each file is either copied or listed with a reason in `legacy/MIGRATION.md`, along with problems found in the old records, such as duplicate decision ids. The run fails if any file is unaccounted for.

## Contributing

[SPEC.md](SPEC.md) is the contract. To run the tests:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/chaos.py
python3 tests/agentic/run.py   # real haiku agents; uses your Claude Code account
```

## License

MIT
