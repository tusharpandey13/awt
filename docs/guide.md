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

The agent now works. It writes `outbox/update-eng.md` and runs `./awt effect plan --target "slack:#eng" --body outbox/update-eng.md`. That prints an effect id and the next command. the tool never sends anything: you (or the agent, with its own tools) do.

Read the draft, post it in Slack, then:

```sh
./awt effect mark e-1a2b3c4d sent --ref https://example.slack.com/archives/C02XYZ/p1700000500
```

The id is the one `plan` printed. `./awt list effects` shows it as `sent`. Finish with `./awt status done`, which is refused while a question is unanswered or an effect is `planned`, `begun` or `unknown`. The refusal lists them.

## 3. Sending things

The tool never runs a command. You or the agent send with your own tools, so Claude Code, opencode or Paseo see and gate the real command. it keeps the ledger.

**The declared path** (when a blind retry is costly):

```sh
./awt effect plan --target "jira:PK-142" --body outbox/comment.md --how 'post-jira-comment PK-142 < outbox/comment.md'
./awt effect begin e-1a2b3c4d      # claims it once; prints the body path and the mark command
# send it yourself
./awt effect mark e-1a2b3c4d sent --ref https://example.atlassian.net/browse/PK-142
```

(`post-jira-comment` is your own command.) `--how` is only text for people to read; it is never run. If you sent it by hand without `begin`, `mark ... sent` works straight from `planned`. `begin` on an effect that is not `planned` is refused.

**A send that went wrong.** `./awt effect mark e-1a2b3c4d not-sent --why "gateway refused"` returns it to `planned` for another attempt. `./awt effect mark e-1a2b3c4d unknown --why "timed out"` says you cannot tell. A `begun` effect with no mark stays `begun` and blocks `status done`: only the sender knows what happened.

**`unknown`.** The send may have happened. the tool never retries. Check the real destination, then:

```sh
./awt effect mark e-1a2b3c4d sent        # it went out
./awt effect mark e-1a2b3c4d not-sent --why "checked, nothing there"   # back to planned for another attempt
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

**`save` is gone.** Use `git add -A && awt doctor --staged && git commit -m "message"`. `doctor --staged` refuses when a staged file matches the secret scan; put it in `.git/hooks/pre-commit` to run on every commit.

## 6. Backups and privacy

Commit the directory locally with `git commit`. `scratch/`, `.awt/claims/`, `.awt/blobs/` and `.awt/runs/` are git-ignored, so snapshots and run logs are not in commits. Back up the directory itself if you need those.

The directory holds internal chats and docs. If you add a git remote, make it private; `doctor` warns when one exists. Avoid iCloud, Dropbox and network folders: `doctor` warns there too.

Coming from `wt`? See [Migrating from wt](../README.md#migrating-from-wt).
