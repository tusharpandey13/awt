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
| `init` | Above. `--kind` creates nodes: see Node tree. |
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

Sections in this order, each with a budget in one constants table. Total at most 4,400 chars (more for a tree node, see Node tree), tested at maximum fill, labels included. Empty sections are omitted. Truncate at a line boundary with `+N more: ./awt list <section>`.

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

- Without `--kind`, `init` is unchanged.
- `--kind root`: creates the root in the resolved directory (`--dir`, `AWT_DIR` or `cwd`). Writes the contract in its tree form. Refused on a directory that is already a node.
- Any other kind: the parent is the resolved node. Refuse an illegal kind/parent pair (fix names the legal kinds). `--name` is required.
- The child is built under `<parent>/<kinds>/.new-<random>/` with its `.awt/events.jsonl` complete, then moved into place with `rename`. A crash leaves only a `.new-*` directory, which no listing shows and `doctor` reports. The built directory is never empty, so `rename` onto an existing node fails (`ENOTEMPTY`/`EEXIST`) and two racing creators cannot both win; an empty directory already at the slug is replaced, which loses nothing.
- With `--key`, the search for an existing node with that key anywhere under the tree root and the `rename` happen under `flock` on the tree root's `.awt/events.jsonl`. A match prints the existing path and exits 0 (idempotent). A different `--name` or parent with an existing key is not a new node; the existing one is returned.
- Missing `--name`, or `--goal`/`--done` for a `task`: usage error, exit 2. Other kinds without `--goal` get a placeholder `task` row: goal `<kind> <name>`, done-means `n/a`.
- Output: one line, `init <path relative to the resolved node> <kind>`.

Layout by kind:

| Kind | Creates |
|---|---|
| `root` | `.awt/`, `AGENTS.md` (tree form), `README.md`, `workspaces/` |
| `workspace` | `.awt/`, `context/`, `docs/`, `misc/` |
| `task` | The `init` layout above, with `AGENTS.md` in tree form, the `.claude/settings.json` hook running `awt resume --hook`, and no `README.md` |
| `agent` | `.awt/`, `scratch/`, `out.md` created on first write |

`.gitignore` lines for `scratch/` and `.awt/claims|blobs|runs/` are written at every node.

### Resolution

Unchanged: `--dir` > `AWT_DIR` > script directory > walk up from `cwd`. A person or harness opened in a task node resolves it by the walk. An agent running in a repository needs its harness to set `AWT_DIR` to its node and `AWT_BY` to its id; the Paseo plugin does that, and without such a harness an agent uses the tree only from a task node's directory. A shared `awt` on `PATH` replaces the per-directory copy; `./awt` remains valid for a standalone node.

Ancestors are the parent chain, nearest first, at most 8 levels, stopping after the first `root`. Descendants are found by walking the reserved directories only, at most 8 levels deep and 2,000 nodes. Symlinked directories are never followed, so a loop cannot occur; `doctor` reports them. Hitting a limit is reported, never silent.

Every walk of a node's own files (listing, `find`, resume section 5, `save`) skips any subdirectory that contains `.awt/`, and the reserved directories are not listed under `misc`. A child's files belong to the child.

### Reading across nodes

- In a node that has a `node` row or a parent, every printed command is `awt`, not `./awt`.
- `resume`: sections are added. Sections 1 to 7 keep their budgets and order. Lineage prints right after the goal, Task right after Lineage, Children right after the state; the numbers name them, they do not order them.

  | # | Section | Budget |
  |---|---|---|
  | 8 | Lineage: one line per ancestor, outermost first: kind, name, status, goal cut to 110 chars. Over budget, the outer levels are dropped (`+N outer levels`), never the nearest | 300 |
  | 9 | Children: one line per direct child with kind, name, status, age and the `now` of its newest state cut to 100 chars; a child with no state shows its `out.md` age and size, else `no state`. Active first. Overflow: `+N more: awt list nodes` | 500 |
  | 10 | Task (agent nodes only), from the nearest `task` ancestor's log: goal and done-means 400; newest state in full, other scopes one line 600; open questions 300; attention effects 250; current non-rule decisions cut to 120 chars 250. Overflow: `+N more: awt list <section> --dir <task path>` | 1,800 |

  Maximum total: 4,400 with no ancestors and no children (the brief is unchanged); 5,200 otherwise; 7,000 for an agent node (5,200 + section 10). Section 6 also lists the `rule`-tagged current decisions of every ancestor, outermost first, each marked with its origin kind. Ancestors' rules count against the section 6 budget. Section 5 uses the `repo` refs of the node and its ancestors, nearest first, each path once.
- `list nodes [--all]`: every descendant with kind, name, status, key and relative path. `--all` includes `done` nodes.
- `list tree [--all]`: the same, indented. Nodes with open questions or attention effects are marked.
- `list <section> --json` and `resume --json`: machine-readable output for the same data, one JSON array or object, UTF-8. These key names are the contract the Paseo plugin and `migrate-paseo` rely on; adding a key is compatible, renaming or removing one is not.
  - `list nodes --json`: array of `path`, `depth`, `kind`, `name`, `key`, `status`, `goal`, `now`, `state_ts`, `out_ts`, `out_bytes`, `open_questions`, `attention_effects` (missing values are `null`).
  - `list refs|decisions|questions|effects|notes|state --json`: the rows as derived by `load()`, with the field names of the Events table; decisions add `superseded_by`, questions add `answer`.
  - `list context|docs|outbox|misc --json`: array of `path`, `title`.
  - `resume --json`: `node` (`kind`, `name`, `key`, `legacy`), `status`, `goal`, `done_means`, `state`, `open_questions`, `attention_effects`, `decisions`, `lineage` and `children` (arrays of `list nodes` objects), `task` (agent nodes: a `list nodes` object for the task with its `done_means`, `state`, `open_questions`, `attention_effects` and `decisions` added; else `null`), `brief` (the text).
- `find --up|--down|--tree TERM`: searches ancestors, descendants, or both, with the same caps (40 hits in total). Hits are prefixed with the node path relative to the resolved node. Without a flag, only the resolved node is searched.
- `ref TARGET`: a target that is a directory containing `.awt/` and no `.git` infers `kind=node` (a node that is its own git repository still infers `repo`; pass `--kind node` to override) and stores the target's `key`, if it has one, and its path relative to the referencing node. Reading resolves by key under the tree root first, then by path, so a keyed target survives any move within the tree and an unkeyed one survives a move that contains both ends. A `paseo:` target infers `kind=paseo`. A node ref that resolves nowhere on this host is shown with `access: none`.
- `status done`: refused while a descendant `workspace` or `task` is `active`, or any descendant has an unanswered question or an effect in `planned`, `claimed` or `unknown`. The refusal lists each with its path. A node archived by a harness without being finished is `paused`, not `done`.
- Each node's event log is separate, so concurrent agents never contend on a log. `by` still names the writer.
- `doctor` adds. `fail`: illegal kind nesting; a key used twice in the tree. `warn`: a `node` row that is not first or names a different kind than its reserved directory; a node inside another node but outside a reserved directory; a non-node entry in a reserved directory; leftover `.new-*` directories; a symlinked directory in a reserved directory; an active child under a `done` parent; `awt` not on `PATH` in a tree node.

### Agent node contract

- The orchestrating harness creates the node, sets `AWT_DIR` and `AWT_BY`, and passes the rules. The agent does not create its own node.
- A primary agent runs `awt resume` first; section 10 gives it its task's state, decisions, questions and effects. It writes `state` before stopping.
- A subagent does not resume. Its harness gives it the `rule` decisions of its task, the task path, and `out.md` as the place for its result. It does not write `state`; the parent's Children line shows the child's `out.md` age and size, and reading it is left to the parent.
- A subagent's node is created under its parent agent's node. If the parent is unknown, it is created under the task and a `note` records the missing parent.

### Paseo plugin

`paseo-plugin/` is a second target in this repository: a trusted local Paseo plugin (`paseo-plugin.json`, `index.server.ts`, `requirements.paseo` `>=0.15.0`). It contains no awt logic. It runs `awt` as a subprocess with `AWT_DIR`, `AWT_BY` and `--json`, so the CLI and Paseo see the same tree, rooted at `AWT_ROOT`. Core `awt` stays one stdlib Python file; the plugin may use Node and TypeScript.

The plugin never fails an agent. Every hook runs `awt` with a 5 second timeout and catches every error; on failure the agent starts without awt and a `note` is attempted. Background agents are ignored everywhere.

Mapping:

| Paseo | awt | Key |
|---|---|---|
| Project | not a node. Recorded as a `ref kind=paseo` on each workspace node | `paseo:project/<id>` |
| Workspace | `workspace` node | `paseo:workspace/<id>` |
| none | `task` node. Created by `/task`, or `main` on first agent (goal `Work in this workspace that belongs to no other task`, done-means `n/a`) | `paseo:task/<workspace id>/<slug>` |
| Agent | `agent` node under its task, named by its id; its title, redacted like `migrate-paseo`, is the goal | `paseo:agent/<id>` |
| Subagent (`parentAgentId`) | `agent` node under the parent agent's node | `paseo:agent/<id>` |

Paseo owns existence and liveness; awt owns goals, decisions, refs and handoffs. The node `key` is the only link: both directions look nodes up by key in `list nodes --json`. No Paseo metadata or `paseo:` ref repeats it.

Hooks:

| Hook | Action |
|---|---|
| `workspace.create.after` | Ensure the workspace node and `ref` the repository path |
| `agent.create.before` | Resolve the task (the workspace's current task, else `main`). Append the static awt block to `systemPrompt` (at most 600 chars: rules, "call `awt_resume` first", "never `effect apply` unprompted"). For a subagent, append the short subagent block (at most 350 chars) instead |
| `agent.create.after` | Ensure the agent node |
| `agent.open.before` | Set `AWT_DIR` and `AWT_BY`. Attach the `awt_resume` tool (returns `resume` output for this node). Runs on every open, so resumed agents are covered |
| `agent.turn.after` | Opt-in (`AWT_NUDGE=1`): if the turn completed, the agent is not a subagent, and its node has no `state` newer than the turn start, send one follow-up asking for `awt state`. At most one per turn chain; the follow-up's own turn never triggers another |
| `agent.permission.before` | Never approves anything. `awt effect apply` stays pending for a person |
| `agent.archive.after`, `workspace.archive.after` | `awt status done`; if refused, `paused` |

Commands (second phase): `/task new "goal"`, `/task list`, `/task switch <slug>` set the workspace's current task; a composer pill shows it. `/awt migrate` runs the migration with exact workspace ids from the SDK.

Prompt cost: only the static block enters the system prompt, so it caches. The brief is fetched by tool, fresh on every resume. The block is the same text for every agent of a kind, so it is stored once in the plugin, never per node.

Compatibility: the plugin is optional. Without Paseo, `awt init --kind` and `list tree` give the same hierarchy from a shell, and task nodes carry the contract for any harness opened in them. Hook names above follow the plugin docs for Paseo 0.15; the first implementation task is to check each payload field named here against a real daemon, in particular whether `parentAgentId` is present in `agent.create.before`.

### migrate-paseo

`migrate-paseo ROOT [--dry-run] [--from SNAPSHOT] [--home PATH]`: a separate one-off script like `migrate-wt`, not counted against the verb limit. It is read-only on Paseo and writes only through the `awt` next to it.

Sources:
1. `--from SNAPSHOT`, a JSON file with `projects`, `workspaces` and `agents`. The plugin writes one from the SDK with exact `workspaceId` and `parentAgentId` for every agent. Tests use the same format.
2. Otherwise the daemon's on-disk store under `--home` (default `~/.paseo`), read directly: `projects/projects.json`, `projects/workspaces.json` and `agents/*/*.json`. No `paseo` process is run. Unknown fields are ignored; an unreadable or malformed file is reported and its items count as skipped. The store records no parent agent, so every agent from it is a primary agent.

Mapping:

| Paseo item | awt result |
|---|---|
| Workspace | `workspace` node, name `<project>--<name>`, `ref` repository path, `ref paseo:project/<id>` |
| Agent with a known workspace id | `agent` node under task `imported` of that workspace |
| Agent with no known workspace id whose `cwd` matches exactly one workspace | The same |
| Any other agent | Under workspace `unassigned--<project or cwd basename>`, task `imported`. Listed in the report |
| Subagent whose parent was imported | Under the parent agent's node |
| Subagent whose parent is missing, or a parent cycle | Under the task; reported |
| Archived agent | Imported with `status done`. Archived workspaces appear only through their agents and use the `unassigned` rule |
| Background agent | Skipped; listed in the report |

Each agent node is named by its id, gets `goal` from its Paseo title (cut to the cap), a `note` with provider and model, and nothing else. The timeline is not copied: Paseo keeps it, and rule 3 applies. An agent title that matches the secret scan is imported with the match redacted, and the report names the agent.

Properties:
- Idempotent: a second run, or a run after a crash, imports only what is missing and appends a `status` row only when it differs. Names are never changed after creation.
- A lock: a second concurrent run exits 1 with a fix.
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
