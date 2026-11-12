# awt guide

For the person running the agent. [SPEC.md](../SPEC.md) is the contract; this page is what you do.

## 1. Adopt it

**New directory.** Copy `awt` in (see the [README](../README.md#quick-start)), then:

```sh
./awt init --goal "Cut parsekit retry storms" --done "Fix merged, #eng told, PK-142 closed"
./awt doctor
```

`doctor` prints `ok`, `warn` or `fail` per check. Fix any `fail` before starting an agent.

**Directory that already has files.** Run the same `init`. It never overwrites or deletes:

- An existing `AGENTS.md` gets a marked block appended. Your text is untouched.
- Your other files stay where they are. Top-level files and directories outside the standard ones show up under `misc` in `./awt list`.
- `.gitignore` gets missing lines appended. `.claude/settings.json` is created only if absent; if you have one, `init` prints the snippet for you to merge.
- It does not run `git init`.

Run `./awt list` to see what the agent will see.

## 2. A worked task

You are looking at a retry bug in `parsekit`. The thread is in Slack, which the agent can't read.

Copy the thread, then:

```sh
pbpaste | ./awt capture --from slack --title "Retry storm thread" --ref https://example.slack.com/archives/C01ABC/p1700000000
```

You see one line with the new path under `context/`. Secrets in the pasted text are replaced with `[REDACTED:...]` and counted in that line.

Add links. The agent can read Jira; it can't read the Confluence page:

```sh
./awt ref PK-142 --title "Retry storm ticket"
./awt ref https://example.atlassian.net/wiki/spaces/ENG/pages/123 --title "Retry design page" --no-access
```

`--no-access` tells the agent to ask you to paste that page instead of guessing.

Record a decision:

```sh
./awt decide "Cap parsekit retries at 3" --why "Thread shows retries amplify the outage" --tag rule
```

The agent now works. It writes `outbox/update-eng.md` and runs `./awt effect plan --target "slack:#eng" --body outbox/update-eng.md`. That prints an effect id and the next command. There is no `--run`, so it is manual: nothing can send it but you.

Read the draft, post it in Slack, then:

```sh
./awt effect mark e-1a2b3c4d sent --ref https://example.slack.com/archives/C02XYZ/p1700000500
```

The id is the one `plan` printed. `./awt list effects` shows it as `sent`. Finish with `./awt status done`, which is refused while a question is unanswered or an effect is `planned`, `claimed` or `unknown`. The refusal lists them.

## 3. Sending things

**Manual effect** (no `--run`): `./awt effect apply` refuses and prints the body path and the `mark` command. You send it yourself, then `mark ... sent`. Use this for Slack and anything the agent has no access to.

**Effect with `--run`**: `plan` records a shell command, and `apply` runs it:

```sh
./awt effect plan --target "jira:PK-142" --body outbox/comment.md --run 'post-jira-comment "$AWT_TARGET" "$AWT_BODY"'
./awt effect show e-1a2b3c4d
./awt effect apply e-1a2b3c4d --target "jira:PK-142"
```

(`post-jira-comment` is your own command.) Run `effect show` first. It prints the command, the body and the history.

**The approval prompt.** In Claude Code, `init` adds a rule so `./awt effect apply` asks you first. The prompt shows the `apply` command line: the id and target. It does not show the `--run` command or the body. Read those with `effect show` before you approve. The rule only works in Claude Code, only with `.claude/settings.json` in place, and only for commands it can match as text. An agent that runs a script around it isn't stopped. See Limits in the README.

**`unknown`.** The send may have happened. Causes: the command failed, timed out, failed its `--verify`, or the process crashed. `awt` never retries. Check the real destination, then:

```sh
./awt effect mark e-1a2b3c4d sent        # it went out
./awt effect mark e-1a2b3c4d not-sent    # it did not; goes back to planned for another apply
```

A new plan on a target with an open `unknown` effect is refused unless you pass `--again`. `dropped` is allowed only from `planned`.

## 4. Resuming

Start the agent. In Claude Code the hook runs `./awt resume` for you. Anywhere else, the agent runs it because `AGENTS.md` says so. You can run it too.

The brief contains: goal and status, the latest handoff (`state`), open questions, effects needing attention, files and commits changed since the handoff, current decisions (tagged `rule` first, each cut short), and a count of what exists.

It does not contain: captured text, doc contents, notes, answered questions, sent effects, or the full wording of long decisions. Those are one `./awt list` or `./awt find "term"` away. The brief is short on purpose. If it says `+N more`, run the `./awt list` command it names.

If the last session recorded no handoff, the brief says so and shows what changed on disk anyway. A decision made only in chat is lost; ask the agent to run `./awt decide`.

## 5. Troubleshooting

**Agent ignores AGENTS.md.** Claude Code may skip `AGENTS.md` when a `CLAUDE.md` exists in the directory or a parent. `init` and `doctor` warn about it. Add the line `@AGENTS.md` to that `CLAUDE.md`. `awt` never edits it.

**Secret refusal.** Any write whose text matches a token pattern is refused with the pattern name. There is no bypass. Remove the secret and refer to where it lives. `capture` is different: it redacts and continues. The scan is pattern-based and misses some formats.

**Quarantined rows.** A malformed or illegal row is skipped and counted, never fatal. `doctor` warns, and the brief's inventory line shows the count. Don't hand-edit `.awt/`. Rows are skipped, not deleted, so nothing is lost; the spec has no command to list which rows were skipped.

**`save` refused.** It needs this directory to be the root of its own git repo. If it isn't a repo, or sits inside another one, run `git init` here yourself. Files that match the secret scan are unstaged and reported. It never pushes.

## 6. Backups and privacy

`./awt save "message"` commits the directory locally. `scratch/`, `.awt/claims/`, `.awt/blobs/` and `.awt/runs/` are git-ignored, so snapshots and run logs are not in commits. Back up the directory itself if you need those.

The directory holds internal chats and docs. If you add a git remote, make it private; `doctor` warns when one exists. Avoid iCloud, Dropbox and network folders: `doctor` warns there too.

Coming from `wt`? See [Migrating from wt](../README.md#migrating-from-wt).
