# awt: install and usage guide

This is the one page an agent (or a person) needs to install `awt`, set it up, and use it day to day. Read it top to bottom the first time. Every command here is safe to run as written unless it says to ask a person first.

Changing this repository rather than using the tool? Read [Working on this repository](#working-on-this-repository) at the end; those rules apply to you.

## Install the CLI

Needs Python 3.9 or later. `git` is optional; it powers `awt save` and the "changed since last handoff" part of the brief.

**On your `PATH`** (recommended when you have several tasks):

```sh
mkdir -p ~/.local/bin && cd ~/.local/bin
base=https://github.com/tusharpandey13/awt/releases/latest/download
curl -fsSLO "$base/awt" && curl -fsSLO "$base/SHA256SUMS"
shasum -a 256 -c SHA256SUMS --ignore-missing && rm SHA256SUMS
chmod +x awt
awt --version
```

If `awt --version` is not found, add `~/.local/bin` to `PATH` in the shell profile, and tell the person you did.

**Inside one task directory** (no install at all): download `awt` into the directory with the same `curl` line and call it as `./awt`. The rest of this guide writes `awt`; use `./awt` in that case.

**From a clone**, when you also want the migrators: `git clone https://github.com/tusharpandey13/awt.git`. The scripts `awt`, `relay`, `migrate-paseo` and `migrate-wt` sit at the top level.

To update, download again. Release notes are in [CHANGELOG.md](CHANGELOG.md).

## Set up a task

In the task's directory:

```sh
awt init --goal "Ship the parser rewrite" --done "Merged, announced, ticket closed"
awt doctor
```

- `init` never overwrites or deletes. An existing `AGENTS.md` gets a marked block appended; `.gitignore` gets missing lines appended; `.claude/settings.json` is created only if absent, otherwise `init` prints the snippet to merge.
- `doctor` prints `ok`, `warn` or `fail` per check. Fix every `fail` before working.
- The common `warn`: a `CLAUDE.md` in the directory or a parent can stop Claude Code reading `AGENTS.md`. Add the line `@AGENTS.md` to that `CLAUDE.md`.
- Do not run `init` in a directory that already has `.awt/` unless a person asks.

After `init`, the task's own `AGENTS.md` holds the working rules for agents in that task. They match "Work in a task" below.

## Work in a task

**Start of a session:** `awt resume`. It prints the goal, the current state, open questions and effects, and what changed since the last handoff. A subagent with a brief skips this and reads its brief.

**Before adding anything,** check it isn't known already: `awt find "term"` (exact), `awt find --like "a sentence"` (related records from the whole tree), or `awt list` for everything.

**While working,** record through the verbs, never by editing `.awt/`:

| You have | Run |
|---|---|
| A choice, with its reason | `awt decide "Retry with jitter" --why "Fixed backoff synchronised the clients"` |
| A choice every later agent must obey | `awt decide "..." --why "..." --tag rule` |
| A choice that replaces an earlier one | `awt decide "new" --why "r" --supersedes d-7f3a9c21` |
| A small fact for later | `awt note "CI takes 12 minutes"` |
| A question for a person | `awt ask "Is the 30 s timeout a hard limit?"` |
| The answer to one | `awt answer q-1a2b3c4d "Yes, set by the gateway"` |
| A link | `awt ref https://example.com/doc --title "Design doc"` (add `--no-access` if you can't open it) |
| Text that can't be linked | `awt capture --from slack --title "Retry thread" notes.txt` |
| A doc replaced by a better one | `awt supersede docs/old.md docs/new.md --why "r"` |

Long text goes in a file under `docs/`, with its path in the field.

**End of a session:** leave the handoff. This is the only handoff; don't write a `HANDOFF.md`.

```sh
awt state --now "Jitter patch in review" --next "Load test once CI is green"
```

**Task finished:** `awt status done`. It is refused while questions or effects are open, and it lists them.

**Sending anything outward** (Slack, PR comments, Jira, email): you send with your own tools; the tool never runs the command. Where a blind retry would be costly, declare the send first. Draft it in `outbox/`, then:

```sh
awt effect plan --target "slack:#eng" --body outbox/release-note.md --how "slack-cli post ..."
awt effect begin e-3c91d0aa        # claims it
# send it with your own tools
awt effect mark e-3c91d0aa sent --ref https://example.slack.com/archives/C1/p1
```

`--how` is only text. A failed send: `mark ... not-sent --why "..."`. Unsure: `mark ... unknown --why "..."`. A `begun` effect blocks `status done` until it is marked. If an effect is `unknown`, it may already have gone out: run `awt effect show <id>`, tell a person, and wait. Never resend it.

**Committing:** `awt save "message"` commits the task directory locally and never pushes. Run it only when a person asks.

The full lookup table, every refusal and what to do about it, and the subagent rules are in `awt help agents`.

## Big work: the node tree

When a task has parts, make it a tree. A node is a directory with `.awt/`, and its parent is the nearest enclosing node.

```sh
mkdir ~/awt-root && cd ~/awt-root && awt init --kind root
awt init --kind workspace --name parsekit
cd workspaces/parsekit && awt init --kind task --name retry-bug --goal "Fix the retry storm" --done "Merged"
cd tasks/retry-bug && awt init --kind agent --name chat-1
awt list tree
```

- `resume` in a node adds its ancestors' goals and `rule` decisions, and a rollup of its children.
- Search the tree with `awt find --up TERM` (ancestors), `awt find --down TERM` (descendants) or `awt find --tree TERM` (everything under the nearest root).
- An agent whose working directory is elsewhere, such as its repo, sets `AWT_DIR` to its node. Every `awt` command then reads and writes that node.
- `status done` is refused while a descendant has open work.

The contract is [SPEC.md](SPEC.md#node-tree).

## Paseo plugin

The plugin keeps one tree for everything in Paseo: a workspace node per Paseo workspace with a `main` task, an agent node per agent chat, and subagents under their parent agent. Each agent gets `AWT_DIR` and `AWT_BY` in its environment, an `awt_resume` tool and a short instruction block. Archiving marks nodes done, or paused when work is open. If `awt` fails, the agent starts without it; the plugin never blocks an agent.

Install, on the machine running the Paseo daemon (Paseo 0.15.4 or later):

1. Install the CLI (above) somewhere on the daemon's `PATH`, or set `AWT_BIN` to its full path in the daemon's environment.
2. Install the plugin. This trusts and runs its code inside the daemon, so ask the person first:

   ```sh
   paseo plugin install git:tusharpandey13/awt:paseo-plugin --ref v0.2.0
   ```

3. Check it: `paseo plugin ls` should show `awt`, and `paseo plugin logs awt` should end with `Plugin ready`.

Settings, read from the daemon's environment:

| Variable | Default | Meaning |
|---|---|---|
| `AWT_BIN` | `awt` | The CLI to run |
| `AWT_ROOT` | `${XDG_DATA_HOME:-~/.local/share}/awt` | Where the tree lives |
| `AWT_TIMEOUT_MS` | `5000` | How long one `awt` call may take |
| `AWT_AUTO_HANDOFF` | on | `0` stops the plugin keeping an agent's last reply as an `auto` state when it ended a turn without a handoff |
| `AWT_RELATED` | `3` | Related records `decide` and `ask` print after writing (0 to 20; 0 is off). Forwarded to every agent's environment |
| `AWT_RECEIPT` | on | `0` turns off the per-turn receipt line in the chat; `changes` shows it only when something was stored |
| `AWT_NUDGE` | off | `1` sends a follow-up prompt when an agent ends a turn without a handoff. Off by default: it adds a visible message and a model turn to the chat |

To upgrade, install again with the new `--ref`. To remove: `paseo plugin remove awt`; the tree stays on disk.

More: [paseo-plugin/OVERVIEW.md](paseo-plugin/OVERVIEW.md).

## Import Paseo history

`migrate-paseo` (get it by cloning the repo; see Install the CLI) imports existing Paseo workspaces and agents into the tree, with subagents under their parents. It only reads `~/.paseo` and writes through `awt`, and a second run changes nothing. Always show the person the dry run first:

```sh
awt/migrate-paseo --dry-run "${XDG_DATA_HOME:-$HOME/.local/share}/awt"   # the plan
awt/migrate-paseo "${XDG_DATA_HOME:-$HOME/.local/share}/awt"
```

Pass the same root as the plugin's `AWT_ROOT`. `--home` reads a Paseo home other than `~/.paseo`.

## Migrate from wt

`migrate-wt` converts a `wt` tracker or task directory into a new `awt` one:

```sh
awt/migrate-wt --dry-run ~/work ~/work-awt   # the plan
awt/migrate-wt ~/work ~/work-awt
```

The old directory is only read. The new one must be empty or absent. Each file is either copied or listed with a reason in `legacy/MIGRATION.md`, along with problems found in the old records, such as duplicate decision ids. The run fails if any file is unaccounted for.

## Long tasks: relay

`relay` runs a large task as small, fresh `claude -p` sessions instead of one long, expensive one. Download it the same way as `awt`, with `relay` as the file name.

If `./relay` exists and the work splits into parts: write a plan file (`./relay help` shows the format) with small units, a cheap model for reading, and a `check` command wherever a test can decide. Show the person the plan and the command `./relay run docs/relay.plan.json`, then stop. Afterwards, `awt resume` shows the result. Workers cannot send anything.

## Troubleshooting

| Symptom | Do |
|---|---|
| Exit 1 with `error:` and `fix:` | Read the `fix:` line and follow it. `awt help agents` lists every refusal. |
| Exit 2 | Usage error. Run the verb with `--help`. |
| Exit 3 | No write permission. Give the printed command to a person. |
| Exit 4, no `.awt/` | Not in a task: `cd` to it, pass `--dir`, or set `AWT_DIR`. |
| Claude Code ignores `AGENTS.md` | Add `@AGENTS.md` to the `CLAUDE.md` that shadows it. |
| `doctor` warns about the disk | Move the task off network drives and synced folders. |
| `doctor` warns about a remote | Make sure the remote is private; task data is often internal. |
| A secret was refused | Remove it and refer to it by name or location. There is no bypass. |

## Working on this repository

This repository is the source of the tool. The `AGENTS.md` that users get is a template embedded in the `awt` script, not this file.

- `SPEC.md` is the contract. Change it in the same commit as behaviour.
- `awt` is a Python 3.9+ executable. It prefers the standard library; a third-party dependency needs a stated reason in its PR and must keep the documented install working. `migrate-wt` is a separate one-off.
- Complexity is debt. The verb limit in `SPEC.md` is real: a new verb means removing one.
- A rule belongs in a script or test, not in prompt text.
- Run before committing: `python3 -m unittest discover -s tests -p 'test_*.py' && python3 tests/chaos.py`.
- `tests/agentic/run.py` spends real tokens. Run it when `AGENTS.md` text or a verb's interface changes.
- Fixtures use the fictional `parsekit` project. Never add real task data or token-shaped strings to this repository.
- The node tree, Paseo plugin and `migrate-paseo` are specified in `SPEC.md` (Node tree) and `tests/TEST-SPEC.md`. Write the test for a rule before the code for it.
- The plugin's tests: `cd paseo-plugin && npm ci && npm test`.
