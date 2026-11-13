# awt spec

`awt` (agent work task) turns one directory into a workspace for one piece of agent-operated work. Tests are normative where they exist; this file and `tests/TEST-SPEC.md` (the test plan) are the only prose specs. Do not restate its constants elsewhere.

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

- `awt`: a Python 3.9+ executable with shebang `#!/usr/bin/env python3`. It prefers the standard library; a third-party dependency needs a stated reason in its PR and must keep the documented install working. All templates embedded. It is one file today.
- The first statements must drop the script directory from `sys.path` before any other import (`import sys; sys.path[:] = ...`), so a `json.py` in the task dir cannot be imported. Also set `sys.dont_write_bytecode = True`.
- Setup: copy `awt` into a directory and run `./awt init --goal "..." --done "..."`.
- `migrate-wt`: separate one-off script in the repo. Not needed for normal use.

## Layout created by `init`

```
AGENTS.md              contract (template below); existing file gets the marked block appended
README.md              only if absent; short human guide (template below)
.gitignore             lines appended if missing: scratch/ .awt/claims/ .awt/runs/
.claude/settings.json  only if absent (template below); if present, print the snippet instead
context/ docs/ outbox/ misc/ scratch/
.awt/events.jsonl      the only state
.awt/claims/
```

`init` is idempotent, never overwrites or deletes anything, and with `--goal`/`--done` on a later run appends a new `task` row, unless the latest task row already has the same goal and done-means. It does not run `git init`. It creates empty dirs without placeholder files. If `CLAUDE.md` exists in the directory or an ancestor (excluding `~/.claude/`), it prints a warning: Claude Code may then skip `AGENTS.md`; add the line `@AGENTS.md` to that file. It never edits that file.

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
| `decision` | `id`, `choice` 300, `why` 300, `supersedes` optional, `tags` optional list, each tag 40 |
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
| `init` | Above. `--kind` creates nodes: see Node tree. |
| `resume [--hook] [--scope S]` | Print the brief. `--hook`: exit 0 and print nothing when no task resolves or on any internal error. Never fails because git failed. |
| `list [refs\|context\|docs\|outbox\|misc\|decisions\|questions\|effects\|notes\|state] [--all]`; `list --since ISO8601 [--down] --json` | Discoverability. No argument prints all sections. `--all` adds superseded docs and decisions, answered questions, all state history and terminal effects. `--since` (with `--json`, no section) prints the rows of every type at or after the timestamp; see Reading across nodes. |
| `find <term>`, `find --like TEXT [--limit N]` | Case-insensitive literal search across event text and all text files in the root (excluding `.awt/`, `.git/`, `scratch/`, the `awt` script, binary files, and files over 2 MB). Prints `path:line: snippet`; event hits print `event:<id or type>: snippet`. Caps at 40 hits, then `+N more`. Exit 0 even with no hits. Does not follow symlinks. `--like` ranks related records instead; see Reading across nodes. |
| `state --now T --next T [--scope S]` | Refuse if identical to the current state for that scope. |
| `note T` | |
| `decide CHOICE --why T [--supersedes ID] [--tag T]... [--related N]` | `--why` required. Refuse unknown `--supersedes` id, or one already superseded (fix names the current superseder). After the id line, prints up to N `related:` lines (default 3; see Reading across nodes). |
| `ask T [--related N]` | After the id line, prints up to N `related:` lines, an answered question with its answer. |
| `answer ID T` | Refuse unknown id or already answered. |
| `ref TARGET --title T [--why T] [--kind K] [--no-access]` | Prefer this to copying. Infer `kind` from the target unless given: local directory containing `.git` gives `repo` (store absolute `path` and current `branch`); `slack.com` gives `slack`; `atlassian.net/wiki` or `confluence` gives `confluence`; `atlassian.net/browse`, `jira` host or `[A-Z]+-[0-9]+` alone gives `jira`; `/pull/` or `/merge_requests/` gives `pr`; other URL gives `link`; otherwise `other`. `--no-access` sets `access: none`, meaning the agent cannot read it and must ask a person to paste it. |
| `capture --from SRC --title T [--ref URL] [FILE]` | Stdin when FILE is absent or `-`. Writes `context/<YYYYMMDD>-<slug>.md` via temp file and `rename`, with a header block of `source`, `title`, `captured`, `ref`. Slug is `[a-z0-9-]` only, max 50, with a numeric suffix on collision. Secret matches in the **body** are replaced with `[REDACTED:<pattern>]` and counted in the output; the capture is not refused. Same body sha as an earlier capture: return that path, exit 0, no new row. Refuse an empty body. |
| `supersede OLD NEW [--why T]` | Both must be under `docs/` and exist; moves OLD to `docs/_superseded/` with `rename`, with a numeric suffix on collision. Refuse OLD equal to NEW. |
| `status active\|paused\|done` | `done` is refused while any question is unanswered or any effect is `planned`, `begun` or `unknown`; the refusal lists them. |
| `effect plan\|begin\|mark\|show` | Below. |
| `doctor [--staged]` | Below. |
| `ingest [--source claude\|all] [--hook]` | Below. |

`help` and `--help` print usage and do not count as verbs. `help agents` prints the embedded agent reference. `--version` prints the version.

## Resume brief

Sections in this order, each with a budget in one constants table. Total at most 4,400 chars (more for a tree node, see Node tree), tested at maximum fill, labels included. Empty sections are omitted. Truncate at a line boundary with `+N more: ./awt list <section>`.

| # | Section | Budget |
|---|---|---|
| 1 | Goal, done-means, status | 600 |
| 2 | Newest state in full with its age and scope; other scopes one line each | 1,200 |
| 3 | Open questions | 600 |
| 4 | Effects needing attention: `planned`, `begun`, `unknown`, with the next command | 500 |
| 5 | Changes since the newest state, not counting scope `auto` (the Paseo plugin's stand-in handoff) unless it is the only one: files in the root newer than it (count, up to 8 paths; excluding `.awt/`, `.git/`, `scratch/`), and for each `repo` ref on this host `git log` commit subjects since then plus a dirty count. No state yet: say so. Git failure: one degraded line. | 500 |
| 6 | Current decisions: tag `rule` first, then newest, each cut to 120 chars | 800 |
| 7 | One inventory line (counts of refs, no-access refs, context, docs, outbox, misc), quarantine count if nonzero, the pointer `./awt list`, `./awt find <term>` | 200 |

Add one last line when the newest state is missing: `No handoff yet. Before stopping: ./awt state --now "..." --next "..."`.

## Listing

Listings walk the filesystem, so a file a person drops into `context/`, `docs/`, `outbox/` or `misc/` is discoverable with no registration. Any other top-level file or directory except `.awt`, `.git`, `.claude`, `scratch`, `awt`, `AGENTS.md`, `README.md`, `CLAUDE.md`, `.gitignore`, `legacy` shows under `misc`; in a tree node, `workspaces/`, `tasks/` and `agents/` are reserved for child nodes and never show (standalone behaviour is unchanged); `legacy/` also shows under `misc`. Title for a file: capture title, else first `# ` heading, else first nonblank line, cut to 60 chars, else `(binary)`. Read at most 4 KB per file. `docs/_superseded/` is hidden unless `--all`. `outbox` lines show effect state for files an effect references. Do not follow symlinks; show them as `path -> target`. Unreadable files never break a listing.

## Effects

An effect is a record of one thing leaving your machine (a message, comment, doc or edit), tracked so it is never sent twice or retried blindly.

**awt never executes commands.** It keeps the ledger; the sender (an agent or a person) sends with their own tools, so the host's permission system sees the real command. No code path of an `effect` verb starts a process (no `git` either: the effect verbs only read and append the log and touch `.awt/claims/`). This is the *declared* path: optional, for sends where a blind retry is costly. (Detected effects, where a host hook writes the same rows, are a later phase.)

```
planned --begin--> begun --mark sent--------> sent
   |  \              |--mark not-sent-------> planned (attempt+1)
   |   \             +--mark unknown--------> unknown --mark sent|not-sent
   |    mark sent (a person, straight from planned) --> sent
   +--mark dropped--> dropped
```

`effect plan --target T [--body FILE] [--how TEXT] [--after ID]... [--again] [--why T]`

- `--target` is free text such as `slack:#eng` or `jira:TKT-1`, cap 200. `--body` is optional; it must be a regular file inside the root, `outbox/` is the convention.
- `--how` is the intended command as text, cap 400. It is shown to people (`begin`, `show`, `list effects --json` as `how`). It is never run and is not part of the key.
- `key = sha256(target, body sha, nonce)`. `nonce` is empty unless `--again` sets a random one.
- Same key as an existing effect: print its id and state, exit 0, write nothing (if it is `sent`, say so and point to `--again` or a narrower `--target`). If that effect is `dropped`, refuse with fix `--again`. An old effect (its row has `class`) was keyed `sha256(target, run, body sha, class or additive, nonce)`; it also matches by that formula, using its own `run` and `class`, so a re-plan across the upgrade finds it.
- A new plan on a target with an open `unknown` effect is refused unless `--again`.
- `--after` ids must exist. Output includes the exact next command.

`effect begin ID`

1. Refuse unless the state is `planned`, every `--after` effect is `sent`, and a body file's sha still matches (fix: plan again).
2. Create `.awt/claims/<key>.<attempt>` with `O_EXCL`. Losing means someone else is sending: exit 1.
3. Emit `step: begun` and print the body path, `--how` and the `mark` command. Then the caller sends.

`effect mark ID sent [--ref URL] | not-sent --why T | unknown --why T | dropped`

Legal only as drawn: from `planned`: `sent` (a person who sent it without `begin`) and `dropped`; from `begun`: `sent`, `not-sent`, `unknown`; from `unknown`: `sent`, `not-sent`. `not-sent` emits `step: planned` with `attempt+1`. `not-sent` and `unknown` need `--why` (exit 2). `begin`, `mark` and `plan` hold an exclusive lock on the log while they check and write, so concurrent verbs serialise.

`effect show ID` prints every field, the state, the attempt history, `how`, the body path and body.

A `begun` effect with no mark stays `begun`, needs attention in the brief, and blocks `status done`. A reader cannot tell whether a `begun` effect was sent (a legacy dead-pid `claimed` row, or a crash between the claim file and the row, also read `begun`), so the brief and the agent reference say: send only if you ran `begin` yourself in this session, otherwise treat it as unknown and ask a person. No timeout changes it: only the sender knows. A crash after `begin` leaves `begun`, never retried, shown to a person. awt cannot verify a send: the sender records it with `mark sent --ref`.

State derivation in `load()`: `planned` with an existing claim file for the current attempt reads as `begun` (crash between steps 2 and 3). Effect rows other than `planned` for an unknown id, and illegal transitions, are quarantined; so is a second `begun` row for an attempt already `begun`. Two legacy `claimed` rows for one attempt (the old `conflict`: two processes ran it) are not quarantined: the effect reads `begun`, and `show` and the brief say `legacy conflict: may have been sent twice`. Old trees read unchanged: step `claimed` reads as `begun`; a row's `run`, `class`, `snapshot` and `verify` are accepted, and `show` prints `run` as `how` and the others as `legacy NAME: VALUE`, plus `legacy file:` lines for `.awt/runs/<id>.*`, and for `.awt/blobs/*` (marked tree-wide: blobs are named by content hash) only for an effect whose row had `snapshot`. A `planned` row with `run` is an ordinary planned effect. `events.jsonl` is never rewritten; `.awt/runs/` and `.awt/blobs/` are never written by effect verbs and never deleted.

Removed: `effect apply`, and the flags `--run`, `--snapshot`, `--verify`, `--class`, `--timeout`. They are registered as hidden options and refused after parsing (exit 2, `fix:` naming `plan`, `begin` and `mark`), so an option value such as `--why=--timeout` is not mistaken for one. (`.awt/runs/` is still written by `relay` for worker logs.)

## doctor

Prints one `ok`, `warn` or `fail` line per check, and exits 1 on any `fail`. It tests behaviour rather than inspecting files.

- `fail`: Python below 3.9; no task root; a real `O_APPEND` and `O_EXCL` probe in `.awt/` fails; `AGENTS.md` lacks the awt block; `./awt resume --hook` run as a subprocess prints no brief.
- `warn`: quarantined rows, with their line numbers; the path contains `iCloud`, `Dropbox`, `OneDrive` or `Google Drive`, or is a network mount; `CLAUDE.md` in the directory or an ancestor; `.claude/settings.json` lacks the awt hook; `.claude/settings.json` still has the obsolete `ask` rule for `effect apply` (one warning per line, naming the line number and text to remove; awt never edits the file); `awt` is not executable; a git remote exists (task data would be pushed if committed, so check it is private); open `begun` or `unknown` effects.
- Store checks (run even without a task root, never create anything): `warn` when the store directory is not mode 700 or holds files that others can read, when it sits in a sync folder, network mount or git work tree, when `ingest` never ran or last ran over 7 days ago, and when the oldest Claude transcript is within 7 days of `cleanupPeriodDays` (from `${AWT_CLAUDE_SETTINGS:-~/.claude/settings.json}`, default 30) and ingest is more than a day old.
- `doctor --staged`: needs only a git work tree (`--dir`, default the current directory), not a task. Scans the staged blobs (not the working copy) of added, copied, modified and renamed text files under 2 MB for the secret scan; prints each match as `error:` with the file and pattern, never the secret, and exits 1. Meant for `.git/hooks/pre-commit`. `save` was removed: it exits 2 with a `fix:` naming `git commit` and `doctor --staged`.

## ingest

`ingest [--source claude|all] [--hook]`: copy provider transcripts into the canonical store. Only `claude` exists; `all` means every source that exists. Design: `docs/adr/0003-canonical-raw-jsonl.md`; the wider plan is in ARCHITECTURE-v2 section 3.

- **Store:** `${AWT_STORE:-${XDG_DATA_HOME:-~/.local/share}/awt-store}`. Directories mode 700, files mode 600, whatever the umask. Separate from the task tree on purpose: it holds full conversation text.
- **Source:** `${AWT_CLAUDE_PROJECTS:-~/.claude/projects}`, every `*.jsonl` below it, including `<session>/subagents/agent-<id>.jsonl` (session name `<session>.agent-<id>`). Read-only: awt never writes, renames or touches a transcript. Symlinks are not followed. A missing directory is not an error.
- **Output:** `log/claude/<YYYY-MM>/<session>.jsonl` (the month of the file's first timestamped record), one row per non-blank source line:
  `{"v":1,"src":"claude","adapter":1,"session":S,"seq":N,"ingested":ISO,"src_ref":"<path under projects>:<line>","secret_flags":K,"raw":<the provider record, verbatim>}`. A line that is not JSON is kept as `raw: {"_unparsed": TEXT}`.
- **No redaction and no size cap.** `raw` is never altered or cut. `secret_flags` counts matches of the secret scan inside `raw`; it only informs.
- **Incremental by (path, inode, byte offset)**, kept in `ingest/claude.offsets.json` under the store, written by rename after each file, all under `flock` on `ingest/claude.lock`. A source line without its newline is left for the next run unless it is already a complete JSON object.
- **Idempotent and crash safe.** One `O_APPEND` write per row. A torn tail on a canonical file is closed with a newline before appending. If a run died after appending but before saving its offset, the next run skips rows whose `seq` is already present. A source whose inode changed, or that is shorter than the saved offset, is rescanned from the start and only rows not already stored are appended. Rerunning with nothing new writes no rows.
- **`--hook`:** prints nothing and exits 0 on any error. `init` puts it in the `SessionEnd` hook of `.claude/settings.json`.
- Without `--hook`: prints `ingested N rows from M claude files into STORE`; a store that cannot be written exits 1 with a `fix:`.
- awt never deletes store data and has no verb that does.

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

**Find things:** `./awt list`. `./awt find "term"` for an exact match; `./awt find --like "a sentence"` for related decisions, answers and notes from every workspace in the tree. Check before deciding or asking; `decide` and `ask` also list related records, so read them.
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
```

### .claude/settings.json

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/awt resume --hook" } ] }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "command": "\"$CLAUDE_PROJECT_DIR\"/awt ingest --source claude --hook" } ] }
    ]
  }
}
```

Do not add an `Edit` deny rule for `.awt/`: Claude Code merges those into the OS sandbox, which then stops `awt` writing its own log. A chaos run confirmed this. Hand edits are handled by quarantine.

## Node tree

Status: proposed. Everything in this section is additive: a directory with no parent and no children behaves exactly as described above. Tests for each rule are listed in `tests/TEST-SPEC.md`; a rule without a test is not yet in force.

One directory per task stops working when a task has parts. Putting the parts in one directory makes it too big to resume; making them separate tasks loses the links between them. The tree gives them a place to live while each node stays a normal awt directory.

### Nodes and kinds

A **node** is a directory that contains `.awt/`. Child nodes live in reserved directories, created on demand: `workspaces/`, `tasks/`, `agents/`. The **parent** of a node is the directory two levels up when the node sits directly in a reserved directory of a node, and nothing otherwise. That is the only definition: lineage, inherited rules, Children, `list nodes`, `status done` blocking and I1 all use it. The hierarchy is the filesystem, so `mv` of a subtree keeps it intact and no parent pointer is stored (rule 3). A node elsewhere inside another node (for example `w/foo/`) has no parent; `doctor` warns.

| Kind | Meaning | May contain |
|---|---|---|
| `root` | The top of a tree. Holds the contract (`AGENTS.md`) | `workspace` |
| `workspace` | A long-lived area of work: a repo, a project, a Paseo workspace. Holds shared `context/`, `docs/` and `rule` decisions | `task` |
| `task` | One piece of work with a goal and a done-means. The existing layout | `task`, `agent` |
| `agent` | One chat or subagent. Its own event log, `scratch/`, `out.md` | `agent` (subagents) |

An `agent` directly under a `workspace` is refused. A chat that belongs to no task goes under a task named `main`. A node whose `.awt/` has no `node` row is a legacy node: its kind is `task`, or the kind its reserved directory implies, and no kind rules are enforced on it. Converting a standalone task: move it into a workspace's `tasks/`.

The **tree root** is the nearest ancestor of kind `root`, else the outermost ancestor, else the node itself. Tools that need a tree without being given one (the Paseo plugin) use `AWT_ROOT`, default `${XDG_DATA_HOME:-~/.local/share}/awt`. Keep it outside any repository that is pushed.

New row type, written once at creation by `init`:

| Type | Fields |
|---|---|
| `node` | `kind`, `name` 60, `key` optional 200 |

The `node` row is the first row of the log. A later `node` row is quarantined. Older `awt` copies quarantine it as an unknown type and `doctor` warns; nothing else changes for them.

`key` is an external identity such as `paseo:workspace/wks_1f2e`. Keys are unique across the whole tree. The name is cosmetic: the directory is `[a-z0-9-]` slug, max 50, with a numeric suffix on collision, like `capture`.

### Creating nodes

`init --kind root|workspace|task|agent [--name N] [--key K] [--goal T --done T]`

- Without `--kind`, `init` is unchanged. `--name` and `--key` need `--kind` (exit 2 otherwise).
- `init` never converts: on a directory whose first row is a `node` row it refuses unless `--kind` equals that node's kind (re-running `--kind root` on a root is a no-op); plain `init` on a tree node is refused. `--kind root` is refused on a directory that has records but no `node` row (a root needs a directory without records).
- `--kind root`: creates the root in the resolved directory (`--dir`, `AWT_DIR` or `cwd`). Writes the contract in its tree form.
- Any other kind: the parent is the resolved node. Refuse an illegal kind/parent pair (fix names the legal kinds). `--name` is required.
- The child is built under `<parent>/<kinds>/.new-<random>/` with its `.awt/events.jsonl` complete, then moved into place with `rename`. A crash leaves only a `.new-*` directory, which no listing shows and `doctor` reports. A `rename` onto an existing non-empty directory fails, so two racing creators cannot both win; an existing empty directory with the chosen slug is taken over, with no data lost.
- With `--key`, the check for an existing node with that key and the `rename` happen under `flock` on the tree root's `.awt/events.jsonl`. The search starts at the tree root (the topmost node above the resolved one) and covers every descendant, so a key is unique across the whole tree. A match prints the existing node's path relative to the resolved node and its kind, and exits 0 (idempotent), wherever it is and whatever `--name`, parent or kind was asked. If the filesystem has no `flock`, the command refuses with fix "keyed init needs a local filesystem". Without `--key`, a retry after a crash can leave a duplicate (`t`, `t-2`): a harness that retries must pass `--key`.
- `--goal`/`--done` are required for `task`, optional for the others. `workspace` and `agent` get a placeholder goal from `--name` when absent.
- Output: one line, `init <path relative to the resolved node> <kind>` for child kinds. `--kind root` and plain `init` print `init <dir>: <what was made>`.

Layout by kind:

| Kind | Creates |
|---|---|
| `root` | `.awt/`, `AGENTS.md` (tree form), `README.md`, `workspaces/` |
| `workspace` | `.awt/`, `context/`, `docs/`, `misc/` |
| `task` | The `init` layout above, with `AGENTS.md` in tree form, the `.claude/settings.json` hook running `awt resume --hook`, and no `README.md` |
| `agent` | `.awt/`, `scratch/`, `out.md` created on first write |

`.gitignore` lines for `scratch/` and `.awt/claims|runs/` are written at every node.

### Resolution

Unchanged: `--dir` > `AWT_DIR` > script directory > walk up from `cwd`. A person or harness opened in a task node resolves it by the walk. An agent running in a repository needs its harness to set `AWT_DIR` to its node and `AWT_BY` to its id; the Paseo plugin does that, and without such a harness an agent uses the tree only from a task node's directory. A shared `awt` on `PATH` replaces the per-directory copy; `./awt` remains valid for a standalone node.

Ancestors are the parent chain, nearest first, at most 8 levels, stopping after the first `root`. Descendants are found by walking the reserved directories only, at most 8 levels deep and 2,000 nodes. Symlinked directories are never followed, so a loop cannot occur; `doctor` reports them. Hitting a limit is reported, never silent.

Every walk of a node's own files (listing, `find`, resume section 5) skips any subdirectory that contains `.awt/`, and the reserved directories are not listed under `misc`. A child's files belong to the child.

### Reading across nodes

- In a node that has a `node` row or a parent, every printed command is `awt`, not `./awt`.
- `resume`: sections are added. Sections 1 to 7 keep their budgets and order. Lineage prints right after the goal, Task right after Lineage, Children right after the state; the numbers name them, they do not order them.

  | # | Section | Budget |
  |---|---|---|
  | 8 | Lineage: one line per ancestor, outermost first: kind, name, status, goal cut to 110 chars. Over budget, the outer levels are dropped (`+N outer levels`), never the nearest | 300 |
  | 9 | Children: one line per direct child with kind, name, status, age and the `now` of its newest state cut to 100 chars; a child with no state shows its `out.md` age and size, else `no state`. Order: `active`, then `paused`, then `done`, newest first within each. Overflow: `+N more: awt list nodes` | 500 |
  | 10 | Task (agent nodes only), from the nearest `task` ancestor's log: goal and done-means 400; newest state in full, other scopes one line 600; open questions 300; attention effects 250; current non-rule decisions cut to 120 chars 250. Overflow: `+N more: awt list <section> --dir <task path>` | 1,800 |

  Maximum total: 4,400 with no ancestors and no children (the brief is unchanged); 5,200 otherwise; 7,000 for an agent node (5,200 + section 10). Section 6 lists the node's own current decisions first, then the `rule`-tagged current decisions of every ancestor, outermost first, each marked `[rule, KIND NAME]`. Ancestors' rules count against the section 6 budget; the overflow line then adds `inherited: awt find --up rule`. Section 5 uses the `repo` refs of the node and its ancestors, nearest first, each path once.
- `list nodes [--all]`: every descendant with kind, name, status, key and relative path. `--all` includes `done` nodes.
- `list tree [--all]` (and `list tree --json`, which equals `list nodes --json`): the same, indented. Nodes with open questions or attention effects are marked.
- `list <section> --json` and `resume --json`: machine-readable output for the same data, one JSON array or object, UTF-8. These key names are the contract the Paseo plugin and `migrate-paseo` rely on; adding a key is compatible, renaming or removing one is not.
  - `list nodes --json`: array of `path`, `depth`, `kind`, `name`, `key`, `status`, `goal`, `now`, `state_ts`, `out_ts`, `out_bytes`, `open_questions`, `attention_effects` (missing values are `null`).
  - `list refs|decisions|questions|effects|notes|state --json`: arrays of rows with a fixed key set per section; an absent optional field is `null` (`tags` is `[]`, `scope` is `main`). `refs`: `ts`, `by`, `target`, `title`, `kind`, `why`, `access`, `path`, `branch`, `key`. `decisions`: `ts`, `by`, `id`, `choice`, `why`, `tags`, `supersedes`, `superseded_by`. `questions`: `ts`, `by`, `id`, `text`, `answer`. `effects`: `ts`, `by`, `id`, `target`, `why`, `body`, `run`, `state`, `attempt`. `notes`: `ts`, `by`, `id`, `text`. `state`: `ts`, `by`, `scope`, `now`, `next`.
  - `list context|docs|outbox|misc --json`: array of `path`, `title`.
  - `resume --json`: `node` (`kind`, `name`, `key`, `legacy`), `status`, `goal`, `done_means`, `state` (the newest, or the newest of `--scope`), `open_questions`, `attention_effects`, `decisions`, `lineage` and `children` (arrays of `list nodes` objects), `task` (agent nodes: a `list nodes` object for the task with its `done_means`, `state`, `open_questions`, `attention_effects` and `decisions` added; else `null`), `brief` (the text).
- `find --up|--down|--tree TERM`: `--up` searches ancestors, `--down` descendants. `--tree` searches the whole tree under the nearest `root` ancestor: the root node and every descendant of it, including sibling tasks and their agents (a node with no root above it searches its ancestors and descendants instead). The same caps apply (40 hits in total; depth 8 and 2,000 nodes counted from the searched top). Each hit is prefixed with its node path as seen from the current directory, so it can be passed to `--dir` or opened as is: nothing for the current directory itself; a relative path when the node is inside the current directory or the current directory is inside the tree; an absolute path otherwise (for example an agent whose cwd is its repo while `AWT_DIR` points into the tree). Without a flag, only the resolved node is searched.
- `find --like TEXT [--limit N]`: ranked related records. Words are the lowercase tokens of TEXT matching `[a-z0-9][a-z0-9_./-]+`, with leading and trailing `.`, `/`, `-` and `_` stripped (so `gateway.` is `gateway`), minus the stopwords in the `STOPWORDS` constant of `awt` (about 80 English words) and tokens under 3 characters, duplicates dropped (ids and paths stay). Candidates are event rows only: current decisions, questions (with their answer), notes, refs (title and why) and `main`-scope states; `auto` states, effects and node rows never match, and a record never matches itself. Nodes that are `done` or `paused` are candidates: history is the point. Each distinct shared word adds `log(1 + N/df)` (N candidates, df candidates containing the word). A candidate qualifies with at least 2 shared words, or 1 when TEXT has at most 2 words. `rule` decisions score x1.5; ties go to the newest row. Scope is the `--tree` set; `--up` or `--down` narrows it; same caps. Output: one line per hit, best first, `<id or row type> <@node> [rule]: text`, for example `d-7f3a9c21 @workspaces/parsekit [rule]: choice (why: ...)` or `q-1a2b3c4d @...: question -> answer`; a ref or state has no id and uses its row type (`ref`, `state`); the `@node` prefix is omitted for the resolved node (the one `awt` runs in, wherever the cwd is); for any other node it follows the `--tree` path rule, except that an absolute path is replaced by the path relative to the tree top (for example `@workspaces/w/tasks/t`), so an agent whose cwd is outside the tree does not spend its 200 characters on a long absolute path. Each line is cut to 200 characters; for `related:` lines the 200 includes the `related: ` prefix. Default limit 10, `--limit` 1 to 40. No hits prints `no related records`, exit 0. `--like` with a TERM, or `--limit` without `--like`, is exit 2.
- `decide` and `ask` related lines: after the id line they print up to N lines `related: ID @NODE ...`, ranked as `find --like` over the choice and why (`decide`) or the question text (`ask`), the new row excluded. N is `--related N`, else `AWT_RELATED`, else 3; range 0 to 20, 0 is off. A bad `--related` is exit 2; a bad `AWT_RELATED` warns on stderr and uses 3; an empty `AWT_RELATED` is the same as unset (3, no warning). The write comes first and is never undone: any error in the lookup is swallowed (exit 0), and the lookup stops after 2 s, counted from before the tree walk and checked between nodes during the walk and the reads (a single huge node file can still overrun it, since one read is not interrupted): the hits found so far print, then `related: (lookup stopped at 2 s; run awt find --like ...)`, all on stdout. Unreadable or corrupt nodes are skipped silently. `AWT_RELATED_MS` overrides the 2,000 ms budget (a test hook); a value that is not a finite number of at least 0 means 2,000.
- `list --since ISO8601 [--down] --json`: an array of rows of every type at or after the timestamp in the node (and, with `--down`, its descendants), sorted by `ts` ascending, each with `type`, `ts`, `by`, `id`, `scope` (`null` unless a state) and, with `--down`, `node`: the node path relative to the queried node, `null` for the queried node's own rows. The timestamp is ISO 8601 with `Z` (either case) or an offset (`+HH:MM`, `+HHMM`, `-HH:MM`, `-HHMM`); a naive time (no `Z` or offset) or a bare date is exit 2 with a `fix:` line, as is an empty value. Requires `--json` (else exit 2), takes no section; a bad timestamp is exit 2. The Paseo plugin reads turn receipts through it.
- `ref TARGET`: a target that is a directory containing `.awt/` and no `.git` infers `kind=node` (a node that is its own git repository still infers `repo`; pass `--kind node` to override) and stores the target's `key`, if it has one, and its path relative to the referencing node. Reading resolves by key under the tree root first, then by path, so a keyed target survives any move within the tree and an unkeyed one survives a move that contains both ends. A `paseo:` target infers `kind=paseo`. A node ref that resolves nowhere on this host is shown with `access: none`.
- `status done`: refused while a descendant `workspace` or `task` is `active`, or any descendant has an unanswered question or an effect in `planned`, `begun` or `unknown`. The refusal lists each with its path, at most 20 items and then `+N more`. If the walk hits a limit, the refusal says the tree exceeds depth 8 / 2,000 nodes and that the rest cannot be verified. `find --down|--tree` and `doctor` report a hit limit in the same words. A node archived by a harness without being finished is `paused`, not `done`.
- Each node's event log is separate, so concurrent agents never contend on a log. `by` still names the writer.
- `doctor` adds. `fail`: illegal kind nesting; a key used twice in the tree. `warn`: an unreadable reserved directory (the other checks go on); the walk limit; a `node` row that is not first or names a different kind than its reserved directory; a node inside another node but outside a reserved directory; a non-node entry in a reserved directory; leftover `.new-*` directories; a symlinked directory in a reserved directory; an active child under a `done` parent; `awt` not on `PATH` in a tree node.

### Agent node contract

- The orchestrating harness creates the node, sets `AWT_DIR` and `AWT_BY`, and passes the rules. The agent does not create its own node.
- A primary agent runs `awt resume` first; section 10 gives it its task's state, decisions, questions and effects. It writes `state` before stopping.
- A subagent does not resume. Its harness gives it the `rule` decisions of its task, the task path, and `out.md` as the place for its result. It does not write `state`; the parent's Children line shows the child's `out.md` age and size, and reading it is left to the parent.
- A subagent's node is created under its parent agent's node. If the parent is unknown, it is created under the task and a `note` records the missing parent.

### Paseo plugin

`paseo-plugin/` is a second target in this repository: a trusted local Paseo plugin (`paseo-plugin.json`, `index.server.ts`, `server/`). It keeps no tree of its own: every read and write goes through `awt` as a subprocess (with `--json` for reads), so the CLI and Paseo see the same tree. It does own the glue: key-to-path lookup, the current-task pointer, hashing for unassigned workspaces, parent note/ref repair, and the done-then-paused status rule. Core `awt` stays one stdlib Python file; the plugin is TypeScript.

Configuration comes from the daemon's environment: `AWT_BIN` (default `awt`), `AWT_ROOT` (default `${XDG_DATA_HOME:-~/.local/share}/awt`), `AWT_TIMEOUT_MS` (default 5000), `AWT_NUDGE` (default off; `1` turns on the follow-up prompt described under `agent.turn.after`), `AWT_AUTO_HANDOFF` (default on; `0` turns off the stand-in handoff described there), `AWT_RECEIPT` (default on; `0` or `off` off, `changes` only when something was stored; see the turn receipt below), `AWT_RELATED` (forwarded as is to the agent environment, only when set; `awt` validates it and warns). An `AWT_RECEIPT` value other than `0`, `off`, `changes` or `on` is treated as on, with one logged warning.

The plugin never fails an agent. Every hook catches every error, and the two hooks the daemon waits for (`agent.create.before`, `agent.open.before`) run under one deadline of `AWT_TIMEOUT_MS` for the whole hook, not per `awt` call. At the deadline, or when the daemon cancels the hook, running `awt` children are killed and the request goes through unchanged: the agent starts without awt. Every `awt` call runs in the daemon's environment, minus `AWT_DIR`, and with `--dir NODE --by paseo-plugin` (or the agent id). The one permission request it answers is described under Hooks (an agent writing inside its own node).

Paseo 0.15.4's hook payloads carry no plugin metadata, no `background` flag, and neither the session-open request nor the other hook payloads carry `parentAgentId`: Paseo records a subagent's parent only as the label `paseo.parent-agent-id` (with `paseo.parent-server-id`), which `agent.open.before` receives in `request.labels`. The plugin reads the parent as `parentAgentId ?? labels["paseo.parent-agent-id"]`, remembers the one seen at open for later hooks of that agent, and uses it everywhere a parent is needed (placement, the parent note and ref, the nudge skip). The plugin therefore keeps all identity in awt: a node's `key` is the Paseo id, and nodes are found by key. A key carried by more than one node is an error: the plugin logs it, resolves it to nothing and leaves that agent untouched (no `AWT_DIR`, no tool, no nudge). Cached paths are dropped when the node is gone from disk or `awt` exits nonzero there, and looked up again once.

| Paseo | awt | Key |
|---|---|---|
| Project | not a node. A `ref kind=paseo` on each workspace node | `paseo:project/<id>` |
| Workspace | `workspace` node | `paseo:workspace/<id>` |
| No workspace, or a `cwd` outside any | `workspace` `unassigned--<cwd basename>` | `paseo:unassigned/<hash of cwd>` |
| none | `task` `main`, created with the workspace | `paseo:task/<workspace id>/main` |
| Agent | `agent` node under the workspace's current task | `paseo:agent/<id>` |
| Subagent | `agent` node under the parent agent's node when the parent is known at open time (from `request.labels`); otherwise under the task, with a `note` and a `ref kind=node` to the parent added at `agent.create.after` (both written with `by` `paseo-plugin`, so a subagent's receipt does not count them) | `paseo:agent/<id>` |

The current task of a workspace is the latest `state` row with scope `current-task` on the workspace node, whose `now` is a task key. With no such row it is `main`. A person sets it with `awt state --scope current-task --now <task key> --next -`; a later `/task` command can do the same.

Hooks:

| Hook | Action |
|---|---|
| `workspace.create.after` | Ensure the workspace node (refs: working directory, project, workspace) and its `main` task |
| `agent.create.before` | Append the static awt block (one paragraph, at most 700 chars; it names `awt find --like` and says to call `awt_resume` again after compaction) to `systemPrompt`, once, and only when `awt` is working (the root node could be ensured). Otherwise the request is unchanged. Nothing else changes |
| `agent.open.before` | Only for `purpose: interactive`. Ensure the agent's node. Add `AWT_DIR` (the node), `AWT_BY` (the agent id) and, when the daemon has it set, `AWT_RELATED` to `env`, and the `awt_resume` tool. Runs on every open, so resumed agents get the same node |
| `agent.create.after` | Ensure the node (covers an order where it runs before open). When the parent is known (see above) and the node is not under the parent's, record the parent as above |
| `agent.turn.before` / `agent.turn.after` | By default the plugin sends no prompt into a conversation; the handoff is asked for by the static prompt block and the `awt_resume` brief. After a completed turn of a non-subagent with an `AWT_DIR` (from `agent.open.before` in this process, or, after a plugin reload, an agent whose `paseo:agent/<id>` node already exists, which is then remembered; an agent with no node is skipped) and no `main` `state` row newer than the turn's start, it records the agent's last assistant message (from the timeline, cut to 240 chars, prefixed `[auto] `) as `state --scope auto`. A scope of its own means it never replaces a handoff the agent wrote, `resume` shows it beside one, and awt's refusal of an unchanged state keeps repeated replies from adding rows; `AWT_AUTO_HANDOFF=0` turns this off. With `AWT_NUDGE=1` the plugin instead sends the follow-up below. Nudge rule: at most one follow-up asking for `awt state` per agent per stretch, where a stretch ends when the agent records a `state` row. After a completed turn of a non-subagent that got an `AWT_DIR` from `agent.open.before` in this process, with no `state` row newer than the turn's start, send the follow-up unless one was sent since the agent last recorded state. Agents without `AWT_DIR` are never nudged |
| `agent.turn.after` (receipt) | After the handoff above, for any outcome and for subagents too, an agent with a node (found by key if the plugin was reloaded since it opened) gets one plugin timeline item (`agents.ref(id).timeline.append`, id `awt.receipt.<turn id>`, kind `awt.receipt`, version 1) with `data` `{node, counts, ids (max 5), auto, empty}`, read through `awt list --since <turn start> --down --json`, the turn start being the one `agent.turn.before` recorded. `node` is the agent node's name. `counts` has only the non-zero types; `node` rows and rows written by `paseo-plugin` other than the auto state are not counted. `ids` are the first 5 by `ts`. `auto` is true when the stand-in handoff was written this turn. A receipt counts its own node and the subagent nodes below it, so a subagent's row shows in both its own receipt and its parent's, by design. The client renders one muted line (`awt · 1 decision d-... · 1 note · handoff`, `awt · handoff [auto]`, `awt · 1 handoff · handoff [auto]` when the agent also wrote one; the stand-in handoff is always shown apart from the agent's own, `awt · nothing stored this turn`); an unknown version or bad data renders nothing. `AWT_RECEIPT=changes` skips empty receipts and those whose only row is the auto state, `0` or `off` skips all. An append failure is logged and changes nothing. Plugin timeline items are UI-only; the gated tier 2 test confirms they are not sent to the provider |
| `agent.permission.before` | The node dir (`AWT_DIR`) is always outside the agent's cwd, so opencode (`external_directory`, whose `input.patterns` are `<dir>/*` globs) and Claude (a write, edit or read with a `filePath`) ask before the agent may write there, and a headless run stalls. The plugin answers `allow` through `agents.ref(id).respondToPermission`, and only when every target path, resolved with `realpath` (symlinks followed, a not-yet-existing tail kept, `..` collapsed), is the calling agent's own node dir or inside it. Not its parent's, a sibling's, a child's outside it, or `AWT_ROOT` itself; a request with any target outside, an unknown shape, a relative path, a glob other than the trailing `/*`, shell commands, or from an agent with no node: left untouched for the person. It never denies |
| `agent.archive.after`, `workspace.archive.after` | `awt status done`; if refused, `paused` |

`awt_resume` takes no input and prints the brief of the node found for the calling agent's key. It cannot name another node; which node it reads is decided by the key lookup, which is only as safe as key uniqueness (see above).

Prompt cost: only the static block (654 chars) enters the system prompt, so it caches. The brief arrives by tool, fresh on every call.

Compaction (R5): Paseo's `AgentSessionConfig` has no hooks field (`providerOptions` is an untyped record), so the plugin cannot add a native `SessionStart` (matcher `compact`) hook. The static block carries the line "unless another agent started you, call it again after your context is compacted" instead; it cannot tell a subagent at create time, so the condition is in the text and the line applies to non-subagents only. Standalone Claude Code is covered by the `SessionStart` hook that `init` writes, which has no matcher and so runs on `compact` too.

Not in this version: `/task` commands and the composer pill, background-agent filtering (needs a Paseo release that reports it), and metadata (`awt.node`). Hook order between `agent.open.before` and `agent.create.after` is unverified against a live daemon; the gated tier 2 tests in `tests/TEST-SPEC.md` are where that is settled.

### migrate-paseo

`migrate-paseo ROOT [--dry-run] [--from SNAPSHOT] [--home PATH]`: a separate one-off script like `migrate-wt`, not counted against the verb limit. It is read-only on Paseo and writes only through the `awt` next to it.

Sources:
1. `--from SNAPSHOT`, a JSON file with `projects`, `workspaces` and `agents`. The plugin writes one from the SDK with exact `workspaceId` and `parentAgentId` for every agent. Tests use the same format.
2. Paseo's on-disk JSON under `--home` (default `~/.paseo`), read-only: `agents/*/*.json` (one file per agent, with `workspaceId`, `archivedAt`, `internal`, label `paseo.parent-agent-id`, which is where Paseo records the parent of a subagent; on a real install it agreed with `paseo inspect` `ParentAgentId` for every agent checked), `projects/projects.json` and `projects/workspaces.json` (`archivedAt`, `background`). It is mapped to the snapshot shape, so every agent has an exact workspace. A `background` workspace and an `internal` agent are skipped. A file that cannot be read is skipped and listed; a missing or malformed `workspaces.json` is a refusal with a fix line.

Mapping:

| Paseo item | awt result |
|---|---|
| Workspace | `workspace` node, name `<project>--<name>`, `ref` repository path, `ref paseo:project/<id>` |
| Agent, exact workspace id | `agent` node under task `imported` of that workspace |
| Agent without a workspace id, `cwd` (normalised with `normpath`) matches exactly one workspace | The same |
| Agent without a workspace id whose `cwd` matches several workspaces or none, or whose workspace id is not listed | Under workspace `unassigned--<cwd basename>`, task `imported`. Listed in the report |
| Subagent whose parent was imported | Under the parent agent's node. Its workspace is not resolved |
| Subagent whose parent is missing, or a parent cycle | Under the task; reported |
| Archived agent | Imported, then moved from `active` to `done` |
| Archived workspace | Imported like any workspace (its agents have an exact workspace id), then its `imported` task and the workspace are moved from `active` to `done` when awt allows it (awt refuses `done` over an active child; the report notes it) |
| Background agent | Skipped; listed in the report |

Each agent node gets `goal` from its Paseo title (cut to the cap), a `ref kind=paseo` with provider and model in `why`, and nothing else. The timeline is not copied: Paseo keeps it, and rule 3 applies. Every text field (titles, workspace and project names, `cwd`, provider, model) that matches the secret scan is imported with the match redacted, and the report names the item and the field. A `cwd` with a match gets no `ref`. An id that matches the scan cannot be a key: it is skipped and listed. Nothing the script writes or prints contains a match, and failed `awt` calls report awt's message, never its arguments. Report fields are single-line and capped.

Properties:
- Idempotent: a second run, or a run after a crash, creates only what is missing; names are never changed after creation. After import awt owns the status: the script never sets `active`, and moves a node only from `active` to `done` when Paseo has it archived, so a status the user set survives reruns. Output and report give created and already-present counts separately.
- Existing nodes are found by key across the whole tree before anything is created, so a node is never duplicated or moved when its parent changes in Paseo. Refs and statuses are read in process and written through `awt`.
- A lock: a second concurrent run exits 1 with a fix. The report file doubles as the lock (`flock`), because `awt` itself takes `flock` on `events.jsonl`. Taking the lock truncates the report to a "run in progress" header, so a killed run never leaves the previous report looking current.
- `legacy/paseo-migration.md` in the root: counts, every ambiguity, every skipped item with its reason.
- Exit 1 if any Paseo item is neither imported nor listed as skipped, as in `migrate-wt`.
- `migrate-wt` is unchanged. A tracker output already has the `tasks/<id>/` shape and can be moved under a workspace's `tasks/` directory.

### Templates

The tree-form `AGENTS.md` block, written at the root and in every task node, is the existing block with these changes, still at most 2 KB: commands are `awt`, not `./awt`; it starts with "Your node is `$AWT_DIR` if set, else this directory. Never hand-edit `.awt/`"; and the subagent line reads "**Subagents:** skip resume, write the result to `$AWT_DIR/out.md`".

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
