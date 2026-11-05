# awt spec

`awt` (agent work task) turns one directory into a workspace for one piece of agent-operated work. Tests are normative where they exist; this file is the only prose spec. Do not restate its constants elsewhere.

## Use case

One directory per task. It holds context from unconnected informal sources (Slack, Jira, Confluence, informal notes, research), working docs (plans, ADRs, decisions, results), outbound side effects (publishable docs, comms for Slack, PRs, comments, Jira) and misc data, so an agent can discover everything relevant. References are preferred over copies, but some information cannot be referenced because the agent has no access to it (Slack chats): that gets captured with provenance.

## Rules

1. Agents are hurried, not hostile. Protect against accidents and shortcuts.
2. One write path, validated before commit. A bad write is refused with a `fix:` line.
3. Record only what no machine can know. Activity comes from the filesystem and git.
4. Views are computed at read time, never written.
5. Only kernel-managed primitives: `O_APPEND`, `O_EXCL`, `rename`, and `flock` where a plan must check then write, since the kernel releases it when a process dies. No lock files, no allocators, no caches.
6. Forgetting must be harmless: a missing record degrades visibly.
7. No hook, settings file or git repo is required. They are conveniences.
8. Complexity is debt. 16 top-level verbs maximum. New verb means removing one.

## Distribution

- `awt`: one executable file. Python 3.9+, stdlib only, shebang `#!/usr/bin/env python3`. All templates embedded.
- The first statements must drop the script directory from `sys.path` before any other import (`import sys; sys.path[:] = ...`), so a `json.py` in the task dir cannot be imported. Also set `sys.dont_write_bytecode = True`.
- Setup: copy `awt` into a directory and run `./awt init --goal "..." --done "..."`.
- `migrate-wt`: separate one-off script in the repo. Not needed for normal use.

## Layout created by `init`

```
AGENTS.md              contract (template below); existing file gets the marked block appended
README.md              only if absent; short human guide (template below)
.gitignore             lines appended if missing: scratch/ .awt/claims/ .awt/blobs/ .awt/runs/
.claude/settings.json  only if absent (template below); if present, print the snippet instead
context/ docs/ outbox/ misc/ scratch/
.awt/events.jsonl      the only state
.awt/claims/ .awt/blobs/ .awt/runs/
```

`init` is idempotent, never overwrites or deletes anything, and with `--goal`/`--done` on a later run appends a new `task` row. It does not run `git init`. It creates empty dirs without placeholder files. If `CLAUDE.md` exists in the directory or an ancestor (excluding `~/.claude/`), it prints a warning: Claude Code may then skip `AGENTS.md`; add the line `@AGENTS.md` to that file. It never edits that file.

## Task root resolution

`--dir` > `AWT_DIR` > directory of the real script file if it contains `.awt/` > walk up from `cwd` to the first `.awt/`. None found: exit 4 with `fix: ./awt init`, except `init` itself, which uses `--dir`, `AWT_DIR` or `cwd`.

## Conventions

- Writes print one line on stdout (id and what happened). Diagnostics go to stderr. Refusals print `error: ...` and `fix: ...`.
- Exit codes: 0 ok; 1 refused or check failed; 2 usage; 3 cannot write because of permissions (also print the exact command for a person to rerun); 4 no task or id not found.
- No prompts, ever.
- Text fields: reject empty after strip; reject over cap with a fix saying to put detail in `docs/` and reference it. Never truncate on write.
- Secret scan runs on every string field of every event: high-confidence patterns only (`AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{36,}`, `github_pat_[A-Za-z0-9_]{20,}`, `xox[abprs]-[A-Za-z0-9-]{10,}`, `(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`, `eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}`). A match refuses the write with the pattern name, never echoing the secret. There is no bypass flag.
- Paths given to `--body`, `supersede`, and `capture` file arguments: resolve symlinks; a path escaping the task root is refused, except that the `capture` input file may be anywhere, since it is only read.

## Events

`.awt/events.jsonl`: one JSON object per line, UTF-8, `ensure_ascii=False`, at most 4096 bytes encoded. Written only via one `emit()`: validate, scan, then a single `os.write` on an `O_APPEND` fd. If the file's last byte is not a newline, prepend one to the row (heals a torn tail). A short write is an error.

Envelope stamped by `emit`: `v` (1), `ts` (UTC ISO8601 with microseconds), `type`, `host`, `by` (`--by` value, else `AWT_BY`, else `agent`).

Ids: prefix plus 8 random hex characters (`d-7f3a9c21`). Prefixes: `d` decision, `q` question, `e` effect, `n` note.

| Type | Fields (caps in chars) |
|---|---|
| `task` | `goal` 250, `done_means` 250 |
| `status` | `status`: `active` `paused` `done` |
| `state` | `scope` 40 (default `main`), `now` 700, `next` 300 |
| `note` | `id`, `text` 280 |
| `decision` | `id`, `choice` 300, `why` 300, `supersedes` optional, `tags` optional list |
| `question` | `id`, `text` 400 |
| `answer` | `ref` question id, `text` 400 |
| `ref` | `target` 1000, `title` 120, `kind`, `why` 200 optional, `access` (`ok` or `none`), plus `path` and `branch` for `kind=repo` |
| `capture` | `path`, `from` 40, `title` 120, `ref` optional 1000, `sha` |
| `doc` | `path`, `action` (`supersede`), `by_doc` new path, `why` 200 optional |
| `effect` | `id`, `step`, plus fields below |

### Reading

One pure-ish function `load()` is the only reader. Rows are never sorted: **file order is canonical**, so "latest" means last in the file (`ts` only feeds the ages in the brief). It **quarantines** (skips and counts) any row that is not valid JSON (including nesting too deep to parse), has an unknown type, lacks a required field, has a field of the wrong type (strings, a list of strings for `tags` and `after`, integers for `v`, `attempt`, `pid`, `timeout`) or a lone surrogate, or an effect row that is an illegal transition. If `events.jsonl` cannot be read at all (a directory, no permission), reads see no rows, the brief says the log is unreadable, `doctor` fails and writes exit 1 with a fix. A bad row must never break a read. Scanning the whole file on every read is intended: no cache.

Latest `state` per `scope` is current. Latest `task` row is the goal. Latest `status` row is the status (default `active`). Latest `ref` per `target` wins. A decision is current unless another decision's `supersedes` names it.

## Verbs (16)

| Verb | Behaviour |
|---|---|
| `init` | Above. |
| `resume [--hook] [--scope S]` | Print the brief. `--hook`: exit 0 and print nothing when no task resolves or on any internal error. Never fails because git failed. |
| `list [refs\|context\|docs\|outbox\|misc\|decisions\|questions\|effects\|notes\|state] [--all]` | Discoverability. No argument prints all sections. `--all` adds superseded docs and decisions, answered questions, all state history and terminal effects. |
| `find <term>` | Case-insensitive literal search across event text and all text files in the root (excluding `.awt/`, `.git/`, `scratch/`, the `awt` script, binary files, and files over 2 MB). Prints `path:line: snippet`; event hits print `event:<id or type>: snippet`. Caps at 40 hits, then `+N more`. Exit 0 even with no hits. Does not follow symlinks. |
| `state --now T --next T [--scope S]` | Refuse if identical to the current state for that scope. |
| `note T` | |
| `decide CHOICE --why T [--supersedes ID] [--tag T]...` | `--why` required. Refuse unknown `--supersedes` id, or one already superseded (fix names the current superseder). |
| `ask T` | |
| `answer ID T` | Refuse unknown id or already answered. |
| `ref TARGET --title T [--why T] [--kind K] [--no-access]` | Prefer this to copying. Infer `kind` from the target unless given: local directory containing `.git` gives `repo` (store absolute `path` and current `branch`); `slack.com` gives `slack`; `atlassian.net/wiki` or `confluence` gives `confluence`; `atlassian.net/browse`, `jira` host or `[A-Z]+-[0-9]+` alone gives `jira`; `/pull/` or `/merge_requests/` gives `pr`; other URL gives `link`; otherwise `other`. `--no-access` sets `access: none`, meaning the agent cannot read it and must ask a person to paste it. |
| `capture --from SRC --title T [--ref URL] [FILE]` | Stdin when FILE is absent or `-`. Writes `context/<YYYYMMDD>-<slug>.md` via temp file and `rename`, with a header block of `source`, `title`, `captured`, `ref`. Slug is `[a-z0-9-]` only, max 50, with a numeric suffix on collision. Secret matches in the **body** are replaced with `[REDACTED:<pattern>]` and counted in the output; the capture is not refused. Same body sha as an earlier capture: return that path, exit 0, no new row. Refuse an empty body. |
| `supersede OLD NEW [--why T]` | Both must be under `docs/` and exist; moves OLD to `docs/_superseded/` with `rename`, with a numeric suffix on collision. Refuse OLD equal to NEW. |
| `status active\|paused\|done` | `done` is refused while any question is unanswered or any effect is `planned`, `claimed` or `unknown`; the refusal lists them. |
| `effect plan\|show\|apply\|mark` | Below. |
| `doctor` | Below. |
| `save MESSAGE` | Below. |

`help` and `--help` print usage and do not count as verbs. `help agents` prints the embedded agent reference. `--version` prints the version.

## Resume brief

Sections in this order, each with a budget in one constants table. Total at most 4,400 chars, tested at maximum fill, labels included. Empty sections are omitted. Truncate at a line boundary with `+N more: ./awt list <section>`.

| # | Section | Budget |
|---|---|---|
| 1 | Goal, done-means, status | 600 |
| 2 | Newest state in full with its age and scope; other scopes one line each | 1,200 |
| 3 | Open questions | 600 |
| 4 | Effects needing attention: `planned`, `unknown`, conflicts, with the next command | 500 |
| 5 | Changes since the newest state: files in the root newer than it (count, up to 8 paths; excluding `.awt/`, `.git/`, `scratch/`), and for each `repo` ref on this host `git log` commit subjects since then plus a dirty count. No state yet: say so. Git failure: one degraded line. | 500 |
| 6 | Current decisions: tag `rule` first, then newest, each cut to 120 chars | 800 |
| 7 | One inventory line (counts of refs, no-access refs, context, docs, outbox, misc), quarantine count if nonzero, the pointer `./awt list`, `./awt find <term>` | 200 |

Add one last line when the newest state is missing: `No handoff yet. Before stopping: ./awt state --now "..." --next "..."`.

## Listing

Listings walk the filesystem, so a file a person drops into `context/`, `docs/`, `outbox/` or `misc/` is discoverable with no registration. Any other top-level file or directory except `.awt`, `.git`, `.claude`, `scratch`, `awt`, `AGENTS.md`, `README.md`, `CLAUDE.md`, `.gitignore`, `legacy` shows under `misc`; `legacy/` also shows under `misc`. Title for a file: capture title, else first `# ` heading, else first nonblank line, cut to 60 chars, else `(binary)`. Read at most 4 KB per file. `docs/_superseded/` is hidden unless `--all`. `outbox` lines show effect state for files an effect references. Do not follow symlinks; show them as `path -> target`. Unreadable files never break a listing.

## Effects

A message, comment, doc or edit leaving this machine.

```
planned --apply--> claimed --exit 0 and verify passes--> sent
   |  \                |
   |   \               +--non-zero exit, failed verify, timeout, crash--> unknown
   |    mark sent (manual effects only) --> sent                            |
   | mark dropped                         mark not-sent: attempt+1, planned-+
   v                                      mark sent: sent ------------------+
dropped
```

`effect plan --target T [--body FILE] [--run CMD] [--class additive|overwrite] [--snapshot CMD] [--verify CMD] [--after ID]... [--again] [--why T]`

- `--target` is free text such as `slack:#eng` or `jira:TKT-1`, cap 200. One of `--body` or `--run` is required. `--body` must be a regular file inside the root; `outbox/` is the convention.
- No `--run` means **manual**: a person sends it. `apply` refuses and prints the body path and the `mark` command. This is the normal case for Slack when the agent has no access.
- `--class` defaults to `additive`. `overwrite` without `--snapshot` is refused.
- `key = sha256(target, run, body sha, class, nonce)`. `nonce` is empty unless `--again` sets a random one.
- Same key as an existing effect: print its id and state, exit 0, write nothing. If that effect is `dropped`, refuse with fix `--again`.
- A new plan on a target with an open `unknown` effect is refused unless `--again`.
- `--after` ids must exist. Output includes the exact next command, quoted with `shlex`.

`effect apply ID --target T`

1. Refuse unless state is `planned`, `--target` equals the effect's target, every `--after` effect is `sent`, and a body file's sha still matches (fix: plan again).
2. With `--snapshot`: run it, store stdout in `.awt/blobs/<sha256>`. Empty stdout, non-zero exit or a timeout aborts with nothing consumed. `--timeout` below 1 is a usage error (exit 2).
3. Re-read the log; abort if the effect is no longer `planned` (for example dropped during the snapshot). Create `.awt/claims/<key>.<attempt>` with `O_EXCL`. Losing means someone else is sending: exit 1.
4. Emit `step: claimed` with `attempt`, `host`, `pid`, `timeout` (the whole time budget in seconds).
5. Run `sh -c CMD` in the root with `AWT_BODY` (absolute path) and `AWT_TARGET` set, stdout and stderr to `.awt/runs/<id>.<attempt>.log`, timeout `--timeout` seconds (default 300).
6. Exit 0: run `--verify` if present. Everything passes: emit `step: sent`. Otherwise emit `step: unknown` with the reason and exit 1. Never retry automatically.

`effect mark ID sent|not-sent|dropped [--ref URL] [--why T]`

Legal only as drawn. `sent` from `planned` is manual effects only. `not-sent` emits `step: planned` with `attempt+1`. Refuse any mark while the effect is `claimed` and the recorded pid is alive on this host.

`effect show ID` prints every field, state, attempt history, body path and body.

State derivation in `load()`: `claimed` with no outcome reads as `unknown`, unless the pid is alive on this host and the claim is younger than its `timeout` plus a 30 s margin (a reused pid cannot hold an effect forever), when it reads as `claimed`. `planned` with an existing claim file for the current attempt reads as `unknown` (crash between steps 3 and 4). Two `claimed` rows with the same attempt read as `conflict`, shown in the brief until marked. Effect rows other than `planned` for an unknown id are quarantined.

## doctor

Prints one `ok`, `warn` or `fail` line per check, and exits 1 on any `fail`. It tests behaviour rather than inspecting files.

- `fail`: Python below 3.9; no task root; a real `O_APPEND` and `O_EXCL` probe in `.awt/` fails; `AGENTS.md` lacks the awt block; `./awt resume --hook` run as a subprocess prints no brief.
- `warn`: quarantined rows, with their line numbers; the path contains `iCloud`, `Dropbox`, `OneDrive` or `Google Drive`, or is a network mount; `CLAUDE.md` in the directory or an ancestor; `.claude/settings.json` lacks the awt hook or `ask` rule; `awt` is not executable; a git remote exists (task data would be pushed if committed, so check it is private); open `unknown` or `conflict` effects.

## save

`save MESSAGE`: commit the task directory.

- Refuse when not a git repo, or when `git rev-parse --show-toplevel` is not the task root (the task sits inside some other repo). Fix: `git init` here. Never run `git init` itself. Never push.
- `git add -A -- .`, excluding nested git repos, which are reported. Unstage and report any staged text file under 2 MB that matches the secret scan. Commit with `--no-gpg-sign`. Nothing staged: exit 0 and say so.

## Templates

### AGENTS.md block

The block is wrapped in `<!-- awt:begin -->` and `<!-- awt:end -->`. On re-init, only a block that is missing gets added. Keep it at or under 2 KB.

```markdown
# Task workspace (awt)

Everything about this task lives here. Keep records with `./awt`. Never hand-edit `.awt/`.

**Start:** unless you are a subagent with its own brief, run `./awt resume` and follow it.
**Before stopping** with changes made: `./awt state --now "where things stand" --next "the next concrete step"`. Parallel workstreams: add `--scope <name>`.

| You have | Do |
|---|---|
| A link to something readable later (Slack, Jira, Confluence, PR, repo path) | `./awt ref <url-or-path> --title "..."`. Prefer this to copying. |
| A link you cannot open | Still record it: `./awt ref <url> --title "..." --no-access`, then `./awt ask` for a paste |
| Text with no usable link (pasted chat, meeting notes, research) | `./awt capture --from slack --title "..." [file]` |
| A plan, ADR, result or other working doc | Write it in `docs/`. Replaced: `./awt supersede docs/old.md docs/new.md` |
| A decision | `./awt decide "the choice" --why "the reason"`. Reversing one: add `--supersedes <id>` |
| A small fact worth keeping | `./awt note "..."` |
| A question for a person | `./awt ask "..."`; record the reply with `./awt answer <id> "..."` |
| Anything else | `misc/`. Throwaway work: `scratch/`. |

**Anything leaving this machine** (message, comment, PR, ticket edit, published doc) goes through the outbox. Never send it directly.

1. Write the draft in `outbox/`.
2. `./awt effect plan --target "slack:#eng" --body outbox/x.md`. Add `--run '<cmd>'` only if a command can send it.
3. Stop and show the person. They send it or approve `./awt effect apply`. Then `./awt effect mark <id> sent`.

Effect state `unknown` means it may have been sent. Never resend, use `--again` or mark it. Ask a person.

**Find things:** `./awt list`, `./awt find "term"`. Check before asking.
**Stuck or refused:** read the `fix:` line, then `./awt help agents`.
**Subagents:** skip resume, write output to `docs/<brief>.out.md`, leave `state` to the orchestrator.
```

### README.md (task dir)

```markdown
# <goal, or "Task workspace">

Workspace for one piece of agent-operated work, managed by [awt](https://github.com/tusharpandey13/awt).

- `./awt resume`: where things stand
- `./awt list`, `./awt find <term>`: everything known about this task
- `context/` inbound material, `docs/` working docs, `outbox/` drafts going out, `misc/` the rest, `scratch/` throwaway
- `./awt effect mark <id> sent` after you send something from `outbox/`
```

### .claude/settings.json

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/awt resume --hook" } ] }
    ]
  },
  "permissions": {
    "ask": [ "Bash(./awt effect apply *)", "Bash(awt effect apply *)" ]
  }
}
```

Do not add an `Edit` deny rule for `.awt/`: Claude Code merges those into the OS sandbox, which then stops `awt` writing its own log. A chaos run confirmed this. Hand edits are handled by quarantine.

## relay

`relay`: separate optional script, not needed for normal use, and its verbs do not count against the `awt` limit. It replaces a long-lived orchestrator agent, whose idle context is rewritten on every cache miss, with a script and short-lived workers. `relay help` documents the plan format and is the contract for it. Rules: a worker starts from `./awt resume --scope <unit>` and file pointers; a check command decides pass or fail where one exists; a failed unit retries once at higher effort and then blocks only its dependents; finished units are skipped unless edited; workers never approve effects.

`resume --scope S` puts scope S first in the State section and measures changes from its newest row.

## migrate-wt

`migrate-wt OLD NEW [--dry-run]`: read-only on `OLD`. `NEW` must be absent or empty. It writes only through the `awt` next to it, copied into `NEW`.

`OLD` containing `tasks/*/` is a tracker: each task goes to `NEW/<id>/`. Otherwise `OLD` is one task.

| Old | New |
|---|---|
| `TASK.md` | `docs/TASK.md`; first paragraph, cut to the cap, becomes the goal |
| `task.yml` | `legacy/`; every URL and every `repos[].repo`, `sources`, `links` entry becomes a `ref`; a reference to `context/...` stays a file; `status` maps `done` and `archived` to `done`, anything else to `active`. Line-based parsing: malformed YAML and duplicate keys must not lose entries. |
| `decisions.md` | `legacy/`; each `## Dn` becomes a `decision`, with the legacy id in `why`, over-cap text cut with a pointer to the legacy file; `supersedes: Dm` becomes a link when Dm has been imported and is current; duplicates are imported and reported; overturn language with no link is reported. |
| `log.jsonl` | `legacy/` unchanged; URL refs in parseable rows become `ref` rows, deduplicated |
| `AGENTS.md` or `HANDOFF.md` | `legacy/`; "Carry-forward" and "Next action" sections become one `state`, cut with a pointer to the legacy file |
| `context/` | `context/` |
| `artifacts/`, `docs/` | `docs/` |
| `refs/` symlinks | `ref` rows, when the target exists on this machine; otherwise reported |
| `tmp/`, `scratch/` | `misc/old-scratch/`, minus bulk |
| Anything else | `misc/` |

Skipped and reported: `.git` and whole nested git repos (the latter become a `ref`), `node_modules`, `.venv`, `venv`, `target`, `dist`, `__pycache__`, `.flowly`, files over 50 MB. Symlinks are recorded, not followed.

It writes `legacy/MIGRATION.md`: what was imported, reported problems, and every skipped path with its reason. It exits 1 if any regular source file is neither copied nor listed as skipped. `--dry-run` prints the plan and writes nothing.
